"""Run the daemon: hold the repo, and tick on the configured interval."""

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from time import sleep

from dreamcatcher.clock import now
from dreamcatcher.commands import locate
from dreamcatcher.config import Harness, read_config
from dreamcatcher.documents import write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.harnesses import ADAPTERS
from dreamcatcher.lock import hold
from dreamcatcher.state import LastTick, StateDirectory


class Daemon:
    """The foreground process watching one repo.

    The clock and the wait are the daemon's own, so a test can pin the time and
    end the loop.
    """

    def __init__(
        self,
        root: Path,
        harness: Harness,
        clock: Callable[[], datetime] = now,
        wait: Callable[[float], None] = sleep,
    ) -> None:
        """Set the daemon up for the repo checked out at root."""
        if not (root / ".git").is_dir():
            raise ReportableError(
                f"Start dreamcatcher from a repository's main checkout. "
                f"{root} is not one."
            )
        self.harness = harness
        self.config = read_config(root)
        self.state = StateDirectory(root)
        self.clock = clock
        self.wait = wait

    def run(self) -> None:
        """Hold the repo and tick until the user interrupts."""
        self._locate_harnesses()
        self.state.bootstrap()
        with hold(self.state.lock), suppress(KeyboardInterrupt):
            while True:
                self.tick()
                self.wait(self.config.interval)

    def _locate_harnesses(self) -> None:
        """Refuse the run when a harness it could dispatch to is not installed.

        Every harness a mapping can settle a label on is looked up, not just
        the one the run named, because a label carrying one harness block runs
        on that harness whatever the run named. Without this a missing CLI
        would read as a round that fails every fifteen minutes, since the hold
        after a failure cannot tell a misconfiguration from a blip.
        """
        for harness in sorted({self.harness, *self.config.mapped_harnesses}):
            locate(ADAPTERS[harness].program)

    def tick(self) -> None:
        """Record that a tick happened."""
        write_json(LastTick(at=self.clock()), self.state.last_tick)
