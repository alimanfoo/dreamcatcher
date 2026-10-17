"""Inspect issue conversations and prepare their next rounds."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial

from dreamcatcher.agent_rounds import AgentRound
from dreamcatcher.agent_work import (
    AgentWork,
    find_open_agent_work_by_issue,
    read_agent_work_of_kind,
)
from dreamcatcher.config import ConversationRoute
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    ConversationComment,
    Issue,
    UnknownGitHubResponse,
    list_issue_comments,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import (
    create_conversation,
    is_conversation_ready_for_input,
    list_undelivered_issue_comments,
    post_conversation_answer,
    prepare_conversation_round,
    read_issue_comment_delivery_position,
)
from dreamcatcher.prompts import compose_conversation_input_prompt
from dreamcatcher.scheduler.agent_work import (
    AgentWorkScheduler,
    RouteIssueListing,
    compose_agent_work_row,
)
from dreamcatcher.scheduler.faults import (
    derive_agent_work_fault,
    is_last_round_unfinished,
)
from dreamcatcher.scheduler.models import (
    AgentWorkInspection,
    ConflictingLabelsFinding,
    ConversationObservation,
    IssueCommentsFinding,
    ObservedFact,
    ReadFailure,
    RequestFinding,
    RequestRow,
    SchedulerRecord,
    Truth,
    UnlistedIssueFinding,
)
from dreamcatcher.words import describe_count


@dataclass(frozen=True, kw_only=True)
class ConversationBatchCandidate:
    """Describe an eligible issue with trusted comments waiting."""

    issue: Issue
    comments: list[ConversationComment]
    conversation: AgentWork | None
    route: ConversationRoute


@dataclass(frozen=True, kw_only=True)
class _ConversationInspection:
    observation: ConversationObservation
    rows: list[RequestRow]
    candidate: ConversationBatchCandidate | None
    is_fault: bool = False


@dataclass(frozen=True, kw_only=True)
class _ListedConversationInspection:
    candidates: list[ConversationBatchCandidate]
    observations: list[ConversationObservation]
    rows: list[RequestRow]
    fault_count: int
    failures: list[str]


class ConversationScheduler(
    AgentWorkScheduler[
        ConversationBatchCandidate,
        ConversationObservation,
        tuple[str, int],
    ]
):
    """Inspect, rank and launch conversation work."""

    def inspect(
        self, *, previous_record: SchedulerRecord | None, at: datetime
    ) -> AgentWorkInspection[ConversationBatchCandidate, ConversationObservation]:
        """Observe matching issues and return conversation work ready to run."""
        listing = self.list_route_issues(routes=self.config.conversation)
        conversations_by_issue = find_open_agent_work_by_issue(
            work=read_agent_work_of_kind(
                state=self.state, kind=AgentWorkKind.CONVERSATION
            )
        )
        most_recent_cooldown_ended = (
            None
            if previous_record is None
            else previous_record.most_recent_cooldown_ended
        )
        listed = self._inspect_listed_conversations(
            listing=listing,
            conversations_by_issue=conversations_by_issue,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        observations = list(listed.observations)
        carried_observations = _carry_forward_unlisted_observations(
            listing=listing, previous_record=previous_record
        )
        observations.extend(carried_observations)
        fault_count = listed.fault_count + _count_carried_conversation_faults(
            observations=carried_observations,
            conversations_by_issue=conversations_by_issue,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        candidates = listed.candidates
        if listed.failures:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.conversation is not None
                and is_last_round_unfinished(
                    rounds=candidate.conversation.rounds, is_daemon_running=True
                )
            ]
        return AgentWorkInspection(
            candidates=sorted(candidates, key=self.rank),
            observations=observations,
            rows=[
                *listed.rows,
                *_compose_unlisted_conversation_rows(
                    listing=listing, conversations_by_issue=conversations_by_issue
                ),
            ],
            fault_count=fault_count,
            failures=listed.failures,
        )

    def rank(self, candidate: ConversationBatchCandidate, /) -> tuple[str, int]:
        """Rank a conversation candidate when `sorted` passes it by position."""
        first_comment = candidate.comments[0]
        return (first_comment.written_at, first_comment.id)

    def launch(
        self, *, candidate: ConversationBatchCandidate, at: datetime
    ) -> AgentRound:
        """Create any new conversation, then start its next round."""
        conversation = candidate.conversation or create_conversation(
            state=self.state,
            route=candidate.route,
            preferred_harness=self.preferred_harness,
            issue=candidate.issue,
            at=at,
        )
        harness_session_identifier = conversation.find_harness_session_identifier()
        return self.start_round(
            work=conversation,
            harness_session_identifier=harness_session_identifier,
            prepare_round=partial(
                prepare_conversation_round,
                state=self.state,
                conversation=conversation,
                issue=candidate.issue,
                comments=candidate.comments,
                is_resuming=harness_session_identifier is not None,
            ),
            input_prompt=compose_conversation_input_prompt(
                issue=conversation.record.issue,
                round_input=conversation.compose_round_paths(
                    number=conversation.next_round_number
                ).round_input,
            ),
            finish_round=partial(
                post_conversation_answer,
                repository=self.repository,
                issue=conversation.record.issue,
            ),
        )

    def _inspect_listed_conversations(
        self,
        *,
        listing: RouteIssueListing,
        conversations_by_issue: dict[int, AgentWork],
        most_recent_cooldown_ended: datetime | None,
    ) -> _ListedConversationInspection:
        candidates: list[ConversationBatchCandidate] = []
        observations: list[ConversationObservation] = []
        rows: list[RequestRow] = []
        fault_count = 0
        failures = list(listing.failures)
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
            rows.extend(inspection.rows)
            fault_count += inspection.is_fault
            if inspection.candidate is not None:
                candidates.append(inspection.candidate)
            elif (
                is_conversation_ready_for_input(conversation=conversation)
                and inspection.observation.requires_round.value is Truth.UNKNOWN
            ):
                failures.append(inspection.observation.requires_round.evidence)
        return _ListedConversationInspection(
            candidates=candidates,
            observations=observations,
            rows=rows,
            fault_count=fault_count,
            failures=failures,
        )

    def _inspect_listed_issue(
        self,
        *,
        issue: Issue,
        conversation: AgentWork | None,
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
        labels = sorted((route.label for route in routes), key=str.casefold)
        finding = ConflictingLabelsFinding(labels=labels)
        return _ConversationInspection(
            observation=ConversationObservation(
                identifier=None if conversation is None else conversation.identifier,
                issue=issue.number,
                title=issue.title,
                requires_round=ObservedFact(
                    value=Truth.FALSE,
                    evidence="no round required",
                ),
                routing_conflict=ObservedFact(
                    value=Truth.TRUE,
                    evidence=(
                        "carries more than one conversation label: " + ", ".join(labels)
                    ),
                ),
            ),
            rows=(
                [
                    _compose_new_conversation_row(
                        issue=issue, label=label, finding=finding
                    )
                    for label in labels
                ]
                if conversation is None
                else [compose_agent_work_row(work=conversation, finding=finding)]
            ),
            candidate=None,
        )

    def _inspect_conversation(
        self,
        *,
        route: ConversationRoute,
        issue: Issue,
        conversation: AgentWork | None,
        most_recent_cooldown_ended: datetime | None,
    ) -> _ConversationInspection:
        """Observe one eligible issue and return a candidate when ready."""
        fault = _inspect_conversation_fault(
            issue=issue,
            conversation=conversation,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        if fault is not None:
            return fault
        comments, requires_round, finding = self._observe_comments(
            issue=issue.number,
            conversation=conversation,
        )
        observation = ConversationObservation(
            identifier=None if conversation is None else conversation.identifier,
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
        return _ConversationInspection(
            observation=observation,
            rows=[
                _compose_new_conversation_row(
                    issue=issue, label=route.label, finding=finding
                )
                if conversation is None
                else compose_agent_work_row(work=conversation, finding=finding)
            ],
            candidate=candidate,
        )

    def _observe_comments(
        self,
        *,
        issue: int,
        conversation: AgentWork | None,
    ) -> tuple[
        list[ConversationComment],
        ObservedFact,
        IssueCommentsFinding | ReadFailure,
    ]:
        try:
            comments = _list_comments_to_answer(
                repository=self.repository,
                account=self.account,
                issue=issue,
                conversation=conversation,
            )
        except ReportableError as failure:
            return (
                [],
                ObservedFact(value=Truth.UNKNOWN, evidence=str(failure)),
                ReadFailure(reason=str(failure)),
            )
        return (
            comments,
            (
                ObservedFact(
                    value=Truth.TRUE,
                    evidence=(
                        f"{describe_count(number=len(comments), noun='comment')} "
                        "to answer"
                    ),
                )
                if comments
                else ObservedFact(
                    value=Truth.FALSE,
                    evidence="no round required",
                )
            ),
            IssueCommentsFinding(new_comments=len(comments)),
        )


def _list_comments_to_answer(
    *,
    repository: str,
    account: str,
    issue: int,
    conversation: AgentWork | None,
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
        delivery_position = (
            None
            if conversation is None
            else read_issue_comment_delivery_position(conversation=conversation)
        )
    except ReportableError as failure:
        raise ReportableError(
            f"could not read delivered comments for GH{issue}: {failure}"
        ) from failure
    return list_undelivered_issue_comments(
        comments=comment_response,
        account=account,
        delivery_position=delivery_position,
    )


def _carry_forward_unlisted_observations(
    *,
    listing: RouteIssueListing,
    previous_record: SchedulerRecord | None,
) -> list[ConversationObservation]:
    if not listing.failures or previous_record is None:
        return []
    unknown = ObservedFact(value=Truth.UNKNOWN, evidence="; ".join(listing.failures))
    listed_issues = {issue.number for issue in listing.issues}
    return [
        observation.model_copy(
            update={
                "requires_round": unknown,
                "routing_conflict": unknown,
            }
        )
        for observation in previous_record.conversation_observations
        if observation.issue not in listed_issues
    ]


def _inspect_conversation_fault(
    *,
    issue: Issue,
    conversation: AgentWork | None,
    most_recent_cooldown_ended: datetime | None,
) -> _ConversationInspection | None:
    if conversation is None or not derive_agent_work_fault(
        rounds=conversation.rounds,
        retry_requested_at=conversation.retry_requested_at,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
    ):
        return None
    return _ConversationInspection(
        observation=ConversationObservation(
            identifier=conversation.identifier,
            issue=issue.number,
            title=issue.title,
            requires_round=ObservedFact(
                value=Truth.FALSE,
                evidence="in fault",
            ),
        ),
        rows=[compose_agent_work_row(work=conversation, finding=None)],
        candidate=None,
        is_fault=True,
    )


def _count_carried_conversation_faults(
    *,
    observations: list[ConversationObservation],
    conversations_by_issue: dict[int, AgentWork],
    most_recent_cooldown_ended: datetime | None,
) -> int:
    """Count faults among conversations carried across a failed listing."""
    return sum(
        derive_agent_work_fault(
            rounds=conversation.rounds,
            retry_requested_at=conversation.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        for observation in observations
        if (conversation := conversations_by_issue.get(observation.issue)) is not None
    )


def _compose_new_conversation_row(
    *, issue: Issue, label: str, finding: RequestFinding
) -> RequestRow:
    """Return the row of a conversation request that has no open conversation."""
    return RequestRow(
        issue=issue.number,
        title=issue.title,
        dispatch_label=label,
        kind=AgentWorkKind.CONVERSATION,
        finding=finding,
    )


def _compose_unlisted_conversation_rows(
    *, listing: RouteIssueListing, conversations_by_issue: dict[int, AgentWork]
) -> list[RequestRow]:
    """Return the rows of open conversations whose issues the listing did not return.

    A failed listing may be why, so the row holds the failure.
    """
    listed_issues = {issue.number for issue in listing.issues}
    finding = (
        ReadFailure(reason="; ".join(listing.failures))
        if listing.failures
        else UnlistedIssueFinding()
    )
    return [
        compose_agent_work_row(work=conversation, finding=finding)
        for issue, conversation in sorted(conversations_by_issue.items())
        if issue not in listed_issues
    ]
