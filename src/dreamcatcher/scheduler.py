"""Schedule agent work for one Dreamcatcher instance.

Each tick reads local agent work, observes relevant issues on GitHub, applies
the concurrency cap and global cooldown, and fills every free agent slot.

Within assignment work, a missing first round comes first, followed by recovery,
wrap-up, user feedback, and dispatch of the oldest available issue. Conversation
recovery precedes fresh batches. When both kinds are ready, the scheduler
alternates which kind receives the next free slot.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Annotated, Protocol, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    AgentAssignmentCreator,
    AgentAssignmentRoundInput,
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
    AgentAssignmentRoundPurpose,
    AgentRound,
    AgentRoundOutcome,
    AgentRoundPlan,
    AgentRoundRecord,
    AgentRoundStartRequest,
    ErroredAgentRoundEnding,
    IssueConversationRoundPurpose,
    start_agent_round,
)
from dreamcatcher.config import (
    AgentHarness,
    DreamcatcherConfig,
    IssueConversationConfig,
)
from dreamcatcher.documents import DreamcatcherDocument, read_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    ConversationComment,
    Issue,
    IssueState,
    PullRequest,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    list_blocking_issues,
    list_issue_comments,
    list_issues,
    read_issue,
    read_issue_pull_request_context,
    read_pull_request,
)
from dreamcatcher.harness_adapters import AgentRoundLaunchRequest, AgentWorkKind
from dreamcatcher.issue_conversations import (
    IssueConversation,
    IssueConversationInput,
    create_issue_conversation,
    find_issue_conversation_harness_session_identifier,
    list_undelivered_issue_comments,
    post_issue_conversation_answer,
    prepare_issue_conversation_input,
    read_issue_comment_delivery_cursor,
    read_issue_conversation_input,
    read_issue_conversations,
    record_issue_conversation_session_identifier,
)
from dreamcatcher.prompts import (
    ISSUE_CONVERSATION_RECOVERY_PROMPT,
    RECOVERY_PROMPT,
    compose_issue_conversation_prompt,
    compose_issue_conversation_round_prompt,
    compose_user_posts_prompt,
)
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
    evidence: str


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


class IssueConversationObservation(DreamcatcherDocument):
    """Model what the scheduler found for one conversation issue in one tick.

    The scheduler observes every eligible issue. When it cannot list eligible
    issues, it observes the previous tick's issues again with an unknown fact.
    """

    issue: int
    title: str
    has_comments_to_answer: IssueFact


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
    launched_agent_work_identifiers: list[str] = Field(default_factory=list)
    issue_observations: list[IssueObservation] = Field(default_factory=list)
    assignment_observations: list[AgentAssignmentObservation] = Field(
        default_factory=list
    )
    conversation_observations: list[IssueConversationObservation] = Field(
        default_factory=list
    )
    cooldown: GlobalCooldown | None = None
    most_recent_cooldown_ended: UtcDateTime | None = None


@dataclass(frozen=True, kw_only=True)
class RequiredAgentRound:
    """Describe the next round that an assignment requires."""

    assignment: AgentAssignment
    plan: AgentRoundPlan[AgentAssignmentRoundInput]
    reason: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class NewIssueConversationRoundCandidate:
    """Describe an eligible issue with trusted comments waiting."""

    issue: Issue
    comments: list[ConversationComment]
    conversation: IssueConversation | None
    config: IssueConversationConfig


@dataclass(frozen=True, kw_only=True)
class IssueConversationRecoveryCandidate:
    """Describe an eligible conversation with unfinished work to recover."""

    conversation: IssueConversation


type IssueConversationCandidate = (
    NewIssueConversationRoundCandidate | IssueConversationRecoveryCandidate
)


@dataclass(frozen=True, kw_only=True)
class IssueConversationCandidateResult:
    """Collect conversation observations, candidates, and any failed read."""

    candidates: list[IssueConversationCandidate]
    observations: list[IssueConversationObservation]
    failure: str | None = None


@dataclass(frozen=True, kw_only=True)
class _IssueConversationInspection:
    observation: IssueConversationObservation
    candidate: IssueConversationCandidate | None


@dataclass(frozen=True, kw_only=True)
class _IssueConversationCandidateContext:
    repository: str
    account: str
    config: DreamcatcherConfig
    most_recent_cooldown_ended: datetime | None


@dataclass(frozen=True, kw_only=True)
class _PreparedIssueConversationRound:
    conversation: IssueConversation
    round_input: IssueConversationInput
    prompt: str
    harness_session_identifier: str | None
    is_recovery: bool


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
    return IssueFact(
        value=IssueFactValue.TRUE,
        evidence="available for assignment",
    )


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
        is_open = IssueFact(value=IssueFactValue.UNKNOWN, evidence=external_reason)
        is_assigned = IssueFact(value=IssueFactValue.UNKNOWN, evidence=external_reason)
        dispatch_labels = None
        routing_conflict = IssueFact(
            value=IssueFactValue.UNKNOWN, evidence=external_reason
        )
    else:
        title = issue_response.title
        created_at = issue_response.created_at
        is_open = (
            IssueFact(value=IssueFactValue.TRUE, evidence="issue is open")
            if issue_response.state is IssueState.OPEN
            else IssueFact(value=IssueFactValue.FALSE, evidence="issue is closed")
        )
        watched_account = (
            context.account
            if context.config.assignee == "@me"
            else context.config.assignee
        )
        is_assigned_to_user = watched_account.casefold() in {
            assignee.login.casefold() for assignee in issue_response.assignees
        }
        is_assigned = (
            IssueFact(
                value=IssueFactValue.TRUE,
                evidence=f"is assigned to {watched_account}",
            )
            if is_assigned_to_user
            else IssueFact(
                value=IssueFactValue.FALSE,
                evidence=f"is not assigned to {watched_account}",
            )
        )
        dispatch_labels = context.config.identify_dispatch_labels(
            labels=[label.name for label in issue_response.labels]
        )
        has_routing_conflict = len(dispatch_labels) > 1
        routing_conflict = (
            IssueFact(
                value=IssueFactValue.TRUE,
                evidence=(
                    "carries more than one dispatch label: "
                    + ", ".join(dispatch_labels)
                ),
            )
            if has_routing_conflict
            else IssueFact(
                value=IssueFactValue.FALSE,
                evidence="has no routing conflict",
            )
        )
    is_claimed_here = issue in context.assignments
    claimed_here = (
        IssueFact(
            value=IssueFactValue.TRUE,
            evidence="an assignment in this checkout is working on it",
        )
        if is_claimed_here
        else IssueFact(
            value=IssueFactValue.FALSE,
            evidence="no assignment in this checkout is working on it",
        )
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
        return IssueFact(
            value=IssueFactValue.FALSE,
            evidence="no pull request outside this checkout claims it",
        )
    pull_request_context = read_issue_pull_request_context(
        repository=context.repository, issue=issue
    )
    if isinstance(pull_request_context, UnknownGitHubResponse):
        if setup_failure is not None:
            return IssueFact(
                value=IssueFactValue.UNKNOWN,
                evidence=setup_failure,
            )
        return IssueFact(
            value=IssueFactValue.UNKNOWN,
            evidence=(
                "cannot tell whether a pull request claims it: "
                f"{pull_request_context.reason}"
            ),
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
        return IssueFact(
            value=IssueFactValue.TRUE,
            evidence=f"a pull request is open on it: {external_pull_requests}",
        )
    if setup_failure is not None:
        return IssueFact(
            value=IssueFactValue.UNKNOWN,
            evidence=setup_failure,
        )
    return IssueFact(
        value=IssueFactValue.FALSE,
        evidence="no pull request outside this checkout claims it",
    )


def _observe_blocking_issues(*, repository: str, issue: int) -> IssueFact:
    """Observe whether an open issue dependency blocks the issue."""
    blocking = list_blocking_issues(repository=repository, issue=issue)
    if isinstance(blocking, UnknownGitHubResponse):
        return IssueFact(
            value=IssueFactValue.UNKNOWN,
            evidence=f"cannot tell what blocks it: {blocking.reason}",
        )
    open_blockers = [
        blocker.number for blocker in blocking if blocker.state is IssueState.OPEN
    ]
    blocker_names = ", ".join(f"GH{number}" for number in open_blockers)
    return (
        IssueFact(
            value=IssueFactValue.TRUE,
            evidence=f"blocked by {blocker_names}",
        )
        if open_blockers
        else IssueFact(
            value=IssueFactValue.FALSE,
            evidence="no open issue blocks it",
        )
    )


def derive_agent_work_fault(
    *,
    rounds: list[AgentRoundRecord],
    retry_requested_at: datetime | None,
    most_recent_cooldown_ended: datetime | None,
) -> bool:
    """Derive whether agent work has two current consecutive errors."""
    if len(rounds) < 2:
        return False
    boundaries = [
        boundary
        for boundary in (
            most_recent_cooldown_ended,
            retry_requested_at,
        )
        if boundary is not None
    ]
    most_recent_fault_boundary = max(boundaries, default=None)
    latest_endings = [record.ending for record in rounds[-2:]]
    return all(
        isinstance(ending, ErroredAgentRoundEnding)
        and (
            most_recent_fault_boundary is None
            or ending.at >= most_recent_fault_boundary
        )
        for ending in latest_endings
    )


def _count_observed_conversation_faults(
    *,
    conversations: list[IssueConversation],
    observations: list[IssueConversationObservation],
    most_recent_cooldown_ended: datetime | None,
) -> int:
    """Count faults among conversations this tick keeps in the report."""
    observed_issues = {observation.issue for observation in observations}
    return sum(
        derive_agent_work_fault(
            rounds=conversation.rounds,
            retry_requested_at=conversation.record.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        for conversation in conversations
        if conversation.record.issue in observed_issues
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
    fault_count: int,
    at: datetime,
) -> GlobalCooldown | None:
    """Start a cooldown when two agent work items are currently in fault."""
    if active is not None:
        return active
    if fault_count < 2:
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
    if required.plan.purpose is AgentAssignmentRoundPurpose.WRAP_UP:
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
    if derive_agent_work_fault(
        rounds=assignment.rounds,
        retry_requested_at=assignment.record.retry_requested_at,
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
                purpose=derive_round_purpose(pull_request=pull_request),
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
        plan=AgentRoundPlan(
            purpose=AgentAssignmentRoundPurpose.IMPLEMENT, is_recovery=False
        ),
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
            purpose=derive_round_purpose(pull_request=pull_request),
            is_recovery=recovery_reason is not None,
            input=AgentAssignmentRoundInput(
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


class _PullRequestRoundFacts(Protocol):
    """Describe the pull-request facts that choose a round purpose."""

    @property
    def is_open(self) -> bool:
        """Whether the pull request is open."""

    @property
    def is_draft(self) -> bool:
        """Whether the pull request is a draft."""


def derive_round_purpose(
    *, pull_request: _PullRequestRoundFacts
) -> AgentAssignmentRoundPurpose:
    """Return the purpose that the pull request currently requires."""
    if not pull_request.is_open:
        return AgentAssignmentRoundPurpose.WRAP_UP
    if pull_request.is_draft:
        return AgentAssignmentRoundPurpose.IMPLEMENT
    return AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK


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


def _list_issue_conversation_candidates(
    *,
    context: _IssueConversationCandidateContext,
    conversations: list[IssueConversation],
    previous_observations: list[IssueConversationObservation],
) -> IssueConversationCandidateResult:
    """Observe every eligible issue and return conversation work ready to run.

    Comments are read for every eligible issue that can accept a fresh batch,
    whether or not an agent is free, so that status can tell waiting from idle.
    Recovery uses the saved batch and does not read new comments. A failed read
    holds launches only where the conversation could take a new batch. When
    eligible issues cannot be listed, the previous tick's issues are observed
    again with an unknown fact, so the ones the user took off the report stay
    off it.
    """
    conversation_config = context.config.conversation
    if conversation_config is None:
        return IssueConversationCandidateResult(candidates=[], observations=[])
    issue_response = list_issues(
        repository=context.repository,
        label=conversation_config.label,
        assignee=context.account,
    )
    if isinstance(issue_response, UnknownGitHubResponse):
        failure = f"could not list issue conversations: {issue_response.reason}"
        return IssueConversationCandidateResult(
            candidates=[],
            observations=[
                observation.model_copy(
                    update={
                        "has_comments_to_answer": IssueFact(
                            value=IssueFactValue.UNKNOWN,
                            evidence=failure,
                        )
                    }
                )
                for observation in previous_observations
            ],
            failure=failure,
        )
    conversations_by_issue = {
        conversation.record.issue: conversation for conversation in conversations
    }
    candidates: list[IssueConversationCandidate] = []
    observations: list[IssueConversationObservation] = []
    failures: list[str | None] = []
    for issue in sorted(
        issue_response, key=lambda item: (item.created_at, item.number)
    ):
        conversation = conversations_by_issue.get(issue.number)
        inspection = _inspect_issue_conversation(
            context=context,
            config=conversation_config,
            issue=issue,
            conversation=conversation,
        )
        observations.append(inspection.observation)
        if inspection.candidate is not None:
            candidates.append(inspection.candidate)
        elif (
            _is_conversation_ready_for_input(conversation=conversation)
            and inspection.observation.has_comments_to_answer.value
            is IssueFactValue.UNKNOWN
        ):
            failures.append(inspection.observation.has_comments_to_answer.evidence)
    return IssueConversationCandidateResult(
        candidates=sorted(candidates, key=_rank_issue_conversation_candidate),
        observations=observations,
        failure=_combine_scheduler_failures(failures=failures),
    )


def _inspect_issue_conversation(
    *,
    context: _IssueConversationCandidateContext,
    config: IssueConversationConfig,
    issue: Issue,
    conversation: IssueConversation | None,
) -> _IssueConversationInspection:
    """Observe one eligible issue, and return a candidate when it is ready."""
    if conversation is not None and derive_agent_work_fault(
        rounds=conversation.rounds,
        retry_requested_at=conversation.record.retry_requested_at,
        most_recent_cooldown_ended=context.most_recent_cooldown_ended,
    ):
        return _IssueConversationInspection(
            observation=IssueConversationObservation(
                issue=issue.number,
                title=issue.title,
                has_comments_to_answer=IssueFact(
                    value=IssueFactValue.FALSE,
                    evidence="no comments to answer",
                ),
            ),
            candidate=None,
        )
    if (
        conversation is not None
        and conversation.rounds
        and conversation.rounds[-1].outcome
        in {AgentRoundOutcome.ERRORED, AgentRoundOutcome.INTERRUPTED}
    ):
        return _IssueConversationInspection(
            observation=IssueConversationObservation(
                issue=issue.number,
                title=issue.title,
                has_comments_to_answer=IssueFact(
                    value=IssueFactValue.FALSE,
                    evidence="no comments to answer",
                ),
            ),
            candidate=IssueConversationRecoveryCandidate(
                conversation=conversation,
            ),
        )
    try:
        comments = _list_comments_to_answer(
            repository=context.repository,
            account=context.account,
            issue=issue.number,
            conversation=conversation,
        )
    except ReportableError as failure:
        has_comments_to_answer = IssueFact(
            value=IssueFactValue.UNKNOWN,
            evidence=str(failure),
        )
        comments = []
    else:
        has_comments_to_answer = (
            IssueFact(
                value=IssueFactValue.TRUE,
                evidence=(
                    f"{describe_count(number=len(comments), noun='comment')} to answer"
                ),
            )
            if comments
            else IssueFact(
                value=IssueFactValue.FALSE,
                evidence="no comments to answer",
            )
        )
    observation = IssueConversationObservation(
        issue=issue.number,
        title=issue.title,
        has_comments_to_answer=has_comments_to_answer,
    )
    if not comments or not _is_conversation_ready_for_input(conversation=conversation):
        return _IssueConversationInspection(observation=observation, candidate=None)
    return _IssueConversationInspection(
        observation=observation,
        candidate=NewIssueConversationRoundCandidate(
            issue=issue,
            comments=comments,
            conversation=conversation,
            config=config,
        ),
    )


def _rank_issue_conversation_candidate(
    candidate: IssueConversationCandidate, /
) -> tuple[int, str, int]:
    """Rank recovery before fresh batches, then fresh batches oldest first."""
    if isinstance(candidate, IssueConversationRecoveryCandidate):
        return (0, "", candidate.conversation.record.issue)
    first_comment = candidate.comments[0]
    return (1, first_comment.written_at, first_comment.id)


def _prepare_issue_conversation_round(
    *,
    state: StateDirectory,
    candidate: IssueConversationCandidate,
    requested_harness: AgentHarness,
) -> _PreparedIssueConversationRound:
    """Prepare either a fresh conversation batch or unfinished work."""
    if isinstance(candidate, IssueConversationRecoveryCandidate):
        return _prepare_issue_conversation_recovery(conversation=candidate.conversation)
    conversation = candidate.conversation or create_issue_conversation(
        state=state,
        config=candidate.config,
        requested_harness=requested_harness,
        issue=candidate.issue,
    )
    round_input = prepare_issue_conversation_input(
        state=state,
        conversation=conversation,
        issue=candidate.issue,
        comments=candidate.comments,
    )
    paths = conversation.compose_round_paths(number=conversation.next_round_number)
    harness_session_identifier = None
    prompt = compose_issue_conversation_prompt(
        template=conversation.record.prompt,
        issue=conversation.record.issue,
        round_input=paths.round_input,
    )
    if conversation.rounds:
        harness_session_identifier = find_issue_conversation_harness_session_identifier(
            conversation=conversation
        )
        if harness_session_identifier is None:
            raise ReportableError(
                f"Could not resume {conversation.identifier}: its first round did "
                "not report a harness session identifier."
            )
        prompt = compose_issue_conversation_round_prompt(
            issue=conversation.record.issue,
            round_input=paths.round_input,
        )
    return _PreparedIssueConversationRound(
        conversation=conversation,
        round_input=round_input,
        prompt=prompt,
        harness_session_identifier=harness_session_identifier,
        is_recovery=False,
    )


def _prepare_issue_conversation_recovery(
    *, conversation: IssueConversation
) -> _PreparedIssueConversationRound:
    """Prepare a recovery from the latest round's saved input and session."""
    latest_round = conversation.rounds[-1]
    round_input = read_issue_conversation_input(
        conversation=conversation,
        number=latest_round.number,
    )
    harness_session_identifier = find_issue_conversation_harness_session_identifier(
        conversation=conversation
    )
    if harness_session_identifier is None:
        next_input = conversation.compose_round_paths(
            number=conversation.next_round_number
        ).round_input
        prompt = compose_issue_conversation_prompt(
            template=conversation.record.prompt,
            issue=conversation.record.issue,
            round_input=next_input,
        )
    else:
        prompt = ISSUE_CONVERSATION_RECOVERY_PROMPT
    return _PreparedIssueConversationRound(
        conversation=conversation,
        round_input=round_input,
        prompt=prompt,
        harness_session_identifier=harness_session_identifier,
        is_recovery=True,
    )


