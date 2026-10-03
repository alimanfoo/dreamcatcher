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
from dreamcatcher.config import ConversationRoute
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    ConversationComment,
    Issue,
    UnknownGitHubResponse,
    list_issue_comments,
)
from dreamcatcher.harness_adapters import AgentRoundLaunchRequest, AgentWorkKind
from dreamcatcher.issue_conversations import (
    Conversation,
    ConversationInput,
    compose_conversation_identifier,
    create_conversation,
    find_conversation_harness_session_identifier,
    is_conversation_ready_for_input,
    list_undelivered_issue_comments,
    post_conversation_answer,
    prepare_conversation_input,
    read_conversation_input,
    read_conversations,
    read_issue_comment_delivery_cursor,
    record_conversation_harness_session_identifier,
)
from dreamcatcher.prompts import (
    CONVERSATION_RECOVERY_PROMPT,
    compose_conversation_prompt,
    compose_conversation_round_prompt,
)
from dreamcatcher.scheduler.agent_work import AgentWorkScheduler, RouteIssueListing
from dreamcatcher.scheduler.faults import derive_agent_work_fault
from dreamcatcher.scheduler.models import (
    AgentWorkInspection,
    ConversationObservation,
    IssueFact,
    IssueFactValue,
    SchedulerRecord,
    combine_scheduler_failures,
)
from dreamcatcher.words import describe_count


@dataclass(frozen=True, kw_only=True)
class ConversationBatchCandidate:
    """Describe an eligible issue with trusted comments waiting."""

    issue: Issue
    comments: list[ConversationComment]
    conversation: Conversation | None
    route: ConversationRoute


@dataclass(frozen=True, kw_only=True)
class ConversationRecoveryCandidate:
    """Describe an eligible conversation with unfinished work to recover."""

    conversation: Conversation


type ConversationCandidate = ConversationBatchCandidate | ConversationRecoveryCandidate


@dataclass(frozen=True, kw_only=True)
class _ConversationInspection:
    observation: ConversationObservation
    candidate: ConversationCandidate | None
    is_fault: bool = False


