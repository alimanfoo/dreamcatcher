"""Read the open issues that block an issue, as assignment and campaign requests do."""

from dreamcatcher.github import (
    BlockingIssue,
    IssueState,
    UnknownGitHubResponse,
    list_blocking_issues,
)
from dreamcatcher.scheduler.inspection import SchedulingContext
from dreamcatcher.scheduler.models import IssueReference, ReadFailureFinding


def list_open_blocking_issues(
    *, context: SchedulingContext, issue: int
) -> list[IssueReference] | ReadFailureFinding:
    """Return the open issues that GitHub records as blocking the issue.

    A closed blocker blocks nothing, so it is left out.
    """
    blocking = list_blocking_issues(repository=context.repository, issue=issue)
    if isinstance(blocking, UnknownGitHubResponse):
        return ReadFailureFinding(reason=blocking.reason)
    return [
        _refer_to_issue(context=context, issue=blocker)
        for blocker in blocking
        if blocker.state is IssueState.OPEN
    ]


def _refer_to_issue(
    *, context: SchedulingContext, issue: BlockingIssue
) -> IssueReference:
    """Return a reference that names the issue's repository when it is another one."""
    if issue.repository.casefold() == context.repository.casefold():
        return IssueReference(number=issue.number)
    return IssueReference(number=issue.number, repository=issue.repository)
