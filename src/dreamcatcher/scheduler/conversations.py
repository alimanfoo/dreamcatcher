"""Inspect issue conversations and prepare their next rounds."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial

from dreamcatcher.agent_rounds import AgentRound
from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkEndReason,
    create_agent_work,
    end_agent_work,
    read_agent_work_of_kind,
)
from dreamcatcher.config import ConversationRoute
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    ConversationComment,
    Issue,
    IssueState,
    UnknownGitHubResponse,
    list_issue_comments,
    read_issue,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import (
    list_undelivered_issue_comments,
    post_conversation_answer,
    prepare_conversation_round,
    read_issue_comment_delivery_position,
)
from dreamcatcher.prompts import compose_conversation_input_prompt
from dreamcatcher.scheduler.agent_work import (
    AgentWorkScheduler,
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
    PauseCause,
    PausedFinding,
    ReadFailureFinding,
    RequestRow,
    SchedulerRecord,
)


@dataclass(frozen=True, kw_only=True)
class ConversationBatchCandidate:
    """Describe a conversation request or conversation with trusted comments waiting.

    The conversation is the open one, or the route of the one to start.
    """

    issue: Issue
    comments: list[ConversationComment]
    conversation: AgentWork | ConversationRoute


@dataclass(frozen=True, kw_only=True)
class _ConversationInspection:
    row: RequestRow
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
        """Inspect the open conversations and the listed requests, and rank the work.

        Open conversations are found on disk and read their own issue, so a
        failed listing starts no new conversation but leaves them alone. Fresh
        batches start in order of their oldest waiting comment, so a failed
        comment read for a conversation that could take a round leaves only
        rounds that give a conversation the input of one that did not finish.
        """
        listing = self.list_route_issues(routes=self.config.conversation)
        conversations = [
            conversation
            for conversation in read_agent_work_of_kind(
                state=self.state, kind=AgentWorkKind.CONVERSATION
            )
            if conversation.is_open
        ]
        most_recent_cooldown_ended = (
            None
            if previous_record is None
            else previous_record.most_recent_cooldown_ended
        )
        open_requests = {
            (conversation.record.issue, conversation.record.dispatch_label.casefold())
            for conversation in conversations
        }
        inspections = [
            *(
                self._inspect_open_conversation(
                    conversation=conversation,
                    most_recent_cooldown_ended=most_recent_cooldown_ended,
                )
                for conversation in conversations
            ),
            *(
                self._inspect_request(issue=issue, route=route, routes=routes)
                for issue in listing.issues
                if (
                    routes := self.config.identify_conversation_routes(
                        labels=[label.name for label in issue.labels]
                    )
                )
                for route in routes
                if (issue.number, route.label.casefold()) not in open_requests
            ),
        ]
        candidates = [
            inspection.candidate
            for inspection in inspections
            if inspection.candidate is not None
        ]
        if any(inspection.is_blocking_fresh_batches for inspection in inspections):
            candidates = [
                candidate
                for candidate in candidates
                if isinstance(candidate.conversation, AgentWork)
                and is_last_round_unfinished(
                    rounds=candidate.conversation.rounds, is_daemon_running=True
                )
            ]
        return AgentWorkInspection(
            candidates=sorted(candidates, key=self.rank),
            rows=[inspection.row for inspection in inspections],
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
        conversation = (
            candidate.conversation
            if isinstance(candidate.conversation, AgentWork)
            else create_agent_work(
                state=self.state,
                route=candidate.conversation,
                preferred_harness=self.preferred_harness,
                issue=candidate.issue.number,
                title=candidate.issue.title,
                at=at,
            )
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

    def _inspect_open_conversation(
        self,
        *,
        conversation: AgentWork,
        most_recent_cooldown_ended: datetime | None,
    ) -> _ConversationInspection:
        """Read an open conversation's issue, then its comments unless it rests.

        Nothing is read for a conversation whose round is running. A closed
        issue ends the conversation. A paused conversation's fault does not
        count, since it starts no round however its rounds ended.
        """
        unread = compose_agent_work_row(work=conversation, finding=None)
        if conversation.rounds and conversation.rounds[-1].ending is None:
            return _ConversationInspection(row=unread)
        issue = read_issue(repository=self.repository, issue=conversation.record.issue)
        is_fault = derive_agent_work_fault(
            rounds=conversation.rounds,
            retry_requested_at=conversation.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        if isinstance(issue, UnknownGitHubResponse):
            return _ConversationInspection(
                row=compose_agent_work_row(
                    work=conversation,
                    finding=ReadFailureFinding(reason=issue.reason),
                ),
                is_fault=is_fault,
            )
        if issue.state is IssueState.CLOSED:
            end_agent_work(
                work=conversation,
                reason=AgentWorkEndReason.ISSUE_CLOSED,
                at=self.clock(),
            )
            return _ConversationInspection(row=unread)
        pause_cause = self._find_pause_cause(conversation=conversation, issue=issue)
        if pause_cause is not None:
            return _ConversationInspection(
                row=compose_agent_work_row(
                    work=conversation, finding=PausedFinding(cause=pause_cause)
                )
            )
        if is_fault:
            return _ConversationInspection(row=unread, is_fault=True)
        return self._inspect_comments(
            issue=issue, conversation=conversation, row=unread
        )

    def _find_pause_cause(
        self, *, conversation: AgentWork, issue: Issue
    ) -> PauseCause | None:
        """Return why the open conversation at this open issue rests, if it does."""
        labels = [label.name.casefold() for label in issue.labels]
        label = conversation.record.dispatch_label.casefold()
        if label not in labels:
            return PauseCause.LABEL_REMOVED
        if self.account.casefold() not in {
            assignee.login.casefold() for assignee in issue.assignees
        }:
            return PauseCause.ISSUE_UNASSIGNED
        routes = self.config.identify_conversation_routes(labels=labels)
        if any(route.label.casefold() != label for route in routes):
            return PauseCause.CONFLICTING_LABELS
        return None

    def _inspect_request(
        self, *, issue: Issue, route: ConversationRoute, routes: list[ConversationRoute]
    ) -> _ConversationInspection:
        """Inspect one conversation label on a listed issue with no open conversation.

        An issue with two conversation labels starts nothing, so its comments
        are not read.
        """
        row = RequestRow(
            issue=issue.number,
            title=issue.title,
            dispatch_label=route.label,
            kind=AgentWorkKind.CONVERSATION,
        )
        if len(routes) > 1:
            finding = ConflictingLabelsFinding(
                labels=[conflicting.label for conflicting in routes]
            )
            return _ConversationInspection(
                row=row.model_copy(update={"finding": finding})
            )
        return self._inspect_comments(issue=issue, conversation=route, row=row)

    def _inspect_comments(
        self,
        *,
        issue: Issue,
        conversation: AgentWork | ConversationRoute,
        row: RequestRow,
    ) -> _ConversationInspection:
        """Read the comments at the issue and return a candidate when some wait.

        The conversation is the open one, or the route of the one that would
        start, and the row is the request's row before the read.
        """
        comments = _list_comments_to_answer(
            repository=self.repository,
            account=self.account,
            issue=issue.number,
            conversation=conversation if isinstance(conversation, AgentWork) else None,
        )
        if isinstance(comments, ReadFailureFinding):
            return _ConversationInspection(
                row=row.model_copy(update={"finding": comments}),
                is_blocking_fresh_batches=True,
            )
        row = row.model_copy(
            update={"finding": IssueCommentsFinding(new_comments=len(comments))}
        )
        if not comments:
            return _ConversationInspection(row=row)
        return _ConversationInspection(
            row=row,
            candidate=ConversationBatchCandidate(
                issue=issue, comments=comments, conversation=conversation
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
