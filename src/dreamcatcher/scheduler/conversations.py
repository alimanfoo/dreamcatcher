"""Inspect issue conversations and prepare their next rounds."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundOutcome,
)
from dreamcatcher.config import AgentHarness, ConversationRoute, DreamcatcherConfig
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    ConversationComment,
    Issue,
    UnknownGitHubResponse,
    list_issue_comments,
    list_issues,
)
from dreamcatcher.issue_conversations import (
    IssueConversation,
    IssueConversationInput,
    create_issue_conversation,
    find_issue_conversation_harness_session_identifier,
    is_issue_conversation_ready_for_input,
    list_undelivered_issue_comments,
    prepare_issue_conversation_input,
    read_issue_comment_delivery_cursor,
    read_issue_conversation_input,
)
from dreamcatcher.prompts import (
    ISSUE_CONVERSATION_RECOVERY_PROMPT,
    compose_issue_conversation_prompt,
    compose_issue_conversation_round_prompt,
)
from dreamcatcher.scheduler.faults import derive_agent_work_fault
from dreamcatcher.scheduler.models import (
    IssueConversationObservation,
    IssueFact,
    IssueFactValue,
    combine_scheduler_failures,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.words import describe_count


class _ConversationScheduler(Protocol):
    """Provide the state that inspects and starts conversation work."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    requested_harness: AgentHarness
    clock: Callable[[], datetime]
    rounds: dict[str, AgentRound]


@dataclass(frozen=True, kw_only=True)
class NewIssueConversationRoundCandidate:
    """Describe an eligible issue with trusted comments waiting."""

    issue: Issue
    comments: list[ConversationComment]
    conversation: IssueConversation | None
    route: ConversationRoute


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
class _ConversationRouteListing:
    """Hold conversation issues, or the failure that stopped listing."""

    issues: list[Issue]
    failure: str | None = None


@dataclass(frozen=True, kw_only=True)
class _IssueConversationInspection:
    observation: IssueConversationObservation
    candidate: IssueConversationCandidate | None


@dataclass(frozen=True, kw_only=True)
class _PreparedIssueConversationRound:
    conversation: IssueConversation
    round_input: IssueConversationInput
    prompt: str
    harness_session_identifier: str | None
    is_recovery: bool


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
        route=candidate.route,
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
            was_stopped=(conversation.rounds[-1].outcome is AgentRoundOutcome.STOPPED),
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


def list_issue_conversation_candidates(
    *,
    scheduler: _ConversationScheduler,
    conversations: list[IssueConversation],
    previous_observations: list[IssueConversationObservation],
    most_recent_cooldown_ended: datetime | None,
) -> IssueConversationCandidateResult:
    """Observe every matching issue and return conversation work ready to run.

    Comments are read for every eligible issue that can accept a fresh batch,
    whether or not an agent is free, so that status can tell waiting from idle.
    Recovery uses the saved batch and does not read new comments. A failed read
    holds launches only where the conversation could take a new batch. When
    matching issues cannot be listed, the previous tick's issues are observed
    again with an unknown fact, so the ones the user took off the report stay
    off it.
    """
    if not scheduler.config.conversation:
        return IssueConversationCandidateResult(candidates=[], observations=[])
    listing = _list_conversation_route_issues(scheduler=scheduler)
    conversations_by_issue = {
        conversation.record.issue: conversation for conversation in conversations
    }
    candidates, observations, failures = _inspect_listed_conversations(
        scheduler=scheduler,
        listing=listing,
        conversations_by_issue=conversations_by_issue,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
    )
    observations.extend(
        _carry_forward_unlisted_observations(
            listing=listing,
            previous_observations=previous_observations,
        )
    )
    return IssueConversationCandidateResult(
        candidates=sorted(candidates, key=_rank_issue_conversation_candidate),
        observations=observations,
        failure=combine_scheduler_failures(failures=failures),
    )


