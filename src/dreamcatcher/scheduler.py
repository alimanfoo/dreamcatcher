"""Schedule agent work for one Dreamcatcher instance.

Each tick reads local assignments, observes relevant issues on GitHub, applies
the concurrency cap and global cooldown, and launches at most one round.

Within existing work, a missing first round comes first, followed by recovery,
wrap-up, and user feedback. After issue observation succeeds, the scheduler
dispatches the oldest available issue only when no assignment requires a round
and neither capacity nor cooldown prevents a launch.
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
    find_open_agent_assignments_by_issue,
    inspect_incomplete_assignment_setups,
    read_agent_assignments,
    record_agent_assignment_title,
    record_harness_session_identifier,
    record_pull_request_observation,
)
from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundInput,
    AgentRoundPlan,
    AgentRoundPurpose,
    AgentRoundStartRequest,
    ErroredAgentRoundEnding,
    start_agent_round,
)
from dreamcatcher.config import AgentHarness, DreamcatcherConfig
from dreamcatcher.documents import DreamcatcherDocument, read_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    Issue,
    IssueState,
    PullRequest,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    list_blocking_issues,
    list_issues,
    read_issue,
    read_issue_pull_request_context,
    read_pull_request,
)
from dreamcatcher.harness_adapters import AgentRoundLaunchRequest
from dreamcatcher.prompts import RECOVERY_PROMPT, compose_user_posts_prompt
from dreamcatcher.relay import list_undelivered_user_posts
from dreamcatcher.state import StateDirectory
from dreamcatcher.words import describe_count

GLOBAL_COOLDOWN_DURATION = timedelta(minutes=15)
DEFAULT_MAX_AGENTS = 1
NO_ROUND_HAS_RUN = "no round has run yet"


def _normalize_utc(at: datetime, /) -> datetime:
    """Return an aware datetime expressed in UTC; pydantic calls this validator."""
    return at.astimezone(UTC)


UtcDateTime = Annotated[AwareDatetime, AfterValidator(_normalize_utc)]


class IssueFactValue(StrEnum):
    """List the truth states of an observed issue fact."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class IssueFact(DreamcatcherDocument):
    """Model an independently observed issue fact and its evidence."""

    value: IssueFactValue
    evidence: str | None = None


class IssueObservation(DreamcatcherDocument):
    """Model the independent facts observed about an issue in one tick."""

    issue: int
    title: str | None = None
    created_at: datetime | None = None
    observed_at: UtcDateTime | None = None
    is_open: IssueFact
    is_assigned_to_user: IssueFact
    dispatch_labels: list[str] | None = None
    claimed_here: IssueFact
    claimed_elsewhere: IssueFact
    setup_failure: str | None = None
    blocked: IssueFact
    routing_conflict: IssueFact

    @property
    def availability(self) -> IssueFact:
        """Whether the observed facts make the issue available for assignment."""
        return derive_issue_availability(observation=self)


class AgentAssignmentObservation(DreamcatcherDocument):
    """Model what the scheduler found for one idle assignment."""

    assignment_identifier: str
    issue: int
    reason: str
    is_known: bool = True
    is_round_required: bool = True


class GlobalCooldown(DreamcatcherDocument):
    """Model an interval during which the scheduler starts no agent work."""

    started: UtcDateTime
    ends: UtcDateTime

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> Self:
        """Refuse an empty or backwards cooldown interval."""
        if self.ends <= self.started:
            raise ValueError("cooldown end must follow its start")
        return self


class SchedulerRecord(DreamcatcherDocument):
    """Record what one scheduler tick observed and decided."""

    at: UtcDateTime
    hold: str | None = None
    launched_assignment_identifier: str | None = None
    issue_observations: list[IssueObservation] = Field(default_factory=list)
    assignment_observations: list[AgentAssignmentObservation] = Field(
        default_factory=list
    )
    cooldown: GlobalCooldown | None = None
    most_recent_cooldown_ended: UtcDateTime | None = None


