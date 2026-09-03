"""Where dreamcatcher keeps its own files, and what those files hold."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dreamcatcher.documents import Document, write_text

STATE_DIRECTORY = ".dreamcatcher"


class LastTick(Document):
    """When the daemon's most recent tick ran.

    The tick's own time is in here rather than read from the file, so copying a
    state directory cannot make a stale tick look fresh.
    """

    at: datetime


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
