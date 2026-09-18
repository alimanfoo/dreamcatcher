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
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Annotated, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

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
    AgentRoundInput,
    AgentRoundOutputReader,
    AgentRoundPlan,
    ErroredAgentRoundEnding,
    RoundPurpose,
)
from dreamcatcher.config import Config, Harness
from dreamcatcher.documents import Document, read_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    Issue,
    IssueState,
    PullRequest,
    PullRequestState,
    Unknown,
    UserPost,
    list_blockers,
    list_issues,
    list_linked_pull_requests,
    read_issue,
    read_pull_request,
)
from dreamcatcher.harness_adapters import AgentRoundLaunch
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.prompts import CARRY_ON_PROMPT, compose_inbox_prompt
from dreamcatcher.relay import list_undelivered_user_posts
from dreamcatcher.state import StateDirectory
from dreamcatcher.words import describe_count

COOLDOWN = timedelta(minutes=15)
NO_ROUND_HAS_RUN = "no round has run yet"


def _normalize_utc(at: datetime, /) -> datetime:
    """Return an aware datetime expressed in UTC; pydantic calls this validator."""
    return at.astimezone(UTC)


UtcDateTime = Annotated[AwareDatetime, AfterValidator(_normalize_utc)]


class IssueFactValue(StrEnum):
    """A known true or false issue fact, or one that could not be observed."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class IssueFact(Document):
    """One independently observed issue fact and its diagnostic evidence."""

    value: IssueFactValue
    evidence: str | None = None


class IssueObservation(Document):
    """The independent facts that one scheduler tick observed about an issue."""

    issue: int
    created_at: datetime | None = None
    is_open: IssueFact
    is_assigned_to_user: IssueFact
    dispatch_labels: list[str] | None = None
    claimed_here: IssueFact
    claimed_elsewhere: IssueFact
    blocked: IssueFact
    routing_conflict: IssueFact


class AgentAssignmentObservation(Document):
    """What prevents one idle assignment from starting its required round."""

    assignment: str
    issue: int
    reason: str


class GlobalCooldown(Document):
    """The interval during which the scheduler starts no agent work."""

    started: UtcDateTime
    ends: UtcDateTime

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> Self:
        """Refuse an empty or backwards cooldown interval."""
        if self.ends <= self.started:
            raise ValueError("cooldown end must follow its start")
        return self


class SchedulerRecord(Document):
    """What the scheduler's most recent tick observed and decided."""

    at: UtcDateTime
    hold: str | None = None
    launched: str | None = None
    issue_observations: list[IssueObservation] = Field(default_factory=list)
    assignment_observations: list[AgentAssignmentObservation] = Field(
        default_factory=list
    )
    cooldown: GlobalCooldown | None = None
    most_recent_cooldown_ended: UtcDateTime | None = None


@dataclass(frozen=True, kw_only=True)
class RequiredAgentRound:
    """The next round that an assignment requires, ready for the scheduler."""

    assignment: AgentAssignment
    plan: AgentRoundPlan
    reason: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class FaultedAgentAssignment:
    """An assignment whose consecutive errors stop ordinary recovery."""

    assignment: AgentAssignment
    reason: str


type AssignmentFinding = (
    RequiredAgentRound | FaultedAgentAssignment | AgentAssignmentObservation
)


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


@dataclass(frozen=True, kw_only=True)
class _ConsideredIssues:
    """The issues listed successfully and any route listing that failed."""

    issues: list[Issue]
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
    observed: dict[int, Issue | Unknown] = {
        issue.number: issue for issue in listed.issues
    }
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
        failure=listed.failure,
    )


def _list_considered_issues(*, repository: str, config: Config) -> _ConsideredIssues:
    """List open assigned issues that carry any configured dispatch label."""
    found: dict[int, Issue] = {}
    for route in config.dispatch:
        answered = list_issues(
            repository=repository, label=route.label, assignee=config.assignee
        )
        if isinstance(answered, Unknown):
            return _ConsideredIssues(
                issues=list(found.values()),
                failure=answered.reason,
            )
        found.update((issue.number, issue) for issue in answered)
    return _ConsideredIssues(issues=list(found.values()))


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


