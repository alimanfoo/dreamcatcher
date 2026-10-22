"""Inspect conversations' issues and compose the rounds their comments call for."""

from functools import partial

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.config import DispatchRoute
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Issue, IssueComment
from dreamcatcher.issue_conversations import (
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
)
from dreamcatcher.scheduler.issue_work import inspect_open_issue_work, list_new_comments
from dreamcatcher.scheduler.models import (
    IssueCommentsFinding,
    ReadFailureFinding,
    RequestRow,
)


def inspect_open_conversation(
    *, context: SchedulingContext, work: AgentWork, is_fault: bool
) -> Inspection:
    """Read an open conversation's issue, then its comments unless it may not run."""
    return inspect_open_issue_work(
        context=context,
        work=work,
        is_fault=is_fault,
        inspect_eligible=partial(
            _inspect_comments, context=context, work_or_route=work
        ),
    )


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
    try:
        cursor = (
            read_issue_comment_cursor(conversation=work_or_route)
            if isinstance(work_or_route, AgentWork)
            else None
        )
    except ReportableError as failure:
        return Inspection(
            row=row.model_copy(
                update={"finding": ReadFailureFinding(reason=str(failure))}
            )
        )
    comments = list_new_comments(context=context, issue=issue.number, cursor=cursor)
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
