"""Where dreamcatcher keeps its own files, and what those files hold."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import Field

from dreamcatcher.documents import Document, write_text

STATE_DIRECTORY = ".dreamcatcher"


class Candidate(Document):
    """One labelled issue a tick weighed, and what stood in its way.

    A candidate is an issue under one label, because the label settles the
    harness that runs it and the prompt it starts with. An issue carrying two
    mapped labels is a candidate under each of them, and neither can go.

    A candidate with no reason is one that nothing stood in the way of.
    """

    issue: int
    label: str
    reason: str | None = None

    @property
    def is_eligible(self) -> bool:
        """Whether nothing stands in the way of dispatching this issue."""
        return self.reason is None


class LastTick(Document):
    """What the daemon's most recent tick observed and decided.

    The tick's own time is in here rather than read from the file, so copying a
    state directory cannot make a stale tick look fresh.

    A tick that held every launch says why in one line, and looked no further.
    Otherwise the candidates are every labelled issue the tick weighed, in the
    order they would go. A candidate with nothing in its way that the tick did
    not dispatch is one waiting for a later tick, and its place in the list is
    its turn.
    """

    at: datetime
    held: str | None = None
    dispatched: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)


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

        Every worktree that dreamcatcher makes lives under here, whatever the
        checkout's own directory habits are. So a worktree under here is one of
        dreamcatcher's, and that is how the daemon tells its own work from
        everyone else's.
        """
        return self.path / "worktrees"

    @property
    def sessions(self) -> Path:
        """The directory holding each session's own files, named by its key."""
        return self.path / "sessions"

    def bootstrap(self) -> None:
        """Create the directory, ignoring itself, so git never sees its files.

        Writing the .gitignore is what makes the directory, and bootstrap writes
        it every time, so a deleted one heals.
        """
        write_text("*\n", self.path / ".gitignore")
