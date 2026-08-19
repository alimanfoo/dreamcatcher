"""Where dreamcatcher keeps its own files, inside the repo's main checkout."""

from dataclasses import dataclass
from pathlib import Path

STATE_DIRECTORY = ".dreamcatcher"


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

        The .gitignore is written every time. That heals a deleted one, and
        writing it needs no check of whether it is already there.
        """
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / ".gitignore").write_text("*\n", encoding="utf-8")
