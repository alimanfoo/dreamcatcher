"""Schedule agent work for one Dreamcatcher instance.

Each tick reads local agent work, observes relevant issues on GitHub, publishes
saved conversation answers, applies the concurrency cap and global cooldown,
and launches at most one round.

Within assignment work, a missing first round comes first, followed by recovery,
wrap-up, user feedback, and dispatch of the oldest available issue. Conversation
work uses its oldest waiting comment. When both kinds are ready, the scheduler
alternates which kind receives the next free slot.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Annotated, Self, cast

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
    AgentAssignmentRoundInput,
    AgentRound,
    AgentRoundOutcome,
    AgentRoundPlan,
    AgentRoundPurpose,
    AgentRoundRecord,
    AgentRoundStartRequest,
    ErroredAgentRoundEnding,
    IssueConversationInput,
    describe_unfinished_agent_round,
    record_agent_round_launch_failure,
    start_agent_round,
)
from dreamcatcher.config import (
    AgentHarness,
    DreamcatcherConfig,
    IssueConversationConfig,
)
from dreamcatcher.documents import DreamcatcherDocument, read_json, read_text
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
    post_issue_comment,
    read_issue,
    read_issue_pull_request_context,
    read_pull_request,
)
from dreamcatcher.harness_adapters import AgentRoundLaunchRequest, AgentWorkKind
from dreamcatcher.issue_conversations import (
    IssueConversation,
    create_issue_conversation,
    list_undelivered_issue_comments,
    prepare_issue_conversation_input,
    read_issue_comment_delivery_cursor,
    read_issue_conversation_input,
    read_issue_conversation_reply,
    read_issue_conversations,
    record_issue_conversation_reply_publication,
    record_issue_conversation_session_identifier,
    save_issue_conversation_reply,
)
from dreamcatcher.prompts import (
    AGENT_POST_MARKER,
    RECOVERY_PROMPT,
    compose_issue_conversation_prompt,
    compose_issue_conversation_recovery_prompt,
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
    launched_agent_work_identifier: str | None = None
    issue_observations: list[IssueObservation] = Field(default_factory=list)
    assignment_observations: list[AgentAssignmentObservation] = Field(
        default_factory=list
    )
    conversation_eligibility: dict[int, IssueFact] = Field(default_factory=dict)
    cooldown: GlobalCooldown | None = None
    most_recent_cooldown_ended: UtcDateTime | None = None

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_launched_identifiers(cls, value: object, /) -> object:
        """Read scheduler records written before launches had one owner-neutral key."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        assignment = data.pop("launched_assignment_identifier", None)
        conversation = data.pop("launched_conversation_identifier", None)
        if "launched_agent_work_identifier" not in data:
            data["launched_agent_work_identifier"] = assignment or conversation
        return data

    @property
    def launched_assignment_identifier(self) -> str | None:
        """The launched identifier when it belongs to an assignment."""
        identifier = self.launched_agent_work_identifier
        if identifier is None or identifier.startswith("conversation-"):
            return None
        return identifier

    @property
    def launched_conversation_identifier(self) -> str | None:
        """The launched identifier when it belongs to a conversation."""
        identifier = self.launched_agent_work_identifier
        if identifier is not None and identifier.startswith("conversation-"):
            return identifier
        return None


@dataclass(frozen=True, kw_only=True)
class RequiredAgentRound:
    """Describe the next round that an assignment requires."""

    assignment: AgentAssignment
    plan: AgentRoundPlan[AgentAssignmentRoundInput]
    reason: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class IssueConversationCandidate:
    """Describe an eligible issue with trusted comments waiting."""

    issue: Issue
    comments: list[ConversationComment]
    conversation: IssueConversation | None
    config: IssueConversationConfig


@dataclass(frozen=True, kw_only=True)
class IssueConversationCandidateResult:
    """Collect conversation observations, candidates, and any failed read."""

    candidates: list[IssueConversationCandidate]
    eligibility: dict[int, IssueFact]
    failure: str | None = None


@dataclass(frozen=True, kw_only=True)
class RequiredIssueConversationRound:
    """Describe the recovery round that an issue conversation requires."""

    conversation: IssueConversation
    plan: AgentRoundPlan[IssueConversationInput]
    prompt: str


