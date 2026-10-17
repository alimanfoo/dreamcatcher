"""Open agent assignments' pull requests and read the state only assignments have.

Each assignment has its own identifier, branch, worktree and pull request, and
several assignments can exist for one issue. Its first round prepares and
publishes the branch and opens the linked draft pull request, the assignment's
channel, before the harness runs.
"""

from collections.abc import Callable, Iterator
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from pydantic import PositiveInt

from dreamcatcher.agent_assignment_pull_requests import (
    find_or_create_assignment_pull_request,
)
from dreamcatcher.agent_rounds import (
    read_agent_round_records,
    request_agent_round_stop,
)
from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkEndReason,
    end_agent_work,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.documents import (
    DocumentCache,
    DreamcatcherDocument,
    read_json,
    read_json_if_exists,
    write_json,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    add_worktree,
    delete_branch,
    fetch_main,
    has_commits_since_main,
    is_linked_worktree,
    make_empty_commit,
    push_branch,
    remove_worktree,
)
from dreamcatcher.github import PullRequestState, UserPost
from dreamcatcher.state import StateDirectory

# What an assignment's branch is called, before its identifier. The prefix keeps
# dreamcatcher's own branches apart from everyone else's, and from the branches
# that the catcher it replaces left behind.
_ASSIGNMENT_BRANCH_PREFIX = "dreamcatcher-"

# The file in an assignment's directory holding its pull request observation.
_PULL_REQUEST_OBSERVATION_RECORD_NAME = "pull-request-observation.json"


class AssignmentRoundInput(DreamcatcherDocument):
    """Model the pull request state and user posts delivered to an assignment round."""

    pull_request_state: PullRequestState
    user_posts: list[UserPost]


class PullRequestObservation(DreamcatcherDocument):
    """Model the number of the assignment's pull request.

    The round that opens the pull request writes it once, and the scheduler
    reads the pull request by it.
    """

    number: PositiveInt


def compose_assignment_branch(*, identifier: str) -> str:
    """Return the name of the branch that the assignment with this identifier owns."""
    return f"{_ASSIGNMENT_BRANCH_PREFIX}{identifier}"


def read_pull_request_observation(
    *, assignment: AgentWork
) -> PullRequestObservation | None:
    """Return the assignment's pull request observation, once a round has opened it."""
    return read_json_if_exists(
        model=PullRequestObservation,
        path=assignment.directory / _PULL_REQUEST_OBSERVATION_RECORD_NAME,
    )


def cancel_assignment(*, assignment: AgentWork, at: datetime) -> None:
    """Record that the user has taken an open assignment over.

    A round with no ending is asked to stop, so it does not go on pushing to the
    branch. The ending is written before the rounds are read again, so a round
    that starts at the same moment is either asked to stop here or finds the
    ending through request_round_stop_if_ended. An assignment that has already
    ended raises ReportableError.
    """
    if not assignment.is_open:
        raise ReportableError(f"{assignment.identifier} has already ended.")
    end_agent_work(work=assignment, reason=AgentWorkEndReason.CANCELLED, at=at)
    rounds = read_agent_round_records(
        cache=DocumentCache(),
        directory=assignment.rounds_directory,
    )
    if rounds and rounds[-1].ending is None:
        request_agent_round_stop(
            paths=assignment.compose_round_paths(number=rounds[-1].number)
        )


def complete_assignment(
    *,
    assignment: AgentWork,
    clock: Callable[[], datetime],
    final_output: str | None,
) -> None:
    """Record that the assignment completed, as its wrap-up round finishes.

    A round finisher receives the round's final output, which completion does
    not need.
    """
    end_agent_work(work=assignment, reason=AgentWorkEndReason.COMPLETED, at=clock())


def open_assignment_pull_request(
    *, state: StateDirectory, repository: str, assignment: AgentWork
) -> None:
    """Publish the assignment's branch and record its draft pull request.

    This is the preparation of a round whose assignment has no pull request
    yet. It fetches main, adds the worktree on the assignment's branch, makes
    an empty commit, pushes, adopts the pull request already on the branch or
    opens a draft, and records the pull request. A round after one that failed
    part way finds the worktree, the commit and the pull request that the
    earlier attempt made, and makes none of them again. A worktree that cannot
    be added is removed with its branch, so the next attempt adds both afresh.
    """
    issue = assignment.record.issue
    branch = compose_assignment_branch(identifier=assignment.identifier)
    fetch_main(root=state.root)
    if not is_linked_worktree(path=assignment.worktree):
        try:
            add_worktree(root=state.root, path=assignment.worktree, branch=branch)
        except ReportableError:
            _discard_worktree_and_branch(
                state=state, worktree=assignment.worktree, branch=branch
            )
            raise
    if not has_commits_since_main(worktree=assignment.worktree):
        make_empty_commit(worktree=assignment.worktree, message=f"GH{issue}")
    push_branch(root=state.root, branch=branch)
    pull_request = find_or_create_assignment_pull_request(
        repository=repository,
        branch=branch,
        issue=issue,
        title=assignment.record.title,
    )
    write_json(
        document=PullRequestObservation(number=pull_request.number),
        path=assignment.directory / _PULL_REQUEST_OBSERVATION_RECORD_NAME,
    )


def read_user_post_delivery_position(*, assignment: AgentWork) -> str:
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


def is_final_turn_taken(*, assignment: AgentWork) -> bool:
    """Return whether a merged or closed pull request has been relayed."""
    state = read_relayed_pull_request_state(assignment=assignment)
    return state is not None and state is not PullRequestState.OPEN


def _read_relayed_inputs(*, assignment: AgentWork) -> Iterator[AssignmentRoundInput]:
    """Yield the inputs already relayed, newest first."""
    for paths in assignment.list_relayed_inputs():
        yield read_json(model=AssignmentRoundInput, path=paths.round_input)


def _discard_worktree_and_branch(
    *, state: StateDirectory, worktree: Path, branch: str
) -> None:
    """Remove artifacts that a failed worktree creation may have left."""
    with suppress(CommandError):
        remove_worktree(root=state.root, path=worktree)
    with suppress(CommandError):
        delete_branch(root=state.root, branch=branch)
