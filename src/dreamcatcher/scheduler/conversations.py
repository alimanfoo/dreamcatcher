"""Inspect conversations' issues and compose the rounds their comments call for."""

from functools import partial

from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkEndReason,
    DispatchRequest,
    end_agent_work,
)
from dreamcatcher.config import identify_label
from dreamcatcher.github import (
    Issue,
    IssueComment,
    IssueState,
    LabellingEvent,
    UnknownGitHubResponse,
    is_login_of_account,
    read_issue,
)
from dreamcatcher.issue_conversations import (
    post_conversation_answer,
    prepare_conversation_round,
    read_issue_comment_cursor,
)
from dreamcatcher.prompts import compose_conversation_input_prompt
from dreamcatcher.relay import list_issue_comments_past_cursor
from dreamcatcher.scheduler.inspection import (
    Candidate,
    Inspection,
    RoundPlan,
    SchedulingContext,
    compose_open_work_row,
)
from dreamcatcher.scheduler.labelling import read_user_label_application
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    PauseCause,
    PausedFinding,
    ReadFailureFinding,
    RequestRow,
)


def inspect_open_conversation(
    *, context: SchedulingContext, work: AgentWork, is_in_fault: bool
) -> Inspection:
    """Read an open conversation's issue, then its comments unless it may not run."""
    issue = read_issue(repository=context.repository, issue=work.record.issue)
    if isinstance(issue, UnknownGitHubResponse):
        return Inspection(
            row=compose_open_work_row(
                work=work, finding=ReadFailureFinding(reason=issue.reason)
            ),
            is_counted_fault=is_in_fault,
        )
    unread = compose_open_work_row(work=work, finding=None, issue_state=issue.state)
    if issue.state is IssueState.CLOSED:
        if not work.is_round_running:
            end_agent_work(
                work=work, reason=AgentWorkEndReason.ISSUE_CLOSED, at=context.clock()
            )
        return Inspection(row=unread)
    hold = _find_hold(context=context, work=work, issue=issue)
    if hold is None and not work.is_round_running:
        application = read_user_label_application(
            context=context, issue=issue.number, label=work.record.dispatch_label
        )
        hold = None if isinstance(application, LabellingEvent) else application
    if hold is not None:
        return Inspection(
            row=unread.model_copy(update={"finding": hold}),
            is_counted_fault=is_in_fault and isinstance(hold, ReadFailureFinding),
        )
    if is_in_fault:
        return Inspection(row=unread, is_counted_fault=True)
    return _inspect_comments(
        context=context, issue=issue, work_or_request=work, row=unread
    )


def _find_hold(
    *, context: SchedulingContext, work: AgentWork, issue: Issue
) -> PausedFinding | ConflictingLabelsFinding | None:
    """Return what the issue's labels and assignee hold the open work back for.

    The user pauses the work by taking its label off or unassigning the issue.
    Another configured conversation label on the issue is a routing conflict.
    The work's own label counts whether or not its route is still configured.
    """
    labels = [label.name for label in issue.labels]
    label = identify_label(name=work.record.dispatch_label)
    if label not in {identify_label(name=name) for name in labels}:
        return PausedFinding(cause=PauseCause.LABEL_REMOVED)
    if not any(
        is_login_of_account(login=assignee.login, account=context.account)
        for assignee in issue.assignees
    ):
        return PausedFinding(cause=PauseCause.ISSUE_UNASSIGNED)
    others = [
        route.label
        for route in context.config.identify_routes(
            kind=work.record.kind, labels=labels
        )
        if identify_label(name=route.label) != label
    ]
    if others:
        conflicting = sorted(
            [work.record.dispatch_label, *others],
            key=lambda name: identify_label(name=name),
        )
        return ConflictingLabelsFinding(labels=conflicting)
    return None


def inspect_conversation_request(
    *,
    context: SchedulingContext,
    issue: Issue,
    request: DispatchRequest,
    row: RequestRow,
) -> Inspection:
    """Read the comments at a conversation request with no open conversation.

    A new conversation starts when one of them waits.
    """
    return _inspect_comments(
        context=context, issue=issue, work_or_request=request, row=row
    )


def _inspect_comments(
    *,
    context: SchedulingContext,
    issue: Issue,
    work_or_request: AgentWork | DispatchRequest,
    row: RequestRow,
) -> Inspection:
    """Read the comments at the issue and return a candidate when some wait.

    It reads for the open conversation, or for the route of the one that would
    start, and the row is the request's row before the read.
    """
    comments = list_issue_comments_past_cursor(
        repository=context.repository,
        issue=issue.number,
        account=context.account,
        cursor=(
            read_issue_comment_cursor(conversation=work_or_request)
            if isinstance(work_or_request, AgentWork)
            else None
        ),
    )
    if isinstance(comments, UnknownGitHubResponse):
        return Inspection(
            row=row.model_copy(
                update={"finding": ReadFailureFinding(reason=comments.reason)}
            )
        )
    row = row.model_copy(
        update={"finding": IssueCommentsFinding(new_comments=len(comments))}
    )
    if not comments:
        return Inspection(row=row)
    return Inspection(
        row=row,
        candidate=Candidate(
            work_or_request=work_or_request,
            compose_round=partial(
                _compose_comment_round, context=context, issue=issue, comments=comments
            ),
        ),
    )


def _compose_comment_round(
    *,
    context: SchedulingContext,
    issue: Issue,
    comments: list[IssueComment],
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
