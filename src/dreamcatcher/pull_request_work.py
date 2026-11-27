"""Open, prepare and complete pull request work.

Each assignment and campaign has its own branch and worktree. Its opening
round publishes the branch and opens the draft pull request before the
harness runs.
"""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

from pydantic import PositiveInt

from dreamcatcher.agent_rounds import (
    read_agent_round_records,
    request_agent_round_stop,
)
from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkEndReason,
    end_agent_work,
    read_agent_work_ending,
    remove_agent_work_worktree,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.documents import (
    DocumentCache,
    DreamcatcherDocument,
    ReadOnlyList,
    WriteOnceDreamcatcherDocument,
    read_json_if_exists,
    write_json,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    add_worktree,
    delete_branch,
    fetch_base_branch,
    has_commits_since_base,
    is_linked_worktree,
    is_local_branch,
    make_empty_commit,
    push_branch,
)
from dreamcatcher.github import (
    CheckResult,
    PullRequestMergeState,
    PullRequestReference,
    PullRequestSignal,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    close_issue_as_completed,
    create_pull_request,
    list_pull_requests,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.state import StateDirectory

# What a branch is called, before its work identifier. The prefix keeps
# dreamcatcher's own branches apart from everyone else's, and from the branches
# that the catcher it replaces left behind.
_WORK_BRANCH_PREFIX = "dreamcatcher-"

# The file in a work directory holding its pull request's number.
_PULL_REQUEST_RECORD_NAME = "pull-request.json"


class ObservedPullRequest(DreamcatcherDocument):
    """Model what a tick read of a pull request.

    The head is the commit that the checks ran at. A failing check result can
    still have checks running.
    """

    state: PullRequestState
    is_draft: bool
    merge_state: PullRequestMergeState
    head: str
    check_result: CheckResult
    has_running_checks: bool

    @property
    def is_ready_for_review(self) -> bool:
        """Whether the pull request is open and not a draft."""
        return self.state is PullRequestState.OPEN and not self.is_draft


class PullRequestRoundInput(WriteOnceDreamcatcherDocument):
    """Model what a round receives from the work's pull request channel."""

    pull_request: PositiveInt
    pull_request_state: PullRequestState
    pull_request_head: str
    signals: ReadOnlyList[PullRequestSignal]
    user_posts: ReadOnlyList[UserPost]


class _PullRequestRecord(WriteOnceDreamcatcherDocument):
    """Model the work's pull request number.

    The round that opens the pull request writes it once, and the scheduler
    reads the pull request by it.
    """

    number: PositiveInt


def compose_work_branch(*, identifier: str) -> str:
    """Return the branch name derived from the pull request work's identifier."""
    return f"{_WORK_BRANCH_PREFIX}{identifier}"


def read_work_pull_request_number(*, work: AgentWork) -> int | None:
    """Return the work's recorded pull request number once a round has opened it."""
    record = read_json_if_exists(
        model=_PullRequestRecord,
        path=work.directory / _PULL_REQUEST_RECORD_NAME,
    )
    return None if record is None else record.number


def cancel_pull_request_work(*, assignment: AgentWork, at: datetime) -> bool:
    """Record that the user has taken an open assignment over.

    Return whether the cancel is the assignment's ending. An assignment that
    has already ended keeps its ending, even one that lands after the caller
    read the assignment, and no round is asked to stop.

    The ending is written before the running round is asked to stop, so a round
    that starts at the same moment either receives the stop request here or sees
    the ending itself.
    """
    if not end_agent_work(work=assignment, reason=AgentWorkEndReason.CANCELLED, at=at):
        return False
    rounds = read_agent_round_records(
        cache=DocumentCache(),
        directory=assignment.rounds_directory,
    )
    if rounds and rounds[-1].ending is None:
        request_agent_round_stop(
            paths=assignment.compose_round_paths(number=rounds[-1].number)
        )
    return True


def complete_pull_request_work(
    *,
    work: AgentWork,
    clock: Callable[[], datetime],
    final_output: str | None,
) -> None:
    """Record that the work completed, as its wrap-up round finishes.

    An work that has already ended keeps its ending, so a cancel that
    lands while the wrap-up round runs still leaves the worktree to the user.
    """
    end_agent_work(work=work, reason=AgentWorkEndReason.COMPLETED, at=clock())


def close_issue_for_merged_pull_request(
    *,
    repository: str,
    work: AgentWork,
    round_input: PullRequestRoundInput,
) -> None:
    """Close the issue during wrap-up after a merge into a recorded alternate base."""
    if (
        round_input.pull_request_state is PullRequestState.MERGED
        and work.record.base_branch is not None
        and read_agent_work_ending(directory=work.directory) is None
    ):
        comment = f"Merged in #{round_input.pull_request}.\n\n{AGENT_POST_MARKER}"
        close_issue_as_completed(
            repository=repository,
            issue=work.record.issue,
            closing_comment=comment,
        )


def remove_work_worktree_and_branch(*, state: StateDirectory, work: AgentWork) -> None:
    """Remove the work's worktree, then its local branch.

    The branch on origin stays, and so do the work's records. A worktree
    or branch that is not there is already removed. A removal or a deletion
    that Git refuses raises ReportableError.
    """
    remove_agent_work_worktree(state=state, work=work)
    branch = compose_work_branch(identifier=work.identifier)
    if not is_local_branch(root=state.root, branch=branch):
        return
    try:
        delete_branch(root=state.root, branch=branch)
    except CommandError as failure:
        raise ReportableError(
            f"could not delete the branch {branch}: {failure.reason}"
        ) from failure


@dataclass(frozen=True, kw_only=True)
class OpenedPullRequest:
    """Identify the recorded pull request and whether an earlier attempt opened it."""

    number: int
    was_adopted: bool


def open_work_pull_request(
    *, state: StateDirectory, repository: str, work: AgentWork
) -> OpenedPullRequest:
    """Publish the work's branch and record its draft pull request.

    Adopt a pull request an earlier attempt created, even if its base has
    since gone. Otherwise prepare and publish the work's branch, and
    open the draft. Record its number before returning it.
    """
    branch = compose_work_branch(identifier=work.identifier)
    pull_request = _find_branch_pull_request(repository=repository, branch=branch)
    was_adopted = pull_request is not None
    if pull_request is None:
        base = _publish_work_branch(state=state, work=work, branch=branch)
        pull_request = create_pull_request(
            repository=repository,
            base=base,
            branch=branch,
            issue=work.record.issue,
            title=work.record.title,
        )
        if isinstance(pull_request, UnknownGitHubResponse):
            raise ReportableError(pull_request.reason)
    write_json(
        document=_PullRequestRecord(number=pull_request.number),
        path=work.directory / _PULL_REQUEST_RECORD_NAME,
    )
    return OpenedPullRequest(number=pull_request.number, was_adopted=was_adopted)


def _publish_work_branch(*, state: StateDirectory, work: AgentWork, branch: str) -> str:
    """Publish a branch with commits beyond its base and return the base's name.

    Keep the worktree and commits from a previous attempt. Remove a worktree
    that cannot be added and its branch so the next attempt can add both.
    """
    base, base_ref = fetch_base_branch(root=state.root, branch=work.record.base_branch)
    if not is_linked_worktree(path=work.worktree):
        try:
            add_worktree(
                root=state.root,
                path=work.worktree,
                branch=branch,
                base_ref=base_ref,
            )
        except ReportableError:
            with suppress(ReportableError):
                remove_work_worktree_and_branch(state=state, work=work)
            raise
    if not has_commits_since_base(worktree=work.worktree, base_ref=base_ref):
        make_empty_commit(worktree=work.worktree, message=f"GH{work.record.issue}")
    push_branch(root=state.root, branch=branch)
    return base


def _find_branch_pull_request(
    *, repository: str, branch: str
) -> PullRequestReference | None:
    """Return the sole pull request on the branch, when it has one."""
    pull_requests = list_pull_requests(repository=repository, branch=branch)
    if isinstance(pull_requests, UnknownGitHubResponse):
        raise ReportableError(
            f"cannot tell whether {branch} has a pull request: {pull_requests.reason}"
        )
    if len(pull_requests) > 1:
        raise ReportableError(f"{branch} has more than one pull request.")
    return pull_requests[0] if pull_requests else None
