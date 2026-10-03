"""Inspect issue conversations and prepare their next rounds."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial

from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundOutcome,
    AgentRoundPlan,
    AgentRoundStartRequest,
    ConversationRoundPurpose,
    start_agent_round,
)
from dreamcatcher.config import AgentHarness, ConversationRoute
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    ConversationComment,
    Issue,
    UnknownGitHubResponse,
    list_issue_comments,
    list_issues,
)
from dreamcatcher.harness_adapters import AgentRoundLaunchRequest, AgentWorkKind
from dreamcatcher.issue_conversations import (
    Conversation,
    ConversationInput,
    create_conversation,
    find_conversation_harness_session_identifier,
    is_conversation_ready_for_input,
    list_undelivered_issue_comments,
    post_conversation_answer,
    prepare_conversation_input,
    read_conversation_input,
    read_issue_comment_delivery_cursor,
    record_conversation_session_identifier,
)
from dreamcatcher.prompts import (
    CONVERSATION_RECOVERY_PROMPT,
    compose_conversation_prompt,
    compose_conversation_round_prompt,
)
from dreamcatcher.scheduler.agent_work import AgentWorkScheduler
from dreamcatcher.scheduler.faults import derive_agent_work_fault
from dreamcatcher.scheduler.models import (
    ConversationObservation,
    IssueFact,
    IssueFactValue,
    SchedulerRecord,
    combine_scheduler_failures,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.words import describe_count


@dataclass(frozen=True, kw_only=True)
class NewConversationRoundCandidate:
    """Describe an eligible issue with trusted comments waiting."""

    issue: Issue
    comments: list[ConversationComment]
    conversation: Conversation | None
    route: ConversationRoute


@dataclass(frozen=True, kw_only=True)
class ConversationRecoveryCandidate:
    """Describe an eligible conversation with unfinished work to recover."""

    conversation: Conversation


type ConversationCandidate = (
    NewConversationRoundCandidate | ConversationRecoveryCandidate
)


@dataclass(frozen=True, kw_only=True)
class ConversationCandidateResult:
    """Collect conversation observations, candidates, and any failed read."""

    candidates: list[ConversationCandidate]
    observations: list[ConversationObservation]
    failure: str | None = None


@dataclass(frozen=True, kw_only=True)
class _ConversationRouteListing:
    """Hold conversation issues, or the failure that stopped listing."""

    issues: list[Issue]
    failure: str | None = None


@dataclass(frozen=True, kw_only=True)
class _ConversationInspection:
    observation: ConversationObservation
    candidate: ConversationCandidate | None


@dataclass(frozen=True, kw_only=True)
class _PreparedConversationRound:
    conversation: Conversation
    round_input: ConversationInput
    prompt: str
    harness_session_identifier: str | None
    is_recovery: bool


@dataclass(frozen=True, kw_only=True)
class ConversationInspectionRequest:
    """Hold the current inputs for inspecting conversation work."""

    conversations: list[Conversation]
    previous_observations: list[ConversationObservation]
    most_recent_cooldown_ended: datetime | None


@dataclass(frozen=True, kw_only=True)
class ConversationLaunchRequest:
    """Hold the current inputs for launching conversation work."""

    record: SchedulerRecord
    candidate: ConversationCandidate


class ConversationScheduler(
    AgentWorkScheduler[
        ConversationCandidate,
        tuple[int, str, int],
        ConversationInspectionRequest,
        ConversationLaunchRequest,
    ]
):
    """Inspect, rank and launch conversation work."""

    def inspect(
        self, *, request: ConversationInspectionRequest
    ) -> ConversationCandidateResult:
        """Observe matching issues and return conversation work ready to run."""
        if not self.config.conversation:
            return ConversationCandidateResult(candidates=[], observations=[])
        listing = self._list_route_issues()
        conversations_by_issue = {
            conversation.record.issue: conversation
            for conversation in request.conversations
        }
        candidates, observations, failures = self._inspect_listed_conversations(
            listing=listing,
            conversations_by_issue=conversations_by_issue,
            most_recent_cooldown_ended=request.most_recent_cooldown_ended,
        )
        observations.extend(
            _carry_forward_unlisted_observations(
                listing=listing,
                previous_observations=request.previous_observations,
            )
        )
        return ConversationCandidateResult(
            candidates=sorted(candidates, key=self.rank),
            observations=observations,
            failure=combine_scheduler_failures(failures=failures),
        )

    def rank(self, candidate: ConversationCandidate, /) -> tuple[int, str, int]:
        """Rank a conversation candidate when `sorted` passes it by position."""
        if isinstance(candidate, ConversationRecoveryCandidate):
            return (0, "", candidate.conversation.record.issue)
        first_comment = candidate.comments[0]
        return (1, first_comment.written_at, first_comment.id)

    def launch(
        self, *, request: ConversationLaunchRequest
    ) -> tuple[SchedulerRecord, AgentRound]:
        """Prepare a conversation's required work and start its next round."""
        prepared = _prepare_conversation_round(
            state=self.state,
            candidate=request.candidate,
            requested_harness=self.requested_harness,
        )
        conversation, round_ = self._start_round(prepared=prepared)
        return (
            _record_conversation_comments_delivered(
                record=request.record,
                issue=conversation.record.issue,
            ),
            round_,
        )

    def _inspect_listed_conversations(
        self,
        *,
        listing: _ConversationRouteListing,
        conversations_by_issue: dict[int, Conversation],
        most_recent_cooldown_ended: datetime | None,
    ) -> tuple[
        list[ConversationCandidate],
        list[ConversationObservation],
        list[str | None],
    ]:
        candidates: list[ConversationCandidate] = []
        observations: list[ConversationObservation] = []
        failures: list[str | None] = [listing.failure]
        for issue in listing.issues:
            conversation = conversations_by_issue.get(issue.number)
            inspection = self._inspect_listed_issue(
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
                is_conversation_ready_for_input(conversation=conversation)
                and inspection.observation.has_comments_to_answer.value
                is IssueFactValue.UNKNOWN
            ):
                failures.append(inspection.observation.has_comments_to_answer.evidence)
        return candidates, observations, failures

    def _list_route_issues(self) -> _ConversationRouteListing:
        """List each issue found through a configured conversation route."""
        issues_by_number: dict[int, Issue] = {}
        failures: list[str | None] = []
        for route in self.config.conversation:
            issue_response = list_issues(
                repository=self.repository,
                label=route.label,
                assignee=self.account,
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

    def _inspect_listed_issue(
        self,
        *,
        issue: Issue,
        conversation: Conversation | None,
        most_recent_cooldown_ended: datetime | None,
    ) -> _ConversationInspection | None:
        """Inspect one currently matching listed issue."""
        routes = self.config.identify_conversation_routes(
            labels=[label.name for label in issue.labels]
        )
        if not routes:
            return None
        if len(routes) == 1:
            return self._inspect_conversation(
                route=routes[0],
                issue=issue,
                conversation=conversation,
                most_recent_cooldown_ended=most_recent_cooldown_ended,
            )
        labels = ", ".join(sorted((route.label for route in routes), key=str.casefold))
        return _ConversationInspection(
            observation=ConversationObservation(
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

    def _inspect_conversation(
        self,
        *,
        route: ConversationRoute,
        issue: Issue,
        conversation: Conversation | None,
        most_recent_cooldown_ended: datetime | None,
    ) -> _ConversationInspection:
        """Observe one eligible issue and return a candidate when ready."""
        recovery = _inspect_conversation_recovery(
            issue=issue,
            conversation=conversation,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        if recovery is not None:
            return recovery
        comments, has_comments_to_answer = self._observe_comments(
            issue=issue.number,
            conversation=conversation,
        )
        observation = ConversationObservation(
            issue=issue.number,
            title=issue.title,
            has_comments_to_answer=has_comments_to_answer,
        )
        candidate = None
        if comments and is_conversation_ready_for_input(conversation=conversation):
            candidate = NewConversationRoundCandidate(
                issue=issue,
                comments=comments,
                conversation=conversation,
                route=route,
            )
        return _ConversationInspection(observation=observation, candidate=candidate)

    def _observe_comments(
        self,
        *,
        issue: int,
        conversation: Conversation | None,
    ) -> tuple[list[ConversationComment], IssueFact]:
        try:
            comments = _list_comments_to_answer(
                repository=self.repository,
                account=self.account,
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

    def _start_round(
        self, *, prepared: _PreparedConversationRound
    ) -> tuple[Conversation, AgentRound]:
        conversation = prepared.conversation
        round_ = start_agent_round(
            request=AgentRoundStartRequest(
                harness=conversation.record.harness,
                launch_request=AgentRoundLaunchRequest(
                    agent_work_identifier=conversation.identifier,
                    model=conversation.record.model,
                    effort=conversation.record.effort,
                    prompt=prepared.prompt,
                    work_kind=AgentWorkKind.CONVERSATION,
                ),
                harness_session_identifier=prepared.harness_session_identifier,
                record_harness_session_identifier=partial(
                    record_conversation_session_identifier,
                    conversation=conversation,
                ),
                finish_round=partial(
                    post_conversation_answer,
                    repository=self.repository,
                    issue=conversation.record.issue,
                ),
                paths=conversation.compose_round_paths(
                    number=conversation.next_round_number
                ),
                plan=AgentRoundPlan(
                    purpose=ConversationRoundPurpose.DISCUSS,
                    is_recovery=prepared.is_recovery,
                    input=prepared.round_input,
                ),
            ),
            clock=self.clock,
        )
        return conversation, round_


def _prepare_conversation_round(
    *,
    state: StateDirectory,
    candidate: ConversationCandidate,
    requested_harness: AgentHarness,
) -> _PreparedConversationRound:
    """Prepare either a fresh conversation batch or unfinished work."""
    if isinstance(candidate, ConversationRecoveryCandidate):
        return _prepare_conversation_recovery(conversation=candidate.conversation)
    conversation = candidate.conversation or create_conversation(
        state=state,
        route=candidate.route,
        requested_harness=requested_harness,
        issue=candidate.issue,
    )
    round_input = prepare_conversation_input(
        state=state,
        conversation=conversation,
        issue=candidate.issue,
        comments=candidate.comments,
    )
    paths = conversation.compose_round_paths(number=conversation.next_round_number)
    harness_session_identifier = None
    prompt = compose_conversation_prompt(
        template=conversation.record.prompt,
        issue=conversation.record.issue,
        round_input=paths.round_input,
    )
    if conversation.rounds:
        harness_session_identifier = find_conversation_harness_session_identifier(
            conversation=conversation
        )
        if harness_session_identifier is None:
            raise ReportableError(
                f"Could not resume {conversation.identifier}: its first round did "
                "not report a harness session identifier."
            )
        prompt = compose_conversation_round_prompt(
            issue=conversation.record.issue,
            round_input=paths.round_input,
            was_stopped=(conversation.rounds[-1].outcome is AgentRoundOutcome.STOPPED),
        )
    return _PreparedConversationRound(
        conversation=conversation,
        round_input=round_input,
        prompt=prompt,
        harness_session_identifier=harness_session_identifier,
        is_recovery=False,
    )


def _prepare_conversation_recovery(
    *, conversation: Conversation
) -> _PreparedConversationRound:
    """Prepare a recovery from the latest round's saved input and session."""
    latest_round = conversation.rounds[-1]
    round_input = read_conversation_input(
        conversation=conversation,
        number=latest_round.number,
    )
    harness_session_identifier = find_conversation_harness_session_identifier(
        conversation=conversation
    )
    if harness_session_identifier is None:
        next_input = conversation.compose_round_paths(
            number=conversation.next_round_number
        ).round_input
        prompt = compose_conversation_prompt(
            template=conversation.record.prompt,
            issue=conversation.record.issue,
            round_input=next_input,
        )
    else:
        prompt = CONVERSATION_RECOVERY_PROMPT
    return _PreparedConversationRound(
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
    conversation: Conversation | None,
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


def _carry_forward_unlisted_observations(
    *,
    listing: _ConversationRouteListing,
    previous_observations: list[ConversationObservation],
) -> list[ConversationObservation]:
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


def _inspect_conversation_recovery(
    *,
    issue: Issue,
    conversation: Conversation | None,
    most_recent_cooldown_ended: datetime | None,
) -> _ConversationInspection | None:
    if conversation is not None and derive_agent_work_fault(
        rounds=conversation.rounds,
        retry_requested_at=conversation.record.retry_requested_at,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
    ):
        return _ConversationInspection(
            observation=ConversationObservation(
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
        return _ConversationInspection(
            observation=ConversationObservation(
                issue=issue.number,
                title=issue.title,
                has_comments_to_answer=IssueFact(
                    value=IssueFactValue.FALSE,
                    evidence="no comments to answer",
                ),
            ),
            candidate=ConversationRecoveryCandidate(
                conversation=conversation,
            ),
        )
    return None


def _record_conversation_comments_delivered(
    *, record: SchedulerRecord, issue: int
) -> SchedulerRecord:
    no_comments = IssueFact(
        value=IssueFactValue.FALSE,
        evidence="no comments to answer",
    )
    return record.model_copy(
        update={
            "conversation_observations": [
                observation.model_copy(update={"has_comments_to_answer": no_comments})
                if observation.issue == issue
                else observation
                for observation in record.conversation_observations
            ]
        }
    )
