"""Run agent rounds and persist their inputs, output, and outcomes.

A round runs a harness in its owner's worktree and stores its prompt, input,
stop request, raw and rendered output, final output, and lifecycle record in a
numbered directory. The daemon watches rather than waits, so the round reads
its streams and records its ending on threads of its own.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import Event as Flag
from threading import Lock, Thread
from typing import Annotated, Literal, Protocol, Self

from pydantic import AwareDatetime, Field, PositiveInt, model_validator

from dreamcatcher.clock import read_current_time
from dreamcatcher.commands import spawn_command
from dreamcatcher.config import AgentHarness
from dreamcatcher.documents import (
    DocumentCache,
    DreamcatcherDocument,
    append_text,
    read_text,
    remove_file,
    write_json,
    write_text,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedEvent, FeedNote, FeedProse, FeedRenderer
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    HarnessAdapter,
    HarnessInvocation,
    HarnessOutput,
    HarnessSessionIdentifier,
)
from dreamcatcher.harnesses import HARNESS_ADAPTERS

# How long a successful harness process may take to expose its final output
# after it exits. A reader normally settles immediately on the result event or
# pipe EOF. This bound is for an escaped descendant that keeps the pipe open.
_FINAL_OUTPUT_CAPTURE_TIMEOUT_SECONDS = 5

# How often a live round checks whether the web process asked it to stop.
_STOP_REQUEST_POLL_INTERVAL_SECONDS = 1
_AGENT_ROUND_RECORD_NAME = "round.json"


@dataclass(frozen=True, kw_only=True)
class AgentRoundPaths:
    """Provide the worktree and file paths for a numbered round.

    The round runs in its owner's worktree and writes into the directory its
    number selects under that owner's rounds directory. Keeping the number
    beside that parent makes one value authoritative for both the path and the
    record the round writes. The paths are available before the round creates
    any files.
    """

    worktree: Path
    rounds_directory: Path
    number: PositiveInt

    @property
    def directory(self) -> Path:
        """The directory holding this numbered round's files."""
        return self.rounds_directory / str(self.number)

    @property
    def prompt(self) -> Path:
        """The file holding what the round asked the harness to do."""
        return self.directory / "prompt.txt"

    @property
    def record(self) -> Path:
        """The file saying when the round started, and how it ended."""
        return self.directory / _AGENT_ROUND_RECORD_NAME

    @property
    def feed(self) -> Path:
        """The file holding the round as a reader reads it."""
        return self.directory / "feed.txt"

    @property
    def raw_output(self) -> Path:
        """The file holding the harness's own stdout, as it arrived."""
        return self.directory / "raw.jsonl"

    @property
    def round_input(self) -> Path:
        """The file holding the input that the round's owner delivered."""
        return self.directory / "inbox.json"

    @property
    def stop_request(self) -> Path:
        """The file asking this round to stop, when one has been requested."""
        return self.directory / "stop-request"

    @property
    def final_output(self) -> Path:
        """The file holding the final output that the harness reports, if any."""
        return self.directory / "final.md"


class HarnessSessionIdentifierRecorder(Protocol):
    """Record the harness session identifier that an agent round observes."""

    def __call__(self, *, identifier: str) -> None:
        """Record the identifier."""


class AgentRoundFinisher(Protocol):
    """Finish a successful round before its ending is recorded.

    Raising a `ReportableError` fails the round, and the round notes why in its
    feed.
    """

    def __call__(self, *, final_output: str | None) -> None:
        """Finish the round with the final output its harness reported, if any."""


@dataclass(frozen=True, kw_only=True)
class _AgentRoundHarness:
    """The harness command that a round runs, and the reader of its output."""

    adapter: HarnessAdapter
    invocation: HarnessInvocation
    record_harness_session_identifier: HarnessSessionIdentifierRecorder

    def read(self, *, line: str) -> HarnessOutput:
        """Return the output one line reports, recording any harness session in it."""
        output = self.adapter.read_output(line=line)
        identifier = output.harness_session_identifier
        if identifier is not None:
            self.record_harness_session_identifier(identifier=identifier)
        return output


class AssignmentRoundPurpose(StrEnum):
    """The kinds of assignment work that an agent round advances."""

    IMPLEMENT = "implement"
    ADDRESS_FEEDBACK = "address feedback"
    WRAP_UP = "wrap up"