def _inspect_listed_conversations(
    *,
    scheduler: _ConversationScheduler,
    listing: _ConversationRouteListing,
    conversations_by_issue: dict[int, IssueConversation],
    most_recent_cooldown_ended: datetime | None,
) -> tuple[
    list[IssueConversationCandidate],
    list[IssueConversationObservation],
    list[str | None],
]:
    candidates: list[IssueConversationCandidate] = []
    observations: list[IssueConversationObservation] = []
    failures: list[str | None] = [listing.failure]
    for issue in listing.issues:
        conversation = conversations_by_issue.get(issue.number)
        inspection = _inspect_listed_conversation_issue(
            scheduler=scheduler,
            issue=issue,
            conversation=conversation,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        if inspection is None:
            continue
        observations.append(inspection.observation)
        if inspection.candidate is not None:
            candidates.append(inspection.candidate)
        elif (
            is_issue_conversation_ready_for_input(conversation=conversation)
            and inspection.observation.has_comments_to_answer.value
            is IssueFactValue.UNKNOWN
        ):
            failures.append(inspection.observation.has_comments_to_answer.evidence)
    return candidates, observations, failures


def _carry_forward_unlisted_observations(
    *,
    listing: _ConversationRouteListing,
    previous_observations: list[IssueConversationObservation],
) -> list[IssueConversationObservation]:
    if listing.failure is None:
        return []
    unknown = IssueFact(value=IssueFactValue.UNKNOWN, evidence=listing.failure)
    listed_issues = {issue.number for issue in listing.issues}
    return [
        observation.model_copy(
            update={
                "has_comments_to_answer": unknown,
                "routing_conflict": unknown,
            }
        )
        for observation in previous_observations
        if observation.issue not in listed_issues
    ]


def _list_conversation_route_issues(
    *, scheduler: _ConversationScheduler
) -> _ConversationRouteListing:
    """List each issue found through any configured conversation route."""
    issues_by_number: dict[int, Issue] = {}
    failures: list[str | None] = []
    for route in scheduler.config.conversation:
        issue_response = list_issues(
            repository=scheduler.repository,
            label=route.label,
            assignee=scheduler.account,
        )
        if isinstance(issue_response, UnknownGitHubResponse):
            failures.append(
                f"could not list issue conversations for {route.label}: "
                f"{issue_response.reason}"
            )
        else:
            for issue in issue_response:
                issues_by_number[issue.number] = issue
    return _ConversationRouteListing(
        issues=sorted(
            issues_by_number.values(),
            key=lambda item: (item.created_at, item.number),
        ),
        failure=combine_scheduler_failures(failures=failures),
    )


def _inspect_listed_conversation_issue(
    *,
    scheduler: _ConversationScheduler,
    issue: Issue,
    conversation: IssueConversation | None,
    most_recent_cooldown_ended: datetime | None,
) -> _IssueConversationInspection | None:
    """Inspect one currently matching listed issue."""
    routes = scheduler.config.identify_conversation_routes(
        labels=[label.name for label in issue.labels]
    )
    if not routes:
        return None
    if len(routes) == 1:
        return _inspect_issue_conversation(
            scheduler=scheduler,
            route=routes[0],
            issue=issue,
            conversation=conversation,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
    labels = ", ".join(sorted((route.label for route in routes), key=str.casefold))
    return _IssueConversationInspection(
        observation=IssueConversationObservation(
            issue=issue.number,
            title=issue.title,
            has_comments_to_answer=IssueFact(
                value=IssueFactValue.FALSE,
                evidence="no comments to answer",
            ),
            routing_conflict=IssueFact(
                value=IssueFactValue.TRUE,
                evidence=f"carries more than one conversation label: {labels}",
            ),
        ),
        candidate=None,
    )


def _inspect_issue_conversation(
    *,
    scheduler: _ConversationScheduler,
    route: ConversationRoute,
    issue: Issue,
    conversation: IssueConversation | None,
    most_recent_cooldown_ended: datetime | None,
) -> _IssueConversationInspection:
    """Observe one eligible issue, and return a candidate when it is ready."""
    recovery = _inspect_conversation_recovery(
        issue=issue,
        conversation=conversation,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
    )
    if recovery is not None:
        return recovery
    comments, has_comments_to_answer = _observe_conversation_comments(
        scheduler=scheduler,
        issue=issue.number,
        conversation=conversation,
    )
    observation = IssueConversationObservation(
        issue=issue.number,
        title=issue.title,
        has_comments_to_answer=has_comments_to_answer,
    )
    candidate = None
    if comments and is_issue_conversation_ready_for_input(conversation=conversation):
        candidate = NewIssueConversationRoundCandidate(
            issue=issue,
            comments=comments,
            conversation=conversation,
            route=route,
        )
    return _IssueConversationInspection(observation=observation, candidate=candidate)


def _inspect_conversation_recovery(
    *,
    issue: Issue,
    conversation: IssueConversation | None,
    most_recent_cooldown_ended: datetime | None,
) -> _IssueConversationInspection | None:
    if conversation is not None and derive_agent_work_fault(
        rounds=conversation.rounds,
        retry_requested_at=conversation.record.retry_requested_at,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
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
    return None


def _observe_conversation_comments(
    *,
    scheduler: _ConversationScheduler,
    issue: int,
    conversation: IssueConversation | None,
) -> tuple[list[ConversationComment], IssueFact]:
    try:
        comments = _list_comments_to_answer(
            repository=scheduler.repository,
            account=scheduler.account,
            issue=issue,
            conversation=conversation,
        )
    except ReportableError as failure:
        return [], IssueFact(value=IssueFactValue.UNKNOWN, evidence=str(failure))
    return comments, (
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
