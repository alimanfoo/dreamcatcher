"""Create agent assignments and read the state that only assignments have.

Each assignment dispatch creates a piece of agent work with its own identifier,
branch, worktree and pull request. Several assignments can exist for one issue.

Creation prepares and publishes the assignment's branch, opens its linked draft
pull request, then records the assignment. The scheduler decides when to create
each assignment.
"""

from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime

from dreamcatcher.agent_assignment_pull_requests import (
    find_or_create_assignment_pull_request,
    validate_assignment_pull_request_setup,
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
    find_open_agent_work_by_issue,
    is_agent_work_recorded,
    read_agent_work_of_kind,
    record_agent_work,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import AgentHarness, AssignmentRoute
from dreamcatcher.documents import (
    DocumentCache,
    DreamcatcherDocument,
    read_json,
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
    read_worktree_branch,
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

    Creation records the number, and the scheduler reads that pull request by
    it. Scheduling reads the pull request's state from GitHub, not from this
    observation, which keeps it for reporting.
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


def read_pull_request_observation(*, assignment: AgentWork) -> PullRequestObservation:
    """Return the assignment's pull request observation."""
    return read_json(
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


def inspect_incomplete_assignment_setups(
    *, state: StateDirectory, repository: str
) -> dict[int, str | None]:
    """Return each incomplete setup's latest failure, if any.

    A setup with no failure is safe for assignment creation to resume. This
    boundary owns that decision.
    """
    return {
        issue: _inspect_incomplete_assignment_setup(
            state=state,
            repository=repository,
            issue=issue,
            identifiers=identifiers,
        )
        for issue, identifiers in _find_incomplete_assignment_identifiers(
            state=state
        ).items()
    }


def _find_incomplete_assignment_identifiers(
    *, state: StateDirectory
) -> dict[int, list[str]]:
    """Return each issue's setup identifiers whose record is absent."""
    identifiers_by_issue: dict[int, list[str]] = {}
    for path in state.worktrees.glob(f"GH*-{AgentWorkKind.ASSIGNMENT}"):
        if not is_linked_worktree(path=path) or is_agent_work_recorded(
            state=state, identifier=path.name
        ):
            continue
        issue = int(path.name.split("-", maxsplit=1)[0].removeprefix("GH"))
        identifiers_by_issue.setdefault(issue, []).append(path.name)
    return identifiers_by_issue


def _inspect_incomplete_assignment_setup(
    *,
    state: StateDirectory,
    repository: str,
    issue: int,
    identifiers: list[str],
) -> str | None:
    """Return this issue's incomplete setup failure, if any."""
    if len(identifiers) > 1:
        identifier_names = ", ".join(sorted(identifiers))
        return (
            f"GH{issue} has several incomplete assignment setups: {identifier_names}."
        )
    identifier = identifiers[0]
    branch = compose_assignment_branch(identifier=identifier)
    try:
        _check_worktree_branch(state=state, identifier=identifier, branch=branch)
        validate_assignment_pull_request_setup(
            repository=repository, branch=branch, issue=issue
        )
    except ReportableError as error:
        return str(error)
    return None


@dataclass(frozen=True, kw_only=True)
class AssignmentCreator:
    """Create durable agent assignments in one repository."""

    state: StateDirectory
    repository: str

    def create(
        self,
        *,
        route: AssignmentRoute,
        preferred_harness: AgentHarness,
        issue: int,
        at: datetime,
    ) -> AgentWork:
        """Create and publish the issue's assignment with no rounds run yet.

        The route selects a recipe in response to the preferred harness. The
        recipe supplies the settings that the record keeps. Creation fetches
        main, makes the branch and worktree, adds and pushes an empty commit,
        and opens the linked draft pull request. It then writes the pull request
        observation, and last the record, which marks the setup complete.

        A retry reuses an incomplete setup that has the expected worktree and
        branch. A failed worktree creation is removed; failures after that point
        leave evidence for a later recovery. An issue with an open local
        assignment cannot receive another.
        """
        open_assignment = find_open_agent_work_by_issue(
            work=read_agent_work_of_kind(
                state=self.state, kind=AgentWorkKind.ASSIGNMENT
            )
        ).get(issue)
        if open_assignment is not None:
            raise ReportableError(
                f"GH{issue} already has open assignment {open_assignment.identifier}."
            )
        selected_harness = route.choose_harness(preferred_harness=preferred_harness)
        recipe = route.recipes[selected_harness]
        fetch_main(root=self.state.root)
        identifier = _find_incomplete_assignment(
            state=self.state, issue=issue
        ) or compose_agent_work_identifier(
            issue=issue, kind=AgentWorkKind.ASSIGNMENT, at=at
        )
        branch = compose_assignment_branch(identifier=identifier)
        worktree = self.state.worktrees / identifier
        if is_linked_worktree(path=worktree):
            _check_worktree_branch(
                state=self.state, identifier=identifier, branch=branch
            )
        else:
            try:
                add_worktree(root=self.state.root, path=worktree, branch=branch)
            except ReportableError:
                _discard_worktree_and_branch(
                    state=self.state, worktree=worktree, branch=branch
                )
                raise
        if not has_commits_since_main(worktree=worktree):
            make_empty_commit(worktree=worktree, message=f"GH{issue}")
        push_branch(root=self.state.root, branch=branch)
        title, pull_request = find_or_create_assignment_pull_request(
            repository=self.repository, branch=branch, issue=issue
        )
        record = AgentWorkRecord(
            issue=issue,
            title=title,
            dispatch_label=route.label,
            kind=AgentWorkKind.ASSIGNMENT,
            harness=selected_harness,
            model=recipe.model,
            effort=recipe.effort,
            harness_config=recipe.config,
            prompt=compose_issue_instructions(template=recipe.prompt, issue=issue),
        )
        observation = PullRequestObservation(
            number=pull_request.number,
            state=pull_request.state,
            is_draft=pull_request.is_draft,
            observed_at=at,
        )

        # The record marks the setup complete, so every assignment whose setup
        # finished has an observation.
        write_json(
            document=observation,
            path=self.state.work / identifier / _PULL_REQUEST_OBSERVATION_RECORD_NAME,
        )
        return record_agent_work(state=self.state, identifier=identifier, record=record)


def _find_incomplete_assignment(*, state: StateDirectory, issue: int) -> str | None:
    """Return the identifier of this issue's incomplete assignment setup."""
    identifiers = _find_incomplete_assignment_identifiers(state=state).get(issue, [])
    if len(identifiers) > 1:
        identifier_names = ", ".join(sorted(identifiers))
        raise ReportableError(
            f"GH{issue} has several incomplete assignment setups: {identifier_names}."
        )
    return identifiers[0] if identifiers else None


def _check_worktree_branch(
    *, state: StateDirectory, identifier: str, branch: str
) -> None:
    """Require an incomplete setup's worktree to have its assignment branch."""
    checked_out_branch = read_worktree_branch(worktree=state.worktrees / identifier)
    if checked_out_branch != branch:
        raise ReportableError(
            f"cannot reconcile {identifier}: its worktree has branch "
            f"{checked_out_branch}, not {branch}."
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
        recorded.state is pull_request.state
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