def derive_assignment_fault(
    *, assignment: AgentAssignment, after: datetime | None
) -> bool:
    """Derive whether an assignment has two current consecutive errors."""
    if len(assignment.rounds) < 2:
        return False
    latest = [record.ending for record in assignment.rounds[-2:]]
    return all(
        isinstance(ending, ErroredAgentRoundEnding)
        and (after is None or ending.at >= after)
        for ending in latest
    )


def _read_scheduler_record(*, state: StateDirectory) -> SchedulerRecord | None:
    """Read the scheduler record when a preceding tick has written one."""
    if not state.scheduler_record.exists():
        return None
    try:
        return read_json(model=SchedulerRecord, path=state.scheduler_record)
    except ReportableError as failure:
        raise InvalidSchedulerRecordError(str(failure)) from failure


class InvalidSchedulerRecordError(ReportableError):
    """A scheduler record the daemon cannot safely replace by retrying."""


def advance_scheduler_record(
    *, previous: SchedulerRecord | None, at: datetime
) -> SchedulerRecord | None:
    """Advance an elapsed cooldown to the record's completed boundary."""
    if previous is None:
        return None
    cooldown = previous.cooldown
    if cooldown is not None and at >= cooldown.ends:
        return previous.model_copy(
            update={
                "hold": None,
                "cooldown": None,
                "most_recent_cooldown_ended": cooldown.ends,
            }
        )
    return previous


def _start_cooldown_if_required(
    *,
    active: GlobalCooldown | None,
    found: list[AssignmentFinding],
    at: datetime,
) -> GlobalCooldown | None:
    """Start a cooldown when two assignments are currently in fault."""
    if active is not None:
        return active
    faults = [one for one in found if isinstance(one, FaultedAgentAssignment)]
    if len(faults) < 2:
        return None
    return GlobalCooldown(started=at, ends=at + COOLDOWN)


def _describe_cooldown(*, cooldown: GlobalCooldown) -> str:
    """Describe when the active global cooldown permits another launch."""
    return f"global cooldown — next attempt at {cooldown.ends:%H:%M:%S} UTC"


def prioritize_required_rounds(
    *, found: list[RequiredAgentRound]
) -> list[RequiredAgentRound]:
    """Return required rounds with the most open work first."""
    return sorted(found, key=_required_round_priority)


def _required_round_priority(required: RequiredAgentRound, /) -> int:
    """Return the existing scheduling priority of one required round."""
    if not required.assignment.rounds:
        return 0
    if required.plan.is_recovery:
        return 1
    if required.plan.purpose is RoundPurpose.WRAP_UP:
        return 2
    return 3


def list_assignment_observations(
    *, found: list[AssignmentFinding]
) -> list[AgentAssignmentObservation]:
    """Return the operational observation for every unlaunched finding."""
    return [
        one
        if isinstance(one, AgentAssignmentObservation)
        else compose_assignment_observation(
            assignment=one.assignment,
            reason=one.reason,
        )
        for one in found
    ]


def inspect_agent_assignment(
    *,
    repository: str,
    account: str,
    assignment: AgentAssignment,
    after: datetime | None,
) -> AssignmentFinding | None:
    """Return what one assignment needs after reading any external facts."""
    if not assignment.rounds:
        return compose_initial_round_requirement(assignment=assignment)
    if assignment.is_complete:
        return None
    if derive_assignment_fault(assignment=assignment, after=after):
        return FaultedAgentAssignment(
            assignment=assignment,
            reason="two consecutive rounds failed",
        )
    return _inspect_assignment_pull_request(
        repository=repository,
        account=account,
        assignment=assignment,
    )


