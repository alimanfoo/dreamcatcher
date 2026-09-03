"""Run one round of a session, and leave behind what it did.

A round is a harness command running as a child of the daemon, in the session's
worktree. It writes into a directory of its own as it goes.

`raw.jsonl` keeps the harness's own stdout as it arrived, so that whoever works
on a parser can read what the harness really sent. `feed.txt` is that same stream
read through the harness's adapter and rendered as lines a person can read, with
whatever the harness said on stderr among them, where it happened. `round.json`
says when the round started, what process it ran as, and how it ended.

The daemon watches a round rather than waiting for it, so a round reads its own
streams on threads of its own, and records its own ending on another.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread

from dreamcatcher.adapters import Adapter
from dreamcatcher.clock import now
from dreamcatcher.commands import spawn
from dreamcatcher.documents import Document, append_text, write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import Prose, Renderer


class RoundRecord(Document):
    """What a round says about itself, written at each end of the round.

    A record with no ending is the signature of a round that was interrupted.
    The daemon that was watching it exited before the round could say how it
    ended, so a later tick reads the round as one to carry on.
    """

    started: datetime
    pid: int
    ended: datetime | None = None
    status: int | None = None


class Round:
    """One round of a session, running as a child of the daemon.

    Making one starts it. From then on the round runs on its own threads, and
    the daemon reads its state rather than waiting on it.
    """

    def __init__(
        self,
        adapter: Adapter,
        command: list[str],
        worktree: Path,
        directory: Path,
        clock: Callable[[], datetime] = now,
    ) -> None:
        """Start the command as a round in worktree, recording into directory."""
        self.adapter = adapter
        self.directory = directory
        self.clock = clock
        self.renderer = Renderer(worktree, clock=clock)
        self.started = clock()
        self.interrupted = False
        self._writing = Lock()
        self.child = spawn(*command, cwd=worktree)
        try:
            write_json(
                RoundRecord(started=self.started, pid=self.child.pid), self.record
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
    def record(self) -> Path:
        """The file saying when the round started, and how it ended."""
        return self.directory / "round.json"

    @property
    def feed(self) -> Path:
        """The file holding the round as a reader reads it."""
        return self.directory / "feed.txt"

    @property
    def raw(self) -> Path:
        """The file holding the harness's own stdout, as it arrived."""
        return self.directory / "raw.jsonl"

    @property
    def alive(self) -> bool:
        """Whether the round is still running, or still recording its ending."""
        return self._closing.is_alive()

    def wait(self) -> None:
        """Wait for the round to end and for its record to say how."""
        self._closing.join()

    def stop(self) -> None:
        """End the round now, and everything it started, leaving it unfinished.

        A round somebody stopped did not finish, so nothing writes an ending to
        its record. That is what a later tick reads as a round to carry on.
        """
        self.interrupted = True
        self.child.kill()
        self.wait()

    def _pump(self, read: Callable[[], None]) -> None:
        """Read one of the round's streams, and end the round if that fails.

        A round that cannot write its own files has nothing to show for itself.
        Worse, a reader that stopped reading would leave the harness blocked on
        a full pipe for ever, and the round would never end. So the round ends
        here, and its record keeps no ending, which reads as one to carry on.
        """
        try:
            read()
        except ReportableError:
            self.interrupted = True
            self.child.kill()

    def _read_stdout(self) -> None:
        """Keep each line that the harness streams, and write what it says."""
        for line in self.child.out:
            append_text(line, self.raw)
            self._append(line, self._rendered)

    def _read_stderr(self) -> None:
        """Write what the harness says on stderr, among the lines around it."""
        for line in self.child.err:
            self._append(line, self._passed)

    def _close(self) -> None:
        """Wait for the round to end, then record how it ended."""
        status = self.child.wait()
        for pump in self._pumps:
            pump.join()
        if not self.interrupted:
            write_json(
                RoundRecord(
                    started=self.started,
                    pid=self.child.pid,
                    ended=self.clock(),
                    status=status,
                ),
                self.record,
            )

    def _rendered(self, line: str) -> str:
        """Return the feed lines that one line of the harness's stream becomes.

        An adapter promises that reading a line raises nothing. Rendering what
        it read is a second step, and that one fails when an event holds
        anything other than text. So a line that the feed cannot write costs
        the reader that one line, and arrives as the harness sent it.
        """
        try:
            return "".join(
                self.renderer.render(event) for event in self.adapter.read(line)
            )
        except Exception:
            return self.renderer.render(Prose(line))

    def _passed(self, line: str) -> str:
        """Return the feed line one line of the harness's stderr becomes."""
        return self.renderer.render(Prose(line))

    def _append(self, line: str, render: Callable[[str], str]) -> None:
        """Add what one line says to the feed, one of the two streams at a time.

        The line is rendered under the same lock that the write takes, so the
        stamp a line carries and the order it lands in agree.
        """
        with self._writing:
            written = render(line)
            if written:
                append_text(written, self.feed)