class ConversationRoundPurpose(StrEnum):
    """The kind of conversation work that an agent round advances."""

    DISCUSS = "discuss"


# Every round records its purpose, so the shared record holds either owner's.
type _AgentRoundPurpose = AssignmentRoundPurpose | ConversationRoundPurpose


class AgentRoundOutcome(StrEnum):
    """The possible outcomes of an agent round."""

    RUNNING = "running"
    SUCCESSFUL = "successful"
    ERRORED = "errored"
    INTERRUPTED = "interrupted"
    STOPPED = "stopped"


class SuccessfulAgentRoundEnding(DreamcatcherDocument):
    """A successful agent round ending."""

    outcome: Literal[AgentRoundOutcome.SUCCESSFUL] = AgentRoundOutcome.SUCCESSFUL
    at: AwareDatetime
    status: Literal[0] = 0


class ErroredAgentRoundEnding(DreamcatcherDocument):
    """An agent round ending with an error exit, or a failure after a clean one.

    A round whose harness exited cleanly errors when its owner cannot finish it,
    and its reason says why.
    """

    outcome: Literal[AgentRoundOutcome.ERRORED] = AgentRoundOutcome.ERRORED
    at: AwareDatetime
    status: int
    reason: str | None = None

    @model_validator(mode="after")
    def _refuse_unexplained_success(self) -> Self:
        """Keep a clean exit out of an errored ending that gives no reason."""
        if self.status == 0 and self.reason is None:
            raise ValueError("an errored round cannot have exit status 0 and no reason")
        return self


class InterruptedAgentRoundEnding(DreamcatcherDocument):
    """An agent round ending without an observed exit."""

    outcome: Literal[AgentRoundOutcome.INTERRUPTED] = AgentRoundOutcome.INTERRUPTED


class StoppedAgentRoundEnding(DreamcatcherDocument):
    """An agent round ending at the user's request."""

    outcome: Literal[AgentRoundOutcome.STOPPED] = AgentRoundOutcome.STOPPED
    at: AwareDatetime


type _AgentRoundEnding = Annotated[
    SuccessfulAgentRoundEnding
    | ErroredAgentRoundEnding
    | InterruptedAgentRoundEnding
    | StoppedAgentRoundEnding,
    Field(discriminator="outcome"),
]


def _compose_agent_round_ending(
    *, at: datetime, status: int, failure: str | None = None
) -> SuccessfulAgentRoundEnding | ErroredAgentRoundEnding:
    """Return the terminal outcome observed when a harness exited.

    A failure is what stopped the owner finishing a round whose harness exited
    cleanly, and it errors the round.
    """
    if failure is not None:
        return ErroredAgentRoundEnding(at=at, status=status, reason=failure)
    if status == 0:
        return SuccessfulAgentRoundEnding(at=at)
    return ErroredAgentRoundEnding(at=at, status=status)


class AgentRoundRecord(DreamcatcherDocument):
    """Model an agent round's identity, purpose, recovery, and outcome."""

    number: PositiveInt
    purpose: _AgentRoundPurpose
    is_recovery: bool = False
    started: AwareDatetime
    pid: PositiveInt
    ending: _AgentRoundEnding | None = None

    @property
    def outcome(self) -> AgentRoundOutcome:
        """How far the round has got."""
        if self.ending is None:
            return AgentRoundOutcome.RUNNING
        return self.ending.outcome


def record_agent_round_interruption(
    *, record: AgentRoundRecord, path: Path
) -> AgentRoundRecord:
    """Record an interruption when a formerly running round has ended.

    A terminal record is already reconciled, so repeating the operation keeps
    that record unchanged.
    """
    if record.ending is not None:
        return record
    return _record_agent_round_ending(
        record=record, ending=InterruptedAgentRoundEnding(), path=path
    )


def record_agent_round_stop(
    *, record: AgentRoundRecord, path: Path, at: datetime
) -> AgentRoundRecord:
    """Record a requested stop when a formerly running round has ended.

    A terminal record is already reconciled, so repeating the operation keeps
    that record unchanged.
    """
    if record.ending is not None:
        return record
    return _record_agent_round_ending(
        record=record, ending=StoppedAgentRoundEnding(at=at), path=path
    )


