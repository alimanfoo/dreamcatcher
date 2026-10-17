"""Inspect issue conversations and prepare their next rounds."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial

from dreamcatcher.agent_rounds import AgentRound
from dreamcatcher.agent_work import (
    AgentWork,
    create_agent_work,
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
    IssueCommentsFinding,
    ReadFailureFinding,
    RequestFinding,
    RequestRow,
    SchedulerRecord,
    UnlistedIssueFinding,
)


@dataclass(frozen=True, kw_only=True)
class ConversationBatchCandidate:
    """Describe a conversation request or conversation with trusted comments waiting."""

    issue: Issue
    comments: list[ConversationComment]
    conversation: AgentWork | None
    route: ConversationRoute


@dataclass(frozen=True, kw_only=True)
class _ConversationInspection:
    rows: list[RequestRow]
    candidate: ConversationBatchCandidate | None = None
    is_fault: bool = False
    is_blocking_fresh_batches: bool = False


class ConversationScheduler(
    AgentWorkScheduler[ConversationBatchCandidate, tuple[str, int]]
):
    """Inspect, rank and launch conversation work."""

    def inspect(
        self, *, previous_record: SchedulerRecord | None
    ) -> AgentWorkInspection[ConversationBatchCandidate]:
        """Inspect the listed issues and the open conversations, and rank the work.

        Fresh batches start in order of their oldest waiting comment, so a
        failed listing, or a failed comment read for a conversation that could
        take a round, leaves only rounds that give a conversation the input of
        one that did not finish. The faults of open conversations that a failed
        listing did not return still count towards a cooldown.
        """
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
        listed = [
            inspection
            for issue in listing.issues
            if (
                inspection := self._inspect_listed_issue(
                    issue=issue,
                    conversation=conversations_by_issue.get(issue.number),
                    most_recent_cooldown_ended=most_recent_cooldown_ended,
                )
            )
            is not None
        ]
        unlisted = _inspect_unlisted_conversations(
            listing=listing,
            conversations_by_issue=conversations_by_issue,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        candidates = [
            inspection.candidate
            for inspection in listed
            if inspection.candidate is not None
        ]
        if listing.failures or any(
            inspection.is_blocking_fresh_batches for inspection in listed
        ):
            candidates = [
                candidate
                for candidate in candidates
                if candidate.conversation is not None
                and is_last_round_unfinished(
                    rounds=candidate.conversation.rounds, is_daemon_running=True
                )
            ]
        inspections = [*listed, *unlisted]
        return AgentWorkInspection(
            candidates=sorted(candidates, key=self.rank),
            rows=[row for inspection in inspections for row in inspection.rows],
            fault_count=sum(inspection.is_fault for inspection in inspections),
            failures=listing.failures,
        )

    def rank(self, candidate: ConversationBatchCandidate, /) -> tuple[str, int]:
        """Rank a conversation candidate when `sorted` passes it by position."""
        first_comment = candidate.comments[0]
        return (first_comment.written_at, first_comment.id)

    def launch(
        self, *, candidate: ConversationBatchCandidate, at: datetime
    ) -> AgentRound:
        """Create any new conversation, then start its next round."""
        conversation = candidate.conversation or create_agent_work(
            state=self.state,
            route=candidate.route,
            preferred_harness=self.preferred_harness,
            issue=candidate.issue.number,
            title=candidate.issue.title,
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

    def _inspect_listed_issue(
        self,
        *,
        issue: Issue,
        conversation: AgentWork | None,
        most_recent_cooldown_ended: datetime | None,
    ) -> _ConversationInspection | None:
        """Inspect one listed issue that carries a conversation label.

        An issue with two conversation labels starts nothing, so its comments
        are not read.
        """
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
        finding = ConflictingLabelsFinding(
            labels=sorted((route.label for route in routes), key=str.casefold)
        )
        if conversation is not None:
            return _ConversationInspection(
                rows=[compose_agent_work_row(work=conversation, finding=finding)]
            )
        return _ConversationInspection(
            rows=[
                _compose_new_conversation_row(issue=issue, label=label, finding=finding)
                for label in finding.labels
            ]
        )

    def _inspect_conversation(
        self,
        *,
        route: ConversationRoute,
        issue: Issue,
        conversation: AgentWork | None,
        most_recent_cooldown_ended: datetime | None,
    ) -> _ConversationInspection:
        """Read the comments at one listed issue and return a candidate when ready.

        Nothing is read for a conversation in fault.
        """
        if conversation is not None and derive_agent_work_fault(
            rounds=conversation.rounds,
            retry_requested_at=conversation.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        ):
            return _ConversationInspection(
                rows=[compose_agent_work_row(work=conversation, finding=None)],
                is_fault=True,
            )
        comments = _list_comments_to_answer(
            repository=self.repository,
            account=self.account,
            issue=issue.number,
            conversation=conversation,
        )
        finding = (
            comments
            if isinstance(comments, ReadFailureFinding)
            else IssueCommentsFinding(new_comments=len(comments))
        )
        row = (
            _compose_new_conversation_row(
                issue=issue, label=route.label, finding=finding
            )
            if conversation is None
            else compose_agent_work_row(work=conversation, finding=finding)
        )
        is_ready = is_conversation_ready_for_input(conversation=conversation)
        if isinstance(comments, ReadFailureFinding):
            return _ConversationInspection(
                rows=[row], is_blocking_fresh_batches=is_ready
            )
        if not comments or not is_ready:
            return _ConversationInspection(rows=[row])
        return _ConversationInspection(
            rows=[row],
            candidate=ConversationBatchCandidate(
                issue=issue,
                comments=comments,
                conversation=conversation,
                route=route,
            ),
        )


def _list_comments_to_answer(
    *,
    repository: str,
    account: str,
    issue: int,
    conversation: AgentWork | None,
) -> list[ConversationComment] | ReadFailureFinding:
    """Return the trusted comments that no round has been given yet.

    A read that fails answers why.
    """
    comment_response = list_issue_comments(repository=repository, issue=issue)
    if isinstance(comment_response, UnknownGitHubResponse):
        return ReadFailureFinding(reason=comment_response.reason)
    try:
        delivery_position = (
            None
            if conversation is None
            else read_issue_comment_delivery_position(conversation=conversation)
        )
    except ReportableError as failure:
        return ReadFailureFinding(reason=str(failure))
    return list_undelivered_issue_comments(
        comments=comment_response,
        account=account,
        delivery_position=delivery_position,
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


def _inspect_unlisted_conversations(
    *,
    listing: RouteIssueListing,
    conversations_by_issue: dict[int, AgentWork],
    most_recent_cooldown_ended: datetime | None,
) -> list[_ConversationInspection]:
    """Inspect the open conversations whose issues the listing did not return.

    A failed listing may be why, so the row holds the failure and a fault
    still counts.
    """
    listed_issues = {issue.number for issue in listing.issues}
    finding = (
        ReadFailureFinding(reason="; ".join(listing.failures))
        if listing.failures
        else UnlistedIssueFinding()
    )
    return [
        _ConversationInspection(
            rows=[compose_agent_work_row(work=conversation, finding=finding)],
            is_fault=bool(listing.failures)
            and derive_agent_work_fault(
                rounds=conversation.rounds,
                retry_requested_at=conversation.retry_requested_at,
                most_recent_cooldown_ended=most_recent_cooldown_ended,
            ),
        )
        for issue, conversation in sorted(conversations_by_issue.items())
        if issue not in listed_issues
    ]
