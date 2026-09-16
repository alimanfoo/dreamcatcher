"""Run one agent round, and leave behind what it did.

A round is a harness command running as a child of the daemon, in the assignment's
worktree. It writes into a directory of its own as it goes.

`prompt.txt` holds what the round asked the harness to do, which the harness
reads as its stdin. `raw.jsonl` keeps the harness's own stdout as it arrived, so
that whoever works on a parser can read what the harness really sent. `feed.txt`
is that same stream read through the harness's adapter and rendered as lines a
person can read, with whatever the harness said on stderr among them, where it
happened. `round.json` says the round's number, purpose, recovery flag, process,
and outcome.

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
from typing import Annotated, Literal

from pydantic import Field, PositiveInt, field_validator

from dreamcatcher.adapters import Adapter, Invocation
from dreamcatcher.clock import now
from dreamcatcher.commands import spawn
from dreamcatcher.documents import (
    Document,
    append_text,
    read_json,
    write_json,
    write_text,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import Event, Prose, Renderer

# The file in a round's own directory saying what the round did.
RECORD = "round.json"


class RoundPurpose(StrEnum):
    """What work an agent round advances."""

    IMPLEMENT = "implement"
    ADDRESS_FEEDBACK = "address feedback"
    WRAP_UP = "wrap up"


class RoundOutcome(StrEnum):
    """How far an agent round has got."""

    RUNNING = "running"
    SUCCESSFUL = "successful"
    ERRORED = "errored"
    INTERRUPTED = "interrupted"


class SuccessfulAgentRoundEnding(Document):
    """An agent round that exited successfully."""

    outcome: Literal[RoundOutcome.SUCCESSFUL] = RoundOutcome.SUCCESSFUL
    at: datetime
    status: Literal[0] = 0


class ErroredAgentRoundEnding(Document):
    """An agent round that exited with an error."""

    outcome: Literal[RoundOutcome.ERRORED] = RoundOutcome.ERRORED
    at: datetime
    status: int

    @field_validator("status")
    @classmethod
    def _refuse_success(cls, status: int, /) -> int:
        """Keep a successful exit out of an errored ending."""
        if status == 0:
            raise ValueError("an errored round cannot have exit status 0")
        return status


class InterruptedAgentRoundEnding(Document):
    """An agent round stopped without an observed exit."""

    outcome: Literal[RoundOutcome.INTERRUPTED] = RoundOutcome.INTERRUPTED


type AgentRoundEnding = Annotated[
    SuccessfulAgentRoundEnding | ErroredAgentRoundEnding | InterruptedAgentRoundEnding,
    Field(discriminator="outcome"),
]


def compose_agent_round_ending(
    *, at: datetime, status: int
) -> SuccessfulAgentRoundEnding | ErroredAgentRoundEnding:
    """Return the terminal outcome observed when a harness exited."""
    if status == 0:
        return SuccessfulAgentRoundEnding(at=at)
    return ErroredAgentRoundEnding(at=at, status=status)


class AgentRoundRecord(Document):
    """The independent identity, purpose, recovery, and outcome of one round."""

    number: PositiveInt
    purpose: RoundPurpose
    is_recovery: bool = False
    started: datetime
    pid: PositiveInt
    ending: AgentRoundEnding | None = None

    @property
    def outcome(self) -> RoundOutcome:
        """How far the round has got."""
        if self.ending is None:
            return RoundOutcome.RUNNING
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
    ended = record.model_copy(update={"ending": ending})
    write_json(document=ended, path=path)
    return ended


@dataclass(frozen=True, kw_only=True)
class AgentRoundPlan:
    """The purpose and recovery decision that a new round executes."""

    purpose: RoundPurpose
    is_recovery: bool


@dataclass(frozen=True, kw_only=True)
class AgentRoundPaths:
    """A numbered round's worktree and files.

    The round runs in its assignment's worktree and writes into the directory
    its number selects under the assignment's rounds directory. Keeping the
    number beside that parent makes one value authoritative for both the path
    and the record the round writes.

    The files themselves are named here, beside the directory that holds them,
    so whoever has the paths can name a file before the round that writes it
    exists.
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
        return self.directory / RECORD

    @property
    def feed(self) -> Path:
        """The file holding the round as a reader reads it."""
        return self.directory / "feed.txt"

    @property
    def raw(self) -> Path:
        """The file holding the harness's own stdout, as it arrived."""
        return self.directory / "raw.jsonl"

    @property
    def inbox(self) -> Path:
        """The file holding the batch that the round was woken with."""
        return self.directory / "inbox.json"