@dataclass(frozen=True, kw_only=True)
class RequiredAgentRound:
    """Describe the next round that an assignment requires."""

    assignment: AgentAssignment
    plan: AgentRoundPlan
    reason: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class FaultedAgentAssignment:
    """Describe an assignment whose errors stop ordinary recovery."""

    assignment: AgentAssignment
    reason: str


type AgentAssignmentInspectionResult = (
    RequiredAgentRound | FaultedAgentAssignment | AgentAssignmentObservation
)


@dataclass(frozen=True, kw_only=True)
class _IssueObservationContext:
    """Collect the shared inputs for observing issues in one tick."""

    repository: str
    account: str
    config: DreamcatcherConfig
    assignments: dict[int, AgentAssignment]
    incomplete_setups: dict[int, str | None]


@dataclass(frozen=True, kw_only=True)
class IssueObservationResult:
    """Group issue observations with any failed listing behind them."""

    observations: list[IssueObservation]
    failure: str | None = None


@dataclass(frozen=True, kw_only=True)
class _ConsideredIssueResult:
    """Group listed issues with any route listing failure."""

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
    config: DreamcatcherConfig,
    assignments: list[AgentAssignment],
    incomplete_setups: dict[int, str | None],
) -> IssueObservationResult:
    """Observe every issue considered for dispatch or claimed by this instance."""
    considered_issues = _list_considered_issues(repository=repository, config=config)
    open_assignments = find_open_agent_assignments_by_issue(assignments=assignments)
    context = _IssueObservationContext(
        repository=repository,
        account=account,
        config=config,
        assignments=open_assignments,
        incomplete_setups=incomplete_setups,
    )
    issue_responses_by_number: dict[int, Issue | UnknownGitHubResponse] = {
        issue.number: issue for issue in considered_issues.issues
    }
    local_issue_numbers = open_assignments.keys() | incomplete_setups.keys()
    for issue in local_issue_numbers - issue_responses_by_number.keys():
        issue_responses_by_number[issue] = read_issue(
            repository=repository, issue=issue
        )
    issue_observations = [
        _observe_issue(
            context=context,
            issue=issue,
            issue_response=issue_response,
        )
        for issue, issue_response in issue_responses_by_number.items()
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
        failure=considered_issues.failure,
    )


def _record_missing_assignment_titles(
    *, assignments: list[AgentAssignment], observations: list[IssueObservation]
) -> None:
    """Record titles first learned after legacy assignments were created."""
    open_assignments = find_open_agent_assignments_by_issue(assignments=assignments)
    for observation in observations:
        assignment = open_assignments.get(observation.issue)
        if assignment is not None and observation.title is not None:
            record_agent_assignment_title(
                assignment=assignment,
                title=observation.title,
            )


def _list_considered_issues(
    *, repository: str, config: DreamcatcherConfig
) -> _ConsideredIssueResult:
    """List open assigned issues that carry any configured dispatch label."""
    issues_by_number: dict[int, Issue] = {}
    for route in config.dispatch:
        issue_response = list_issues(
            repository=repository, label=route.label, assignee=config.assignee
        )
        if isinstance(issue_response, UnknownGitHubResponse):
            return _ConsideredIssueResult(
                issues=list(issues_by_number.values()),
                failure=issue_response.reason,
            )
        issues_by_number.update((issue.number, issue) for issue in issue_response)
    return _ConsideredIssueResult(issues=list(issues_by_number.values()))