def request_agent_round_stop(*, paths: "AgentRoundPaths") -> None:
    """Ask the live round at these paths to stop."""
    write_text(text="", path=paths.stop_request)


def _record_agent_round_ending(
    *, record: AgentRoundRecord, ending: _AgentRoundEnding, path: Path
) -> AgentRoundRecord:
    """Write and return a record with its terminal outcome."""
    ended_record = record.model_copy(update={"ending": ending})
    write_json(document=ended_record, path=path)
    return ended_record


@dataclass(frozen=True, kw_only=True)
class AgentRoundPlan[RoundInputT: DreamcatcherDocument]:
    """Describe the decisions and input that a new round executes."""

    purpose: _AgentRoundPurpose
    is_recovery: bool
    input: RoundInputT | None = None


@dataclass(frozen=True, kw_only=True)
class AgentRoundStartRequest:
    """Describe everything that the round boundary needs to start a round."""

    harness: AgentHarness
    launch_request: AgentRoundLaunchRequest
    harness_session_identifier: HarnessSessionIdentifier | None
    record_harness_session_identifier: HarnessSessionIdentifierRecorder
    finish_round: AgentRoundFinisher | None
    paths: "AgentRoundPaths"
    plan: AgentRoundPlan[DreamcatcherDocument]


def start_agent_round(
    *,
    request: AgentRoundStartRequest,
    clock: Callable[[], datetime] = read_current_time,
) -> "AgentRound":
    """Start a first or resumed round through its owner's harness."""
    harness_adapter = HARNESS_ADAPTERS[request.harness]
    if request.harness_session_identifier is None:
        invocation = harness_adapter.build_first_round(
            request=request.launch_request,
            final_output_path=request.paths.final_output,
        )
    else:
        invocation = harness_adapter.build_resumed_round(
            request=request.launch_request,
            harness_session_identifier=request.harness_session_identifier,
            final_output_path=request.paths.final_output,
        )
    return AgentRound(
        agent_work_identifier=request.launch_request.agent_work_identifier,
        harness=_AgentRoundHarness(
            adapter=harness_adapter,
            invocation=invocation,
            record_harness_session_identifier=(
                request.record_harness_session_identifier
            ),
        ),
        paths=request.paths,
        plan=request.plan,
        finish_round=request.finish_round,
        clock=clock,
    )


def read_agent_round_records(
    *, cache: DocumentCache, directory: Path
) -> list[AgentRoundRecord]:
    """Return round records under the directory, oldest first.

    The records determine the order. A directory without a record is not a
    round and is omitted.

    A terminal record has had both of its writes, and nothing writes it again,
    so the cache keeps it and a later read does not open it. A running record is
    opened on every read, because its ending may arrive later.
    """
    records = [
        _read_agent_round_record(cache=cache, path=record_path)
        for record_path in directory.glob(f"*/{_AGENT_ROUND_RECORD_NAME}")
    ]
    return sorted(records, key=lambda record: record.number)


def _read_agent_round_record(*, cache: DocumentCache, path: Path) -> AgentRoundRecord:
    """Return the record at path, or refuse one that its directory contradicts.

    The check runs on every read, so a record that the cache keeps is refused
    each time just as one that it opens.
    """
    record = cache.read_json(
        model=AgentRoundRecord,
        path=path,
        is_unchanging=lambda record: record.outcome is not AgentRoundOutcome.RUNNING,
    )
    if path.parent.name != str(record.number):
        raise ReportableError(
            f"{path} says it is round {record.number}, "
            f"but its directory names round {path.parent.name}."
        )
    return record