def _list_comments_to_answer(
    *,
    repository: str,
    account: str,
    issue: int,
    conversation: IssueConversation | None,
) -> list[ConversationComment]:
    """Return the trusted comments that no round has been given yet.

    Raise a `ReportableError` naming the issue when a read fails.
    """
    comment_response = list_issue_comments(repository=repository, issue=issue)
    if isinstance(comment_response, UnknownGitHubResponse):
        raise ReportableError(
            f"could not read comments for GH{issue}: {comment_response.reason}"
        )
    try:
        cursor = (
            None
            if conversation is None
            else read_issue_comment_delivery_cursor(conversation=conversation)
        )
    except ReportableError as failure:
        raise ReportableError(
            f"could not read delivered comments for GH{issue}: {failure}"
        ) from failure
    return list_undelivered_issue_comments(
        comments=comment_response,
        account=account,
        cursor=cursor,
    )


def _is_conversation_ready_for_input(*, conversation: IssueConversation | None) -> bool:
    """Return whether a conversation can accept another comment batch."""
    if conversation is None or not conversation.rounds:
        return True
    return conversation.rounds[-1].outcome is AgentRoundOutcome.SUCCESSFUL


def _combine_scheduler_failures(*, failures: list[str | None]) -> str | None:
    """Join independent scheduler failures."""
    present = [failure for failure in failures if failure is not None]
    return "; ".join(present) if present else None