def _observe_issue(
    *,
    context: _IssueObservationContext,
    issue: int,
    issue_response: Issue | UnknownGitHubResponse,
) -> IssueObservation:
    """Observe the independent scheduling facts for one issue."""
    if isinstance(issue_response, UnknownGitHubResponse):
        external_reason = f"cannot read issue: {issue_response.reason}"
        title = None
        created_at = None
        is_open = _compose_unknown_issue_fact(evidence=external_reason)
        is_assigned = _compose_unknown_issue_fact(evidence=external_reason)
        dispatch_labels = None
        routing_conflict = _compose_unknown_issue_fact(evidence=external_reason)
    else:
        title = issue_response.title
        created_at = issue_response.created_at
        is_open = _compose_known_issue_fact(
            value=issue_response.state is IssueState.OPEN,
            evidence=(
                None if issue_response.state is IssueState.OPEN else "issue is closed"
            ),
        )
        watched_account = (
            context.account
            if context.config.assignee == "@me"
            else context.config.assignee
        )
        is_assigned_to_user = watched_account.casefold() in {
            assignee.login.casefold() for assignee in issue_response.assignees
        }
        is_assigned = _compose_known_issue_fact(
            value=is_assigned_to_user,
            evidence=(
                None if is_assigned_to_user else f"is not assigned to {watched_account}"
            ),
        )
        dispatch_labels = context.config.identify_dispatch_labels(
            labels=[label.name for label in issue_response.labels]
        )
        has_routing_conflict = len(dispatch_labels) > 1
        routing_conflict = _compose_known_issue_fact(
            value=has_routing_conflict,
            evidence=(
                "carries more than one dispatch label: " + ", ".join(dispatch_labels)
                if has_routing_conflict
                else None
            ),
        )
    is_claimed_here = issue in context.assignments
    claimed_here = _compose_known_issue_fact(
        value=is_claimed_here,
        evidence=(
            "an assignment in this checkout is working on it"
            if is_claimed_here
            else None
        ),
    )
    return IssueObservation(
        issue=issue,
        title=title,
        created_at=created_at,
        is_open=is_open,
        is_assigned_to_user=is_assigned,
        dispatch_labels=dispatch_labels,
        claimed_here=claimed_here,
        claimed_elsewhere=_observe_external_claim(
            context=context,
            issue=issue,
        ),
        setup_failure=context.incomplete_setups.get(issue),
        blocked=_observe_blocking_issues(repository=context.repository, issue=issue),
        routing_conflict=routing_conflict,
    )


def _observe_external_claim(
    *,
    context: _IssueObservationContext,
    issue: int,
) -> IssueFact:
    """Observe whether an open linked pull request claims the issue elsewhere."""
    setup_failure = context.incomplete_setups.get(issue)
    if issue in context.incomplete_setups and setup_failure is None:
        return _compose_known_issue_fact(value=False)
    pull_request_context = read_issue_pull_request_context(
        repository=context.repository, issue=issue
    )
    if isinstance(pull_request_context, UnknownGitHubResponse):
        if setup_failure is not None:
            return _compose_unknown_issue_fact(evidence=setup_failure)
        return _compose_unknown_issue_fact(
            evidence=(
                "cannot tell whether a pull request claims it: "
                f"{pull_request_context.reason}"
            )
        )
    assignment = context.assignments.get(issue)
    owned = None if assignment is None else assignment.record.pull_request
    external = [
        pull_request
        for pull_request in pull_request_context.pull_requests
        if pull_request.number != owned
    ]
    external_pull_requests = ", ".join(
        f"#{pull_request.number}" for pull_request in external
    )
    if external:
        return _compose_known_issue_fact(
            value=True,
            evidence=f"a pull request is open on it: {external_pull_requests}",
        )
    if setup_failure is not None:
        return _compose_unknown_issue_fact(evidence=setup_failure)
    return _compose_known_issue_fact(value=False)


def _observe_blocking_issues(*, repository: str, issue: int) -> IssueFact:
    """Observe whether an open issue dependency blocks the issue."""
    blocking = list_blocking_issues(repository=repository, issue=issue)
    if isinstance(blocking, UnknownGitHubResponse):
        return _compose_unknown_issue_fact(
            evidence=f"cannot tell what blocks it: {blocking.reason}"
        )
    open_blockers = [
        blocker.number for blocker in blocking if blocker.state is IssueState.OPEN
    ]
    blocker_names = ", ".join(f"GH{number}" for number in open_blockers)
    return _compose_known_issue_fact(
        value=bool(open_blockers),
        evidence=(None if not blocker_names else f"blocked by {blocker_names}"),
    )


