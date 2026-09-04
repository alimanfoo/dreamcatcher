"""Run the daemon: hold the repo, and tick on the configured interval.

A tick looks once and launches at most one round. It weighs its own live rounds
against the cap first, which costs no GitHub call, then reads the sessions on
disk, then asks GitHub which labelled issues it could dispatch, and dispatches
the oldest one nothing stands in the way of. Whatever it observed and decided
goes into `last-tick.json`, so what the daemon did not do, and why, is as
readable as what it did.
"""

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from time import sleep

import psutil

from dreamcatcher import teardown
from dreamcatcher.adapters import Launch
from dreamcatcher.clock import now
from dreamcatcher.commands import locate
from dreamcatcher.config import Harness, read_config
from dreamcatcher.documents import write_json
from dreamcatcher.eligibility import judge_issues
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Unknown, identify
from dreamcatcher.harnesses import ADAPTERS
from dreamcatcher.lock import hold
from dreamcatcher.rounds import Round
from dreamcatcher.sessions import create_session, read_sessions
from dreamcatcher.state import Candidate, LastTick, StateDirectory

# What a round that a tick dispatched says woke it.
DISPATCHED = "dispatched"


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
        # The rounds this daemon is running, by the key of the session each
        # belongs to. They are what the cap counts, and what the daemon ends as
        # it goes down.
        self.rounds: dict[str, Round] = {}

    def run(self) -> None:
        """Hold the repo and tick until the user interrupts."""
        self._locate_harnesses()
        self.state.bootstrap()
        repository = self._identify()
        with hold(self.state.lock):
            self._sweep_orphans()
            try:
                with suppress(KeyboardInterrupt):
                    while True:
                        self.tick(repository)
                        self.wait(self.config.interval)
            finally:
                self._stop_rounds()

    def tick(self, repository: str) -> None:
        """Look once, launch at most one round, and record what happened.

        A round that has ended is forgotten first, so the cap counts what is
        running now.

        A tick that failed still leaves the evidence where the user can read
        it, and the next tick tries again. A daemon that ended on a full disk
        or a GitHub outage would leave the sessions it holds to nobody.
        """
        self.rounds = {
            key: running for key, running in self.rounds.items() if running.is_alive
        }
        at = self.clock()
        try:
            observed = self._decide(repository, at)
        except ReportableError as failure:
            observed = LastTick(at=at, held=str(failure))
        write_json(observed, self.state.last_tick)

    def _identify(self) -> str:
        """Return the repository that GitHub knows this checkout as.

        A run reads this once, as it starts. It cannot change while the daemon
        holds the repo, and a run that cannot name it can do nothing at all, so
        the run refuses here rather than failing every tick.
        """
        named = identify(self.state.root)
        if isinstance(named, Unknown):
            raise ReportableError(
                f"dreamcatcher cannot tell which repository this is: {named.reason}"
            )
        return named

    def _decide(self, repository: str, at: datetime) -> LastTick:
        """Launch at most one round, and return what the tick observed.

        The cap comes first and spends no GitHub call, because the daemon knows
        its own rounds. So a tick that was at the cap says so, rather than
        pretending that it looked.
        """
        if len(self.rounds) >= self.config.max_agents:
            return LastTick(at=at, held=f"at cap: {len(self.rounds)} rounds running")
        sessions = read_sessions(self.state)
        judged = judge_issues(
            repository, self.config, {session.record.issue for session in sessions}
        )
        if isinstance(judged, Unknown):
            return LastTick(at=at, held=judged.reason)
        return self._dispatch(at, judged)

    def _dispatch(self, at: datetime, judged: list[Candidate]) -> LastTick:
        """Dispatch the oldest issue that nothing stands in the way of.

        A tick launches one round, so every other eligible issue waits for a
        later tick. Every candidate is written down in the order it would go,
        and that order is the only place its turn is recorded.
        """
        eligible = [candidate for candidate in judged if candidate.is_eligible]
        if not eligible:
            return LastTick(at=at, candidates=judged)
        key = self._launch(eligible[0], at)
        return LastTick(at=at, dispatched=key, candidates=judged)

    def _launch(self, candidate: Candidate, at: datetime) -> str:
        """Cut a session for the candidate, run its first round, and hold it."""
        session = create_session(
            self.state,
            self.config.mappings[candidate.label],
            self.harness,
            candidate.issue,
            at,
        )
        adapter = ADAPTERS[session.record.harness]
        launch = Launch(
            session=session.key,
            model=session.record.model,
            effort=session.record.effort,
            prompt=session.record.prompt,
        )
        self.rounds[session.key] = Round(
            adapter,
            adapter.first_round(launch),
            session.next_workspace,
            DISPATCHED,
            clock=self.clock,
        )
        return session.key

    def _stop_rounds(self) -> None:
        """End every round the daemon still holds, and all they started.

        Rounds die with the daemon by design, so this runs however the run
        ends: on the user's interrupt, and on a failure the daemon could not
        carry on from. A round that already ended keeps the ending it recorded
        for itself.
        """
        for running in self.rounds.values():
            running.stop()

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

    def _sweep_orphans(self) -> None:
        """End whatever a daemon that ran before this one left running.

        Rounds die with the daemon that started them, so a round still running
        here means the daemon that started it went down without ending it,
        which a crash or a kill does. A round whose record says how it ended
        is over, and so is a round with no ending whose pid no process holds.
        Both of those are left alone, and a round with no ending reads as
        interrupted, which a later tick carries on.

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
        for session in read_sessions(self.state):
            for record in session.rounds:
                if record.ended is None and psutil.pid_exists(record.pid):
                    teardown.end(record.pid)
