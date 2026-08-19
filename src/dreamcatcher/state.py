"""Where dreamcatcher keeps its own files, and what those files hold."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dreamcatcher.documents import Document

STATE_DIRECTORY = ".dreamcatcher"


class LastTick(Document):
    """What the daemon's most recent tick observed and decided.

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

    def bootstrap(self) -> None:
        """Create the directory, ignoring itself, so git never sees its files.

        Bootstrap writes the .gitignore every time. That heals a deleted one.
        It also saves checking whether the file is already there.
        """
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / ".gitignore").write_text("*\n", encoding="utf-8")
