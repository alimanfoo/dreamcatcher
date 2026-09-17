"""Schedule one round of agent work at a time.

A scheduler tick reads the assignments on disk and asks GitHub which labelled
issues are available. It weighs the active rounds against the cap, works out
what each assignment needs next, and launches at most one round.

Open work goes before new work, and the most open of it first: a recorded
assignment missing its first round finishes its dispatch, a round that did not
finish is recovered, a merged or closed pull request gets a wrap-up round, then
an assignment answers what the user posted. Only when no assignment needs
anything does an uncapped tick dispatch the oldest available issue.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    AgentAssignmentCreator,
    advance_user_post_delivery_cursor,
    find_harness_session_identifier,
    inspect_incomplete_assignment_setups,
    read_agent_assignments,
    record_harness_session_identifier,
)
from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundOutputReader,
    ErroredAgentRoundEnding,
)
from dreamcatcher.config import Config, Harness
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    Issue,
    IssueState,
    Unknown,
    list_blockers,
    list_issues,
    list_linked_pull_requests,
    read_issue,
)
from dreamcatcher.harness_adapters import AgentRoundLaunch
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.state import (
    IssueFact,
    IssueFactValue,
    IssueObservation,
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


@dataclass(frozen=True, kw_only=True)
class _IssueObservationContext:
    """The shared inputs for observing each issue in one scheduler tick."""

    repository: str
    account: str
    config: Config
    assignments: dict[int, AgentAssignment]
    recovery_obstacles: dict[int, str | None]


@dataclass(frozen=True, kw_only=True)
class IssueObservationResult:
    """The issue facts one tick observed and any failed listing behind them."""

    observations: list[IssueObservation]
    failure: str | None = None


def derive_issue_availability(*, observation: IssueObservation) -> IssueFact:
    """Derive whether an issue is available from its independent facts."""
    preventing = _find_preventing_issue_fact(observation=observation)
    if preventing is not None:
        return IssueFact(
            value=IssueFactValue.FALSE,
            evidence=preventing.evidence,
        )
    required = [
        observation.is_open,
        observation.is_assigned_to_user,
        observation.claimed_here,
        observation.claimed_elsewhere,
        observation.blocked,
        observation.routing_conflict,
    ]
    unknown = next(
        (fact for fact in required if fact.value is IssueFactValue.UNKNOWN), None
    )
    if unknown is not None:
        return unknown
    if observation.dispatch_labels is None:
        return IssueFact(
            value=IssueFactValue.UNKNOWN,
            evidence="cannot tell which dispatch labels it carries",
        )
    return IssueFact(value=IssueFactValue.TRUE)


def _find_preventing_issue_fact(*, observation: IssueObservation) -> IssueFact | None:
    """Return the first known fact that prevents assignment."""
    preventing = [
        observation.routing_conflict,
        observation.claimed_here,
        observation.claimed_elsewhere,
        observation.blocked,
    ]
    for fact in preventing:
        if fact.value is IssueFactValue.TRUE:
            return fact
    for fact in [observation.is_open, observation.is_assigned_to_user]:
        if fact.value is IssueFactValue.FALSE:
            return fact
    labels = observation.dispatch_labels
    if labels is not None and len(labels) != 1:
        return IssueFact(
            value=IssueFactValue.FALSE,
            evidence="carries no configured dispatch label",
        )
    return None


def observe_issues(
    *,
    repository: str,
    account: str,
    config: Config,
    assignments: list[AgentAssignment],
    recovery_obstacles: dict[int, str | None],
) -> IssueObservationResult:
    """Observe every issue considered for dispatch or claimed by this instance."""
    listed = _list_considered_issues(repository=repository, config=config)
    open_assignments = {
        assignment.record.issue: assignment
        for assignment in assignments
        if not assignment.is_complete
    }
    context = _IssueObservationContext(
        repository=repository,
        account=account,
        config=config,
        assignments=open_assignments,
        recovery_obstacles=recovery_obstacles,
    )
    observed: dict[int, Issue | Unknown]
    if isinstance(listed, Unknown):
        observed = {}
        failure = listed.reason
    else:
        observed = {issue.number: issue for issue in listed}
        failure = None
    local_issues = open_assignments.keys() | recovery_obstacles.keys()
    for issue in local_issues - observed.keys():
        observed[issue] = read_issue(repository=repository, issue=issue)
    issue_observations = [
        _observe_issue(
            context=context,
            issue=issue,
            answer=answer,
        )
        for issue, answer in observed.items()
    ]
    return IssueObservationResult(
        observations=sorted(
            issue_observations,
            key=lambda observation: (
                observation.created_at is None,
                observation.created_at,
                observation.issue,
            ),
        ),
        failure=failure,
    )


def _list_considered_issues(
    *, repository: str, config: Config
) -> list[Issue] | Unknown:
    """List open assigned issues that carry any configured dispatch label."""
    found: dict[int, Issue] = {}
    for route in config.dispatch:
        answered = list_issues(
            repository=repository, label=route.label, assignee=config.assignee
        )
        if isinstance(answered, Unknown):
            return answered
        found.update((issue.number, issue) for issue in answered)
    return list(found.values())


def _observe_issue(
    *,
    context: _IssueObservationContext,
    issue: int,
    answer: Issue | Unknown,
) -> IssueObservation:
    """Observe the independent scheduling facts for one issue."""
    if isinstance(answer, Unknown):
        external_reason = f"cannot read issue: {answer.reason}"
        created_at = None
        is_open = _unknown_fact(evidence=external_reason)
        is_assigned = _unknown_fact(evidence=external_reason)
        dispatch_labels = None
        routing_conflict = _unknown_fact(evidence=external_reason)
    else:
        created_at = answer.created_at
        is_open = _known_fact(
            value=answer.state is IssueState.OPEN,
            evidence=(None if answer.state is IssueState.OPEN else "issue is closed"),
        )
        watched_account = (
            context.account
            if context.config.assignee == "@me"
            else context.config.assignee
        )
        is_assigned_to_user = watched_account.casefold() in {
            assignee.login.casefold() for assignee in answer.assignees
        }
        is_assigned = _known_fact(
            value=is_assigned_to_user,
            evidence=(
                None if is_assigned_to_user else f"is not assigned to {watched_account}"
            ),
        )
        dispatch_labels = context.config.identify_dispatch_labels(
            labels=[label.name for label in answer.labels]
        )
        has_routing_conflict = len(dispatch_labels) > 1
        routing_conflict = _known_fact(
            value=has_routing_conflict,
            evidence=(
                "carries more than one dispatch label: " + ", ".join(dispatch_labels)
                if has_routing_conflict
                else None
            ),
        )
    is_claimed_here = issue in context.assignments
    claimed_here = _known_fact(
        value=is_claimed_here,
        evidence=(
            "an assignment in this checkout is working on it"
            if is_claimed_here
            else None
        ),
    )
    return IssueObservation(
        issue=issue,
        created_at=created_at,
        is_open=is_open,
        is_assigned_to_user=is_assigned,
        dispatch_labels=dispatch_labels,
        claimed_here=claimed_here,
        claimed_elsewhere=_observe_external_claim(
            context=context,
            issue=issue,
        ),
        blocked=_observe_blocking_issues(repository=context.repository, issue=issue),
        routing_conflict=routing_conflict,
    )


def _observe_external_claim(
    *,
    context: _IssueObservationContext,
    issue: int,
) -> IssueFact:
    """Observe whether an open linked pull request claims the issue elsewhere."""
    has_recovery_setup = issue in context.recovery_obstacles
    obstacle = context.recovery_obstacles.get(issue)
    if has_recovery_setup and obstacle is None:
        return _known_fact(value=False)
    linked = list_linked_pull_requests(repository=context.repository, issue=issue)
    if isinstance(linked, Unknown):
        if obstacle is not None:
            return _unknown_fact(evidence=obstacle)
        return _unknown_fact(
            evidence=f"cannot tell whether a pull request claims it: {linked.reason}"
        )
    assignment = context.assignments.get(issue)
    owned = None if assignment is None else assignment.record.pull_request
    external = [pull_request for pull_request in linked if pull_request.number != owned]
    named = ", ".join(f"#{pull_request.number}" for pull_request in external)
    if external:
        return _known_fact(
            value=True, evidence=f"a pull request is open on it: {named}"
        )
    if obstacle is not None:
        return _unknown_fact(evidence=obstacle)
    return _known_fact(value=False)


def _observe_blocking_issues(*, repository: str, issue: int) -> IssueFact:
    """Observe whether an open issue dependency blocks the issue."""
    blocking = list_blockers(repository=repository, issue=issue)
    if isinstance(blocking, Unknown):
        return _unknown_fact(evidence=f"cannot tell what blocks it: {blocking.reason}")
    open_blockers = [
        blocker.number for blocker in blocking if blocker.state is IssueState.OPEN
    ]
    named = ", ".join(f"GH{number}" for number in open_blockers)
    return _known_fact(
        value=bool(open_blockers),
        evidence=(None if not named else f"blocked by {named}"),
    )


def _known_fact(*, value: bool, evidence: str | None = None) -> IssueFact:
    """Return a known issue fact."""
    return IssueFact(
        value=IssueFactValue.TRUE if value else IssueFactValue.FALSE,
        evidence=evidence,
    )


def _unknown_fact(*, evidence: str) -> IssueFact:
    """Return an issue fact that an external read could not establish."""
    return IssueFact(value=IssueFactValue.UNKNOWN, evidence=evidence)


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

        Every tick observes the relevant issues, so the board keeps showing the
        current queue while the daemon is carrying on open work or waiting for
        a launch slot. A failed listing holds the tick.

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
        observed = observe_issues(
            repository=self.repository,
            account=self.account,
            config=self.config,
            assignments=assignments,
            recovery_obstacles=inspect_incomplete_assignment_setups(
                state=self.state, repository=self.repository
            ),
        )
        issue_failure = observed.failure
        issue_observations = observed.observations
        if len(self.rounds) >= self.config.max_agents:
            cap = (
                f"at cap: {len(self.rounds)} of {self.config.max_agents} rounds running"
            )
            hold = (
                cap
                if issue_failure is None
                else f"{cap}; could not refresh issues: {issue_failure}"
            )
            return LastTick(
                at=at,
                hold=hold,
                issue_observations=issue_observations,
                waiting=[
                    compose_wait(assignment=assignment, reason=cap)
                    for assignment in assignments
                    if assignment.identifier not in self.rounds
                    and not assignment.is_complete
                ],
            )
        found = self._judge_assignments(assignments=assignments)
        if issue_failure is not None:
            return LastTick(
                at=at,
                hold=issue_failure,
                issue_observations=issue_observations,
                waiting=list_waiting(found=found),
            )
        cooling = _check_cooldown(assignments=assignments, at=at)
        if cooling is not None:
            return LastTick(
                at=at,
                hold=cooling,
                issue_observations=issue_observations,
                waiting=list_waiting(found=found),
            )
        ready = sort_wakeups(found=[one for one in found if isinstance(one, Wakeup)])
        if ready:
            return self._launch_assignment_round(
                at=at,
                wakeup=ready[0],
                found=found,
                issue_observations=issue_observations,
            )
        return self._dispatch_oldest_issue(
            at=at,
            observed=issue_observations,
            waiting=list_waiting(found=found),
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
        issue_observations: list[IssueObservation],
    ) -> LastTick:
        """Launch the next round for the highest-priority assignment."""
        try:
            self._launch_wakeup(wakeup=wakeup)
        except ReportableError as failure:
            return LastTick(
                at=at,
                hold=str(failure),
                issue_observations=issue_observations,
                waiting=list_waiting(found=found),
            )
        rest = [one for one in found if one is not wakeup]
        return LastTick(
            at=at,
            launched=wakeup.assignment.identifier,
            issue_observations=issue_observations,
            waiting=list_waiting(found=rest),
        )

    def _launch_wakeup(self, *, wakeup: Wakeup) -> None:
        """Start the round and advance the delivery cursor once it is running."""
        assignment = wakeup.assignment
        harness_adapter = HARNESS_ADAPTERS[assignment.record.harness]
        launch = AgentRoundLaunch(
            assignment_id=assignment.identifier,
            model=assignment.record.model,
            effort=assignment.record.effort,
            prompt=wakeup.prompt,
        )
        if assignment.rounds:
            harness_session_identifier = find_harness_session_identifier(
                assignment=assignment, harness_adapter=harness_adapter
            )
            if harness_session_identifier is None:
                raise ReportableError(
                    f"Could not resume {assignment.identifier}: its first round did "
                    "not report a harness session identifier."
                )
            record_harness_session_identifier(
                assignment=assignment, identifier=harness_session_identifier
            )
            invocation = harness_adapter.build_resumed_round(
                launch=launch,
                harness_session_identifier=harness_session_identifier,
            )
        else:
            invocation = harness_adapter.build_first_round(launch=launch)
        self.rounds[assignment.identifier] = AgentRound(
            output_reader=AgentRoundOutputReader(
                harness_adapter=harness_adapter,
                record_harness_session_identifier=partial(
                    record_harness_session_identifier, assignment=assignment
                ),
            ),
            invocation=invocation,
            paths=assignment.round_paths(number=assignment.next_round_number),
            plan=wakeup.plan,
            clock=self.clock,
        )
        round_input = wakeup.plan.input
        if round_input is not None and round_input.posts:
            advance_user_post_delivery_cursor(
                assignment=assignment,
                newest=round_input.posts[-1].written_at,
            )

    def _dispatch_oldest_issue(
        self,
        *,
        at: datetime,
        observed: list[IssueObservation],
        waiting: list[WaitingAgentAssignment],
    ) -> LastTick:
        """Dispatch the oldest issue whose independent facts make it available."""
        eligible = [
            observation
            for observation in observed
            if derive_issue_availability(observation=observation).value
            is IssueFactValue.TRUE
        ]
        if not eligible:
            return LastTick(at=at, issue_observations=observed, waiting=waiting)
        oldest = eligible[0]
        labels = oldest.dispatch_labels or []
        try:
            assignment_id = self._launch_assignment(
                issue=oldest.issue, label=labels[0], at=at
            )
        except ReportableError as failure:
            return LastTick(
                at=at,
                hold=str(failure),
                issue_observations=observed,
                waiting=waiting,
            )
        return LastTick(
            at=at,
            launched=assignment_id,
            issue_observations=observed,
            waiting=waiting,
        )

    def _launch_assignment(self, *, issue: int, label: str, at: datetime) -> str:
        """Create an assignment and start its first round."""
        creator = AgentAssignmentCreator(
            state=self.state,
            repository=self.repository,
        )
        assignment = creator.create(
            route=self.config.dispatch_routes[label],
            named=self.harness,
            issue=issue,
            at=at,
        )
        self._launch_wakeup(wakeup=compose_dispatch_wakeup(assignment=assignment))
        return assignment.identifier
