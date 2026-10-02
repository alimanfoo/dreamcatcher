"""Find, validate, and create pull requests for agent assignments."""

from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    IssuePullRequestContext,
    LinkedPullRequest,
    PullRequest,
    PullRequestState,
    UnknownGitHubResponse,
    create_pull_request,
    list_pull_requests,
    read_issue_pull_request_context,
)


def find_or_create_assignment_pull_request(
    *, repository: str, branch: str, issue: int
) -> tuple[str, PullRequest]:
    """Return the issue title and branch's existing or newly created draft."""
    branch_pull_request = _find_branch_pull_request(
        repository=repository, branch=branch
    )
    pull_request_context = _read_issue_pull_request_context(
        repository=repository, issue=issue
    )
    if branch_pull_request is not None:
        pull_request = _adopt_pull_request(
            pull_request=branch_pull_request,
            linked=pull_request_context.pull_requests,
            branch=branch,
            issue=issue,
        )
    else:
        _refuse_linked_pull_requests(
            linked=pull_request_context.pull_requests, branch=branch, issue=issue
        )
        pull_request = _create_assignment_pull_request(
            repository=repository, branch=branch, context=pull_request_context
        )
    return pull_request_context.title, pull_request


def validate_assignment_pull_request_setup(
    *, repository: str, branch: str, issue: int
) -> None:
    """Require an incomplete setup's pull request state to be recoverable."""
    branch_pull_request = _find_branch_pull_request(
        repository=repository, branch=branch
    )
    context = _read_issue_pull_request_context(repository=repository, issue=issue)
    if branch_pull_request is None:
        _refuse_linked_pull_requests(
            linked=context.pull_requests,
            branch=branch,
            issue=issue,
        )
        return
    _adopt_pull_request(
        pull_request=branch_pull_request,
        linked=context.pull_requests,
        branch=branch,
        issue=issue,
    )


def _find_branch_pull_request(*, repository: str, branch: str) -> PullRequest | None:
    """Return the sole pull request on a recovery branch, when it has one."""
    pull_requests = list_pull_requests(repository=repository, branch=branch)
    if isinstance(pull_requests, UnknownGitHubResponse):
        raise ReportableError(
            f"cannot reconcile the pull request for {branch}: {pull_requests.reason}"
        )
    if len(pull_requests) > 1:
        raise ReportableError(f"{branch} has more than one pull request.")
    return pull_requests[0] if pull_requests else None


def _read_issue_pull_request_context(
    *, repository: str, issue: int
) -> IssuePullRequestContext:
    """Return the issue's pull request context or report why it is unknown."""
    context = read_issue_pull_request_context(repository=repository, issue=issue)
    if isinstance(context, UnknownGitHubResponse):
        raise ReportableError(
            f"cannot tell whether another pull request claims GH{issue}: "
            f"{context.reason}"
        )
    return context


def _adopt_pull_request(
    *,
    pull_request: PullRequest,
    linked: list[LinkedPullRequest],
    branch: str,
    issue: int,
) -> PullRequest:
    """Return the branch's linked open draft pull request."""
    if pull_request.state is not PullRequestState.OPEN:
        raise ReportableError(
            f"cannot reconcile {branch}: pull request #{pull_request.number} "
            f"is {pull_request.state.lower()}."
        )
    if not pull_request.is_draft:
        raise ReportableError(
            f"cannot reconcile {branch}: pull request #{pull_request.number} "
            "is ready for review rather than draft."
        )
    if pull_request.number not in {
        linked_pull_request.number for linked_pull_request in linked
    }:
        raise ReportableError(
            f"cannot reconcile {branch}: pull request #{pull_request.number} "
            f"is not linked to GH{issue}."
        )
    unrelated_pull_requests = [
        linked_pull_request
        for linked_pull_request in linked
        if linked_pull_request.number != pull_request.number
    ]
    _refuse_linked_pull_requests(
        linked=unrelated_pull_requests, branch=branch, issue=issue
    )
    return pull_request


def _refuse_linked_pull_requests(
    *, linked: list[LinkedPullRequest], branch: str, issue: int
) -> None:
    """Refuse open linked pull requests not owned by the recovery branch."""
    if linked:
        pull_request_names = ", ".join(
            f"#{pull_request.number}" for pull_request in linked
        )
        raise ReportableError(
            f"cannot create a pull request for {branch}: GH{issue} already has "
            f"an open linked pull request ({pull_request_names})."
        )


def _create_assignment_pull_request(
    *, repository: str, branch: str, context: IssuePullRequestContext
) -> PullRequest:
    """Create and return the assignment branch's open draft pull request."""
    pull_request = create_pull_request(
        repository=repository, branch=branch, context=context
    )
    if isinstance(pull_request, UnknownGitHubResponse):
        raise ReportableError(pull_request.reason)
    if pull_request.state is not PullRequestState.OPEN or not pull_request.is_draft:
        raise ReportableError(
            f"pull request #{pull_request.number} for {branch} was not created as "
            "an open draft."
        )
    return pull_request
