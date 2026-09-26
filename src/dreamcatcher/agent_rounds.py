"""Run agent rounds and persist their inputs, output, and outcomes.

A round runs a harness command in its owner's worktree. It writes into a
numbered directory of its own.

`prompt.txt` supplies the harness's stdin. `inbox.json` holds any input that the
round's owner delivers. `raw.jsonl` preserves harness stdout, `feed.txt` renders
both streams for the user, `final.md` keeps the final result the harness
reports, and `round.json` records identity, purpose, recovery, process, and
outcome.

The daemon watches a round rather than waiting for it, so a round reads its own
streams on threads of its own, and records its own ending on another.
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
    DreamcatcherDocument,
    append_text,
    read_json,
    read_text,
    write_json,
    write_text,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedEvent, FeedNote, FeedProse, FeedRenderer
from dreamcatcher.github import ConversationComment, PullRequestState, UserPost
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    HarnessAdapter,
    HarnessInvocation,
    HarnessOutput,
    HarnessSessionIdentifier,
)
from dreamcatcher.harnesses import HARNESS_ADAPTERS

# The file in a round's own directory saying what the round did.
AGENT_ROUND_RECORD_NAME = "round.json"

# How long a successful harness process may take to expose its final result
# after it exits. A reader normally settles immediately on the result event or
# pipe EOF. This bound is for an escaped descendant that keeps the pipe open.
FINAL_OUTPUT_CAPTURE_TIMEOUT_SECONDS = 5


class HarnessSessionIdentifierRecorder(Protocol):
    """Record the harness session identifier that an agent round observes."""

    def __call__(self, *, identifier: str) -> None:
        """Record the identifier."""


class AgentRoundFinisher(Protocol):
    """Finish a round whose harness exited successfully, before the round ends.

    Raising a `ReportableError` fails the round, and the round notes why in its
    feed.
    """

    def __call__(self, *, final_output: str | None) -> None:
        """Finish the round with the final output its harness reported, if any."""


@dataclass(frozen=True, kw_only=True)
class AgentRoundHarness:
    """The harness command that a round runs, and the reader of its output."""

    adapter: HarnessAdapter
    invocation: HarnessInvocation
    record_harness_session_identifier: HarnessSessionIdentifierRecorder

    def read(self, *, line: str) -> HarnessOutput:
        """Record the harness session that one line reports, and return the line."""
        output = self.adapter.read_output(line=line)
        identifier = output.harness_session_identifier
        if identifier is not None:
            self.record_harness_session_identifier(identifier=identifier)
        return output


class AgentAssignmentRoundPurpose(StrEnum):
    """The kinds of assignment work that an agent round advances."""

    IMPLEMENT = "implement"
    ADDRESS_FEEDBACK = "address feedback"
    WRAP_UP = "wrap up"


class IssueConversationRoundPurpose(StrEnum):
    """The kind of conversation work that an agent round advances."""

    DISCUSS = "discuss"


# Every round records its purpose, so the shared record holds either owner's.
type AgentRoundPurpose = AgentAssignmentRoundPurpose | IssueConversationRoundPurpose


class AgentRoundOutcome(StrEnum):
    """The possible outcomes of an agent round."""

    RUNNING = "running"
    SUCCESSFUL = "successful"
    ERRORED = "errored"
    INTERRUPTED = "interrupted"


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


type AgentRoundEnding = Annotated[
    SuccessfulAgentRoundEnding | ErroredAgentRoundEnding | InterruptedAgentRoundEnding,
    Field(discriminator="outcome"),
]


def compose_agent_round_ending(
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
    purpose: AgentRoundPurpose
    is_recovery: bool = False
    started: AwareDatetime
    pid: PositiveInt
    ending: AgentRoundEnding | None = None

    @property
    def outcome(self) -> AgentRoundOutcome:
        """How far the round has got."""
        if self.ending is None:
            return AgentRoundOutcome.RUNNING
        return self.ending.outcome


def record_agent_round_interruption(
    *, record: AgentRoundRecord, path: Path
) -> AgentRoundRecord:
    """Record interruption when a formerly running round has stopped.

    A terminal record is already reconciled, so repeating the operation keeps
    that record unchanged.
    """
    if record.ending is not None:
        return record
    return _record_agent_round_ending(
        record=record, ending=InterruptedAgentRoundEnding(), path=path
    )


def _record_agent_round_ending(
    *, record: AgentRoundRecord, ending: AgentRoundEnding, path: Path
) -> AgentRoundRecord:
    """Write and return a record with its terminal outcome."""
    ended_record = record.model_copy(update={"ending": ending})
    write_json(document=ended_record, path=path)
    return ended_record


class AgentAssignmentRoundInput(DreamcatcherDocument):
    """Model the pull request state and user posts delivered to an assignment round."""

    pull_request_state: PullRequestState
    user_posts: list[UserPost]


class IssueConversationInput(DreamcatcherDocument):
    """Model the trusted issue input frozen for one conversation round."""

    issue: int
    title: str | None = Field(default=None, exclude_if=lambda value: value is None)
    body: str | None = Field(default=None, exclude_if=lambda value: value is None)
    comments: list[ConversationComment]
    revision: str


@dataclass(frozen=True, kw_only=True)
class AgentRoundPlan[RoundInputT: DreamcatcherDocument]:
    """Describe the decisions and input that a new round executes."""

    purpose: AgentRoundPurpose
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
    plan: (
        AgentRoundPlan[AgentAssignmentRoundInput]
        | AgentRoundPlan[IssueConversationInput]
    )


def start_agent_round(
    *,
    request: AgentRoundStartRequest,
    clock: Callable[[], datetime] = read_current_time,
) -> "AgentRound":
    """Start a first or resumed round through its owner's harness."""
    harness_adapter = HARNESS_ADAPTERS[request.harness]
    if request.harness_session_identifier is None:
        invocation = harness_adapter.build_first_round(request=request.launch_request)
    else:
        invocation = harness_adapter.build_resumed_round(
            request=request.launch_request,
            harness_session_identifier=request.harness_session_identifier,
        )
    return AgentRound(
        harness=AgentRoundHarness(
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


@dataclass(frozen=True, kw_only=True)
class AgentRoundPaths:
    """Provide the worktree and file paths for a numbered round.

    The round runs in its owner's worktree and writes into the directory its
    number selects under that owner's rounds directory. Keeping the
    number beside that parent makes one value authoritative for both the path
    and the record the round writes.

    The paths are available before the round creates any files.
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
        return self.directory / AGENT_ROUND_RECORD_NAME

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
    def final_output(self) -> Path:
        """The file holding the final result that the harness reports, if any."""
        return self.directory / "final.md"


class AgentRoundReader:
    """Read round records and cache terminal records.

    A terminal record has had both of its writes, and nothing writes it again,
    so a reader that has read one need never open it again.

    Running records are reopened on every read because their endings may arrive
    later. Each read lists the rounds directory and opens only records that have
    no cached terminal outcome.
    """

    def __init__(self) -> None:
        """Set up a reader that has read nothing yet."""
        self._cache: dict[Path, AgentRoundRecord] = {}

    def read_records(self, *, directory: Path) -> list[AgentRoundRecord]:
        """Return round records under the directory, oldest first.

        The records determine the order. A directory without a record is not a
        round and is omitted.
        """
        records = [
            self._read_record(path=record_path)
            for record_path in directory.glob(f"*/{AGENT_ROUND_RECORD_NAME}")
        ]
        return sorted(records, key=lambda record: record.number)

    def _read_record(self, *, path: Path) -> AgentRoundRecord:
        """Return what the record at path says, and cache it once it is terminal."""
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        record = read_json(model=AgentRoundRecord, path=path)
        if path.parent.name != str(record.number):
            raise ReportableError(
                f"{path} says it is round {record.number}, "
                f"but its directory names round {path.parent.name}."
            )
        if record.outcome is not AgentRoundOutcome.RUNNING:
            self._cache[path] = record
        return record


class AgentRound:
    """Run one agent round as a child of the daemon.

    Making one starts it. From then on the round runs on its own threads, and
    the daemon reads its state rather than waiting on it.
    """

    def __init__(
        self,
        *,
        harness: AgentRoundHarness,
        paths: AgentRoundPaths,
        plan: AgentRoundPlan[AgentAssignmentRoundInput]
        | AgentRoundPlan[IssueConversationInput],
        finish_round: AgentRoundFinisher | None = None,
        clock: Callable[[], datetime] = read_current_time,
    ) -> None:
        """Run the harness as a round at the paths it was given.

        The input and prompt go to files of the round's own before its process
        starts, and the harness reads the prompt as its stdin. A prompt therefore
        reaches the harness as it was written however long it is and whatever it
        holds, and a reader can see afterwards what the round received. A failure
        to write either file stops the round before it starts.

        A round given a finisher lets its owner finish it before it records its
        ending.
        """
        self.harness = harness
        self.finish_round = finish_round
        self.paths = paths
        self.clock = clock
        self.feed_renderer = FeedRenderer(worktree=paths.worktree, clock=clock)
        self.started_at = clock()
        self.is_interrupted = False
        self._round_ended = Flag()
        self._final_output_settled = Flag()
        self._feed_write_lock = Lock()
        if plan.input is not None:
            write_json(document=plan.input, path=paths.round_input)
        write_text(text=harness.invocation.prompt, path=paths.prompt)
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
        method can wait indefinitely. The daemon uses `is_alive` and `stop`
        instead.
        """
        self._ending_recorder.join()

    def stop(self) -> None:
        """End the round and its contained process group or job.

        This returns as soon as the round has ended, and does not wait for the
        feed, so that a stream somebody else is still holding cannot hold up
        the daemon. A round whose harness has already exited is finished by
        its owner first.
        """
        self._interrupt()
        self._round_ended.wait()

    def _interrupt(self) -> None:
        """Mark the round interrupted and end its remaining process tree.

        This acts only while the child's exit status is uncollected. The
        interruption flag is set before the kill releases the ending recorder
        from `harness_process.wait()`.

        The child can exit between the exit-status check and the flag update,
        which records that narrow race as an interruption. Closing the race
        would require holding a lock across the blocking wait and would prevent
        a prompt stop.
        """
        if self.harness_process.is_exit_status_uncollected:
            self.is_interrupted = True
            self.harness_process.kill()

    def _read_stream_until_finished(self, *, read_stream: Callable[[], None]) -> None:
        """Read one output stream and interrupt the round if persistence fails.

        Stopping a stream reader would eventually fill the pipe and block the
        harness, so a write failure must end the round.
        """
        try:
            read_stream()
        except ReportableError:
            self._interrupt()

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
            if self.is_interrupted:
                self.record = record_agent_round_interruption(
                    record=self.record, path=self.paths.record
                )
            else:
                self.record = _record_agent_round_ending(
                    record=self.record,
                    ending=compose_agent_round_ending(
                        at=self.clock(), status=status, failure=failure
                    ),
                    path=self.paths.record,
                )
        finally:
            # However the close went, the round has ended, so whoever is
            # waiting on it waits no longer, and whatever the pumps still have
            # to write is still written.
            self._round_ended.set()
            for stream_reader in self._stream_readers:
                stream_reader.join()

    def _finish_round(self, *, status: int) -> str | None:
        """Let the owner finish a successful round, and return why it could not.

        A finisher that raises fails the round, and the feed says why too. An
        interrupted round is not finished.
        """
        if self.finish_round is None or status != 0 or self.is_interrupted:
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
        self._final_output_settled.wait(FINAL_OUTPUT_CAPTURE_TIMEOUT_SECONDS)
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
