"""Find or create the pull request that an agent assignment talks through."""

from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    PullRequest,
    PullRequestState,
    UnknownGitHubResponse,
    create_pull_request,
    list_pull_requests,
)


def find_or_create_assignment_pull_request(
    *, repository: str, branch: str, issue: int, title: str
) -> PullRequest:
    """Return the pull request on the assignment's branch, opening a draft if none.

    A pull request already on the branch is the assignment's own, whatever its
    state. No other pull request is looked at, since the scheduler asked before
    the assignment existed whether one claims the issue.
    """
    branch_pull_request = _find_branch_pull_request(
        repository=repository, branch=branch
    )
    if branch_pull_request is not None:
        return branch_pull_request
    pull_request = create_pull_request(
        repository=repository, branch=branch, issue=issue, title=title
    )
    if isinstance(pull_request, UnknownGitHubResponse):
        raise ReportableError(pull_request.reason)
    if pull_request.state is not PullRequestState.OPEN or not pull_request.is_draft:
        raise ReportableError(
            f"pull request #{pull_request.number} for {branch} was not created as "
            "an open draft."
        )
    return pull_request


def _find_branch_pull_request(*, repository: str, branch: str) -> PullRequest | None:
    """Return the sole pull request on the branch, when it has one."""
    pull_requests = list_pull_requests(repository=repository, branch=branch)
    if isinstance(pull_requests, UnknownGitHubResponse):
        raise ReportableError(
            f"cannot tell whether {branch} has a pull request: {pull_requests.reason}"
        )
    if len(pull_requests) > 1:
        raise ReportableError(f"{branch} has more than one pull request.")
    return pull_requests[0] if pull_requests else None
