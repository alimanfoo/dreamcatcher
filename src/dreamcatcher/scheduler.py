"""Schedule one round of agent work at a time.

A scheduler tick reads the sessions on disk and asks GitHub which labelled
issues could be dispatched. It weighs the active rounds against the cap, works
out what each session needs next, and launches at most one round.

Open work goes before new work, and the most open of it first: a round that did
not finish is carried on, then a merged or closed pull request gets its last
round, then a session answers what the user posted. Only when no session needs
anything does an uncapped tick dispatch the oldest candidate that no session
and no pull request has claimed and no open issue blocks.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from dreamcatcher.adapters import Launch
from dreamcatcher.config import Config, Harness
from dreamcatcher.documents import write_json
from dreamcatcher.eligibility import judge_issues
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Unknown
from dreamcatcher.harnesses import ADAPTERS
from dreamcatcher.rounds import Cause, Round
from dreamcatcher.sessions import (
    Session,
    advance_watermark,
    create_session,
    discard_session,
    read_sessions,
)
from dreamcatcher.state import CandidateIssue, LastTick, StateDirectory, WaitingSession
from dreamcatcher.wakeups import (
    Finding,
    Wakeup,
    compose_wait,
    judge_session,
    list_waiting,
    sort_wakeups,
)

# How long scheduling holds every launch once a round has failed, dispatches
# and retries alike. There is no cause detection behind this and no schedule:
# the failure worth spending nothing on is a usage limit, which belongs to the
# account and so hits every session at once, and a passing blip costs at most
# this long of an idle daemon.
COOLDOWN = timedelta(minutes=15)


def _check_cooldown(*, sessions: list[Session], at: datetime) -> str | None:
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


@dataclass(kw_only=True)
class Scheduler:
    """Choose and start the work for one Dreamcatcher instance."""

    repository: str
    account: str
    config: Config
    state: StateDirectory
    harness: Harness
    clock: Callable[[], datetime]
    rounds: dict[str, Round]

    def tick(self, *, at: datetime) -> LastTick:
        """Look once and launch at most one round.

        A round that has ended is forgotten first, so the cap counts what is
        running now. A failure reaches the daemon, which records and reports it
        before the next tick tries again.
        """
        ended = [key for key, running in self.rounds.items() if not running.is_alive]
        for key in ended:
            del self.rounds[key]
        return self._decide_and_launch(at=at)

    def _decide_and_launch(self, *, at: datetime) -> LastTick:
        """Launch at most one round, and return what the tick observed.

        Every tick tries to weigh the candidate issues, so the board keeps
        showing the current queue while the daemon is carrying on open work or
        waiting for a launch slot. A failed listing holds the tick.

        The cooldown holds every launch, a wakeup and a dispatch alike, but it
        holds no read. So a tick under it still says what each session is
        waiting on, rather than going quiet for the whole fifteen minutes.
        """
        sessions = read_sessions(state=self.state)
        judged = judge_issues(
            repository=self.repository,
            config=self.config,
            claimed={session.record.issue for session in sessions},
        )
        if isinstance(judged, Unknown):
            candidate_failure = judged.reason
            candidates = []
        else:
            candidate_failure = None
            candidates = judged
        if len(self.rounds) >= self.config.max_agents:
            cap = (
                f"at cap: {len(self.rounds)} of {self.config.max_agents} rounds running"
            )
            hold = (
                cap
                if candidate_failure is None
                else f"{cap}; could not refresh queue: {candidate_failure}"
            )
            return LastTick(
                at=at,
                hold=hold,
                candidates=candidates,
                waiting=[
                    compose_wait(session=session, reason=cap)
                    for session in sessions
                    if session.key not in self.rounds
                    and not session.has_run_final_round
                ],
            )
        found = self._judge_sessions(sessions=sessions)
        if candidate_failure is not None:
            return LastTick(
                at=at, hold=candidate_failure, waiting=list_waiting(found=found)
            )
        cooling = _check_cooldown(sessions=sessions, at=at)
        if cooling is not None:
            return LastTick(
                at=at,
                hold=cooling,
                candidates=candidates,
                waiting=list_waiting(found=found),
            )
        ready = sort_wakeups(found=[one for one in found if isinstance(one, Wakeup)])
        if ready:
            return self._resume_session(
                at=at, wakeup=ready[0], found=found, candidates=candidates
            )
        return self._dispatch_oldest_issue(
            at=at, judged=candidates, waiting=list_waiting(found=found)
        )

    def _judge_sessions(self, *, sessions: list[Session]) -> list[Finding]:
        """Return what each session needs next, and what each is waiting on."""
        found: list[Finding] = []
        for session in sessions:
            if session.key in self.rounds:
                continue
            needed = judge_session(
                repository=self.repository, account=self.account, session=session
            )
            if needed is not None:
                found.append(needed)
        return found

    def _resume_session(
        self,
        *,
        at: datetime,
        wakeup: Wakeup,
        found: list[Finding],
        candidates: list[CandidateIssue],
    ) -> LastTick:
        """Resume the session with the highest priority this tick."""
        try:
            self._launch_wakeup(wakeup=wakeup)
        except ReportableError as failure:
            return LastTick(
                at=at,
                hold=str(failure),
                candidates=candidates,
                waiting=list_waiting(found=found),
            )
        rest = [one for one in found if one is not wakeup]
        return LastTick(
            at=at,
            launched=wakeup.session.key,
            candidates=candidates,
            waiting=list_waiting(found=rest),
        )

    def _launch_wakeup(self, *, wakeup: Wakeup) -> None:
        """Start the round and advance the watermark once it is running."""
        session = wakeup.session
        if wakeup.inbox is not None:
            write_json(document=wakeup.inbox, path=session.next_workspace.inbox)
        self._start_round(session=session, prompt=wakeup.prompt, cause=wakeup.cause)
        if wakeup.newest_post:
            advance_watermark(session=session, newest=wakeup.newest_post)

    def _start_round(self, *, session: Session, prompt: str, cause: Cause) -> None:
        """Start a round with the settings that the dispatch settled."""
        adapter = ADAPTERS[session.record.harness]
        launch = Launch(
            session=session.key,
            model=session.record.model,
            effort=session.record.effort,
            prompt=prompt,
        )
        invocation = (
            adapter.build_first_round(launch=launch)
            if cause is Cause.DISPATCH
            else adapter.build_resumed_round(launch=launch)
        )
        self.rounds[session.key] = Round(
            adapter=adapter,
            invocation=invocation,
            workspace=session.next_workspace,
            cause=cause,
            clock=self.clock,
        )

    def _dispatch_oldest_issue(
        self,
        *,
        at: datetime,
        judged: list[CandidateIssue],
        waiting: list[WaitingSession],
    ) -> LastTick:
        """Dispatch the oldest issue that `eligibility.py` judged free to go."""
        eligible = [candidate for candidate in judged if candidate.is_eligible]
        if not eligible:
            return LastTick(at=at, candidates=judged, waiting=waiting)
        try:
            key = self._launch_session(candidate=eligible[0], at=at)
        except ReportableError as failure:
            return LastTick(
                at=at, hold=str(failure), candidates=judged, waiting=waiting
            )
        return LastTick(at=at, launched=key, candidates=judged, waiting=waiting)

    def _launch_session(self, *, candidate: CandidateIssue, at: datetime) -> str:
        """Create a session and remove it again if its first round cannot start."""
        session = create_session(
            state=self.state,
            mapping=self.config.label_mappings[candidate.label],
            named=self.harness,
            issue=candidate.issue,
            at=at,
        )
        try:
            self._start_round(
                session=session, prompt=session.record.prompt, cause=Cause.DISPATCH
            )
        except ReportableError:
            discard_session(state=self.state, record=session.record)
            raise
        return session.key