@dataclass(frozen=True, kw_only=True)
class IssueConversationInspectionResult:
    """Collect locally required rounds, faults, and failed reads."""

    required_rounds: list[RequiredIssueConversationRound]
    fault_count: int
    failure: str | None = None


type IssueConversationWork = IssueConversationCandidate | RequiredIssueConversationRound


@dataclass(frozen=True, kw_only=True)
class _AgentWorkReadFailures:
    """Collect the read failures that constrain launch selection."""

    assignment: str | None
    scheduler: str | None


@dataclass(frozen=True, kw_only=True)
class FaultedAgentAssignment:
    """Describe an assignment whose errors stop ordinary recovery."""

    assignment: AgentAssignment
    reason: str


type AgentAssignmentInspectionResult = (
    RequiredAgentRound | FaultedAgentAssignment | AgentAssignmentObservation
)


def _select_agent_work_kind(
    *,
    last_selected: AgentWorkKind | None,
    is_assignment_ready: bool,
    is_conversation_ready: bool,
) -> AgentWorkKind | None:
    """Select one ready work kind while alternating when both are ready."""
    if is_assignment_ready and is_conversation_ready:
        return (
            AgentWorkKind.CONVERSATION
            if last_selected is AgentWorkKind.ASSIGNMENT
            else AgentWorkKind.ASSIGNMENT
        )
    if is_assignment_ready:
        return AgentWorkKind.ASSIGNMENT
    if is_conversation_ready:
        return AgentWorkKind.CONVERSATION
    return None


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


def derive_assignment_fault(
    *, assignment: AgentAssignment, most_recent_cooldown_ended: datetime | None
) -> bool:
    """Derive whether an assignment has two current consecutive errors."""
    return derive_agent_work_fault(
        rounds=assignment.rounds,
        retry_requested_at=assignment.record.retry_requested_at,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
    )


