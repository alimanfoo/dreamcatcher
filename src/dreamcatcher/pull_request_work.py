"""Open pull requests for agent work and read their relayed state.

Each assignment has its own identifier, branch, worktree and pull request, and
several assignments can exist for one issue. The round that opens the pull
request prepares and publishes the branch and opens the linked draft pull
request, the assignment's channel, before the harness runs.
"""

from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from datetime import datetime
from itertools import islice

from pydantic import PositiveInt

from dreamcatcher.agent_rounds import (
    read_agent_round_records,
    request_agent_round_stop,
)
from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkEndReason,
    end_agent_work,
    refresh_agent_work,
    remove_agent_work_worktree,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.documents import (
    DocumentCache,
    DreamcatcherDocument,
    ReadOnlyList,
    WriteOnceDreamcatcherDocument,
    read_json,
    read_json_if_exists,
    write_json,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    add_worktree,
    delete_branch,
    fetch_branch,
    fetch_default_branch,
    has_commits_since_base,
    is_linked_worktree,
    is_local_branch,
    make_empty_commit,
    push_branch,
)
from dreamcatcher.github import (
    CheckResult,
    PullRequest,
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

# What an assignment's branch is called, before its identifier. The prefix keeps
# dreamcatcher's own branches apart from everyone else's, and from the branches
# that the catcher it replaces left behind.
_ASSIGNMENT_BRANCH_PREFIX = "dreamcatcher-"

# The file in an assignment's directory holding its pull request's number.
_PULL_REQUEST_RECORD_NAME = "pull-request.json"


class ObservedPullRequest(DreamcatcherDocument):
    """Model what a tick read of an assignment's pull request.

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


class AssignmentRoundInput(WriteOnceDreamcatcherDocument):
    """Model where an assignment's pull request stood and what a round relayed.

    The head is the pull request's head commit when the round started, which is
    the commit that each relayed pull request signal was raised at.
    """

    pull_request_state: PullRequestState
    pull_request_head: str
    signals: ReadOnlyList[PullRequestSignal]
    user_posts: ReadOnlyList[UserPost]


class _PullRequestRecord(WriteOnceDreamcatcherDocument):
    """Model the number of the assignment's pull request.

    The round that opens the pull request writes it once, and the scheduler
    reads the pull request by it.
    """

    number: PositiveInt


def compose_work_branch(*, identifier: str) -> str:
    """Return the name of the branch that the assignment with this identifier owns."""
    return f"{_ASSIGNMENT_BRANCH_PREFIX}{identifier}"


def read_work_pull_request_number(*, assignment: AgentWork) -> int | None:
    """Return the number of the assignment's pull request, once a round opened it."""
    record = read_json_if_exists(
        model=_PullRequestRecord,
        path=assignment.directory / _PULL_REQUEST_RECORD_NAME,
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
    assignment: AgentWork,
    clock: Callable[[], datetime],
    final_output: str | None,
) -> None:
    """Record that the assignment completed, as its wrap-up round finishes.

    An assignment that has already ended keeps its ending, so a cancel that
    lands while the wrap-up round runs still leaves the worktree to the user.
    """
    end_agent_work(work=assignment, reason=AgentWorkEndReason.COMPLETED, at=clock())


def prepare_assignment_round_input(
    *,
    state: StateDirectory,
    repository: str,
    assignment: AgentWork,
    pull_request: PullRequest,
    signals: Sequence[PullRequestSignal],
    posts: Sequence[UserPost],
) -> AssignmentRoundInput:
    """Build the input after closing the issue for a merge into another base."""
    if (
        pull_request.state is PullRequestState.MERGED
        and assignment.record.base_branch is not None
        and refresh_agent_work(state=state, work=assignment).is_open
    ):
        close_issue_as_completed(
            repository=repository,
            issue=assignment.record.issue,
            closing_comment=f"Merged in #{pull_request.number}.\n\n{AGENT_POST_MARKER}",
        )
    return AssignmentRoundInput(
        pull_request_state=pull_request.state,
        pull_request_head=pull_request.head,
        signals=signals,
        user_posts=posts,
    )


def remove_work_worktree_and_branch(
    *, state: StateDirectory, assignment: AgentWork
) -> None:
    """Remove the assignment's worktree, then its local branch.

    The branch on origin stays, and so do the assignment's records. A worktree
    or branch that is not there is already removed. A removal or a deletion
    that Git refuses raises ReportableError.
    """
    remove_agent_work_worktree(state=state, work=assignment)
    branch = compose_work_branch(identifier=assignment.identifier)
    if not is_local_branch(root=state.root, branch=branch):
        return
    try:
        delete_branch(root=state.root, branch=branch)
    except CommandError as failure:
        raise ReportableError(
            f"could not delete the branch {branch}: {failure.reason}"
        ) from failure


def open_work_pull_request(
    *, state: StateDirectory, repository: str, assignment: AgentWork
) -> None:
    """Publish the assignment's branch and record its draft pull request.

    Adopt a pull request an earlier attempt created, even if its base has
    since gone. Otherwise prepare and publish the assignment's branch, and
    open the draft. Record the pull request's number once it is known.
    """
    branch = compose_work_branch(identifier=assignment.identifier)
    pull_request = _find_branch_pull_request(repository=repository, branch=branch)
    if pull_request is None:
        base = _publish_work_branch(state=state, assignment=assignment, branch=branch)
        pull_request = create_pull_request(
            repository=repository,
            base=base,
            branch=branch,
            issue=assignment.record.issue,
            title=assignment.record.title,
        )
        if isinstance(pull_request, UnknownGitHubResponse):
            raise ReportableError(pull_request.reason)
    write_json(
        document=_PullRequestRecord(number=pull_request.number),
        path=assignment.directory / _PULL_REQUEST_RECORD_NAME,
    )


def _publish_work_branch(
    *, state: StateDirectory, assignment: AgentWork, branch: str
) -> str:
    """Publish a branch with commits beyond its base and return the base's name.

    Keep the worktree and commits from a previous attempt. Remove a worktree
    that cannot be added and its branch so the next attempt can add both.
    """
    base = assignment.record.base_branch
    if base is None:
        base = fetch_default_branch(root=state.root)
    else:
        fetch_branch(root=state.root, branch=base)
    base_ref = f"refs/remotes/origin/{base}"
    if not is_linked_worktree(path=assignment.worktree):
        try:
            add_worktree(
                root=state.root,
                path=assignment.worktree,
                branch=branch,
                base_ref=base_ref,
            )
        except ReportableError:
            with suppress(ReportableError):
                remove_work_worktree_and_branch(state=state, assignment=assignment)
            raise
    if not has_commits_since_base(worktree=assignment.worktree, base_ref=base_ref):
        make_empty_commit(
            worktree=assignment.worktree, message=f"GH{assignment.record.issue}"
        )
    push_branch(root=state.root, branch=branch)
    return base


def read_user_post_cursor(*, assignment: AgentWork) -> str:
    """Return the newest user-post time among the posts already relayed."""
    for round_input in _read_relayed_inputs(assignment=assignment):
        if round_input.user_posts:
            return round_input.user_posts[-1].written_at
    return ""


def read_relayed_pull_request_state(
    *, assignment: AgentWork
) -> PullRequestState | None:
    """Return the pull request state that the newest relayed round input carried."""
    latest = next(_read_relayed_inputs(assignment=assignment), None)
    return None if latest is None else latest.pull_request_state


def is_wrap_up_relayed(*, assignment: AgentWork) -> bool:
    """Return whether a merged or closed pull request has been relayed."""
    state = read_relayed_pull_request_state(assignment=assignment)
    return state is not None and state is not PullRequestState.OPEN


def read_signal_relay_head(
    *, assignment: AgentWork, signal: PullRequestSignal
) -> str | None:
    """Return the head commit at which the signal was last relayed, if ever."""
    for round_input in _read_relayed_inputs(assignment=assignment):
        if signal in round_input.signals:
            return round_input.pull_request_head
    return None


def is_check_failure_withheld(*, assignment: AgentWork) -> bool:
    """Return whether the relay rule withholds a check failure.

    It does when the last two relayed inputs both carried one, which gives an
    agent two attempts at a red build on its own. A round that relayed no check
    failure starts the count again, and one that did not consume its input is
    not counted, since its input is given again.
    """
    latest_two = list(islice(_read_relayed_inputs(assignment=assignment), 2))
    return len(latest_two) == 2 and all(
        PullRequestSignal.CHECK_FAILURE in round_input.signals
        for round_input in latest_two
    )


def _read_relayed_inputs(*, assignment: AgentWork) -> Iterator[AssignmentRoundInput]:
    """Yield the inputs already relayed, newest first."""
    for paths in assignment.list_relayed_round_paths():
        yield read_json(model=AssignmentRoundInput, path=paths.round_input)


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