class AgentRoundReader:
    """Read the records of an assignment's rounds, keeping the terminal ones.

    A terminal record has had both of its writes, and nothing writes it again,
    so a reader that has read one need never open it again.

    A running record is opened again on every read, because the record does
    not say whether its ending is still to come. A round that is running will
    record one, a round that nothing let finish never will, and both read the
    same.

    So a read costs a listing of the rounds directory, and one small read for
    each round of the assignment whose record has no terminal outcome — one while
    a round of the assignment is running, and none at all once every round has
    ended, however many rounds the assignment has run.
    """

    def __init__(self) -> None:
        """Set up a reader that has read nothing yet."""
        self._cache: dict[Path, AgentRoundRecord] = {}

    def read_records(self, *, directory: Path) -> list[AgentRoundRecord]:
        """Return the records of the rounds written under directory, oldest first.

        Each round writes into a directory of its own under this one, so a
        assignment passes the directory holding all of them.

        The order comes from the records themselves, so nothing here has to
        read a directory's name as a number. A directory with no record in it
        yet, and a directory that holds no rounds at all, both come back with
        nothing rather than as a failure.
        """
        records = [
            self._read_record(path=found) for found in directory.glob(f"*/{RECORD}")
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
        if record.outcome is not RoundOutcome.RUNNING:
            self._cache[path] = record
        return record


class AgentRound:
    """One round of an assignment, running as a child of the daemon.

    Making one starts it. From then on the round runs on its own threads, and
    the daemon reads its state rather than waiting on it.
    """

    def __init__(
        self,
        *,
        adapter: Adapter,
        invocation: Invocation,
        paths: AgentRoundPaths,
        plan: AgentRoundPlan,
        clock: Callable[[], datetime] = now,
    ) -> None:
        """Run the invocation as a round at the paths it was given.

        The prompt goes to a file of the round's own, and the harness reads
        that file as its stdin. So a prompt reaches the harness as it was
        written however long it is and whatever it holds, and a reader can see
        afterwards what the round was asked to do. A harness with nothing to
        read would sit and wait, so a prompt the round cannot write stops the
        round before it starts.
        """
        self.adapter = adapter
        self.paths = paths
        self.clock = clock
        self.renderer = Renderer(worktree=paths.worktree, clock=clock)
        self.started = clock()
        self.is_interrupted = False
        self._ended = Flag()
        self._writing = Lock()
        write_text(text=invocation.prompt, path=paths.prompt)
        self.child = spawn(
            program=invocation.program,
            arguments=invocation.arguments,
            cwd=paths.worktree,
            stdin=paths.prompt,
        )
        try:
            self.record = AgentRoundRecord(
                number=paths.number,
                purpose=plan.purpose,
                is_recovery=plan.is_recovery,
                started=self.started,
                pid=self.child.pid,
            )
            write_json(document=self.record, path=self.paths.record)
        except ReportableError:
            # A round nothing recorded is a round nothing will watch or find
            # again, so it does not run on.
            self.child.kill()
            self.child.wait()
            raise
        self._pumps = [
            Thread(
                target=self._pump,
                kwargs={"read": self._read_stdout},
                daemon=True,
            ),
            Thread(
                target=self._pump,
                kwargs={"read": self._read_stderr},
                daemon=True,
            ),
        ]
        for pump in self._pumps:
            pump.start()
        self._closing = Thread(target=self._close, daemon=True)
        self._closing.start()

    @property
    def is_alive(self) -> bool:
        """Whether the round is still running, or still recording its ending.

        A round that reads as finished has its record on disk. Its feed may
        still be growing, because the streams it reads can outlast the child.
        """
        return not self._ended.is_set()

    def wait(self) -> None:
        """Wait for the round to end and for everything it wrote to land.

        Waiting for the feed means waiting for both streams to reach their end,
        and a process the harness left behind can hold one open for as long as
        it likes, so this can wait for ever. Nothing the daemon does waits like
        this: `is_alive` and `stop` read and wait for the record alone.
        """
        self._closing.join()

    def stop(self) -> None:
        """End the round now, and everything it started.

        This returns as soon as the round has ended, and does not wait for the
        feed, so that a stream somebody else is still holding cannot hold up
        the daemon.
        """
        self._interrupt()
        self._ended.wait()

    def _interrupt(self) -> None:
        """End the round while it is still running, so it reads as interrupted.

        A child that has already gone finished by itself keeps the observed
        ending that `_close` writes for it, so this leaves that record alone
        rather than sending an assignment back over a round it has done.

        The mark goes on before the kill, because the kill is what makes
        `_close` return from `child.wait()`. So `_close` reads a mark this
        made, and reordering the two would let it write an ending for a round
        the daemon interrupted.

        One window stays open. The child can go after `child.is_running` has
        answered and before the mark goes on, and a round that has just
        finished then reads as interrupted. Reading the exit status would not
        settle it, because on Windows a killed child leaves the status a
        harness that failed would leave, for the reason `teardown` gives. A
        lock is no help either: `_close` would have to hold it across
        `child.wait()`, and then a stop would wait for the child to finish by
        itself, which is what a stop is there to avoid.
        """
        if self.child.is_running:
            self.is_interrupted = True
            self.child.kill()

    def _pump(self, *, read: Callable[[], None]) -> None:
        """Read one of the round's streams, and end the round if that fails.

        A round that cannot write its own files has nothing to show for itself.
        It would also hang: a reader that stops reading fills the pipe, the
        harness blocks on its next write, and nothing ever ends the round. So
        the round is ended here. A child that had already gone ended the round
        by itself and keeps its ending, however short the feed came out.
        """
        try:
            read()
        except ReportableError:
            self._interrupt()

    def _read_stdout(self) -> None:
        """Keep each line that the harness streams, and write what it says."""
        for line in self.child.out:
            append_text(text=line, path=self.paths.raw)
            self._append(line=line, events=self.adapter.read(line=line))

    def _read_stderr(self) -> None:
        """Write what the harness says on stderr, among the lines around it."""
        for line in self.child.err:
            self._append(line=line, events=[Prose(text=line)])

    def _close(self) -> None:
        """Record how the round ended as soon as its child has gone.

        The pumps are left to catch up afterwards. A pipe reaches its end only
        when every process holding it has closed it, and a process the harness
        left behind can hold one for as long as it likes, so a record that
        waited for the pumps could wait for ever. The child says how the round
        ended, so the record is written as soon as the child has gone, and the
        feed catches up.
        """
        try:
            status = self.child.wait()
            if self.is_interrupted:
                self.record = record_agent_round_interruption(
                    record=self.record, path=self.paths.record
                )
            else:
                self.record = _record_agent_round_ending(
                    record=self.record,
                    ending=compose_agent_round_ending(at=self.clock(), status=status),
                    path=self.paths.record,
                )
        finally:
            # However the close went, the round has ended, so whoever is
            # waiting on it waits no longer, and whatever the pumps still have
            # to write is still written.
            self._ended.set()
            for pump in self._pumps:
                pump.join()

    def _append(self, *, line: str, events: list[Event]) -> None:
        """Add what one line says to the feed, letting one stream write at a time.

        Rendering happens under the same lock as the write. A line is stamped
        as it is rendered, so holding the lock across both keeps the stamps in
        the same order as the lines.

        Rendering an event fails when the event holds something other than
        text. A line the feed cannot render is written out as the harness sent
        it, so one bad line costs one line.
        """
        with self._writing:
            try:
                written = "".join(self.renderer.render(event=event) for event in events)
            except Exception:
                written = self.renderer.render(event=Prose(text=line))
            if written:
                append_text(text=written, path=self.paths.feed)
