"""Create agent assignments and read their persisted state.

Each assignment dispatch creates an assignment with its own identifier, branch,
worktree, assignment directory under the instance state, and pull request.
Several assignments can exist for one issue.

Creation prepares and publishes the assignment's branch, opens its linked draft
pull request, then records the assignment. The scheduler decides when to create
each assignment.
"""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast

from pydantic import AwareDatetime

from dreamcatcher.agent_assignment_pull_requests import (
    find_or_create_assignment_pull_request,
    validate_assignment_pull_request_setup,
)
from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    AssignmentRoundPurpose,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
    read_agent_round_records,
    request_agent_round_stop,
)
from dreamcatcher.agent_work import (
    read_harness_session_identifier,
    read_retry_requested_at,
    read_user_request_time,
    record_user_request,
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
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.harnesses import find_harness_session_identifier
from dreamcatcher.prompts import compose_first_round_prompt
from dreamcatcher.state import StateDirectory

# What an assignment's branch is called, before its identifier. The prefix keeps
# dreamcatcher's own branches apart from everyone else's, and from the branches
# that the catcher it replaces left behind.
_ASSIGNMENT_BRANCH_PREFIX = "dreamcatcher-"

# The file in an assignment's directory saying what the assignment received
# with.
_ASSIGNMENT_RECORD_NAME = "assignment.json"

# The file in an assignment's directory holding its latest pull request
# observation.
_PULL_REQUEST_OBSERVATION_RECORD_NAME = "pull-request-observation.json"

# The file in an assignment's directory saying when the user cancelled it.
_CANCEL_RECORD_NAME = "cancel.json"

# The directory in an assignment's directory holding a directory per round.
_AGENT_ROUNDS_DIRECTORY_NAME = "rounds"


class AssignmentRoundInput(DreamcatcherDocument):
    """Model the pull request state and user posts delivered to an assignment round."""

    pull_request_state: PullRequestState
    user_posts: list[UserPost]


class PullRequestObservation(DreamcatcherDocument):
    """Model the latest pull request state observed for reporting.

    Scheduling reads the pull request from GitHub, not from this observation.
    """

    state: PullRequestState
    is_draft: bool
    observed_at: AwareDatetime

    @property
    def is_open(self) -> bool:
        """Whether the pull request was open when observed."""
        return self.state is PullRequestState.OPEN


class AssignmentRecord(DreamcatcherDocument):
    """Model the identities and settled settings of an agent assignment.

    The assignment dispatch settles the recipe and identities, and nothing
    writes the record again. Every round reads this record, so later config
    edits do not change an assignment in progress.
    """

    issue: int
    title: str
    dispatch_label: str
    branch: str
    worktree: Path
    pull_request: int
    harness: AgentHarness
    model: str
    effort: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class Assignment:
    """Represent an agent assignment as its persisted state currently reads.

    The directory name is the assignment identifier. The record holds the
    settings that the assignment dispatch settled. Every fact that changes
    later, such as the latest pull request observation or a cancel, is read
    from a file of its own beside the record. The rounds are ordered from
    oldest to newest.

    The user-post delivery cursor is read from the newest recorded round input
    that delivered posts. An assignment that has received none has the beginning
    of time, so the first relay from its pull request returns the whole history.
    """

    directory: Path
    record: AssignmentRecord
    pull_request_observation: PullRequestObservation
    harness_session_identifier: HarnessSessionIdentifier | None = None
    retry_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    rounds: list[AgentRoundRecord] = field(default_factory=list)

    @property
    def user_post_delivery_cursor(self) -> str:
        """The time of the newest user post delivered in a recorded round input."""
        return read_user_post_delivery_cursor(assignment=self)

    @property
    def identifier(self) -> str:
        """The identifier that the branch, worktree, and files all carry."""
        return self.directory.name

    @property
    def is_complete(self) -> bool:
        """Whether a wrap-up round has exited successfully."""
        if not self.rounds:
            return False
        round = self.rounds[-1]
        return (
            round.purpose is AssignmentRoundPurpose.WRAP_UP
            and round.outcome is AgentRoundOutcome.SUCCESSFUL
        )

    @property
    def ended_at(self) -> datetime | None:
        """When the assignment was cancelled or completed, if it has ended."""
        if self.cancelled_at is not None:
            return self.cancelled_at
        if not self.is_complete:
            return None
        return cast("SuccessfulAgentRoundEnding", self.rounds[-1].ending).at

    @property
    def is_open(self) -> bool:
        """Whether the assignment has neither completed nor been cancelled."""
        return self.ended_at is None

    def describe_unfinished_round(self) -> str | None:
        """Describe an interrupted or errored final round, if one exists.

        A record with no ending is a round the daemon has not reconciled yet,
        and an interrupted or errored ending says that the work stopped short.
        """
        if not self.rounds:
            return None
        ending = self.rounds[-1].ending
        if isinstance(ending, InterruptedAgentRoundEnding):
            return "the last round was interrupted"
        if isinstance(ending, ErroredAgentRoundEnding):
            return f"the last round failed (exit {ending.status})"
        return None

    def find_harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """Return the recorded or recoverable harness session identifier."""
        return find_harness_session_identifier(
            harness=self.record.harness,
            agent_work_identifier=self.identifier,
            recorded=self.harness_session_identifier,
            raw_outputs=(
                self.compose_round_paths(number=round_record.number).raw_output
                for round_record in reversed(self.rounds)
            ),
        )

    def compose_round_paths(self, *, number: int) -> AgentRoundPaths:
        """Return the worktree and file paths for a numbered round.

        Every round runs in the assignment's worktree, and writes into a
        directory named by the number of the round it is.

        Round numbers start at one and increase in execution order.
        """
        return AgentRoundPaths(
            worktree=self.record.worktree,
            rounds_directory=self.directory / _AGENT_ROUNDS_DIRECTORY_NAME,
            number=number,
        )

    @property
    def next_round_number(self) -> int:
        """The number the assignment's next round will carry."""
        return self.rounds[-1].number + 1 if self.rounds else 1


def read_assignments(*, state: StateDirectory) -> list[Assignment]:
    """Return every complete assignment setup, ordered by identifier.

    A worktree under `worktrees/` declares that an assignment exists. Its state
    sits under `assignments/` in a directory with the same identifier.

    The state directory is also what the round records are read through, so a
    process that reads the same one again reads only the records that can have
    changed since.

    Missing state and worktrees without assignment records are incomplete setups,
    so this read omits them. An invalid record raises ReportableError.
    """
    if not state.worktrees.is_dir():
        return []
    directories = [
        state.assignments / worktree.name
        for worktree in sorted(state.worktrees.iterdir())
        if worktree.is_dir()
    ]
    return [
        _read_assignment(state=state, directory=directory)
        for directory in directories
        if (directory / _ASSIGNMENT_RECORD_NAME).exists()
    ]


def read_assignment(*, state: StateDirectory, identifier: str) -> Assignment | None:
    """Return the complete assignment with this exact identifier, if it exists."""
    if not state.worktrees.is_dir():
        return None
    worktree = next(
        (
            path
            for path in state.worktrees.iterdir()
            if path.is_dir() and path.name == identifier
        ),
        None,
    )
    if worktree is None:
        return None
    directory = state.assignments / worktree.name
    if not (directory / _ASSIGNMENT_RECORD_NAME).exists():
        return None
    return _read_assignment(state=state, directory=directory)


def read_assignments_for_issue(
    *, state: StateDirectory, issue: int
) -> list[Assignment]:
    """Return the assignments at the issue, by identifier."""
    return [
        assignment
        for assignment in read_assignments(state=state)
        if assignment.record.issue == issue
    ]


def find_open_assignments_by_issue(
    *, assignments: list[Assignment]
) -> dict[int, Assignment]:
    """Return each issue's open assignment, keyed by issue."""
    return {
        assignment.record.issue: assignment
        for assignment in assignments
        if assignment.is_open
    }


def cancel_assignment(*, assignment: Assignment, at: datetime) -> None:
    """Record that the user has taken an open assignment over.

    A round with no ending is asked to stop, so it does not go on pushing to the
    branch. The cancel is written before the rounds are read again, so a round
    that starts at the same moment is either asked to stop here or finds the
    cancel through stop_round_if_cancelled. An assignment that has already
    ended raises ReportableError.
    """
    if not assignment.is_open:
        raise ReportableError(f"{assignment.identifier} has already ended.")
    record_user_request(path=assignment.directory / _CANCEL_RECORD_NAME, at=at)
    rounds = read_agent_round_records(
        cache=DocumentCache(),
        directory=assignment.directory / _AGENT_ROUNDS_DIRECTORY_NAME,
    )
    if rounds and rounds[-1].ending is None:
        request_agent_round_stop(
            paths=assignment.compose_round_paths(number=rounds[-1].number)
        )


def stop_round_if_cancelled(*, assignment: Assignment, paths: AgentRoundPaths) -> None:
    """Ask a round that has just started to stop if the user cancelled its work.

    Call this once the round's record exists, so that a cancel either lands
    before this read or finds the round itself.
    """
    cancelled_at = read_user_request_time(
        path=assignment.directory / _CANCEL_RECORD_NAME
    )
    if cancelled_at is not None:
        request_agent_round_stop(paths=paths)


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
    for path in state.worktrees.glob("GH*-*"):
        if (
            not is_linked_worktree(path=path)
            or (state.assignments / path.name / _ASSIGNMENT_RECORD_NAME).exists()
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
    branch = f"{_ASSIGNMENT_BRANCH_PREFIX}{identifier}"
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
        requested_harness: AgentHarness,
        issue: int,
        at: datetime,
    ) -> Assignment:
        """Create and publish the issue's assignment with no rounds run yet.

        The route selects a recipe in response to the requested
        agent harness. The recipe supplies the model, effort, and prompt
        template. Creation fetches main, makes the branch and worktree, adds and
        pushes an empty commit, and opens the linked draft pull request. It then
        writes the pull request observation, and last the record, which marks
        the setup complete.

        A retry reuses an incomplete setup that has the expected worktree and
        branch. A failed worktree creation is removed; failures after that point
        leave evidence for a later recovery. An issue with an open local
        assignment cannot receive another.
        """
        open_assignment = find_open_assignments_by_issue(
            assignments=read_assignments(state=self.state)
        ).get(issue)
        if open_assignment is not None:
            raise ReportableError(
                f"GH{issue} already has open assignment {open_assignment.identifier}."
            )
        selected_harness = route.choose_harness(requested_harness=requested_harness)
        recipe = route.recipes[selected_harness]
        fetch_main(root=self.state.root)
        identifier = _find_incomplete_assignment(state=self.state, issue=issue) or (
            f"GH{issue}-{at:%Y%m%d-%H%M%S}"
        )
        branch = f"{_ASSIGNMENT_BRANCH_PREFIX}{identifier}"
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
        record = AssignmentRecord(
            issue=issue,
            title=title,
            dispatch_label=route.label,
            branch=branch,
            worktree=worktree,
            pull_request=pull_request.number,
            harness=selected_harness,
            model=recipe.model,
            effort=recipe.effort,
            prompt=compose_first_round_prompt(template=recipe.prompt, issue=issue),
        )
        observation = PullRequestObservation(
            state=pull_request.state,
            is_draft=pull_request.is_draft,
            observed_at=at,
        )
        directory = self.state.assignments / identifier

        # The record marks the setup complete, so every complete assignment
        # has an observation.
        write_json(
            document=observation,
            path=directory / _PULL_REQUEST_OBSERVATION_RECORD_NAME,
        )
        write_json(document=record, path=directory / _ASSIGNMENT_RECORD_NAME)
        return Assignment(
            directory=directory, record=record, pull_request_observation=observation
        )


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


def _read_assignment(*, state: StateDirectory, directory: Path) -> Assignment:
    """Return the assignment whose own files sit in this directory."""
    return Assignment(
        directory=directory,
        record=read_json(
            model=AssignmentRecord, path=directory / _ASSIGNMENT_RECORD_NAME
        ),
        pull_request_observation=read_json(
            model=PullRequestObservation,
            path=directory / _PULL_REQUEST_OBSERVATION_RECORD_NAME,
        ),
        harness_session_identifier=read_harness_session_identifier(directory=directory),
        retry_requested_at=read_retry_requested_at(directory=directory),
        cancelled_at=read_user_request_time(path=directory / _CANCEL_RECORD_NAME),
        rounds=read_agent_round_records(
            cache=state.document_cache,
            directory=directory / _AGENT_ROUNDS_DIRECTORY_NAME,
        ),
    )


def read_user_post_delivery_cursor(*, assignment: Assignment) -> str:
    """Return the newest user-post time found in recorded round inputs."""
    for round_record in reversed(assignment.rounds):
        round_input_path = assignment.compose_round_paths(
            number=round_record.number
        ).round_input
        if not round_input_path.exists():
            continue
        round_input = read_json(model=AssignmentRoundInput, path=round_input_path)
        if round_input.user_posts:
            return round_input.user_posts[-1].written_at
    return ""


def record_pull_request_observation(
    *, assignment: Assignment, pull_request: PullRequest, observed_at: datetime
) -> None:
    """Record a pull request state when it differs from the latest observation."""
    recorded = assignment.pull_request_observation
    if (
        recorded.state is pull_request.state
        and recorded.is_draft == pull_request.is_draft
    ):
        return
    write_json(
        document=PullRequestObservation(
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
