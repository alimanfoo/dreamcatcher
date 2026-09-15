"""Run one round of an assignment, and leave behind what it did.

A round is a harness command running as a child of the daemon, in the assignment's
worktree. It writes into a directory of its own as it goes.

`prompt.txt` holds what the round asked the harness to do, which the harness
reads as its stdin. `raw.jsonl` keeps the harness's own stdout as it arrived, so
that whoever works on a parser can read what the harness really sent. `feed.txt`
is that same stream read through the harness's adapter and rendered as lines a
person can read, with whatever the harness said on stderr among them, where it
happened. `round.json`
says when the round started, what process it ran as, what caused it, and how it
ended.

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

from pydantic import PositiveInt

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


class Cause(StrEnum):
    """What woke a round.

    The daemon decides one of these for every round it launches, and the
    round's record keeps it. A reader of an assignment's rounds then reads the
    story of why each one ran, and the tick reads what a round was for without
    reading prose: an assignment whose final round has run is an assignment that is
    done.

    The words are what a feed opens a round with, after the round's number.
    The batch that woke a round is not in them: an inbox resume and a final
    round each keep theirs in the `inbox.json` beside the record.
    """

    DISPATCH = "dispatched"
    CARRY_ON = "carried on"
    POSTS = "new posts"
    FINAL = "final round"


class Ending(Document):
    """How a round ended: when it ended, and the status it ended with.

    The time and the status are one value because a round knows both at once
    and neither without the other, so nothing has to ask whether they agree.
    """

    at: datetime
    status: int

    @property
    def is_failed(self) -> bool:
        """Whether the round ended with a status that says it failed."""
        return self.status != 0


class RoundRecord(Document):
    """What a round says about itself, written at each end of the round.

    The cause is what woke the round: the dispatch that opened the assignment, or
    whatever a later tick found for it to do.

    A record with no ending means the round was still going when something
    ended it. Either the daemon went down and stopped it, or the round could
    not write its own files. Both leave work half done, so a later tick resumes
    the round rather than starting a new one.
    """

    started: datetime
    pid: PositiveInt
    cause: Cause
    ending: Ending | None = None

    @property
    def is_complete(self) -> bool:
        """Whether the round recorded how it ended.

        A round records itself twice and no more: once as it starts, and once
        as it ends, carrying its ending. So a record that has an ending has had
        both of its writes and is complete, and nothing writes it again.

        A round that nothing let finish records no ending, so its record is
        never complete, however long ago the round stopped. What the round
        ended with is another matter. A round that failed recorded that it
        failed, which completes its record and leaves its work unfinished.
        """
        return self.ending is not None


@dataclass(frozen=True, kw_only=True)
class Workspace:
    """Where one round runs, and the files it writes as it goes.

    Both paths come from the assignment the round belongs to: the round runs in
    that assignment's worktree, and writes into a directory of its own under the
    assignment's own files. They travel together because no round ever has one
    without the other.

    The files themselves are named here, beside the directory that holds them,
    so whoever has a workspace can name a file of the round before the round
    that writes it exists.
    """

    worktree: Path
    directory: Path

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


class RoundReader:
    """Read the records of an assignment's rounds, keeping the complete ones.

    A complete record has had both of its writes, and nothing writes it again,
    so a reader that has read one need never open it again.

    An incomplete record is opened again on every read, because the record does
    not say whether its ending is still to come. A round that is running will
    record one, a round that nothing let finish never will, and both read the
    same.

    So a read costs a listing of the rounds directory, and one small read for
    each round of the assignment whose record is incomplete — one while a round of
    the assignment is running, and none at all once every round has ended, however
    many rounds the assignment has run.
    """

    def __init__(self) -> None:
        """Set up a reader that has read nothing yet."""
        self._cache: dict[Path, RoundRecord] = {}

    def read_records(self, *, directory: Path) -> list[RoundRecord]:
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
        return sorted(records, key=lambda record: record.started)

    def _read_record(self, *, path: Path) -> RoundRecord:
        """Return what the record at path says, and cache it once it is complete."""
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        record = read_json(model=RoundRecord, path=path)
        if record.is_complete:
            self._cache[path] = record
        return record


class Round:
    """One round of an assignment, running as a child of the daemon.

    Making one starts it. From then on the round runs on its own threads, and
    the daemon reads its state rather than waiting on it.
    """

    def __init__(
        self,
        *,
        adapter: Adapter,
        invocation: Invocation,
        workspace: Workspace,
        cause: Cause,
        clock: Callable[[], datetime] = now,
    ) -> None:
        """Run the invocation as a round in the workspace it was given.

        The prompt goes to a file of the round's own, and the harness reads
        that file as its stdin. So a prompt reaches the harness as it was
        written however long it is and whatever it holds, and a reader can see
        afterwards what the round was asked to do. A harness with nothing to
        read would sit and wait, so a prompt the round cannot write stops the
        round before it starts.
        """
        self.adapter = adapter
        self.workspace = workspace
        self.cause = cause
        self.clock = clock
        self.renderer = Renderer(worktree=workspace.worktree, clock=clock)
        self.started = clock()
        self.is_interrupted = False
        self._ended = Flag()
        self._writing = Lock()
        write_text(text=invocation.prompt, path=workspace.prompt)
        self.child = spawn(
            program=invocation.program,
            arguments=invocation.arguments,
            cwd=workspace.worktree,
            stdin=workspace.prompt,
        )
        try:
            write_json(
                document=RoundRecord(
                    started=self.started, pid=self.child.pid, cause=cause
                ),
                path=self.workspace.record,
            )
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
        """End the round while it is still running, so it reads as unfinished.

        A round nobody let finish has nothing to show for itself, so nothing
        writes an ending to its record, and a later tick sees an interrupted
        round and resumes it. A child that has already gone finished by itself
        and keeps the ending `_close` writes for it, so this leaves that record
        alone rather than sending an assignment back over a round it has done.

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
            append_text(text=line, path=self.workspace.raw)
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
            if not self.is_interrupted:
                write_json(
                    document=RoundRecord(
                        started=self.started,
                        pid=self.child.pid,
                        cause=self.cause,
                        ending=Ending(at=self.clock(), status=status),
                    ),
                    path=self.workspace.record,
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
                append_text(text=written, path=self.workspace.feed)
