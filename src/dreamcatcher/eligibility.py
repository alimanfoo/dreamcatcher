"""Judge which of the repository's labelled issues a tick can dispatch.

Every read of GitHub here is biased toward doing nothing. If the tool cannot read
the issue listing, it answers Unknown, and the tick dispatches nothing at all. If
it cannot check whether anything has claimed an issue, it treats the issue as
claimed. If it cannot check what blocks an issue, it treats the issue as blocked.
An error from GitHub can therefore cost the daemon a tick, but the daemon can
never dispatch an issue twice, and never dispatch one out of turn.

Two of the checks ask who has a claim on an issue, and they answer different
questions. The first checks whether the current run has a session already working
on the issue, which covers the time before any pull request exists. The second
checks whether the issue has an open linked pull request on GitHub, which covers
the situation where the issue is being worked on via a worktree somewhere else.
"""

from collections import defaultdict

from dreamcatcher.config import Config
from dreamcatcher.github import (
    BlockerState,
    Issue,
    Unknown,
    list_blockers,
    list_issues,
    list_linked_pull_requests,
)
from dreamcatcher.state import Candidate


def judge_issues(
    repository: str, config: Config, claimed: set[int]
) -> list[Candidate] | Unknown:
    """Return every labelled issue assigned to the user, oldest first.

    Each issue comes back as a candidate that carries information about what, if
    anything, stands in the way of dispatching it. A candidate with nothing in
    its way can be dispatched.

    The caller passes in `claimed`, the issues that a session of this run is
    already working on. The caller knows about those and GitHub does not.

    If the tool could not read the listing, it answers Unknown for the whole
    tick. Otherwise, an issue that it cannot see might be dispatched a second
    time.
    """
    listed = _list_issues(repository, config)
    if isinstance(listed, Unknown):
        return listed
    return [
        Candidate(
            issue=issue.number,
            label=label,
            reason=_find_obstacle(repository, issue.number, labels, claimed),
        )
        for issue, labels in listed
        for label in labels
    ]


def _list_issues(
    repository: str, config: Config
) -> list[tuple[Issue, list[str]]] | Unknown:
    """Return each listed issue with the mapped labels it carries, oldest first.

    Two issues can be filed in the same second, so the issue's number breaks the
    tie. They then come back in the same order on every tick.
    """
    labels: defaultdict[int, list[str]] = defaultdict(list)
    found: dict[int, Issue] = {}
    for mapping in config.dispatch:
        answered = list_issues(
            repository, label=mapping.label, assignee=config.assignee
        )
        if isinstance(answered, Unknown):
            return answered
        for issue in answered:
            labels[issue.number].append(mapping.label)
            found[issue.number] = issue
    return [
        (issue, labels[issue.number])
        for issue in sorted(
            found.values(), key=lambda issue: (issue.created_at, issue.number)
        )
    ]


def _find_obstacle(
    repository: str, issue: int, labels: list[str], claimed: set[int]
) -> str | None:
    """Return what stands in the way of dispatching the issue, or nothing.

    If an issue has two dispatch labels, it's not clear which one to use, so the
    label check comes first. It also costs no call to GitHub.
    """
    if len(labels) > 1:
        return f"carries more than one mapped label: {', '.join(sorted(labels))}"
    if issue in claimed:
        return "a session of this run is working on it"
    return _check_pull_requests(repository, issue) or _check_blockers(repository, issue)


def _check_pull_requests(repository: str, issue: int) -> str | None:
    """Return what says somebody has a pull request open on the issue.

    GitHub lists only open pull requests here. A pull request that was closed
    without merging therefore drops out of the listing, and its issue is free to
    be dispatched again. To stop that, the user can remove the label.
    """
    linked = list_linked_pull_requests(repository, issue)
    if isinstance(linked, Unknown):
        return f"cannot tell whether a pull request claims it: {linked.reason}"
    if linked:
        named = ", ".join(f"#{pull_request.number}" for pull_request in linked)
        return f"a pull request is open on it: {named}"
    return None


def _check_blockers(repository: str, issue: int) -> str | None:
    """Return what still blocks the issue, or nothing when no blocker is open."""
    blocking = list_blockers(repository, issue)
    if isinstance(blocking, Unknown):
        return f"cannot tell what blocks it: {blocking.reason}"
    open_blockers = [
        blocker.number for blocker in blocking if blocker.state is BlockerState.OPEN
    ]
    if open_blockers:
        named = ", ".join(f"GH{number}" for number in open_blockers)
        return f"blocked by {named}"
    return None