def _list_available_issues(*, record: SchedulerRecord) -> list[IssueObservation]:
    """Return the issues that the scheduler observed as available, in order."""
    return [
        observation
        for observation in record.issue_observations
        if observation.availability.value is IssueFactValue.TRUE
    ]


@dataclass(kw_only=True)
class _ReadyAgentWork:
    assignment_rounds: list[RequiredAgentRound]
    available_issues: list[IssueObservation]
    conversations: list[IssueConversationCandidate]
    conversation_failure: str | None

    @property
    def is_assignment_ready(self) -> bool:
        """Whether an assignment round or issue can start."""
        return bool(self.assignment_rounds or self.available_issues)

    @property
    def is_conversation_ready(self) -> bool:
        """Whether the next conversation can start safely."""
        return bool(self.conversations) and (
            self.conversation_failure is None
            or isinstance(self.conversations[0], IssueConversationRecoveryCandidate)
        )


def _choose_work_kind(
    *,
    candidates: _ReadyAgentWork,
    last_selected_work_kind: AgentWorkKind | None,
) -> AgentWorkKind | None:
    if candidates.is_assignment_ready and candidates.is_conversation_ready:
        if last_selected_work_kind is AgentWorkKind.ASSIGNMENT:
            return AgentWorkKind.CONVERSATION
        return AgentWorkKind.ASSIGNMENT
    if candidates.is_assignment_ready:
        return AgentWorkKind.ASSIGNMENT
    if candidates.is_conversation_ready:
        return AgentWorkKind.CONVERSATION
    return None


