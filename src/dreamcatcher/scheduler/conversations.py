"""Inspect conversations' issues and compose the rounds their comments call for."""

from functools import partial

from dreamcatcher.agent_work import AgentWork, AgentWorkEndReason, end_agent_work
from dreamcatcher.config import DispatchRoute
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    ConversationComment,
    Issue,
    IssueState,
    UnknownGitHubResponse,
    list_issue_comments,
    read_issue,
)
from dreamcatcher.issue_conversations import (
    list_issue_comments_past_cursor,
    post_conversation_answer,
    prepare_conversation_round,
    read_issue_comment_cursor,
)
from dreamcatcher.prompts import compose_conversation_input_prompt
from dreamcatcher.scheduler.inspection import (
    Candidate,
    Inspection,
    RoundPlan,
    SchedulingContext,
    compose_open_work_row,
)
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    PauseCause,
    PausedFinding,
    ReadFailureFinding,
    RequestRow,
)


def inspect_open_conversation(
    *, context: SchedulingContext, conversation: AgentWork, is_fault: bool
) -> Inspection:
    """Read an open conversation's issue, then its comments unless paused or in fault.

    A closed issue ends the conversation. A paused conversation's fault does
    not count, since it starts no round however its rounds ended.
    """
    unread = compose_open_work_row(work=conversation, finding=None)
    issue = read_issue(repository=context.repository, issue=conversation.record.issue)
    if isinstance(issue, UnknownGitHubResponse):
        return Inspection(
            row=compose_open_work_row(
                work=conversation, finding=ReadFailureFinding(reason=issue.reason)
            ),
            is_counted_fault=is_fault,
        )
    if issue.state is IssueState.CLOSED:
        end_agent_work(
            work=conversation,
            reason=AgentWorkEndReason.ISSUE_CLOSED,
            at=context.clock(),
        )
        return Inspection(row=unread)
    pause = _find_pause(context=context, conversation=conversation, issue=issue)
    if pause is not None:
        return Inspection(row=compose_open_work_row(work=conversation, finding=pause))
    if is_fault:
        return Inspection(row=unread, is_counted_fault=True)
    return _inspect_comments(
        context=context, issue=issue, work_or_route=conversation, row=unread
    )


def _find_pause(
    *, context: SchedulingContext, conversation: AgentWork, issue: Issue
) -> PausedFinding | ConflictingLabelsFinding | None:
    """Return why the open conversation at this open issue is paused, if it is.

    A second configured conversation label on the issue is a routing conflict,
    held as the labels. The conversation's own label counts whether or not its
    route is still configured.
    """
    labels = [label.name for label in issue.labels]
    label = conversation.record.dispatch_label.casefold()
    if label not in {name.casefold() for name in labels}:
        return PausedFinding(cause=PauseCause.LABEL_REMOVED)
    account = context.account.casefold()
    if account not in {assignee.login.casefold() for assignee in issue.assignees}:
        return PausedFinding(cause=PauseCause.ISSUE_UNASSIGNED)
    others = [
        route.label
        for route in context.config.identify_conversation_routes(labels=labels)
        if route.label.casefold() != label
    ]
    if others:
        return ConflictingLabelsFinding(
            labels=sorted(
                [conversation.record.dispatch_label, *others], key=str.casefold
            )
        )
    return None


def inspect_conversation_request(
    *,
    context: SchedulingContext,
    issue: Issue,
    route: DispatchRoute,
    row: RequestRow,
) -> Inspection:
    """Read the comments at a conversation request with no open conversation.

    A new conversation starts when one of them waits.
    """
    return _inspect_comments(context=context, issue=issue, work_or_route=route, row=row)


def _inspect_comments(
    *,
    context: SchedulingContext,
    issue: Issue,
    work_or_route: AgentWork | DispatchRoute,
    row: RequestRow,
) -> Inspection:
    """Read the comments at the issue and return a candidate when some wait.

    It reads for the open conversation, or for the route of the one that would
    start, and the row is the request's row before the read.
    """
    comments = _list_comments_to_answer(
        context=context,
        issue=issue.number,
        conversation=(work_or_route if isinstance(work_or_route, AgentWork) else None),
    )
    if isinstance(comments, ReadFailureFinding):
        return Inspection(row=row.model_copy(update={"finding": comments}))
    row = row.model_copy(
        update={"finding": IssueCommentsFinding(new_comments=len(comments))}
    )
    if not comments:
        return Inspection(row=row)
    return Inspection(
        row=row,
        candidate=Candidate(
            work_or_route=work_or_route,
            compose_round=partial(
                _compose_comment_round, context=context, issue=issue, comments=comments
            ),
        ),
    )


def _list_comments_to_answer(
    *, context: SchedulingContext, issue: int, conversation: AgentWork | None
) -> list[ConversationComment] | ReadFailureFinding:
    """Return the eligible comments that no round has been given yet.

    A read that fails answers why.
    """
    comment_response = list_issue_comments(repository=context.repository, issue=issue)
    if isinstance(comment_response, UnknownGitHubResponse):
        return ReadFailureFinding(reason=comment_response.reason)
    try:
        cursor = (
            None
            if conversation is None
            else read_issue_comment_cursor(conversation=conversation)
        )
    except ReportableError as failure:
        return ReadFailureFinding(reason=str(failure))
    return list_issue_comments_past_cursor(
        comments=comment_response,
        account=context.account,
        cursor=cursor,
    )


def _compose_comment_round(
    *,
    context: SchedulingContext,
    issue: Issue,
    comments: list[ConversationComment],
    work: AgentWork,
) -> RoundPlan:
    """Return the plan of a round given the comments waiting at the issue.

    A round that starts a new harness session is given the issue's title and
    body too, and every round posts its answer as it finishes.
    """
    return RoundPlan(
        prepare_round=partial(
            prepare_conversation_round,
            state=context.state,
            conversation=work,
            issue=issue,
            comments=comments,
            is_resuming=work.find_harness_session_identifier() is not None,
        ),
        input_prompt=compose_conversation_input_prompt(
            issue=work.record.issue,
            round_input=work.compose_round_paths(
                number=work.next_round_number
            ).round_input,
        ),
        finish_round=partial(
            post_conversation_answer,
            repository=context.repository,
            issue=work.record.issue,
        ),
    )