def _inspect_assignment_pull_request(
    *, repository: str, account: str, assignment: AgentAssignment
) -> AssignmentFinding | None:
    """Return what an assignment needs from its pull request and posts."""
    pull_request = read_pull_request(
        repository=repository, pull_request=assignment.record.pull_request
    )
    if isinstance(pull_request, Unknown):
        return compose_assignment_observation(
            assignment=assignment,
            reason=f"cannot read its pull request: {pull_request.reason}",
        )
    recovery_reason = assignment.describe_unfinished_round()
    if recovery_reason is not None and pull_request.state is PullRequestState.OPEN:
        return RequiredAgentRound(
            assignment=assignment,
            plan=AgentRoundPlan(
                purpose=_derive_round_purpose(pull_request=pull_request),
                is_recovery=True,
            ),
            reason=recovery_reason,
            prompt=CARRY_ON_PROMPT,
        )
    posted = list_undelivered_user_posts(
        repository=repository,
        pull_request=pull_request.number,
        account=account,
        delivery_cursor=assignment.user_post_delivery_cursor,
    )
    if isinstance(posted, Unknown):
        return compose_assignment_observation(
            assignment=assignment,
            reason=f"cannot tell what the user posted: {posted.reason}",
        )
    if pull_request.state is PullRequestState.OPEN and not posted:
        return None
    return _compose_resumed_round_requirement(
        assignment=assignment,
        pull_request=pull_request,
        posted=posted,
        recovery_reason=recovery_reason,
    )


def compose_initial_round_requirement(
    *, assignment: AgentAssignment
) -> RequiredAgentRound:
    """Return the first round that a recorded assignment requires."""
    return RequiredAgentRound(
        assignment=assignment,
        plan=AgentRoundPlan(purpose=RoundPurpose.IMPLEMENT, is_recovery=False),
        reason=NO_ROUND_HAS_RUN,
        prompt=assignment.record.prompt,
    )


def _compose_resumed_round_requirement(
    *,
    assignment: AgentAssignment,
    pull_request: PullRequest,
    posted: list[UserPost],
    recovery_reason: str | None,
) -> RequiredAgentRound:
    """Return the round that a pull request and its user posts require."""
    is_open = pull_request.state is PullRequestState.OPEN
    return RequiredAgentRound(
        assignment=assignment,
        plan=AgentRoundPlan(
            purpose=_derive_round_purpose(pull_request=pull_request),
            is_recovery=recovery_reason is not None,
            input=AgentRoundInput(state=pull_request.state, posts=posted),
        ),
        reason=(
            recovery_reason
            or (
                f"{describe_count(number=len(posted), noun='new post')} to answer"
                if is_open
                else f"the pull request is {pull_request.state.lower()}"
            )
        ),
        prompt=compose_inbox_prompt(
            pull_request=pull_request.number,
            inbox=assignment.round_paths(number=assignment.next_round_number).inbox,
        ),
    )


def _derive_round_purpose(*, pull_request: PullRequest) -> RoundPurpose:
    """Return the purpose that the pull request currently requires."""
    if pull_request.state is not PullRequestState.OPEN:
        return RoundPurpose.WRAP_UP
    if pull_request.is_draft:
        return RoundPurpose.IMPLEMENT
    return RoundPurpose.ADDRESS_FEEDBACK


