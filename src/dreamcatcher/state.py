"""Where dreamcatcher keeps its own files, and what those files hold."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import Field

from dreamcatcher.documents import Document, write_text

STATE_DIRECTORY = ".dreamcatcher"


class CandidateIssue(Document):
    """A labelled issue that is a candidate for dispatch.

    A candidate is an issue under a single label, where the label decides which
    harness runs it and which prompt it starts with.

    An issue that carries two mapped labels becomes a candidate under each of
    them, and so cannot be dispatched. The user has to resolve this ambiguity
    first by removing one of the labels.

    If a candidate could not be dispatched, the `reason` attribute describes
    why. `reason` is `None` when the tick found nothing preventing dispatch,
    and that is what `is_eligible` reports.
    """

    issue: int
    label: str
    reason: str | None = None

    @property
    def is_eligible(self) -> bool:
        """Whether nothing stands in the way of dispatching this issue."""
        return self.reason is None


class Waiting(Document):
    """A session where the last round did not complete successfully and so is
    waiting for another round to continue.

    The reason is a string that says why the session's most recent round ended,
    in the words that the round's own record kept. A round may have been
    interrupted, or it may have failed with a status, and the reason carries
    that status. A run of usage-limit failures is therefore recognisable from
    this reason string.
    """

    session: str
    issue: int
    reason: str


class LastTick(Document):
    """What the daemon's most recent tick observed and decided.

    The record carries the tick's own time rather than taking it from the file,
    so copying a state directory cannot make a stale tick look fresh.

    A tick launches at most one round, and the key of that round's session is
    what it launched. A tick that launched nothing at all says in one line what
    held it. A tick that was held at the cap looked no further than its own
    rounds, so it records nothing else, rather than suggesting that it had
    looked.

    The candidates are every labelled issue that the tick weighed, in the order
    they would be dispatched. A candidate with nothing in its way that the tick
    did not dispatch is waiting for a later tick, and its place in the list is
    its turn.
    """

    at: datetime
    hold: str | None = None
    launched: str | None = None
    candidates: list[CandidateIssue] = Field(default_factory=list)
    waiting: list[Waiting] = Field(default_factory=list)


@dataclass(frozen=True)
class StateDirectory:
    """The directory holding everything dreamcatcher knows about one repo."""

    root: Path

    @property
    def path(self) -> Path:
        """The directory itself."""
        return self.root / STATE_DIRECTORY

    @property
    def lock(self) -> Path:
        """The file the running daemon writes its pid to."""
        return self.path / "daemon.pid"

    @property
    def last_tick(self) -> Path:
        """The file the daemon overwrites with what each tick decided."""
        return self.path / "last-tick.json"

    @property
    def worktrees(self) -> Path:
        """The directory holding a worktree for each session, named by its key.

        Every worktree that dreamcatcher makes lives under here, wherever the
        checkout would otherwise put its worktrees. A worktree under here is
        therefore one of dreamcatcher's, and that is how the daemon tells its
        own work from everyone else's.
        """
        return self.path / "worktrees"

    @property
    def sessions(self) -> Path:
        """The directory holding each session's own files, named by its key."""
        return self.path / "sessions"

    def bootstrap(self) -> None:
        """Create the directory, ignoring itself, so git never sees its files.

        Writing the .gitignore is what creates the directory. Bootstrap writes
        it on every run, so a directory that was deleted comes back.
        """
        write_text("*\n", self.path / ".gitignore")