def _compose_known_issue_fact(*, value: bool, evidence: str | None = None) -> IssueFact:
    return IssueFact(
        value=IssueFactValue.TRUE if value else IssueFactValue.FALSE,
        evidence=evidence,
    )


def _compose_unknown_issue_fact(*, evidence: str) -> IssueFact:
    return IssueFact(value=IssueFactValue.UNKNOWN, evidence=evidence)


def derive_assignment_fault(
    *, assignment: AgentAssignment, most_recent_cooldown_ended: datetime | None
) -> bool:
    """Derive whether an assignment has two current consecutive errors."""
    if len(assignment.rounds) < 2:
        return False
    boundaries = [
        boundary
        for boundary in (
            most_recent_cooldown_ended,
            assignment.record.retry_requested_at,
        )
        if boundary is not None
    ]
    most_recent_fault_boundary = max(boundaries, default=None)
    latest_endings = [record.ending for record in assignment.rounds[-2:]]
    return all(
        isinstance(ending, ErroredAgentRoundEnding)
        and (
            most_recent_fault_boundary is None
            or ending.at >= most_recent_fault_boundary
        )
        for ending in latest_endings
    )


def read_scheduler_record(
    *, state: StateDirectory, at: datetime
) -> SchedulerRecord | None:
    """Read the scheduler record advanced to the current time."""
    if not state.scheduler_record.exists():
        return None
    try:
        record = read_json(model=SchedulerRecord, path=state.scheduler_record)
    except ReportableError as failure:
        raise InvalidSchedulerRecordError(str(failure)) from failure
    cooldown = record.cooldown
    if cooldown is not None and at >= cooldown.ends:
        return record.model_copy(
            update={
                "hold": None,
                "cooldown": None,
                "most_recent_cooldown_ended": cooldown.ends,
            }
        )
    return record


class InvalidSchedulerRecordError(ReportableError):
    """Report a scheduler record that retrying cannot safely replace."""


def _start_cooldown_if_required(
    *,
    active: GlobalCooldown | None,
    inspection_results: list[AgentAssignmentInspectionResult],
    at: datetime,
) -> GlobalCooldown | None:
    """Start a cooldown when two assignments are currently in fault."""
    if active is not None:
        return active
    faults = [
        result
        for result in inspection_results
        if isinstance(result, FaultedAgentAssignment)
    ]
    if len(faults) < 2:
        return None
    return GlobalCooldown(started=at, ends=at + GLOBAL_COOLDOWN_DURATION)


def prioritize_required_rounds(
    *, required_rounds: list[RequiredAgentRound]
) -> list[RequiredAgentRound]:
    """Return required rounds with the most open work first."""
    return sorted(required_rounds, key=_rank_required_round)


def _rank_required_round(required: RequiredAgentRound, /) -> int:
    if not required.assignment.rounds:
        return 0
    if required.plan.is_recovery:
        return 1
    if required.plan.purpose is AgentRoundPurpose.WRAP_UP:
        return 2
    return 3


def list_assignment_observations(
    *,
    inspection_results: list[AgentAssignmentInspectionResult],
    required_reason: str | None = None,
) -> list[AgentAssignmentObservation]:
    """Return an agent assignment observation for every inspection result.

    When `required_reason` is given, it replaces the reason of each required
    round. Existing observation and fault reasons remain unchanged.
    """
    return [
        result
        if isinstance(result, AgentAssignmentObservation)
        else compose_assignment_observation(
            assignment=result.assignment,
            reason=(
                required_reason
                if required_reason is not None
                and isinstance(result, RequiredAgentRound)
                else result.reason
            ),
        )
        for result in inspection_results
    ]


def inspect_agent_assignment(
    *,
    repository: str,
    account: str,
    assignment: AgentAssignment,
    most_recent_cooldown_ended: datetime | None,
    observed_at: datetime,
) -> AgentAssignmentInspectionResult | None:
    """Return what one assignment needs after reading any external facts."""
    if not assignment.rounds:
        return compose_initial_round_requirement(assignment=assignment)
    if assignment.is_complete:
        return None
    if derive_assignment_fault(
        assignment=assignment,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
    ):
        return FaultedAgentAssignment(
            assignment=assignment,
            reason="two consecutive rounds failed",
        )
    return _inspect_assignment_pull_request(
        repository=repository,
        account=account,
        assignment=assignment,
        observed_at=observed_at,
    )


