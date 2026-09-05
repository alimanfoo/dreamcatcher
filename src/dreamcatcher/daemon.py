"""Run the daemon: hold the repo, and tick on the configured interval.

A tick looks once and launches at most one round. It weighs its own live rounds
against the cap first, which costs no GitHub call, then reads the sessions on
disk and works out what each of them needs next.

Open work goes before new work, and the most open of it first: a round that did
not finish is carried on, then a merged or closed pull request gets its last
round, then a session answers what the user posted. Only when no session needs
anything does the tick ask GitHub which labelled issues it could dispatch, and
dispatch the oldest one nothing stands in the way of.

Whatever it observed and decided goes into `last-tick.json`, so what the daemon
did not do, and why, is as readable as what it did.
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
from dreamcatcher.github import Unknown, identify_account, identify_repository
from dreamcatcher.harnesses import ADAPTERS
from dreamcatcher.lock import hold
from dreamcatcher.resumes import (
    Finding,
    Resume,
    judge_session,
    list_waiting,
    sort_resumes,
)
from dreamcatcher.rounds import Cause, Round
from dreamcatcher.sessions import (
    Session,
    advance_watermark,
    create_session,
    discard_session,
    read_sessions,
)
from dreamcatcher.state import CandidateIssue, LastTick, StateDirectory, Waiting

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
        harness CLIs, the state directory, the repository's name, the account
        gh is signed in as, the lock, and the sessions the sweep reads. A run
        refuses when any of those will not answer, rather than starting a loop
        that could never dispatch. Once the loop is going, a tick that fails
        records the failure and the next tick tries again.

        The repository and the account are read here and nowhere else. Neither
        can change while the daemon holds the repo, a run that cannot name the
        repository dispatches nothing, and the relay tells the user's posts
        from the session's own by the account.
        """
        self._locate_harnesses()
        self.state.bootstrap()
        repository = _refuse_unknown(
            identify_repository(self.state.root), "which repository this is"
        )
        account = _refuse_unknown(
            identify_account(), "which account gh is signed in as"
        )
        with hold(self.state.lock):
            self._sweep_orphans()
            try:
                with suppress(KeyboardInterrupt):
                    while True:
                        self.tick(repository, account)
                        self.wait(self.config.interval)
            finally:
                # Rounds die with the daemon by design, so this happens however
                # the run ends: on the user's interrupt, and on a failure the
                # daemon could not carry on from. A round that already ended
                # keeps the ending it recorded for itself.
                for running in self.rounds.values():
                    running.stop()

    def tick(self, repository: str, account: str) -> None:
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
            observed = self._decide_and_launch(repository, account, at)
        except ReportableError as failure:
            observed = LastTick(at=at, hold=str(failure))
        write_json(observed, self.state.last_tick)

    def _decide_and_launch(
        self, repository: str, account: str, at: datetime
    ) -> LastTick:
        """Launch at most one round, and return what the tick observed.

        The cap comes first and spends no GitHub call, because the daemon knows
        its own rounds. So a tick that was at the cap says so, rather than
        pretending that it looked.

        The cooldown holds every launch, a resume and a dispatch alike, but it
        holds no read. So a tick under it still says what each session is
        waiting on, rather than going quiet for the whole fifteen minutes.
        """
        if len(self.rounds) >= self.config.max_agents:
            return LastTick(at=at, hold=f"at cap: {len(self.rounds)} rounds running")
        sessions = read_sessions(self.state)
        found = self._reconcile(repository, account, sessions)
        cooling = _check_cooldown(sessions, at)
        if cooling is not None:
            return LastTick(at=at, hold=cooling, waiting=list_waiting(found))
        ready = sort_resumes([one for one in found if isinstance(one, Resume)])
        if ready:
            return self._resume_session(at, ready[0], found)
        judged = judge_issues(
            repository, self.config, {session.record.issue for session in sessions}
        )
        if isinstance(judged, Unknown):
            return LastTick(at=at, hold=judged.reason, waiting=list_waiting(found))
        return self._dispatch_oldest_issue(at, judged, list_waiting(found))

    def _reconcile(
        self, repository: str, account: str, sessions: list[Session]
    ) -> list[Finding]:
        """Return what each session that no round is running for needs next.

        A session the daemon is running a round for is working, not waiting, so
        the tick leaves it alone and spends no GitHub call on it.
        """
        found: list[Finding] = []
        for session in sessions:
            if session.key in self.rounds:
                continue
            needed = judge_session(repository, account, session)
            if needed is not None:
                found.append(needed)
        return found

    def _resume_session(
        self, at: datetime, resume: Resume, found: list[Finding]
    ) -> LastTick:
        """Carry the session on, and return what the tick observed.

        Everything else the tick found waits for a later tick, and says what it
        is waiting on. A launch that went wrong leaves all of it waiting, and
        the next tick tries the same session again.
        """
        try:
            self._launch_resume(resume)
        except ReportableError as failure:
            return LastTick(at=at, hold=str(failure), waiting=list_waiting(found))
        rest = [one for one in found if one is not resume]
        return LastTick(at=at, launched=resume.session.key, waiting=list_waiting(rest))

    def _launch_resume(self, resume: Resume) -> None:
        """Run the round the resume asks for, and hold it.

        The inbox lands before the round starts, because the prompt sends the
        session straight to it.

        The watermark moves once the round is running, and not before. A launch
        that never happened leaves the session's watermark where it was, so the
        next tick reads the same posts again rather than losing them. A round
        that no post woke moves nothing.
        """
        session = resume.session
        if resume.inbox is not None:
            write_json(resume.inbox, session.next_workspace.inbox)
        self._hold_round(session, resume.prompt, resume.cause)
        if resume.newest_post:
            advance_watermark(session, resume.newest_post)

    def _hold_round(self, session: Session, prompt: str, cause: Cause) -> None:
        """Run a round for the session, and hold it until it ends.

        The cause says how the harness starts. A dispatch opens a harness
        session of its own, and every other cause continues the one that the
        session already has, so no caller has to say which.

        Every round runs with the model and the effort the dispatch settled,
        which is why they come from the session's record and never from the
        config.
        """
        adapter = ADAPTERS[session.record.harness]
        launch = Launch(
            session=session.key,
            model=session.record.model,
            effort=session.record.effort,
            prompt=prompt,
        )
        invocation = (
            adapter.build_first_round(launch)
            if cause is Cause.DISPATCH
            else adapter.build_resumed_round(launch)
        )
        self.rounds[session.key] = Round(
            adapter, invocation, session.next_workspace, cause, clock=self.clock
        )

    def _dispatch_oldest_issue(
        self, at: datetime, judged: list[CandidateIssue], waiting: list[Waiting]
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
        return LastTick(at=at, launched=key, candidates=judged, waiting=waiting)

    def _launch_session(self, candidate: CandidateIssue, at: datetime) -> str:
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
        try:
            self._hold_round(session, session.record.prompt, Cause.DISPATCH)
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


def _refuse_unknown(named: str | Unknown, question: str) -> str:
    """Return what gh named, or refuse the run saying what it could not tell."""
    if isinstance(named, Unknown):
        raise ReportableError(f"dreamcatcher cannot tell {question}: {named.reason}")
    return named


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
