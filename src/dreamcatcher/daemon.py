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
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

from dreamcatcher import teardown
from dreamcatcher.adapters import Launch
from dreamcatcher.clock import now
from dreamcatcher.commands import locate
from dreamcatcher.config import Harness, read_config
from dreamcatcher.documents import write_json
from dreamcatcher.eligibility import judge_issues
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Unknown, identify_repository
from dreamcatcher.harnesses import ADAPTERS
from dreamcatcher.lock import hold
from dreamcatcher.rounds import Round
from dreamcatcher.sessions import (
    Session,
    create_session,
    discard_session,
    read_sessions,
)
from dreamcatcher.state import Candidate, LastTick, StateDirectory, Waiting

# What a round that a tick dispatched says woke it.
DISPATCHED = "dispatched"

# How long the daemon holds every launch once a round has failed, dispatches
# and retries alike. There is no cause detection behind this and no schedule:
# the failure worth spending nothing on is a usage limit, which belongs to the
# account and so hits every session at once, and a passing blip costs at most
# this long of an idle daemon.
COOLDOWN = timedelta(minutes=15)


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
        """Hold the repo and tick until the user interrupts.

        Everything a run cannot do without is settled before the loop: the
        harness CLIs, the state directory, the repository's name, the lock, and
        the sessions the sweep reads. A run refuses when any of those will not
        answer, rather than starting a loop that could never dispatch. Once the
        loop is going, a tick that fails records the failure and the next tick
        tries again.
        """
        self._locate_harnesses()
        self.state.bootstrap()
        repository = self._identify_repository()
        with hold(self.state.lock):
            self._sweep_orphans()
            try:
                with suppress(KeyboardInterrupt):
                    while True:
                        self.tick(repository)
                        self.wait(self.config.interval)
            finally:
                # Rounds die with the daemon by design, so this happens however
                # the run ends: on the user's interrupt, and on a failure the
                # daemon could not carry on from. A round that already ended
                # keeps the ending it recorded for itself.
                for running in self.rounds.values():
                    running.stop()

    def tick(self, repository: str) -> None:
        """Look once, launch at most one round, and record what happened.

        A round that has ended is forgotten first, so the cap counts what is
        running now.

        A tick that failed still leaves the evidence where the user can read
        it, and the next tick tries again, rather than the daemon ending and
        leaving the sessions it holds to nobody.

        Writing that evidence down is the exception. A daemon that cannot write
        `last-tick.json` has no way left to say anything at all, so that
        failure ends the run with a message the user can act on, and the rounds
        it was holding end with it and read as interrupted.
        """
        self.rounds = {
            key: running for key, running in self.rounds.items() if running.is_alive
        }
        at = self.clock()
        try:
            observed = self._decide_and_launch(repository, at)
        except ReportableError as failure:
            observed = LastTick(at=at, hold=str(failure))
        write_json(observed, self.state.last_tick)

    def _identify_repository(self) -> str:
        """Return the repository that GitHub knows this checkout as.

        A run reads this once, as it starts. It cannot change while the daemon
        holds the repo, and a run that cannot name it can do nothing at all, so
        the run refuses here rather than failing every tick.
        """
        named = identify_repository(self.state.root)
        if isinstance(named, Unknown):
            raise ReportableError(
                f"dreamcatcher cannot tell which repository this is: {named.reason}"
            )
        return named

    def _decide_and_launch(self, repository: str, at: datetime) -> LastTick:
        """Launch at most one round, and return what the tick observed.

        The cap comes first and spends no GitHub call, because the daemon knows
        its own rounds. So a tick that was at the cap says so, rather than
        pretending that it looked.
        """
        if len(self.rounds) >= self.config.max_agents:
            return LastTick(at=at, hold=f"at cap: {len(self.rounds)} rounds running")
        sessions = read_sessions(self.state)
        waiting = _list_waiting(sessions, self.rounds)
        cooling = _check_cooldown(sessions, at)
        if cooling is not None:
            return LastTick(at=at, hold=cooling, waiting=waiting)
        judged = judge_issues(
            repository, self.config, {session.record.issue for session in sessions}
        )
        if isinstance(judged, Unknown):
            return LastTick(at=at, hold=judged.reason, waiting=waiting)
        return self._dispatch_oldest_issue(at, judged, waiting)

    def _dispatch_oldest_issue(
        self, at: datetime, judged: list[Candidate], waiting: list[Waiting]
    ) -> LastTick:
        """Dispatch the oldest issue that nothing stands in the way of.

        A tick launches one round, so every other eligible issue waits for a
        later tick. Every candidate is written down in the order it would go,
        and that order is the only place its turn is recorded.
        """
        eligible = [candidate for candidate in judged if candidate.is_eligible]
        if not eligible:
            return LastTick(at=at, candidates=judged, waiting=waiting)
        try:
            key = self._launch_session(eligible[0], at)
        except ReportableError as failure:
            # The tick looked, and everything it saw is worth keeping. Only the
            # launch went wrong, and the next tick tries the same issue again.
            return LastTick(
                at=at, hold=str(failure), candidates=judged, waiting=waiting
            )
        return LastTick(at=at, dispatched=key, candidates=judged, waiting=waiting)

    def _launch_session(self, candidate: Candidate, at: datetime) -> str:
        """Cut a session for the candidate, run its first round, and hold it.

        A session whose round will not start is taken away again, because a
        session with no round claims its issue and can never advance by
        itself. So a dispatch that got part way leaves nothing behind, and the
        issue is free for the next tick to try again.
        """
        session = create_session(
            self.state,
            self.config.label_mappings[candidate.label],
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
        try:
            self.rounds[session.key] = Round(
                adapter,
                adapter.build_first_round(launch),
                session.next_workspace,
                DISPATCHED,
                clock=self.clock,
            )
        except ReportableError:
            discard_session(self.state, session.record)
            raise
        return session.key

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
        for session in read_sessions(self.state):
            for record in session.rounds:
                if record.ending is None:
                    teardown.end(record.pid)


def _check_cooldown(sessions: list[Session], at: datetime) -> str | None:
    """Return the hold every launch is under, when a round failed lately enough.

    The words are the evidence the record left and not a diagnosis of it. A
    usage limit and a passing blip both read as a round that failed, and both
    cost the same wait, so nothing here has to tell them apart.
    """
    failed = [
        record.ending
        for session in sessions
        for record in session.rounds
        if record.ending is not None and record.ending.is_failed
    ]
    if not failed:
        return None
    latest = max(failed, key=lambda ending: ending.at)
    until = latest.at + COOLDOWN
    if at >= until:
        return None
    return (
        f"the last round failed (exit {latest.status}) "
        f"— next attempt at {until:%H:%M} UTC"
    )


def _list_waiting(sessions: list[Session], running: dict[str, Round]) -> list[Waiting]:
    """Return every session whose most recent round nothing has carried on.

    A session the daemon is running a round for is working, not waiting.
    Carrying a waiting session on is a later phase's, so a tick here says only
    what each one is waiting on.
    """
    waiting = []
    for session in sessions:
        reason = None if session.key in running else _check_rounds(session)
        if reason is not None:
            waiting.append(
                Waiting(session=session.key, issue=session.record.issue, reason=reason)
            )
    return waiting


def _check_rounds(session: Session) -> str | None:
    """Return what the session's rounds leave it waiting on.

    A session with no round at all is one whose dispatch could not start its
    first round and could not take the session away again either, so it is
    waiting for a first round rather than for another one.
    """
    if not session.rounds:
        return "no round has run yet"
    ending = session.rounds[-1].ending
    if ending is None:
        return "the last round was interrupted"
    if ending.is_failed:
        return f"the last round failed (exit {ending.status})"
    return None
