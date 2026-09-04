"""Judge which of the repository's labelled issues a tick can dispatch.

Every read here biases the daemon toward doing nothing. A listing that failed
answers unknown, so the tick dispatches nothing at all. A claim the tool cannot
check reads as claimed, and a blocker it cannot check reads as blocking. So a
GitHub error can cost the tool a tick, and it can never dispatch an issue twice
or dispatch one out of turn.

Two questions ask who has a claim on an issue, because they answer different
things. A session of this run says this daemon is working on it, which covers
the time before any pull request exists. GitHub's own link says somebody has a
pull request open on it, which covers every attempt whose worktree is not here.
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

    Each answer says what stood in the way of dispatching that issue, and a
    candidate with nothing in its way is one the caller can dispatch. The
    claimed issues are the ones a session of this run is already working on,
    which the caller knows and GitHub does not.

    A listing the tool could not read answers unknown for the whole tick, since
    an issue it cannot see is one it might dispatch a second time.
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

    The issue's number breaks a tie, so two issues filed in the same second
    come back in the same order every tick.
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

    The label check comes first, because it costs no GitHub call and because an
    issue that names two skills has not said which one to run.
    """
    if len(labels) > 1:
        return f"carries more than one mapped label: {', '.join(sorted(labels))}"
    if issue in claimed:
        return "a session of this run is working on it"
    return _check_pull_requests(repository, issue) or _check_blockers(repository, issue)


def _check_pull_requests(repository: str, issue: int) -> str | None:
    """Return what says somebody has a pull request open on the issue.

    GitHub lists only open pull requests here, so an attempt that was declined
    drops out and leaves its issue free to go again. Removing the label is how
    the user says stop.
    """
    linked = list_linked_pull_requests(repository, issue)
    if isinstance(linked, Unknown):
        return f"cannot tell whether a pull request claims it: {linked.reason}"
    if linked:
        named = ", ".join(f"#{pull_request.number}" for pull_request in linked)
        return f"a pull request is open on it: {named}"
    return None


def _check_blockers(repository: str, issue: int) -> str | None:
    """Return what still blocks the issue, or nothing when nothing open does."""
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