class AgentRound:
    """Run one agent round as a child of the daemon.

    Making one starts it. From then on the round runs on its own threads, and
    the daemon reads its state rather than waiting on it.
    """

    def __init__(
        self,
        *,
        agent_work_identifier: str,
        harness: _AgentRoundHarness,
        paths: AgentRoundPaths,
        plan: AgentRoundPlan[DreamcatcherDocument],
        finish_round: AgentRoundFinisher | None = None,
        clock: Callable[[], datetime] = read_current_time,
        wait_for_round_end: Callable[[float], bool] | None = None,
    ) -> None:
        """Run the harness as a round at the paths it was given.

        The input and prompt go to files of the round's own before its process
        starts, and the harness reads the prompt as its stdin. A prompt therefore
        reaches the harness as it was written however long it is and whatever it
        holds, and a reader can see afterwards what the round received. A failure
        to write either file stops the round before it starts.

        A round given a finisher lets its owner finish it before it records its
        ending.

        The stop-request watcher waits between its polls through
        `wait_for_round_end`, which is given the seconds to wait and answers
        whether the round ended first. By default it waits on the round's own
        ending. A caller that supplies its own decides when each poll happens.
        """
        self.agent_work_identifier = agent_work_identifier
        self.harness = harness
        self.finish_round = finish_round
        self.paths = paths
        self.clock = clock
        self.feed_renderer = FeedRenderer(worktree=paths.worktree, clock=clock)
        self.started_at = clock()
        self.forced_ending: _AgentRoundEnding | None = None
        self._round_ended = Flag()
        self._wait_for_round_end = wait_for_round_end or self._round_ended.wait
        self._final_output_settled = Flag()
        self._feed_write_lock = Lock()
        self._termination_lock = Lock()
        if plan.input is not None:
            write_json(document=plan.input, path=paths.round_input)
        write_text(text=harness.invocation.prompt, path=paths.prompt)
        remove_file(path=paths.final_output)
        self.harness_process = spawn_command(
            program=harness.invocation.program,
            arguments=harness.invocation.arguments,
            cwd=paths.worktree,
            stdin=paths.prompt,
        )
        try:
            self.record = AgentRoundRecord(
                number=paths.number,
                purpose=plan.purpose,
                is_recovery=plan.is_recovery,
                started=self.started_at,
                pid=self.harness_process.pid,
            )
            write_json(document=self.record, path=self.paths.record)
        except ReportableError:
            # A round nothing recorded is a round nothing will watch or find
            # again, so it does not run on.
            self.harness_process.kill()
            self.harness_process.wait()
            raise
        self._stream_readers = [
            Thread(
                target=self._read_stream_until_finished,
                kwargs={"read_stream": self._read_stdout},
                daemon=True,
            ),
            Thread(
                target=self._read_stream_until_finished,
                kwargs={"read_stream": self._read_stderr},
                daemon=True,
            ),
        ]
        for stream_reader in self._stream_readers:
            stream_reader.start()
        self._stop_request_watcher = Thread(
            target=self._watch_for_stop_request, daemon=True
        )
        self._stop_request_watcher.start()
        self._ending_recorder = Thread(
            target=self._record_ending_and_join_streams, daemon=True
        )
        self._ending_recorder.start()

    @property
    def is_alive(self) -> bool:
        """Whether the round is still running, finishing or recording its ending.

        A round that reads as finished has its record on disk. Its feed may
        still be growing, because the streams it reads can outlast the child.
        """
        return not self._round_ended.is_set()

    def wait(self) -> None:
        """Wait for the round to end and for everything it wrote to land.

        A harness descendant can keep an output pipe open indefinitely, so this
        method can wait indefinitely. The daemon uses `is_alive` and
        `end_for_daemon_shutdown` instead.
        """
        self._ending_recorder.join()

    def interrupt(self) -> None:
        """Interrupt the round and its contained process group or job.

        This returns as soon as the round has ended, and does not wait for the
        feed, so that a stream somebody else is still holding cannot hold up
        the daemon. A round whose harness has already exited is finished by
        its owner first.
        """
        self._end_process_tree(ending=InterruptedAgentRoundEnding())
        self._round_ended.wait()

    def end_for_daemon_shutdown(self) -> None:
        """End the round while preserving a pending user stop request.

        A stop request already written when shutdown begins is the reason this
        round ends, rather than an interruption the next daemon would recover.
        """
        if self.paths.stop_request.is_file():
            ending: _AgentRoundEnding = StoppedAgentRoundEnding(at=self.clock())
        else:
            ending = InterruptedAgentRoundEnding()
        self._end_process_tree(ending=ending)
        self._round_ended.wait()

    def _end_process_tree(self, *, ending: _AgentRoundEnding) -> None:
        """Record the forced ending and kill the remaining process tree.

        This acts only while the child's exit status is uncollected. The
        ending is set before the kill releases the ending recorder from
        `harness_process.wait()`. The first reason wins when shutdown and a user
        request arrive together.

        The child can exit between the exit-status check and the outcome update,
        which records that narrow race as the requested ending. Closing the
        race would require holding a lock across the blocking wait and would
        prevent a prompt stop.
        """
        with self._termination_lock:
            if self.forced_ending is not None:
                return
            if not self.harness_process.is_exit_status_uncollected:
                return
            self.forced_ending = ending
            self.harness_process.kill()

    def _watch_for_stop_request(self) -> None:
        """Stop the round promptly when its request file appears."""
        while not self._wait_for_round_end(_STOP_REQUEST_POLL_INTERVAL_SECONDS):
            if self.paths.stop_request.is_file():
                self._end_process_tree(ending=StoppedAgentRoundEnding(at=self.clock()))
                return

    def _read_stream_until_finished(self, *, read_stream: Callable[[], None]) -> None:
        """Read one output stream and interrupt the round if persistence fails.

        Stopping a stream reader would eventually fill the pipe and block the
        harness, so a write failure must end the round.
        """
        try:
            read_stream()
        except ReportableError:
            self.interrupt()

    def _read_stdout(self) -> None:
        try:
            for line in self.harness_process.out:
                append_text(text=line, path=self.paths.raw_output)
                output = self.harness.read(line=line)
                if output.final_output is not None:
                    write_text(text=output.final_output, path=self.paths.final_output)
                    self._final_output_settled.set()
                self._append_feed_events(line=line, events=output.events)
        finally:
            self._final_output_settled.set()

    def _read_stderr(self) -> None:
        for line in self.harness_process.err:
            self._append_feed_events(line=line, events=[FeedProse(text=line)])

    def _record_ending_and_join_streams(self) -> None:
        """Record the outcome when the child exits, then join its stream readers.

        A descendant can keep a pipe open indefinitely, so the terminal record
        is written before the stream readers finish.
        """
        try:
            status = self.harness_process.wait()
            failure = self._finish_round(status=status)
            if self.forced_ending is not None:
                self.record = _record_agent_round_ending(
                    record=self.record,
                    ending=self.forced_ending,
                    path=self.paths.record,
                )
            else:
                self.record = _record_agent_round_ending(
                    record=self.record,
                    ending=_compose_agent_round_ending(
                        at=self.clock(), status=status, failure=failure
                    ),
                    path=self.paths.record,
                )
        finally:
            # However the close went, the round has ended, so whoever is
            # waiting on it waits no longer, and whatever the pumps still have
            # to write is still written.
            self._round_ended.set()
            self._stop_request_watcher.join()
            for stream_reader in self._stream_readers:
                stream_reader.join()

    def _finish_round(self, *, status: int) -> str | None:
        """Let the owner finish a successful round, and return why it could not.

        A finisher that raises fails the round, and the feed says why too. An
        interrupted round is not finished.
        """
        if self.finish_round is None or status != 0 or self.forced_ending is not None:
            return None
        try:
            self.finish_round(final_output=self._read_final_output())
        except ReportableError as failure:
            self._append_feed_events(
                line="", events=[FeedNote(label="failed", detail=str(failure))]
            )
            return str(failure)
        return None

    def _read_final_output(self) -> str | None:
        """Return the harness's final output, once it has had time to land."""
        self._final_output_settled.wait(_FINAL_OUTPUT_CAPTURE_TIMEOUT_SECONDS)
        path = self.paths.final_output
        return read_text(path=path) if path.is_file() else None

    def _append_feed_events(self, *, line: str, events: list[FeedEvent]) -> None:
        """Append one output line's events while holding the feed write lock.

        Rendering happens under the same lock as the write. A line is stamped
        as it is rendered, so holding the lock across both keeps the stamps in
        the same order as the lines.

        If an event cannot render, the original harness line reaches the feed
        instead.
        """
        with self._feed_write_lock:
            try:
                written = "".join(
                    self.feed_renderer.render(event=event) for event in events
                )
            except Exception:
                written = self.feed_renderer.render(event=FeedProse(text=line))
            if written:
                append_text(text=written, path=self.paths.feed)
