"""Run the daemon: hold the repo, and tick on the configured interval."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Self

from dreamcatcher.config import Config, Harness, read_config
from dreamcatcher.documents import write_json
from dreamcatcher.errors import DreamcatcherError
from dreamcatcher.lock import hold
from dreamcatcher.state import LastTick, StateDirectory


class NotAMainCheckoutError(DreamcatcherError):
    """The user started the daemon outside a repo's main checkout."""


def now() -> datetime:
    """Return the time now, in UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class Daemon:
    """The foreground process watching one repo.

    The clock and the wait are the daemon's, so a test can pin the time and end
    the loop.
    """

    config: Config
    harness: Harness
    state: StateDirectory
    clock: Callable[[], datetime] = now
    wait: Callable[[float], None] = sleep

    @classmethod
    def for_checkout(cls, root: Path, harness: Harness | None) -> Self:
        """Return the daemon for the repo checked out at root.

        A harness of None means the one the repo's config names.
        """
        if not (root / ".git").is_dir():
            raise NotAMainCheckoutError(
                f"Start dreamcatcher from a repository's main checkout. "
                f"{root} is not one."
            )
        config = read_config(root)
        return cls(
            config=config,
            harness=harness or config.harness,
            state=StateDirectory(root),
        )

    def run(self) -> None:
        """Hold the repo and tick until the user interrupts."""
        self.state.bootstrap()
        with hold(self.state.lock), suppress(KeyboardInterrupt):
            while True:
                self.tick()
                self.wait(self.config.interval)

    def tick(self) -> None:
        """Record that a tick happened."""
        write_json(LastTick(at=self.clock()), self.state.last_tick)
