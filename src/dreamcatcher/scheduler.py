"""Schedule one round of agent work at a time.

A scheduler tick reads the assignments on disk and asks GitHub which labelled
issues could be dispatched. It weighs the active rounds against the cap, works
out what each assignment needs next, and launches at most one round.

Open work goes before new work, and the most open of it first: a recorded
assignment missing its first round finishes its dispatch, a round that did not
finish is recovered, a merged or closed pull request gets a wrap-up round, then
an assignment answers what the user posted. Only when no assignment needs
anything does an uncapped tick dispatch the oldest unclaimed, unblocked candidate.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from dreamcatcher.adapters import Launch
from dreamcatcher.agent_assignments import (
    AgentAssignment,
    AgentAssignmentCreator,
    advance_user_post_delivery_cursor,
    inspect_incomplete_assignment_setups,
    read_agent_assignments,
)
from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundPlan,
    ErroredAgentRoundEnding,
    RoundPurpose,
)
from dreamcatcher.config import Config, Harness
from dreamcatcher.documents import write_json
from dreamcatcher.eligibility import judge_issues
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Unknown
from dreamcatcher.harnesses import ADAPTERS
from dreamcatcher.state import (
    CandidateIssue,
    LastTick,
    StateDirectory,
    WaitingAgentAssignment,
)
from dreamcatcher.wakeups import (
    Finding,
    Wakeup,
    compose_dispatch_wakeup,
    compose_wait,
    judge_assignment,
    list_waiting,
    sort_wakeups,
)

# How long scheduling holds every launch once a round has failed, dispatches
# and retries alike. There is no cause detection behind this and no schedule:
# the failure worth spending nothing on is a usage limit, which belongs to the
# account and so hits every assignment at once, and a passing blip costs at most
# this long of an idle daemon.
COOLDOWN = timedelta(minutes=15)


def _check_cooldown(*, assignments: list[AgentAssignment], at: datetime) -> str | None:
    """Return the hold every launch is under, when a round failed lately enough.

    The words are the evidence the record left and not a diagnosis of it. A
    usage limit and a passing blip both read as a round that failed, and both
    cost the same wait, so nothing here has to tell them apart.
    """
    failed = [
        record.ending
        for assignment in assignments
        for record in assignment.rounds
        if isinstance(record.ending, ErroredAgentRoundEnding)
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
    rounds: dict[str, AgentRound]

    def tick(self, *, at: datetime) -> LastTick:
        """Look once and launch at most one round.

        A round that has ended is forgotten first, so the cap counts what is
        running now. A failure reaches the daemon, which records and reports it
        before the next tick tries again.

        Every tick tries to weigh the candidate issues, so the board keeps
        showing the current queue while the daemon is carrying on open work or
        waiting for a launch slot. A failed listing holds the tick.

        The cooldown holds every launch, a wakeup and a dispatch alike, but it
        holds no read. So a tick under it still says what each assignment is
        waiting on, rather than going quiet for the whole fifteen minutes.
        """
        ended = [
            assignment_id
            for assignment_id, running in self.rounds.items()
            if not running.is_alive
        ]
        for assignment_id in ended:
            del self.rounds[assignment_id]
        assignments = read_agent_assignments(state=self.state)
        judged = judge_issues(
            repository=self.repository,
            config=self.config,
            claimed={
                assignment.record.issue
                for assignment in assignments
                if not assignment.is_complete
            },
            recovery_obstacles=inspect_incomplete_assignment_setups(
                state=self.state, repository=self.repository
            ),
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
                    compose_wait(assignment=assignment, reason=cap)
                    for assignment in assignments
                    if assignment.identifier not in self.rounds
                    and not assignment.is_complete
                ],
            )
        found = self._judge_assignments(assignments=assignments)
        if candidate_failure is not None:
            return LastTick(
                at=at, hold=candidate_failure, waiting=list_waiting(found=found)
            )
        cooling = _check_cooldown(assignments=assignments, at=at)
        if cooling is not None:
            return LastTick(
                at=at,
                hold=cooling,
                candidates=candidates,
                waiting=list_waiting(found=found),
            )
        ready = sort_wakeups(found=[one for one in found if isinstance(one, Wakeup)])
        if ready:
            return self._launch_assignment_round(
                at=at, wakeup=ready[0], found=found, candidates=candidates
            )
        return self._dispatch_oldest_issue(
            at=at, judged=candidates, waiting=list_waiting(found=found)
        )

    def _judge_assignments(
        self, *, assignments: list[AgentAssignment]
    ) -> list[Finding]:
        """Return what each assignment needs next, and what each is waiting on."""
        found: list[Finding] = []
        for assignment in assignments:
            if assignment.identifier in self.rounds:
                continue
            needed = judge_assignment(
                repository=self.repository, account=self.account, assignment=assignment
            )
            if needed is not None:
                found.append(needed)
        return found

    def _launch_assignment_round(
        self,
        *,
        at: datetime,
        wakeup: Wakeup,
        found: list[Finding],
        candidates: list[CandidateIssue],
    ) -> LastTick:
        """Launch the next round for the highest-priority assignment."""
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
            launched=wakeup.assignment.identifier,
            candidates=candidates,
            waiting=list_waiting(found=rest),
        )

    def _launch_wakeup(self, *, wakeup: Wakeup) -> None:
        """Start the round and advance the delivery cursor once it is running."""
        assignment = wakeup.assignment
        if wakeup.inbox is not None:
            write_json(
                document=wakeup.inbox,
                path=assignment.round_paths(number=assignment.next_round_number).inbox,
            )
        self._start_round(
            assignment=assignment,
            prompt=wakeup.prompt,
            purpose=wakeup.purpose,
            is_recovery=wakeup.is_recovery,
        )
        if wakeup.newest_post:
            advance_user_post_delivery_cursor(
                assignment=assignment, newest=wakeup.newest_post
            )

    def _start_round(
        self,
        *,
        assignment: AgentAssignment,
        prompt: str,
        purpose: RoundPurpose,
        is_recovery: bool,
    ) -> None:
        """Start a round with the recipe that the dispatch settled."""
        adapter = ADAPTERS[assignment.record.harness]
        launch = Launch(
            assignment_id=assignment.identifier,
            model=assignment.record.model,
            effort=assignment.record.effort,
            prompt=prompt,
        )
        invocation = (
            adapter.build_first_round(launch=launch)
            if not assignment.rounds
            else adapter.build_resumed_round(launch=launch)
        )
        self.rounds[assignment.identifier] = AgentRound(
            adapter=adapter,
            invocation=invocation,
            paths=assignment.round_paths(number=assignment.next_round_number),
            plan=AgentRoundPlan(purpose=purpose, is_recovery=is_recovery),
            clock=self.clock,
        )

    def _dispatch_oldest_issue(
        self,
        *,
        at: datetime,
        judged: list[CandidateIssue],
        waiting: list[WaitingAgentAssignment],
    ) -> LastTick:
        """Dispatch the oldest issue that `eligibility.py` judged free to go."""
        eligible = [candidate for candidate in judged if candidate.is_eligible]
        if not eligible:
            return LastTick(at=at, candidates=judged, waiting=waiting)
        try:
            assignment_id = self._launch_assignment(candidate=eligible[0], at=at)
        except ReportableError as failure:
            return LastTick(
                at=at, hold=str(failure), candidates=judged, waiting=waiting
            )
        return LastTick(
            at=at, launched=assignment_id, candidates=judged, waiting=waiting
        )

    def _launch_assignment(self, *, candidate: CandidateIssue, at: datetime) -> str:
        """Create an assignment and start its first round."""
        creator = AgentAssignmentCreator(
            state=self.state,
            repository=self.repository,
        )
        assignment = creator.create(
            route=self.config.dispatch_routes[candidate.label],
            named=self.harness,
            issue=candidate.issue,
            at=at,
        )
        self._launch_wakeup(wakeup=compose_dispatch_wakeup(assignment=assignment))
        return assignment.identifier
