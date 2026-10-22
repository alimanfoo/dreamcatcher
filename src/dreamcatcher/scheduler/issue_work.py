"""Inspect the lifetime and the comments of work whose channel is its issue.

A conversation and a campaign each belong to the label that started them. Their
issue's state, labels and assignee decide whether they have ended, are paused or
may take another round, and the user talks to their agent in the issue's
comments.
"""

from typing import Protocol

from dreamcatcher.agent_work import AgentWork, AgentWorkEndReason, end_agent_work
from dreamcatcher.github import (
    Issue,
    IssueComment,
    IssueState,
    UnknownGitHubResponse,
    read_issue,
)
from dreamcatcher.relay import IssueCommentCursor, list_issue_comments_past_cursor
from dreamcatcher.scheduler.inspection import (
    Inspection,
    SchedulingContext,
    compose_open_work_row,
)
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    PauseCause,
    PausedFinding,
    ReadFailureFinding,
    RequestRow,
)


class EligibleIssueWorkInspector(Protocol):
    """Inspect open work whose open issue lets it take another round."""

    def __call__(self, *, issue: Issue, row: RequestRow) -> Inspection:
        """Return what the work's row holds, given the row before any read."""


def inspect_open_issue_work(
    *,
    context: SchedulingContext,
    work: AgentWork,
    is_fault: bool,
    inspect_eligible: EligibleIssueWorkInspector,
) -> Inspection:
    """Read the work's issue, then inspect it further unless paused or in fault.

    A closed issue ends the work once its running round finishes. Paused work's
    fault does not count, since it starts no round however its rounds ended. An
    issue that cannot be read leaves whether the work is paused unknown, so its
    fault counts.
    """
    unread = compose_open_work_row(work=work, finding=None)
    issue = read_issue(repository=context.repository, issue=work.record.issue)
    if isinstance(issue, UnknownGitHubResponse):
        return Inspection(
            row=compose_open_work_row(
                work=work, finding=ReadFailureFinding(reason=issue.reason)
            ),
            is_counted_fault=is_fault,
        )
    if issue.state is IssueState.CLOSED:
        if not work.is_round_running:
            end_agent_work(
                work=work, reason=AgentWorkEndReason.ISSUE_CLOSED, at=context.clock()
            )
        return Inspection(row=unread)
    pause = find_pause(context=context, work=work, issue=issue)
    if pause is not None:
        return Inspection(row=compose_open_work_row(work=work, finding=pause))
    if is_fault:
        return Inspection(row=unread, is_counted_fault=True)
    return inspect_eligible(issue=issue, row=unread)


def find_pause(
    *, context: SchedulingContext, work: AgentWork, issue: Issue
) -> PausedFinding | ConflictingLabelsFinding | None:
    """Return why the open work at this open issue is paused, if it is.

    Work whose channel is its issue belongs to its own label. Another configured
    label of its kind on the issue is a routing conflict, held as the labels.
    The work's own label counts whether or not its route is still configured.
    """
    labels = [label.name for label in issue.labels]
    label = work.record.dispatch_label.casefold()
    if label not in {name.casefold() for name in labels}:
        return PausedFinding(cause=PauseCause.LABEL_REMOVED)
    account = context.account.casefold()
    if account not in {assignee.login.casefold() for assignee in issue.assignees}:
        return PausedFinding(cause=PauseCause.ISSUE_UNASSIGNED)
    others = [
        route.label
        for route in context.config.identify_routes(
            kind=work.record.kind, labels=labels
        )
        if route.label.casefold() != label
    ]
    if others:
        return ConflictingLabelsFinding(
            labels=sorted([work.record.dispatch_label, *others], key=str.casefold)
        )
    return None


def list_new_comments(
    *, context: SchedulingContext, issue: int, cursor: IssueCommentCursor | None
) -> list[IssueComment] | ReadFailureFinding:
    """Return the eligible comments at the issue past the work's cursor.

    Work that has relayed nothing has no cursor, so it is given every eligible
    comment. A read that fails answers why.
    """
    comments = list_issue_comments_past_cursor(
        repository=context.repository,
        issue=issue,
        account=context.account,
        cursor=cursor,
    )
    if isinstance(comments, UnknownGitHubResponse):
        return ReadFailureFinding(reason=comments.reason)
    return comments
