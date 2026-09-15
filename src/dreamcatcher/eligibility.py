"""Judge which of the repository's labelled issues a tick can dispatch.

Every read of GitHub here is biased toward doing nothing. If the tool cannot read
the issue listing, it answers Unknown, and the tick dispatches nothing at all. If
it cannot check whether anything has claimed an issue, it treats the issue as
claimed. If it cannot check what blocks an issue, it treats the issue as blocked.
An error from GitHub can therefore cost the daemon a tick, but the daemon can
never dispatch an issue twice, and never dispatch one out of turn.

Two of the checks ask who has a claim on an issue, and they answer different
questions. The first checks whether a complete assignment in this checkout is
already working on the issue. An assignment outlives the daemon run that cut it,
so one an earlier run left behind claims its issue just as an assignment of the
running daemon's does. The second checks whether the issue has an open linked
pull request on GitHub, which covers work in another checkout. An incomplete
local setup carries its branches separately, so its own linked pull request is
recognized as recovery evidence rather than somebody else's claim.
"""

from collections import defaultdict

from dreamcatcher.config import Config
from dreamcatcher.github import (
    BlockerState,
    Issue,
    LinkedPullRequest,
    PullRequest,
    PullRequestState,
    Unknown,
    list_blockers,
    list_issues,
    list_linked_pull_requests,
    list_pull_requests,
)
from dreamcatcher.state import CandidateIssue


def judge_issues(
    *,
    repository: str,
    config: Config,
    claimed: set[int],
    recovering: dict[int, list[str]],
) -> list[CandidateIssue] | Unknown:
    """Return every labelled issue assigned to the user, oldest first.

    Each issue comes back as a candidate that carries information about what, if
    anything, stands in the way of dispatching it. A candidate with nothing in
    its way can be dispatched.

    The caller passes in `claimed`, the issues that an assignment in this checkout
    is already working on, and `recovering`, the issues whose local creation is
    incomplete. The caller knows about both and GitHub does not. A recovering
    issue's own linked pull request is evidence of its setup rather than a claim
    from elsewhere.

    If the tool could not read the listing, it answers Unknown for the whole
    tick. Otherwise, an issue that it cannot see might be dispatched a second
    time.
    """
    listed = _list_issues(repository=repository, config=config)
    if isinstance(listed, Unknown):
        return listed
    return [
        CandidateIssue(
            issue=issue.number,
            label=label,
            reason=_find_obstacle(
                repository=repository,
                issue=issue.number,
                labels=labels,
                claimed=claimed,
                recovery_branches=recovering.get(issue.number, []),
            ),
        )
        for issue, labels in listed
        for label in labels
    ]


def _list_issues(
    *, repository: str, config: Config
) -> list[tuple[Issue, list[str]]] | Unknown:
    """Return each listed issue with the dispatch labels it carries, oldest first.

    Two issues can be filed in the same second, so the issue's number breaks the
    tie. They then come back in the same order on every tick.
    """
    labels: defaultdict[int, list[str]] = defaultdict(list)
    found: dict[int, Issue] = {}
    for route in config.dispatch:
        answered = list_issues(
            repository=repository, label=route.label, assignee=config.assignee
        )
        if isinstance(answered, Unknown):
            return answered
        for issue in answered:
            labels[issue.number].append(route.label)
            found[issue.number] = issue
    return [
        (issue, labels[issue.number])
        for issue in sorted(
            found.values(), key=lambda issue: (issue.created_at, issue.number)
        )
    ]


def _find_obstacle(
    *,
    repository: str,
    issue: int,
    labels: list[str],
    claimed: set[int],
    recovery_branches: list[str],
) -> str | None:
    """Return what stands in the way of dispatching the issue, or nothing.

    If an issue has two dispatch labels, it's not clear which one to use, so the
    label check comes first. It also costs no call to GitHub.
    """
    if len(labels) > 1:
        return f"carries more than one dispatch label: {', '.join(sorted(labels))}"
    if issue in claimed:
        return "an assignment in this checkout is working on it"
    pull_request = _check_pull_requests(
        repository=repository, issue=issue, recovery_branches=recovery_branches
    )
    if pull_request is not None:
        return pull_request
    return _check_blockers(repository=repository, issue=issue)


def _check_pull_requests(
    *, repository: str, issue: int, recovery_branches: list[str]
) -> str | None:
    """Return what says somebody has a pull request open on the issue.

    GitHub lists only open pull requests here. A pull request that was closed
    without merging therefore drops out of the listing, and its issue is free to
    be dispatched again. To stop that, the user can remove the label.
    """
    if len(recovery_branches) > 1:
        return "several incomplete assignment setups are waiting to recover"
    linked = list_linked_pull_requests(repository=repository, issue=issue)
    if isinstance(linked, Unknown):
        return f"cannot tell whether a pull request claims it: {linked.reason}"
    recovered, obstacle = _find_recovery_pull_request(
        repository=repository, branches=recovery_branches
    )
    if obstacle is not None:
        return obstacle
    external = [
        one for one in linked if recovered is None or one.number != recovered.number
    ]
    if external:
        return _describe_pull_request_claims(pull_requests=external)
    if recovered is not None and recovered.number not in {one.number for one in linked}:
        return (
            f"its incomplete branch has an unlinked pull request: #{recovered.number}"
        )
    return None


def _find_recovery_pull_request(
    *, repository: str, branches: list[str]
) -> tuple[PullRequest | None, str | None]:
    """Return the recovery branch's reusable pull request or its obstacle."""
    if not branches:
        return None, None
    branch = branches[0]
    found = list_pull_requests(repository=repository, branch=branch)
    if isinstance(found, Unknown):
        return None, f"cannot reconcile its incomplete setup: {found.reason}"
    if len(found) > 1:
        return None, f"its incomplete branch {branch} has more than one pull request"
    if not found:
        return None, None
    pull_request = found[0]
    obstacle = _describe_unusable_recovery_pull_request(pull_request=pull_request)
    return (None, obstacle) if obstacle is not None else (pull_request, None)


def _describe_unusable_recovery_pull_request(
    *, pull_request: PullRequest
) -> str | None:
    """Return why this recovery pull request cannot be adopted, if anything."""
    if pull_request.state is not PullRequestState.OPEN:
        return (
            f"its incomplete branch's pull request #{pull_request.number} is "
            f"{pull_request.state.lower()}"
        )
    if not pull_request.is_draft:
        return (
            f"its incomplete branch's pull request #{pull_request.number} "
            "is ready for review rather than draft"
        )
    return None


def _describe_pull_request_claims(*, pull_requests: list[LinkedPullRequest]) -> str:
    """Return the obstacle made by these open linked pull requests."""
    named = ", ".join(f"#{pull_request.number}" for pull_request in pull_requests)
    return f"a pull request is open on it: {named}"


def _check_blockers(*, repository: str, issue: int) -> str | None:
    """Return what still blocks the issue, or nothing when no blocker is open."""
    blocking = list_blockers(repository=repository, issue=issue)
    if isinstance(blocking, Unknown):
        return f"cannot tell what blocks it: {blocking.reason}"
    open_blockers = [
        blocker.number for blocker in blocking if blocker.state is BlockerState.OPEN
    ]
    if open_blockers:
        named = ", ".join(f"GH{number}" for number in open_blockers)
        return f"blocked by {named}"
    return None