def _inspect_assignment_pull_request(
    *,
    repository: str,
    account: str,
    assignment: AgentAssignment,
    observed_at: datetime,
) -> AgentAssignmentInspectionResult | None:
    """Return what an assignment needs from its pull request and posts."""
    pull_request = read_pull_request(
        repository=repository, pull_request=assignment.record.pull_request
    )
    if isinstance(pull_request, UnknownGitHubResponse):
        return compose_assignment_observation(
            assignment=assignment,
            reason=f"cannot read its pull request: {pull_request.reason}",
            is_known=False,
        )
    record_pull_request_observation(
        assignment=assignment,
        pull_request=pull_request,
        observed_at=observed_at,
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
            prompt=RECOVERY_PROMPT,
        )
    undelivered_posts = list_undelivered_user_posts(
        repository=repository,
        pull_request=pull_request.number,
        account=account,
        delivery_cursor=assignment.user_post_delivery_cursor,
    )
    if isinstance(undelivered_posts, UnknownGitHubResponse):
        return compose_assignment_observation(
            assignment=assignment,
            reason=f"cannot tell what the user posted: {undelivered_posts.reason}",
            is_known=False,
        )
    if pull_request.state is PullRequestState.OPEN and not undelivered_posts:
        return None
    return _compose_resumed_round_requirement(
        assignment=assignment,
        pull_request=pull_request,
        undelivered_posts=undelivered_posts,
        recovery_reason=recovery_reason,
    )


def compose_initial_round_requirement(
    *, assignment: AgentAssignment
) -> RequiredAgentRound:
    """Return the first round that a recorded assignment requires."""
    return RequiredAgentRound(
        assignment=assignment,
        plan=AgentRoundPlan(purpose=AgentRoundPurpose.IMPLEMENT, is_recovery=False),
        reason=NO_ROUND_HAS_RUN,
        prompt=assignment.record.prompt,
    )


def _compose_resumed_round_requirement(
    *,
    assignment: AgentAssignment,
    pull_request: PullRequest,
    undelivered_posts: list[UserPost],
    recovery_reason: str | None,
) -> RequiredAgentRound:
    """Return the round that a pull request and its user posts require."""
    is_open = pull_request.state is PullRequestState.OPEN
    return RequiredAgentRound(
        assignment=assignment,
        plan=AgentRoundPlan(
            purpose=_derive_round_purpose(pull_request=pull_request),
            is_recovery=recovery_reason is not None,
            input=AgentRoundInput(
                pull_request_state=pull_request.state, user_posts=undelivered_posts
            ),
        ),
        reason=(
            recovery_reason
            or (
                f"{describe_count(number=len(undelivered_posts), noun='new post')} "
                "to answer"
                if is_open
                else f"the pull request is {pull_request.state.lower()}"
            )
        ),
        prompt=compose_user_posts_prompt(
            pull_request=pull_request.number,
            round_input=assignment.compose_round_paths(
                number=assignment.next_round_number
            ).round_input,
        ),
    )


def _derive_round_purpose(*, pull_request: PullRequest) -> AgentRoundPurpose:
    """Return the purpose that the pull request currently requires."""
    if pull_request.state is not PullRequestState.OPEN:
        return AgentRoundPurpose.WRAP_UP
    if pull_request.is_draft:
        return AgentRoundPurpose.IMPLEMENT
    return AgentRoundPurpose.ADDRESS_FEEDBACK


def compose_assignment_observation(
    *,
    assignment: AgentAssignment,
    reason: str,
    is_known: bool = True,
    is_round_required: bool = True,
) -> AgentAssignmentObservation:
    """Return what the scheduler found for one idle assignment."""
    return AgentAssignmentObservation(
        assignment_identifier=assignment.identifier,
        issue=assignment.record.issue,
        reason=reason,
        is_known=is_known,
        is_round_required=is_round_required,
    )


