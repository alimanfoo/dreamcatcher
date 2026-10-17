"""Inspect conversations' issues and compose the rounds their comments call for."""

from functools import partial

from dreamcatcher.agent_work import AgentWork, AgentWorkEndReason, end_agent_work
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
from dreamcatcher.scheduler.inspection import (
    Candidate,
    Inspection,
    RoundPlan,
    SchedulingContext,
    compose_agent_work_row,
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
    """Read an open conversation's issue, then its comments unless it rests.

    A closed issue ends the conversation. A paused conversation's fault does
    not count, since it starts no round however its rounds ended, and one in
    fault reads no comments.
    """
    unread = compose_agent_work_row(work=conversation, finding=None)
    issue = read_issue(repository=context.repository, issue=conversation.record.issue)
    if isinstance(issue, UnknownGitHubResponse):
        return Inspection(
            row=compose_agent_work_row(
                work=conversation, finding=ReadFailureFinding(reason=issue.reason)
            ),
            is_fault=is_fault,
        )
    if issue.state is IssueState.CLOSED:
        end_agent_work(
            work=conversation,
            reason=AgentWorkEndReason.ISSUE_CLOSED,
            at=context.clock(),
        )
        return Inspection(row=unread)
    cause = _find_pause_cause(context=context, conversation=conversation, issue=issue)
    if cause is not None:
        return Inspection(
            row=compose_agent_work_row(
                work=conversation, finding=PausedFinding(cause=cause)
            )
        )
    if is_fault:
        return Inspection(row=unread, is_fault=True)
    return _inspect_comments(
        context=context, issue=issue, work=conversation, row=unread
    )


def _find_pause_cause(
    *, context: SchedulingContext, conversation: AgentWork, issue: Issue
) -> PauseCause | None:
    """Return why the open conversation at this open issue rests, if it does."""
    labels = [label.name for label in issue.labels]
    label = conversation.record.dispatch_label.casefold()
    if label not in {name.casefold() for name in labels}:
        return PauseCause.LABEL_REMOVED
    account = context.account.casefold()
    if account not in {assignee.login.casefold() for assignee in issue.assignees}:
        return PauseCause.ISSUE_UNASSIGNED
    routes = context.config.identify_conversation_routes(labels=labels)
    if any(route.label.casefold() != label for route in routes):
        return PauseCause.CONFLICTING_LABELS
    return None


def inspect_conversation_request(
    *,
    context: SchedulingContext,
    issue: Issue,
    route: ConversationRoute,
    routes: list[ConversationRoute],
) -> Inspection:
    """Inspect one conversation label on a listed issue with no open conversation.

    The routes are every conversation route the issue's labels select. Two
    conversation labels start nothing, so the comments are read only at an
    issue with one, and a new conversation starts when one of them waits.
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
        return Inspection(row=row.model_copy(update={"finding": finding}))
    return _inspect_comments(context=context, issue=issue, work=route, row=row)


def _inspect_comments(
    *,
    context: SchedulingContext,
    issue: Issue,
    work: AgentWork | ConversationRoute,
    row: RequestRow,
) -> Inspection:
    """Read the comments at the issue and return a candidate when some wait.

    The work is the open conversation, or the route of the one that would
    start, and the row is the request's row before the read.
    """
    comments = _list_comments_to_answer(
        context=context,
        issue=issue.number,
        conversation=work if isinstance(work, AgentWork) else None,
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
            row=row,
            work=work,
            compose_round=partial(
                _compose_comment_round, context=context, issue=issue, comments=comments
            ),
        ),
    )


def _list_comments_to_answer(
    *, context: SchedulingContext, issue: int, conversation: AgentWork | None
) -> list[ConversationComment] | ReadFailureFinding:
    """Return the trusted comments that no round has been given yet.

    A read that fails answers why.
    """
    comment_response = list_issue_comments(repository=context.repository, issue=issue)
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
        account=context.account,
        delivery_position=delivery_position,
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