def derive_issue_conversation_fault(
    *, conversation: IssueConversation, most_recent_cooldown_ended: datetime | None
) -> bool:
    """Derive whether a conversation has two current consecutive errors."""
    return derive_agent_work_fault(
        rounds=conversation.rounds,
        retry_requested_at=conversation.record.retry_requested_at,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
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
    """Start a cooldown when two agent-work owners are currently in fault."""
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
    recovery_reason = describe_unfinished_agent_round(rounds=assignment.rounds)
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


def compose_issue_conversation_recovery_requirement(
    *, conversation: IssueConversation
) -> RequiredIssueConversationRound | None:
    """Return the recovery round required by unfinished conversation work."""
    input_number = conversation.next_round_number
    if conversation.unrecorded_round_input is None:
        if describe_unfinished_agent_round(rounds=conversation.rounds) is None:
            return None
        input_number = conversation.rounds[-1].number
    round_input = read_issue_conversation_input(
        conversation=conversation,
        number=input_number,
    )
    paths = conversation.compose_round_paths(number=conversation.next_round_number)
    return RequiredIssueConversationRound(
        conversation=conversation,
        plan=AgentRoundPlan(
            purpose=AgentRoundPurpose.DISCUSS,
            is_recovery=True,
            input=round_input,
        ),
        prompt=compose_issue_conversation_recovery_prompt(
            issue=conversation.record.issue,
            round_input=paths.round_input,
        ),
    )


def _list_issue_conversation_candidates(
    *,
    repository: str,
    account: str,
    config: DreamcatcherConfig,
    conversations: list[IssueConversation],
    should_read_comments: bool,
) -> IssueConversationCandidateResult:
    """Return eligible issues whose next trusted comment batch is waiting."""
    conversation_config = config.conversation
    if conversation_config is None:
        return IssueConversationCandidateResult(
            candidates=[],
            eligibility={
                conversation.record.issue: _compose_known_issue_fact(value=False)
                for conversation in conversations
            },
        )
    issue_response = list_issues(
        repository=repository,
        label=conversation_config.label,
        assignee=account,
    )
    if isinstance(issue_response, UnknownGitHubResponse):
        return IssueConversationCandidateResult(
            candidates=[],
            eligibility={
                conversation.record.issue: _compose_unknown_issue_fact(
                    evidence=issue_response.reason
                )
                for conversation in conversations
            },
            failure=f"could not list issue conversations: {issue_response.reason}",
        )
    eligible_issue_numbers = {issue.number for issue in issue_response}
    eligibility = {
        conversation.record.issue: _compose_known_issue_fact(
            value=conversation.record.issue in eligible_issue_numbers
        )
        for conversation in conversations
    }
    if not should_read_comments:
        return IssueConversationCandidateResult(
            candidates=[],
            eligibility=eligibility,
        )
    conversations_by_issue = {
        conversation.record.issue: conversation for conversation in conversations
    }
    candidates: list[IssueConversationCandidate] = []
    failures: list[str | None] = []
    for issue in sorted(
        issue_response, key=lambda item: (item.created_at, item.number)
    ):
        conversation = conversations_by_issue.get(issue.number)
        candidate, failure = _inspect_issue_conversation_candidate(
            repository=repository,
            account=account,
            config=conversation_config,
            issue=issue,
            conversation=conversation,
        )
        failures.append(failure)
        if candidate is not None:
            candidates.append(candidate)
    return IssueConversationCandidateResult(
        candidates=sorted(
            candidates,
            key=lambda candidate: (
                candidate.comments[0].written_at,
                candidate.comments[0].id,
            ),
        ),
        eligibility=eligibility,
        failure=_combine_scheduler_failures(failures=failures),
    )


def _inspect_issue_conversation_candidate(
    *,
    repository: str,
    account: str,
    config: IssueConversationConfig,
    issue: Issue,
    conversation: IssueConversation | None,
) -> tuple[IssueConversationCandidate | None, str | None]:
    """Return one ready candidate or the failed read that prevented it."""
    try:
        if conversation is not None and not _is_conversation_ready_for_input(
            conversation=conversation
        ):
            return None, None
    except ReportableError as failure:
        return None, f"could not inspect saved conversation GH{issue.number}: {failure}"
    comment_response = list_issue_comments(repository=repository, issue=issue.number)
    if isinstance(comment_response, UnknownGitHubResponse):
        return (
            None,
            f"could not read comments for GH{issue.number}: {comment_response.reason}",
        )
    try:
        cursor = (
            None
            if conversation is None
            else read_issue_comment_delivery_cursor(conversation=conversation)
        )
    except ReportableError as failure:
        return (
            None,
            f"could not read delivered comments for GH{issue.number}: {failure}",
        )
    comments = list_undelivered_issue_comments(
        comments=comment_response,
        account=account,
        cursor=cursor,
    )
    if not comments:
        return None, None
    return (
        IssueConversationCandidate(
            issue=issue,
            comments=comments,
            conversation=conversation,
            config=config,
        ),
        None,
    )


def _select_issue_conversation_work(
    *,
    required_rounds: list[RequiredIssueConversationRound],
    candidates: list[IssueConversationCandidate],
) -> IssueConversationWork | None:
    """Return the conversation work holding the oldest accepted comment."""
    work: list[IssueConversationWork] = [*required_rounds, *candidates]
    return min(work, key=_rank_issue_conversation_work) if work else None


def _rank_issue_conversation_work(work: IssueConversationWork, /) -> tuple[str, int]:
    if isinstance(work, IssueConversationCandidate):
        comments = work.comments
    else:
        round_input = cast("IssueConversationInput", work.plan.input)
        comments = round_input.comments
    first = comments[0]
    return first.written_at, first.id


def _is_conversation_ready_for_input(*, conversation: IssueConversation) -> bool:
    """Return whether a conversation can accept another comment batch."""
    if conversation.unrecorded_round_input is not None:
        return False
    if not conversation.rounds:
        return True
    latest = conversation.rounds[-1]
    if latest.outcome is not AgentRoundOutcome.SUCCESSFUL:
        return False
    reply = read_issue_conversation_reply(
        conversation=conversation,
        number=latest.number,
    )
    return reply is not None and reply.is_complete


def _publish_issue_conversation_replies(
    *, repository: str, conversations: list[IssueConversation], at: datetime
) -> str | None:
    """Save successful final answers and publish each answer still waiting."""
    failures: list[str | None] = []
    for conversation in conversations:
        try:
            failures.append(
                _publish_issue_conversation_reply(
                    repository=repository,
                    conversation=conversation,
                    at=at,
                )
            )
        except ReportableError as failure:
            failures.append(
                f"could not publish the answer for GH{conversation.record.issue}: "
                f"{failure}"
            )
    return _combine_scheduler_failures(failures=failures)


def _publish_issue_conversation_reply(
    *, repository: str, conversation: IssueConversation, at: datetime
) -> str | None:
    """Publish one conversation's saved or newly completed answer."""
    if not conversation.rounds:
        return None
    record = conversation.rounds[-1]
    reply = read_issue_conversation_reply(
        conversation=conversation,
        number=record.number,
    )
    if reply is None:
        if record.outcome is not AgentRoundOutcome.SUCCESSFUL:
            return None
        final_output = read_text(
            path=conversation.compose_round_paths(number=record.number).final_output
        )
        reply = save_issue_conversation_reply(
            conversation=conversation,
            number=record.number,
            body=final_output,
        )
    if reply.is_complete:
        return None
    response = post_issue_comment(
        repository=repository,
        issue=conversation.record.issue,
        body=f"{reply.body}\n\n{AGENT_POST_MARKER}",
    )
    if isinstance(response, UnknownGitHubResponse):
        return (
            f"could not publish the answer for GH{conversation.record.issue}: "
            f"{response.reason}"
        )
    record_issue_conversation_reply_publication(
        conversation=conversation,
        number=record.number,
        at=at,
    )
    return None


def _combine_scheduler_failures(*, failures: list[str | None]) -> str | None:
    """Join independent scheduler read or publication failures."""
    present = [failure for failure in failures if failure is not None]
    return "; ".join(present) if present else None


def _find_oldest_available_issue(*, record: SchedulerRecord) -> IssueObservation | None:
    """Return the first issue that the scheduler observed as available."""
    return next(
        (
            observation
            for observation in record.issue_observations
            if observation.availability.value is IssueFactValue.TRUE
        ),
        None,
    )


@dataclass(kw_only=True)
class AgentWorkScheduler:
    """Choose and start the work for one Dreamcatcher instance."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    requested_assignment_harness: AgentHarness
    clock: Callable[[], datetime]
    rounds: dict[str, AgentRound]
    max_agents: int = DEFAULT_MAX_AGENTS
    _last_selected_work_kind: AgentWorkKind | None = field(
        default=None, init=False, repr=False
    )

    def tick(self, *, at: datetime) -> SchedulerRecord:
        """Inspect current work and launch at most one agent round.

        A round that has ended is forgotten first, so the cap counts what is
        running now. A failure reaches the daemon, which reports it before the
        next tick tries again.

        Every tick observes relevant issues so that status stays current while
        open work runs or waits for capacity. A failed read prevents launches
        in the workflow that depends on it without holding the other workflow.

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
        ended_agent_work_identifiers = [
            agent_work_identifier
            for agent_work_identifier, running in self.rounds.items()
            if not running.is_alive
        ]
        for agent_work_identifier in ended_agent_work_identifiers:
            del self.rounds[agent_work_identifier]
        assignments = read_agent_assignments(state=self.state)
        conversations = read_issue_conversations(state=self.state)
        publication_failure = _publish_issue_conversation_replies(
            repository=self.repository,
            conversations=conversations,
            at=at,
        )
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
        conversation_inspection = self._inspect_conversations(
            conversations=conversations,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        cooldown = _start_cooldown_if_required(
            active=cooldown,
            fault_count=(
                sum(
                    isinstance(result, FaultedAgentAssignment)
                    for result in inspection_results
                )
                + conversation_inspection.fault_count
            ),
            at=at,
        )
        conversation_candidates = _list_issue_conversation_candidates(
            repository=self.repository,
            account=self.account,
            config=self.config,
            conversations=conversations,
            should_read_comments=(
                cooldown is None and len(self.rounds) < self.max_agents
            ),
        )
        conversation_failure = _combine_scheduler_failures(
            failures=[
                conversation_candidates.failure,
                publication_failure,
            ]
        )
        scheduler_failure = _combine_scheduler_failures(
            failures=[
                assignment_failure,
                conversation_inspection.failure,
                conversation_failure,
            ]
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
            conversation_eligibility=conversation_candidates.eligibility,
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
            conversation_inspection=conversation_inspection,
            conversation_candidates=conversation_candidates,
            failures=_AgentWorkReadFailures(
                assignment=assignment_failure,
                scheduler=scheduler_failure,
            ),
        )

    def _launch_available_work(
        self,
        *,
        record: SchedulerRecord,
        inspection_results: list[AgentAssignmentInspectionResult],
        conversation_inspection: IssueConversationInspectionResult,
        conversation_candidates: IssueConversationCandidateResult,
        failures: _AgentWorkReadFailures,
    ) -> SchedulerRecord:
        """Launch one candidate while alternating between ready work kinds."""
        if failures.scheduler is not None:
            record = record.model_copy(update={"hold": failures.scheduler})
        prioritized_rounds = prioritize_required_rounds(
            required_rounds=[
                result
                for result in inspection_results
                if isinstance(result, RequiredAgentRound)
                and failures.assignment is None
            ]
        )
        available_issue = (
            None
            if failures.assignment is not None
            else _find_oldest_available_issue(record=record)
        )
        conversation_work = _select_issue_conversation_work(
            required_rounds=conversation_inspection.required_rounds,
            candidates=(
                []
                if conversation_candidates.failure is not None
                else conversation_candidates.candidates
            ),
        )
        is_assignment_ready = bool(prioritized_rounds) or available_issue is not None
        is_conversation_ready = conversation_work is not None
        work_kind = _select_agent_work_kind(
            last_selected=self._last_selected_work_kind,
            is_assignment_ready=is_assignment_ready,
            is_conversation_ready=is_conversation_ready,
        )
        if work_kind is None:
            return record
        self._last_selected_work_kind = work_kind
        if work_kind is AgentWorkKind.ASSIGNMENT and prioritized_rounds:
            return self._launch_assignment_round(
                record=record,
                required=prioritized_rounds[0],
                inspection_results=inspection_results,
            )
        if work_kind is AgentWorkKind.ASSIGNMENT:
            return self._dispatch_issue(
                record=record,
                issue=cast("IssueObservation", available_issue),
            )
        if isinstance(conversation_work, RequiredIssueConversationRound):
            return self._launch_required_conversation_round(
                record=record,
                required=conversation_work,
            )
        return self._launch_conversation_round(
            record=record,
            candidate=cast("IssueConversationCandidate", conversation_work),
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

    def _inspect_conversations(
        self,
        *,
        conversations: list[IssueConversation],
        most_recent_cooldown_ended: datetime | None,
    ) -> IssueConversationInspectionResult:
        """Return recovery rounds derived only from saved conversation state."""
        required_rounds: list[RequiredIssueConversationRound] = []
        fault_count = 0
        failures: list[str | None] = []
        for conversation in conversations:
            if conversation.identifier in self.rounds:
                continue
            if derive_issue_conversation_fault(
                conversation=conversation,
                most_recent_cooldown_ended=most_recent_cooldown_ended,
            ):
                fault_count += 1
                continue
            try:
                required = compose_issue_conversation_recovery_requirement(
                    conversation=conversation
                )
            except ReportableError as failure:
                failures.append(
                    f"could not inspect {conversation.identifier}: {failure}"
                )
                continue
            if required is not None:
                required_rounds.append(required)
        return IssueConversationInspectionResult(
            required_rounds=required_rounds,
            fault_count=fault_count,
            failure=_combine_scheduler_failures(failures=failures),
        )

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
                    "hold": _combine_scheduler_failures(
                        failures=[record.hold, str(failure)]
                    ),
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
                "launched_agent_work_identifier": required.assignment.identifier,
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

    def _launch_conversation_round(
        self,
        *,
        record: SchedulerRecord,
        candidate: IssueConversationCandidate,
    ) -> SchedulerRecord:
        """Create a conversation as needed and start its next round."""
        try:
            conversation = candidate.conversation or create_issue_conversation(
                state=self.state,
                config=candidate.config,
                issue=candidate.issue,
            )
            round_input = prepare_issue_conversation_input(
                state=self.state,
                conversation=conversation,
                issue=candidate.issue,
                comments=candidate.comments,
            )
            number = conversation.next_round_number
            paths = conversation.compose_round_paths(number=number)
            prompt = compose_issue_conversation_prompt(
                template=conversation.record.prompt,
                issue=conversation.record.issue,
                round_input=paths.round_input,
            )
            if conversation.rounds:
                prompt = compose_issue_conversation_round_prompt(
                    issue=conversation.record.issue,
                    round_input=paths.round_input,
                )
        except ReportableError as failure:
            return record.model_copy(
                update={
                    "hold": _combine_scheduler_failures(
                        failures=[record.hold, str(failure)]
                    )
                }
            )
        return self._launch_issue_conversation_attempt(
            record=record,
            conversation=conversation,
            plan=AgentRoundPlan(
                purpose=AgentRoundPurpose.DISCUSS,
                is_recovery=False,
                input=round_input,
            ),
            prompt=prompt,
        )

    def _launch_required_conversation_round(
        self,
        *,
        record: SchedulerRecord,
        required: RequiredIssueConversationRound,
    ) -> SchedulerRecord:
        """Start one recovery round from its saved input and revision."""
        return self._launch_issue_conversation_attempt(
            record=record,
            conversation=required.conversation,
            plan=required.plan,
            prompt=required.prompt,
        )

    def _launch_issue_conversation_attempt(
        self,
        *,
        record: SchedulerRecord,
        conversation: IssueConversation,
        plan: AgentRoundPlan[IssueConversationInput],
        prompt: str,
    ) -> SchedulerRecord:
        """Start or durably fail one prepared issue-conversation attempt."""
        harness_session_identifier = conversation.record.harness_session_identifier
        request = AgentRoundStartRequest(
            harness=conversation.record.harness,
            launch_request=AgentRoundLaunchRequest(
                agent_work_identifier=conversation.identifier,
                model=conversation.record.model,
                effort=conversation.record.effort,
                prompt=prompt,
                work_kind=AgentWorkKind.CONVERSATION,
            ),
            harness_session_identifier=harness_session_identifier,
            record_harness_session_identifier=partial(
                record_issue_conversation_session_identifier,
                conversation=conversation,
            ),
            paths=conversation.compose_round_paths(
                number=conversation.next_round_number
            ),
            plan=plan,
        )
        try:
            if (
                any(round.pid is not None for round in conversation.rounds)
                and harness_session_identifier is None
            ):
                raise ReportableError(
                    f"Could not resume {conversation.identifier}: its first "
                    "round did not report a harness session identifier."
                )
            self.rounds[conversation.identifier] = start_agent_round(
                request=request,
                clock=self.clock,
            )
        except ReportableError as failure:
            record_agent_round_launch_failure(
                request=request,
                at=self.clock(),
                reason=str(failure),
            )
            return record.model_copy(
                update={
                    "hold": _combine_scheduler_failures(
                        failures=[record.hold, str(failure)]
                    )
                }
            )
        return record.model_copy(
            update={"launched_agent_work_identifier": conversation.identifier}
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
            assignment_identifier = self._launch_assignment(
                issue=issue.issue, label=labels[0], at=record.at
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
            update={"launched_agent_work_identifier": assignment_identifier}
        )

    def _launch_assignment(self, *, issue: int, label: str, at: datetime) -> str:
        """Create an assignment and start its first round."""
        creator = AgentAssignmentCreator(
            state=self.state,
            repository=self.repository,
        )
        assignment = creator.create(
            route=self.config.dispatch_routes[label],
            requested_harness=self.requested_assignment_harness,
            issue=issue,
            at=at,
        )
        self._launch_required_round(
            required=compose_initial_round_requirement(assignment=assignment)
        )
        return assignment.identifier