@dataclass(kw_only=True)
class AgentWorkScheduler:
    """Choose and start the work for one Dreamcatcher instance."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    harness: AgentHarness
    clock: Callable[[], datetime]
    rounds: dict[str, AgentRound]
    max_agents: int = DEFAULT_MAX_AGENTS

    def tick(self, *, at: datetime) -> SchedulerRecord:
        """Inspect current work and launch at most one agent round.

        A round that has ended is forgotten first, so the cap counts what is
        running now. A failure reaches the daemon, which reports it before the
        next tick tries again.

        Every tick observes relevant issues so that status stays current while
        open work runs or waits for capacity. A failed issue listing prevents a
        launch.

        A global cooldown prevents every launch but does not prevent reads, so
        assignment observations remain current while the cooldown is active.
        """
        previous_record = read_scheduler_record(state=self.state, at=at)
        cooldown = None if previous_record is None else previous_record.cooldown
        most_recent_cooldown_ended = (
            None
            if previous_record is None
            else previous_record.most_recent_cooldown_ended
        )
        ended_assignment_identifiers = [
            assignment_identifier
            for assignment_identifier, running in self.rounds.items()
            if not running.is_alive
        ]
        for assignment_identifier in ended_assignment_identifiers:
            del self.rounds[assignment_identifier]
        assignments = read_agent_assignments(state=self.state)
        issue_observation_result = observe_issues(
            repository=self.repository,
            account=self.account,
            config=self.config,
            assignments=assignments,
            incomplete_setups=inspect_incomplete_assignment_setups(
                state=self.state, repository=self.repository
            ),
        )
        issue_failure = issue_observation_result.failure
        issue_observations = [
            observation.model_copy(update={"observed_at": at})
            for observation in issue_observation_result.observations
        ]
        _record_missing_assignment_titles(
            assignments=assignments,
            observations=issue_observations,
        )
        inspection_results = self._inspect_assignments(
            assignments=assignments,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
            observed_at=at,
        )
        cooldown = _start_cooldown_if_required(
            active=cooldown,
            inspection_results=inspection_results,
            at=at,
        )
        assignment_observations = list_assignment_observations(
            inspection_results=inspection_results
        )
        record = SchedulerRecord(
            at=at,
            cooldown=cooldown,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
            issue_observations=issue_observations,
            assignment_observations=assignment_observations,
        )
        if cooldown is not None:
            hold_reason = "global cooldown"
            if issue_failure is not None:
                hold_reason = (
                    f"{hold_reason}; could not refresh issues: {issue_failure}"
                )
            return record.model_copy(update={"hold": hold_reason})
        if len(self.rounds) >= self.max_agents:
            capacity_reason = (
                f"at cap: {len(self.rounds)} of {self.max_agents} agents running"
            )
            hold_reason = (
                capacity_reason
                if issue_failure is None
                else f"{capacity_reason}; could not refresh issues: {issue_failure}"
            )
            return record.model_copy(
                update={
                    "hold": hold_reason,
                    "assignment_observations": list_assignment_observations(
                        inspection_results=inspection_results,
                        required_reason=capacity_reason,
                    ),
                }
            )
        if issue_failure is not None:
            return record.model_copy(update={"hold": issue_failure})
        prioritized_rounds = prioritize_required_rounds(
            required_rounds=[
                result
                for result in inspection_results
                if isinstance(result, RequiredAgentRound)
            ]
        )
        if prioritized_rounds:
            return self._launch_assignment_round(
                record=record,
                required=prioritized_rounds[0],
                inspection_results=inspection_results,
            )
        return self._dispatch_oldest_issue(
            record=record,
        )

    def _inspect_assignments(
        self,
        *,
        assignments: list[AgentAssignment],
        most_recent_cooldown_ended: datetime | None,
        observed_at: datetime,
    ) -> list[AgentAssignmentInspectionResult]:
        """Return what each assignment needs next, and what each is waiting on."""
        inspection_results: list[AgentAssignmentInspectionResult] = []
        open_assignments = find_open_agent_assignments_by_issue(assignments=assignments)
        for assignment in open_assignments.values():
            if assignment.identifier in self.rounds:
                continue
            inspection_result = inspect_agent_assignment(
                repository=self.repository,
                account=self.account,
                assignment=assignment,
                most_recent_cooldown_ended=most_recent_cooldown_ended,
                observed_at=observed_at,
            )
            if inspection_result is not None:
                inspection_results.append(inspection_result)
            else:
                inspection_results.append(
                    compose_assignment_observation(
                        assignment=assignment,
                        reason="no round required",
                        is_round_required=False,
                    )
                )
        return inspection_results

    def _launch_assignment_round(
        self,
        *,
        record: SchedulerRecord,
        required: RequiredAgentRound,
        inspection_results: list[AgentAssignmentInspectionResult],
    ) -> SchedulerRecord:
        """Launch the next round for the highest-priority assignment."""
        try:
            self._launch_required_round(required=required)
        except ReportableError as failure:
            return record.model_copy(
                update={
                    "hold": str(failure),
                    "assignment_observations": list_assignment_observations(
                        inspection_results=inspection_results
                    ),
                }
            )
        remaining_results = [
            result for result in inspection_results if result is not required
        ]
        return record.model_copy(
            update={
                "launched_assignment_identifier": required.assignment.identifier,
                "assignment_observations": list_assignment_observations(
                    inspection_results=remaining_results
                ),
            }
        )

    def _launch_required_round(self, *, required: RequiredAgentRound) -> None:
        """Start the round and advance the delivery cursor once it is running."""
        assignment = required.assignment
        harness_session_identifier = None
        if assignment.rounds:
            harness_session_identifier = find_harness_session_identifier(
                assignment=assignment
            )
            if harness_session_identifier is None:
                raise ReportableError(
                    f"Could not resume {assignment.identifier}: its first round did "
                    "not report a harness session identifier."
                )
            record_harness_session_identifier(
                assignment=assignment, identifier=harness_session_identifier
            )
        self.rounds[assignment.identifier] = start_agent_round(
            request=AgentRoundStartRequest(
                harness=assignment.record.harness,
                launch_request=AgentRoundLaunchRequest(
                    agent_work_identifier=assignment.identifier,
                    model=assignment.record.model,
                    effort=assignment.record.effort,
                    prompt=required.prompt,
                ),
                harness_session_identifier=harness_session_identifier,
                record_harness_session_identifier=partial(
                    record_harness_session_identifier, assignment=assignment
                ),
                paths=assignment.compose_round_paths(
                    number=assignment.next_round_number
                ),
                plan=required.plan,
            ),
            clock=self.clock,
        )
        round_input = required.plan.input
        if round_input is not None and round_input.user_posts:
            advance_user_post_delivery_cursor(
                assignment=assignment,
                newest=round_input.user_posts[-1].written_at,
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
            if observation.availability.value is IssueFactValue.TRUE
        ]
        if not eligible:
            return record
        oldest = eligible[0]
        labels = oldest.dispatch_labels or []
        try:
            assignment_identifier = self._launch_assignment(
                issue=oldest.issue, label=labels[0], at=record.at
            )
        except ReportableError as failure:
            return record.model_copy(update={"hold": str(failure)})
        return record.model_copy(
            update={"launched_assignment_identifier": assignment_identifier}
        )

    def _launch_assignment(self, *, issue: int, label: str, at: datetime) -> str:
        """Create an assignment and start its first round."""
        creator = AgentAssignmentCreator(
            state=self.state,
            repository=self.repository,
        )
        assignment = creator.create(
            route=self.config.dispatch_routes[label],
            requested_harness=self.harness,
            issue=issue,
            at=at,
        )
        self._launch_required_round(
            required=compose_initial_round_requirement(assignment=assignment)
        )
        return assignment.identifier