class ConversationScheduler(
    AgentWorkScheduler[
        ConversationCandidate,
        ConversationObservation,
        tuple[int, str, int],
    ]
):
    """Inspect, rank and launch conversation work."""

    def inspect(
        self, *, previous_record: SchedulerRecord | None, at: datetime
    ) -> AgentWorkInspection[ConversationCandidate, ConversationObservation]:
        """Observe matching issues and return conversation work ready to run."""
        if not self.config.conversation:
            return AgentWorkInspection(
                candidates=[], observations=[], fault_count=0, failure=None
            )
        listing = self.list_route_issues(routes=self.config.conversation)
        conversations = read_conversations(state=self.state)
        conversations_by_issue = {
            conversation.record.issue: conversation for conversation in conversations
        }
        candidates, observations, fault_count, failures = (
            self._inspect_listed_conversations(
                listing=listing,
                conversations_by_issue=conversations_by_issue,
                most_recent_cooldown_ended=(
                    None
                    if previous_record is None
                    else previous_record.most_recent_cooldown_ended
                ),
            )
        )
        carried_observations = _carry_forward_unlisted_observations(
            listing=listing,
            previous_observations=(
                []
                if previous_record is None
                else previous_record.conversation_observations
            ),
        )
        observations.extend(carried_observations)
        fault_count += _count_carried_conversation_faults(
            observations=carried_observations,
            conversations_by_issue=conversations_by_issue,
            most_recent_cooldown_ended=(
                None
                if previous_record is None
                else previous_record.most_recent_cooldown_ended
            ),
        )
        failure = combine_scheduler_failures(failures=failures)
        if failure is not None:
            candidates = [
                candidate
                for candidate in candidates
                if isinstance(candidate, ConversationRecoveryCandidate)
            ]
        return AgentWorkInspection(
            candidates=sorted(candidates, key=self.rank),
            observations=observations,
            fault_count=fault_count,
            failure=failure,
        )

    def rank(self, candidate: ConversationCandidate, /) -> tuple[int, str, int]:
        """Rank a conversation candidate when `sorted` passes it by position."""
        if isinstance(candidate, ConversationRecoveryCandidate):
            return (0, "", candidate.conversation.record.issue)
        first_comment = candidate.comments[0]
        return (1, first_comment.written_at, first_comment.id)

    def launch(self, *, candidate: ConversationCandidate, at: datetime) -> AgentRound:
        """Prepare a conversation's required work and start its next round."""
        request = self._prepare_round_start_request(candidate=candidate)
        return start_agent_round(request=request, clock=self.clock)

    def _prepare_round_start_request(
        self, *, candidate: ConversationCandidate
    ) -> AgentRoundStartRequest:
        if isinstance(candidate, ConversationRecoveryCandidate):
            return self._prepare_recovery_round(conversation=candidate.conversation)
        conversation = candidate.conversation or create_conversation(
            state=self.state,
            route=candidate.route,
            requested_harness=self.requested_harness,
            issue=candidate.issue,
        )
        round_input = prepare_conversation_input(
            state=self.state,
            conversation=conversation,
            issue=candidate.issue,
            comments=candidate.comments,
        )
        paths = conversation.compose_round_paths(number=conversation.next_round_number)
        return self._compose_round_start_request(
            conversation=conversation,
            next_round_prompt=compose_conversation_round_prompt(
                issue=conversation.record.issue,
                round_input=paths.round_input,
                was_stopped=(
                    bool(conversation.rounds)
                    and conversation.rounds[-1].outcome is AgentRoundOutcome.STOPPED
                ),
            ),
            plan=AgentRoundPlan(
                purpose=ConversationRoundPurpose.DISCUSS,
                is_recovery=False,
                input=round_input,
            ),
        )

    def _prepare_recovery_round(
        self, *, conversation: Conversation
    ) -> AgentRoundStartRequest:
        latest_round = conversation.rounds[-1]
        return self._compose_round_start_request(
            conversation=conversation,
            next_round_prompt=CONVERSATION_RECOVERY_PROMPT,
            plan=AgentRoundPlan(
                purpose=ConversationRoundPurpose.DISCUSS,
                is_recovery=True,
                input=read_conversation_input(
                    conversation=conversation,
                    number=latest_round.number,
                ),
            ),
        )

    def _compose_round_start_request(
        self,
        *,
        conversation: Conversation,
        next_round_prompt: str,
        plan: AgentRoundPlan[ConversationInput],
    ) -> AgentRoundStartRequest:
        paths = conversation.compose_round_paths(number=conversation.next_round_number)
        first_round_prompt = compose_conversation_prompt(
            template=conversation.record.prompt,
            issue=conversation.record.issue,
            round_input=paths.round_input,
        )
        resumption = self.resolve_harness_session(
            agent_work_identifier=conversation.identifier,
            has_rounds=bool(conversation.rounds),
            harness_session_identifier=(
                find_conversation_harness_session_identifier(conversation=conversation)
                if conversation.rounds
                else None
            ),
            is_recovery=plan.is_recovery,
            prompt=(next_round_prompt if conversation.rounds else first_round_prompt),
            replacement_session_prompt=first_round_prompt,
        )
        return AgentRoundStartRequest(
            harness=conversation.record.harness,
            launch_request=AgentRoundLaunchRequest(
                agent_work_identifier=conversation.identifier,
                model=conversation.record.model,
                effort=conversation.record.effort,
                prompt=resumption.prompt,
                work_kind=AgentWorkKind.CONVERSATION,
            ),
            harness_session_identifier=resumption.identifier,
            record_harness_session_identifier=partial(
                record_conversation_harness_session_identifier,
                conversation=conversation,
            ),
            finish_round=partial(
                post_conversation_answer,
                repository=self.repository,
                issue=conversation.record.issue,
            ),
            paths=paths,
            plan=plan,
        )

    def _inspect_listed_conversations(
        self,
        *,
        listing: RouteIssueListing,
        conversations_by_issue: dict[int, Conversation],
        most_recent_cooldown_ended: datetime | None,
    ) -> tuple[
        list[ConversationCandidate],
        list[ConversationObservation],
        int,
        list[str | None],
    ]:
        candidates: list[ConversationCandidate] = []
        observations: list[ConversationObservation] = []
        fault_count = 0
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
            fault_count += inspection.is_fault
            if inspection.candidate is not None:
                candidates.append(inspection.candidate)
            elif (
                is_conversation_ready_for_input(conversation=conversation)
                and inspection.observation.requires_round.value
                is IssueFactValue.UNKNOWN
            ):
                failures.append(inspection.observation.requires_round.evidence)
        return candidates, observations, fault_count, failures

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
                identifier=compose_conversation_identifier(issue=issue.number),
                issue=issue.number,
                title=issue.title,
                requires_round=IssueFact(
                    value=IssueFactValue.FALSE,
                    evidence="no round required",
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
        comments, requires_round = self._observe_comments(
            issue=issue.number,
            conversation=conversation,
        )
        observation = ConversationObservation(
            identifier=compose_conversation_identifier(issue=issue.number),
            issue=issue.number,
            title=issue.title,
            requires_round=requires_round,
        )
        candidate = None
        if comments and is_conversation_ready_for_input(conversation=conversation):
            candidate = ConversationBatchCandidate(
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
                evidence="no round required",
            )
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
    listing: RouteIssueListing,
    previous_observations: list[ConversationObservation],
) -> list[ConversationObservation]:
    if listing.failure is None:
        return []
    unknown = IssueFact(value=IssueFactValue.UNKNOWN, evidence=listing.failure)
    listed_issues = {issue.number for issue in listing.issues}
    return [
        observation.model_copy(
            update={
                "requires_round": unknown,
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
                identifier=conversation.identifier,
                issue=issue.number,
                title=issue.title,
                requires_round=IssueFact(
                    value=IssueFactValue.FALSE,
                    evidence="in fault",
                ),
            ),
            candidate=None,
            is_fault=True,
        )
    if (
        conversation is not None
        and conversation.rounds
        and conversation.rounds[-1].outcome
        in {AgentRoundOutcome.ERRORED, AgentRoundOutcome.INTERRUPTED}
    ):
        return _ConversationInspection(
            observation=ConversationObservation(
                identifier=conversation.identifier,
                issue=issue.number,
                title=issue.title,
                requires_round=IssueFact(
                    value=IssueFactValue.TRUE,
                    evidence=(
                        f"round {conversation.rounds[-1].number} "
                        f"{conversation.rounds[-1].outcome}, to recover"
                    ),
                ),
            ),
            candidate=ConversationRecoveryCandidate(
                conversation=conversation,
            ),
        )
    return None


def _count_carried_conversation_faults(
    *,
    observations: list[ConversationObservation],
    conversations_by_issue: dict[int, Conversation],
    most_recent_cooldown_ended: datetime | None,
) -> int:
    """Count faults among conversations carried across a failed listing."""
    return sum(
        derive_agent_work_fault(
            rounds=conversation.rounds,
            retry_requested_at=conversation.record.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        for observation in observations
        if (conversation := conversations_by_issue.get(observation.issue)) is not None
    )
