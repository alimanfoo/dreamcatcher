"""Run the foreground daemon for one Dreamcatcher instance."""

from __future__ import annotations

import sys
from contextlib import suppress
from time import sleep
from typing import TYPE_CHECKING

from dreamcatcher import teardown
from dreamcatcher.clock import Wait, now
from dreamcatcher.commands import locate
from dreamcatcher.config import Harness, read_config
from dreamcatcher.documents import write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Unknown, identify_account, identify_repository
from dreamcatcher.harnesses import ADAPTERS
from dreamcatcher.lock import hold
from dreamcatcher.scheduler import Scheduler
from dreamcatcher.sessions import read_sessions
from dreamcatcher.state import LastTick, StateDirectory
from dreamcatcher.words import describe_time

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from dreamcatcher.rounds import Round


def _write_output(*, line: str) -> None:
    """Write and flush one line, escaped for the stream that receives it."""
    try:
        encoding = sys.stdout.encoding or "utf-8"
        safe_line = line.encode(encoding, errors="backslashreplace").decode(encoding)
        print(safe_line, flush=True)
    except (OSError, UnicodeError) as error:
        raise ReportableError("Could not write daemon output.") from error


class Daemon:
    """The foreground process watching one repo.

    The clock and the wait are the daemon's own, so a test can pin the time and
    end the loop.
    """

    def __init__(
        self,
        *,
        root: Path,
        harness: Harness,
        clock: Callable[[], datetime] = now,
        wait: Wait = sleep,
    ) -> None:
        """Set the daemon up for the repo checked out at root."""
        if not (root / ".git").is_dir():
            raise ReportableError(
                f"Start dreamcatcher from a repository's main checkout. "
                f"{root} is not one."
            )
        self.harness = harness
        self.config = read_config(root=root)
        self.state = StateDirectory(root=root)
        self.clock = clock
        self.wait = wait
        # The rounds this daemon is running, by the key of the session each
        # belongs to. They are what the cap counts, and what the daemon ends as
        # it goes down.
        self.rounds: dict[str, Round] = {}

    def run(self) -> None:
        """Hold the repo and tick until the user interrupts.

        Everything a run cannot do without is settled before the loop: the
        harness CLIs, the state directory, the repository's name, the account
        gh is signed in as, the lock, and the sessions the sweep reads. A run
        refuses when any of those will not answer, rather than starting a loop
        that could never dispatch. Once the loop is going, a tick that fails
        records the failure and the next tick tries again.

        The repository and the account are read here and nowhere else. Neither
        can change while the daemon holds the repo, a run that cannot name the
        repository dispatches nothing, and the relay reads every post against
        the account before the marker tells the user's posts from the
        session's own.
        """
        self._locate_harnesses()
        self.state.bootstrap()
        repository = _refuse_unknown(
            named=identify_repository(root=self.state.root),
            question="which repository this is",
        )
        account = _refuse_unknown(
            named=identify_account(), question="which account gh is signed in as"
        )
        scheduler = Scheduler(
            repository=repository,
            account=account,
            config=self.config,
            state=self.state,
            harness=self.harness,
            clock=self.clock,
            rounds=self.rounds,
        )
        with hold(path=self.state.lock):
            self._sweep_orphans()
            at = self.clock()
            _write_output(line=f"{describe_time(at=at)}  dreamcatcher is running")
            try:
                with suppress(KeyboardInterrupt):
                    while True:
                        self.tick(scheduler=scheduler, at=at)
                        self.wait(self.config.interval)
                        at = self.clock()
            finally:
                # Rounds die with the daemon by design, so this happens however
                # the run ends: on the user's interrupt, and on a failure the
                # daemon could not carry on from. A round that already ended
                # keeps the ending it recorded for itself.
                for running in self.rounds.values():
                    running.stop()

    def tick(self, *, scheduler: Scheduler, at: datetime) -> None:
        """Run one scheduler tick, then record and report its result.

        A tick that failed still leaves the evidence where the user can read
        it, and the next tick tries again, rather than the daemon ending and
        leaving the sessions it holds to nobody.

        Writing that evidence down is the exception. A daemon that cannot write
        `last-tick.json` has no way left to say anything at all, so that
        failure ends the run with a message the user can act on, and the rounds
        it was holding end with it.
        """
        try:
            observed = scheduler.tick(at=at)
        except ReportableError as failure:
            observed = LastTick(at=at, hold=str(failure))
        write_json(document=observed, path=self.state.last_tick)
        if observed.launched is not None:
            outcome = f"launched round for {observed.launched}"
        elif observed.hold is not None:
            outcome = f"held: {' '.join(observed.hold.split())}"
        else:
            outcome = "nothing launched"
        _write_output(line=f"{describe_time(at=observed.at)}  {outcome}")

    def _locate_harnesses(self) -> None:
        """Refuse the run when a harness it could dispatch to is not installed.

        Every harness a route can settle a label on is looked up, not just
        the one the run named, because a label carrying one harness block runs
        on that harness whatever the run named. Without this a missing CLI
        would read as a round that fails every fifteen minutes, since the hold
        after a failure cannot tell a misconfiguration from a blip.
        """
        for harness in sorted({self.harness, *self.config.routed_harnesses}):
            locate(program=ADAPTERS[harness].program)

    def _sweep_orphans(self) -> None:
        """End whatever a daemon that ran before this one left running.

        Rounds die with the daemon that started them, so a round still running
        here means the daemon that started it went down without ending it,
        which a crash or a kill does. A round whose record says how it ended is
        over and is left alone. Every other round is ended, and ending a round
        that has already gone does nothing, so nothing here has to ask whether
        one has. Its record keeps no ending either way, and a round with no
        ending reads as interrupted, which a later tick carries on.

        The pid is the one the record kept, and the operating system was free
        to give it to somebody else once the daemon that recorded it died.
        Ending it reaches that pid's own process group, and a pid handed on to
        a stranger is almost never a group of its own, so it names no group and
        nothing happens. That leaves a window, and it is accepted, as the same
        window is where the tool ends its own rounds.

        Windows cannot reach this at all: a round there sits in a job that
        empties itself when the daemon's last handle on it closes, so no round
        outlives its daemon and there is never anything to end.
        """
        for session in read_sessions(state=self.state):
            for record in session.rounds:
                if not record.is_complete:
                    teardown.end(pid=record.pid)


def _refuse_unknown(*, named: str | Unknown, question: str) -> str:
    """Return what gh named, or refuse the run saying what it could not tell."""
    if isinstance(named, Unknown):
        raise ReportableError(f"dreamcatcher cannot tell {question}: {named.reason}")
    return named
