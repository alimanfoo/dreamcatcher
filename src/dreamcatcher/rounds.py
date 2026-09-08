"""Run one round of a session, and leave behind what it did.

A round is a harness command running as a child of the daemon, in the session's
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
from threading import Event, Lock, Thread

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
from dreamcatcher.feed import Prose, Renderer

# The file in a round's own directory saying what the round did.
RECORD = "round.json"


class Cause(StrEnum):
    """What woke a round.

    The daemon decides one of these for every round it launches, and the
    round's record keeps it. A reader of a session's rounds then reads the
    story of why each one ran, and the tick reads what a round was for without
    reading prose: a session whose final round has run is a session that is
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

    The cause is what woke the round: the dispatch that opened the session, or
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


@dataclass(frozen=True)
class Workspace:
    """Where one round runs, and the files it writes as it goes.

    Both paths come from the session the round belongs to: the round runs in
    that session's worktree, and writes into a directory of its own under the
    session's own files. They travel together because no round ever has one
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
    """Read the records of a session's rounds, keeping the ones that are fixed.

    A round records itself twice and no more: once as it starts, and once as it
    ends, carrying its ending. So a record that carries an ending has had both
    of its writes, and a reader that has read one need never open it again.

    A record with no ending is opened again on every read, because the record
    does not say whether its ending is still to come. A round that is running
    will record one, a round that nothing let finish never will, and both read
    the same.

    So a read costs a listing of the rounds directory, and one small read for
    each round of the session that has recorded no ending — one while a round
    of the session is running, and none at all once every round has ended,
    however many rounds the session has run.
    """

    def __init__(self) -> None:
        """Set up a reader that has read nothing yet."""
        self._kept: dict[Path, RoundRecord] = {}

    def read(self, directory: Path) -> list[RoundRecord]:
        """Return the records of the rounds written under directory, oldest first.

        Each round writes into a directory of its own under this one, so a
        session passes the directory holding all of them.

        The order comes from the records themselves, so nothing here has to
        read a directory's name as a number. A directory with no record in it
        yet, and a directory that holds no rounds at all, both come back with
        nothing rather than as a failure.
        """
        records = [self._read(found) for found in directory.glob(f"*/{RECORD}")]
        return sorted(records, key=lambda record: record.started)

    def _read(self, path: Path) -> RoundRecord:
        """Return what the record at path says, and keep it once it is fixed."""
        kept = self._kept.get(path)
        if kept is not None:
            return kept
        record = read_json(RoundRecord, path)
        if record.ending is not None:
            self._kept[path] = record
        return record


class Round:
    """One round of a session, running as a child of the daemon.

    Making one starts it. From then on the round runs on its own threads, and
    the daemon reads its state rather than waiting on it.
    """

    def __init__(
        self,
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
        self.renderer = Renderer(workspace.worktree, clock=clock)
        self.started = clock()
        self.is_interrupted = False
        self._ended = Event()
        self._writing = Lock()
        write_text(invocation.prompt, workspace.prompt)
        self.child = spawn(
            *invocation.command, cwd=workspace.worktree, stdin=workspace.prompt
        )
        try:
            write_json(
                RoundRecord(started=self.started, pid=self.child.pid, cause=cause),
                self.workspace.record,
            )
        except ReportableError:
            # A round nothing recorded is a round nothing will watch or find
            # again, so it does not run on.
            self.child.kill()
            self.child.wait()
            raise
        self._pumps = [
            Thread(target=self._pump, args=(self._read_stdout,), daemon=True),
            Thread(target=self._pump, args=(self._read_stderr,), daemon=True),
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
        alone rather than sending a session back over a round it has done.

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

    def _pump(self, read: Callable[[], None]) -> None:
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
            append_text(line, self.workspace.raw)
            self._append(line, self._render)

    def _read_stderr(self) -> None:
        """Write what the harness says on stderr, among the lines around it."""
        for line in self.child.err:
            self._append(line, self._pass_through)

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
                    RoundRecord(
                        started=self.started,
                        pid=self.child.pid,
                        cause=self.cause,
                        ending=Ending(at=self.clock(), status=status),
                    ),
                    self.workspace.record,
                )
        finally:
            # However the close went, the round has ended, so whoever is
            # waiting on it waits no longer, and whatever the pumps still have
            # to write is still written.
            self._ended.set()
            for pump in self._pumps:
                pump.join()

    def _render(self, line: str) -> str:
        """Return the feed lines that one line of the harness's stream becomes.

        Reading a line through an adapter never raises. Rendering what the
        adapter read is a second step, and that step does fail when an event
        holds something other than text. A line the feed cannot render is
        written out as the harness sent it, so one bad line costs one line.
        """
        try:
            return "".join(
                self.renderer.render(event) for event in self.adapter.read(line)
            )
        except Exception:
            return self.renderer.render(Prose(line))

    def _pass_through(self, line: str) -> str:
        """Return the feed line one line of the harness's stderr becomes."""
        return self.renderer.render(Prose(line))

    def _append(self, line: str, render: Callable[[str], str]) -> None:
        """Add what one line says to the feed, letting one stream write at a time.

        Rendering happens under the same lock as the write. A line is stamped
        as it is rendered, so holding the lock across both keeps the stamps in
        the same order as the lines.
        """
        with self._writing:
            written = render(line)
            if written:
                append_text(written, self.workspace.feed)