def _record_session_before_advancing_user_post_cursor(
    *, assignment: AgentAssignment, newest_user_post: str, identifier: str
) -> None:
    """Record a replacement session before acknowledging its delivered posts."""
    record_harness_session_identifier(assignment=assignment, identifier=identifier)
    advance_user_post_delivery_cursor(assignment=assignment, newest=newest_user_post)


@dataclass(kw_only=True)
class AgentWorkScheduler:
    """Choose and start the work for one Dreamcatcher instance."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    requested_harness: AgentHarness
    clock: Callable[[], datetime]
    rounds: dict[str, AgentRound]
    max_agents: int = DEFAULT_MAX_AGENTS
    _last_selected_work_kind: AgentWorkKind | None = field(
        default=None, init=False, repr=False
    )

    def tick(self, *, at: datetime) -> SchedulerRecord:
        """Inspect current work and fill every free agent slot.

        A round that has ended is forgotten first, so the cap counts what is
        running now. A failure reaches the daemon, which reports it before the
        next tick tries again.

        Every tick observes relevant issues so that status stays current while
        open work runs or waits for capacity. A failed read prevents launches
        in the workflow that depends on it without holding the other workflow.

        A global cooldown prevents every launch but does not prevent reads, so
        assignment and conversation observations remain current while the
        cooldown is active.
        """
        previous_record = read_scheduler_record(state=self.state, at=at)
        cooldown = None if previous_record is None else previous_record.cooldown
        most_recent_cooldown_ended = (
            None
            if previous_record is None
            else previous_record.most_recent_cooldown_ended
        )
        ended_agent_work_identifiers = [
            agent_work_identifier
            for agent_work_identifier, running in self.rounds.items()
            if not running.is_alive
        ]
        for agent_work_identifier in ended_agent_work_identifiers:
            del self.rounds[agent_work_identifier]
        assignments = read_agent_assignments(state=self.state)
        conversations = read_issue_conversations(state=self.state)
        issue_observation_result = observe_issues(
            repository=self.repository,
            account=self.account,
            config=self.config,
            assignments=assignments,
            incomplete_setups=inspect_incomplete_assignment_setups(
                state=self.state, repository=self.repository
            ),
        )
        assignment_failure = (
            None
            if issue_observation_result.failure is None
            else f"could not refresh issues: {issue_observation_result.failure}"
        )
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
        conversation_candidates = _list_issue_conversation_candidates(
            context=_IssueConversationCandidateContext(
                repository=self.repository,
                account=self.account,
                config=self.config,
                most_recent_cooldown_ended=most_recent_cooldown_ended,
            ),
            conversations=conversations,
            previous_observations=(
                []
                if previous_record is None
                else previous_record.conversation_observations
            ),
        )
        conversation_fault_count = _count_observed_conversation_faults(
            conversations=conversations,
            observations=conversation_candidates.observations,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        cooldown = _start_cooldown_if_required(
            active=cooldown,
            fault_count=(
                sum(
                    isinstance(result, FaultedAgentAssignment)
                    for result in inspection_results
                )
                + conversation_fault_count
            ),
            at=at,
        )
        scheduler_failure = _combine_scheduler_failures(
            failures=[assignment_failure, conversation_candidates.failure]
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
            conversation_observations=conversation_candidates.observations,
        )
        if cooldown is not None:
            hold_reason = "global cooldown"
            if scheduler_failure is not None:
                hold_reason = f"{hold_reason}; {scheduler_failure}"
            return record.model_copy(update={"hold": hold_reason})
        if len(self.rounds) >= self.max_agents:
            capacity_reason = (
                f"at cap: {len(self.rounds)} of {self.max_agents} agents running"
            )
            hold_reason = (
                capacity_reason
                if scheduler_failure is None
                else f"{capacity_reason}; {scheduler_failure}"
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
        return self._launch_available_work(
            record=record,
            inspection_results=inspection_results,
            conversation_candidates=conversation_candidates,
            assignment_failure=assignment_failure,
            scheduler_failure=scheduler_failure,
        )

    def _launch_available_work(
        self,
        *,
        record: SchedulerRecord,
        inspection_results: list[AgentAssignmentInspectionResult],
        conversation_candidates: IssueConversationCandidateResult,
        assignment_failure: str | None,
        scheduler_failure: str | None,
    ) -> SchedulerRecord:
        """Fill free capacity while alternating between ready work kinds."""
        running_before_launches = set(self.rounds)
        if scheduler_failure is not None:
            record = record.model_copy(update={"hold": scheduler_failure})
        candidates = _ReadyAgentWork(
            assignment_rounds=prioritize_required_rounds(
                required_rounds=[
                    result
                    for result in inspection_results
                    if isinstance(result, RequiredAgentRound)
                    and assignment_failure is None
                ]
            ),
            available_issues=(
                []
                if assignment_failure is not None
                else _list_available_issues(record=record)
            ),
            conversations=list(conversation_candidates.candidates),
            conversation_failure=conversation_candidates.failure,
        )
        while len(self.rounds) < self.max_agents:
            work_kind = _choose_work_kind(
                candidates=candidates,
                last_selected_work_kind=self._last_selected_work_kind,
            )
            if work_kind is None:
                break
            self._last_selected_work_kind = work_kind
            record, inspection_results = self._launch_next_candidate(
                record=record,
                work_kind=work_kind,
                candidates=candidates,
                inspection_results=inspection_results,
            )
        return record.model_copy(
            update={
                "launched_agent_work_identifiers": [
                    identifier
                    for identifier in self.rounds
                    if identifier not in running_before_launches
                ]
            }
        )

    def _launch_next_candidate(
        self,
        *,
        record: SchedulerRecord,
        work_kind: AgentWorkKind,
        candidates: _ReadyAgentWork,
        inspection_results: list[AgentAssignmentInspectionResult],
    ) -> tuple[SchedulerRecord, list[AgentAssignmentInspectionResult]]:
        running_count = len(self.rounds)
        if work_kind is AgentWorkKind.ASSIGNMENT:
            record, inspection_results = self._launch_next_assignment_candidate(
                record=record,
                candidates=candidates,
                inspection_results=inspection_results,
            )
        else:
            record = self._launch_conversation_round(
                record=record,
                candidate=candidates.conversations.pop(0),
            )
        if len(self.rounds) == running_count:
            if work_kind is AgentWorkKind.ASSIGNMENT:
                candidates.assignment_rounds.clear()
                candidates.available_issues.clear()
            else:
                candidates.conversations.clear()
        return record, inspection_results

    def _launch_next_assignment_candidate(
        self,
        *,
        record: SchedulerRecord,
        candidates: _ReadyAgentWork,
        inspection_results: list[AgentAssignmentInspectionResult],
    ) -> tuple[SchedulerRecord, list[AgentAssignmentInspectionResult]]:
        if candidates.assignment_rounds:
            required = candidates.assignment_rounds.pop(0)
            record = self._launch_assignment_round(
                record=record,
                required=required,
            )
            if required.assignment.identifier in self.rounds:
                inspection_results = [
                    result for result in inspection_results if result is not required
                ]
                record = record.model_copy(
                    update={
                        "assignment_observations": list_assignment_observations(
                            inspection_results=inspection_results
                        )
                    }
                )
            return record, inspection_results
        return (
            self._dispatch_issue(
                record=record,
                issue=candidates.available_issues.pop(0),
            ),
            inspection_results,
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
            if (
                assignment.identifier in self.rounds
                and assignment.rounds[-1].outcome is AgentRoundOutcome.RUNNING
            ):
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
    ) -> SchedulerRecord:
        """Launch the next round for the highest-priority assignment."""
        try:
            self._launch_required_round(required=required)
        except ReportableError as failure:
            return record.model_copy(
                update={
                    "hold": _combine_scheduler_failures(
                        failures=[record.hold, str(failure)]
                    ),
                }
            )
        return record

    def _launch_required_round(self, *, required: RequiredAgentRound) -> None:
        """Start the round and advance the delivery cursor once it is running."""
        assignment = required.assignment
        harness_session_identifier = None
        prompt = required.prompt
        is_fresh_recovery = False
        if assignment.rounds:
            harness_session_identifier = find_harness_session_identifier(
                assignment=assignment
            )
            if harness_session_identifier is None:
                if not required.plan.is_recovery:
                    raise ReportableError(
                        f"Could not resume {assignment.identifier}: its first round "
                        "did not report a harness session identifier."
                    )
                prompt = f"{assignment.record.prompt}\n\n{required.prompt}"
                is_fresh_recovery = True
        if harness_session_identifier is not None:
            record_harness_session_identifier(
                assignment=assignment, identifier=harness_session_identifier
            )
        round_input = required.plan.input
        newest_user_post = (
            round_input.user_posts[-1].written_at
            if round_input is not None and round_input.user_posts
            else None
        )
        record_session_identifier = partial(
            record_harness_session_identifier, assignment=assignment
        )
        if is_fresh_recovery and newest_user_post is not None:
            record_session_identifier = partial(
                _record_session_before_advancing_user_post_cursor,
                assignment=assignment,
                newest_user_post=newest_user_post,
            )
        self.rounds[assignment.identifier] = start_agent_round(
            request=AgentRoundStartRequest(
                harness=assignment.record.harness,
                launch_request=AgentRoundLaunchRequest(
                    agent_work_identifier=assignment.identifier,
                    model=assignment.record.model,
                    effort=assignment.record.effort,
                    prompt=prompt,
                ),
                harness_session_identifier=harness_session_identifier,
                record_harness_session_identifier=record_session_identifier,
                finish_round=None,
                paths=assignment.compose_round_paths(
                    number=assignment.next_round_number
                ),
                plan=required.plan,
            ),
            clock=self.clock,
        )
        if newest_user_post is not None and not is_fresh_recovery:
            advance_user_post_delivery_cursor(
                assignment=assignment,
                newest=newest_user_post,
            )

    def _launch_conversation_round(
        self,
        *,
        record: SchedulerRecord,
        candidate: IssueConversationCandidate,
    ) -> SchedulerRecord:
        """Prepare a conversation's required work and start its next round."""
        try:
            prepared = _prepare_issue_conversation_round(
                state=self.state,
                candidate=candidate,
                requested_harness=self.requested_harness,
            )
            conversation = prepared.conversation
            number = conversation.next_round_number
            paths = conversation.compose_round_paths(number=number)
            self.rounds[conversation.identifier] = start_agent_round(
                request=AgentRoundStartRequest(
                    harness=conversation.record.harness,
                    launch_request=AgentRoundLaunchRequest(
                        agent_work_identifier=conversation.identifier,
                        model=conversation.record.model,
                        effort=conversation.record.effort,
                        prompt=prepared.prompt,
                        work_kind=AgentWorkKind.CONVERSATION,
                    ),
                    harness_session_identifier=(prepared.harness_session_identifier),
                    record_harness_session_identifier=partial(
                        record_issue_conversation_session_identifier,
                        conversation=conversation,
                    ),
                    finish_round=partial(
                        post_issue_conversation_answer,
                        repository=self.repository,
                        issue=conversation.record.issue,
                    ),
                    paths=paths,
                    plan=AgentRoundPlan(
                        purpose=IssueConversationRoundPurpose.DISCUSS,
                        is_recovery=prepared.is_recovery,
                        input=prepared.round_input,
                    ),
                ),
                clock=self.clock,
            )
        except ReportableError as failure:
            return record.model_copy(
                update={
                    "hold": _combine_scheduler_failures(
                        failures=[record.hold, str(failure)]
                    )
                }
            )
        return record.model_copy(
            update={
                "conversation_observations": [
                    observation.model_copy(
                        update={
                            "has_comments_to_answer": IssueFact(
                                value=IssueFactValue.FALSE,
                                evidence="no comments to answer",
                            )
                        }
                    )
                    if observation.issue == conversation.record.issue
                    else observation
                    for observation in record.conversation_observations
                ],
            }
        )

    def _dispatch_issue(
        self,
        *,
        record: SchedulerRecord,
        issue: IssueObservation,
    ) -> SchedulerRecord:
        """Dispatch one issue whose independent facts make it available."""
        labels = issue.dispatch_labels or []
        try:
            self._launch_assignment(issue=issue.issue, label=labels[0], at=record.at)
        except ReportableError as failure:
            return record.model_copy(
                update={
                    "hold": _combine_scheduler_failures(
                        failures=[record.hold, str(failure)]
                    )
                }
            )
        return record

    def _launch_assignment(self, *, issue: int, label: str, at: datetime) -> None:
        """Create an assignment and start its first round."""
        creator = AgentAssignmentCreator(
            state=self.state,
            repository=self.repository,
        )
        assignment = creator.create(
            route=self.config.dispatch_routes[label],
            requested_harness=self.requested_harness,
            issue=issue,
            at=at,
        )
        self._launch_required_round(
            required=compose_initial_round_requirement(assignment=assignment)
        )
