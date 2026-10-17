"""Create agent assignments and read the state that only assignments have.

Each assignment dispatch creates a piece of agent work with its own identifier,
branch, worktree and pull request. Several assignments can exist for one issue.

Creation records the assignment and nothing else. Its first round prepares and
publishes the branch and opens the linked draft pull request, the assignment's
channel, before the harness runs. The scheduler decides when to create each
assignment.
"""

from collections.abc import Callable, Iterator
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime

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
    AgentWorkRecord,
    compose_agent_work_identifier,
    end_agent_work,
    record_agent_work,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import AgentHarness, AssignmentRoute
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
from dreamcatcher.github import (
    PullRequest,
    PullRequestState,
    UserPost,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.prompts import compose_issue_instructions
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
    """Model the assignment's pull request and the latest state observed of it.

    The round that opens the pull request records the number, and the scheduler
    reads that pull request by it. Scheduling reads the pull request's state
    from GitHub, not from this observation, which keeps it for reporting.
    """

    number: int
    state: PullRequestState
    is_draft: bool
    observed_at: AwareDatetime

    @property
    def is_open(self) -> bool:
        """Whether the pull request was open when observed."""
        return self.state is PullRequestState.OPEN


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


def create_assignment(
    *,
    state: StateDirectory,
    route: AssignmentRoute,
    preferred_harness: AgentHarness,
    issue: int,
    title: str,
    at: datetime,
) -> AgentWork:
    """Record the issue's assignment with no rounds run yet.

    The route selects a recipe in response to the preferred harness, and the
    recipe supplies the settings that the record keeps.
    """
    selected_harness = route.choose_harness(preferred_harness=preferred_harness)
    recipe = route.recipes[selected_harness]
    return record_agent_work(
        state=state,
        identifier=compose_agent_work_identifier(
            issue=issue, kind=AgentWorkKind.ASSIGNMENT, at=at
        ),
        record=AgentWorkRecord(
            issue=issue,
            title=title,
            dispatch_label=route.label,
            kind=AgentWorkKind.ASSIGNMENT,
            harness=selected_harness,
            model=recipe.model,
            effort=recipe.effort,
            harness_config=recipe.config,
            prompt=compose_issue_instructions(template=recipe.prompt, issue=issue),
        ),
    )


def prepare_assignment_round(
    *,
    state: StateDirectory,
    repository: str,
    assignment: AgentWork,
    round_input: AssignmentRoundInput | None,
    clock: Callable[[], datetime],
) -> AssignmentRoundInput | None:
    """Open the assignment's pull request if it has none, and return the input.

    Opening it fetches main, adds the worktree on the assignment's branch,
    makes an empty commit, pushes, finds or creates the draft pull request,
    and records the pull request's number. Each step does nothing when its
    result already exists, so a round after one that failed part way finds
    most of it done.
    """
    if read_pull_request_observation(assignment=assignment) is None:
        _open_pull_request(
            state=state, repository=repository, assignment=assignment, clock=clock
        )
    return round_input


def _open_pull_request(
    *,
    state: StateDirectory,
    repository: str,
    assignment: AgentWork,
    clock: Callable[[], datetime],
) -> None:
    """Publish the assignment's branch and record its draft pull request.

    A worktree that cannot be added is removed with its branch, so the next
    attempt adds both afresh.
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
        document=PullRequestObservation(
            number=pull_request.number,
            state=pull_request.state,
            is_draft=pull_request.is_draft,
            observed_at=clock(),
        ),
        path=assignment.directory / _PULL_REQUEST_OBSERVATION_RECORD_NAME,
    )


def read_user_post_delivery_position(*, assignment: AgentWork) -> str:
    """Return the newest user-post time among the posts already relayed."""
    for round_input in _read_relayed_inputs(assignment=assignment):
        if round_input.user_posts:
            return round_input.user_posts[-1].written_at
    return ""


def is_final_turn_taken(*, assignment: AgentWork) -> bool:
    """Return whether a merged or closed pull request has been relayed."""
    latest = next(_read_relayed_inputs(assignment=assignment), None)
    return latest is not None and latest.pull_request_state is not PullRequestState.OPEN


def _read_relayed_inputs(*, assignment: AgentWork) -> Iterator[AssignmentRoundInput]:
    """Yield the inputs already relayed, newest first.

    A first round is given no input, so it yields nothing.
    """
    for round_record in reversed(assignment.relayed_rounds):
        round_input_path = assignment.compose_round_paths(
            number=round_record.number
        ).round_input
        if round_input_path.exists():
            yield read_json(model=AssignmentRoundInput, path=round_input_path)


def record_pull_request_observation(
    *, assignment: AgentWork, pull_request: PullRequest, observed_at: datetime
) -> None:
    """Record a pull request state when it differs from the latest observation."""
    recorded = read_pull_request_observation(assignment=assignment)
    if (
        recorded is not None
        and recorded.state is pull_request.state
        and recorded.is_draft == pull_request.is_draft
    ):
        return
    write_json(
        document=PullRequestObservation(
            number=pull_request.number,
            state=pull_request.state,
            is_draft=pull_request.is_draft,
            observed_at=observed_at,
        ),
        path=assignment.directory / _PULL_REQUEST_OBSERVATION_RECORD_NAME,
    )


def _discard_worktree_and_branch(
    *, state: StateDirectory, worktree: Path, branch: str
) -> None:
    """Remove artifacts that a failed worktree creation may have left."""
    with suppress(CommandError):
        remove_worktree(root=state.root, path=worktree)
    with suppress(CommandError):
        delete_branch(root=state.root, branch=branch)