def compose_assignment_observation(
    *, assignment: AgentAssignment, reason: str
) -> AgentAssignmentObservation:
    """Return why an idle assignment has not started another round."""
    return AgentAssignmentObservation(
        assignment=assignment.identifier,
        issue=assignment.record.issue,
        reason=reason,
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

    def tick(self, *, at: datetime) -> SchedulerRecord:
        """Look once and launch at most one round.

        A round that has ended is forgotten first, so the cap counts what is
        running now. A failure reaches the daemon, which records and reports it
        before the next tick tries again.

        Every tick observes the relevant issues, so the board keeps showing the
        current queue while the daemon is carrying on open work or waiting for
        a launch slot. A failed listing holds the tick.

        The cooldown holds every required round and dispatch alike, but it
        holds no read. So a tick under it still says what each assignment is
        waiting on, rather than going quiet for the whole fifteen minutes.
        """
        previous = advance_scheduler_record(
            previous=_read_scheduler_record(state=self.state), at=at
        )
        cooldown = None if previous is None else previous.cooldown
        most_recent_cooldown_ended = (
            None if previous is None else previous.most_recent_cooldown_ended
        )
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
        found = self._judge_assignments(
            assignments=assignments, after=most_recent_cooldown_ended
        )
        cooldown = _start_cooldown_if_required(active=cooldown, found=found, at=at)
        assignment_observations = list_assignment_observations(found=found)
        record = SchedulerRecord(
            at=at,
            cooldown=cooldown,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
            issue_observations=issue_observations,
            assignment_observations=assignment_observations,
        )
        if cooldown is not None:
            hold = _describe_cooldown(cooldown=cooldown)
            if issue_failure is not None:
                hold = f"{hold}; could not refresh issues: {issue_failure}"
            return record.model_copy(update={"hold": hold})
        if len(self.rounds) >= self.config.max_agents:
            cap = (
                f"at cap: {len(self.rounds)} of {self.config.max_agents} rounds running"
            )
            hold = (
                cap
                if issue_failure is None
                else f"{cap}; could not refresh issues: {issue_failure}"
            )
            return record.model_copy(
                update={
                    "hold": hold,
                    "assignment_observations": [
                        compose_assignment_observation(
                            assignment=assignment, reason=cap
                        )
                        for assignment in assignments
                        if assignment.identifier not in self.rounds
                        and not assignment.is_complete
                    ],
                }
            )
        if issue_failure is not None:
            return record.model_copy(update={"hold": issue_failure})
        ready = prioritize_required_rounds(
            found=[one for one in found if isinstance(one, RequiredAgentRound)]
        )
        if ready:
            return self._launch_assignment_round(
                record=record,
                required=ready[0],
                found=found,
            )
        return self._dispatch_oldest_issue(
            record=record,
        )

    def _judge_assignments(
        self, *, assignments: list[AgentAssignment], after: datetime | None
    ) -> list[AssignmentFinding]:
        """Return what each assignment needs next, and what each is waiting on."""
        found: list[AssignmentFinding] = []
        for assignment in assignments:
            if assignment.identifier in self.rounds:
                continue
            needed = inspect_agent_assignment(
                repository=self.repository,
                account=self.account,
                assignment=assignment,
                after=after,
            )
            if needed is not None:
                found.append(needed)
        return found

    def _launch_assignment_round(
        self,
        *,
        record: SchedulerRecord,
        required: RequiredAgentRound,
        found: list[AssignmentFinding],
    ) -> SchedulerRecord:
        """Launch the next round for the highest-priority assignment."""
        try:
            self._launch_required_round(required=required)
        except ReportableError as failure:
            return record.model_copy(
                update={
                    "hold": str(failure),
                    "assignment_observations": list_assignment_observations(
                        found=found
                    ),
                }
            )
        rest = [one for one in found if one is not required]
        return record.model_copy(
            update={
                "launched": required.assignment.identifier,
                "assignment_observations": list_assignment_observations(found=rest),
            }
        )

    def _launch_required_round(self, *, required: RequiredAgentRound) -> None:
        """Start the round and advance the delivery cursor once it is running."""
        assignment = required.assignment
        harness_adapter = HARNESS_ADAPTERS[assignment.record.harness]
        launch = AgentRoundLaunch(
            assignment_id=assignment.identifier,
            model=assignment.record.model,
            effort=assignment.record.effort,
            prompt=required.prompt,
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
            plan=required.plan,
            clock=self.clock,
        )
        round_input = required.plan.input
        if round_input is not None and round_input.posts:
            advance_user_post_delivery_cursor(
                assignment=assignment,
                newest=round_input.posts[-1].written_at,
            )

    def _dispatch_oldest_issue(
        self,
        *,
        record: SchedulerRecord,
    ) -> SchedulerRecord:
        """Dispatch the oldest issue whose independent facts make it available."""
        eligible = [
            observation
            for observation in record.issue_observations
            if derive_issue_availability(observation=observation).value
            is IssueFactValue.TRUE
        ]
        if not eligible:
            return record
        oldest = eligible[0]
        labels = oldest.dispatch_labels or []
        try:
            assignment_id = self._launch_assignment(
                issue=oldest.issue, label=labels[0], at=record.at
            )
        except ReportableError as failure:
            return record.model_copy(update={"hold": str(failure)})
        return record.model_copy(update={"launched": assignment_id})

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
        self._launch_required_round(
            required=compose_initial_round_requirement(assignment=assignment)
        )
        return assignment.identifier
