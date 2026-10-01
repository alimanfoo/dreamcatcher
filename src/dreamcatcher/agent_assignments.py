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

from pydantic import AwareDatetime

from dreamcatcher import prompts
from dreamcatcher.agent_rounds import (
    AgentAssignmentRoundPurpose,
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    read_agent_round_records,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import AgentHarness, AssignmentRoute
from dreamcatcher.documents import (
    DreamcatcherDocument,
    read_json,
    read_text,
    write_json,
    write_text,
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
    IssuePullRequestContext,
    LinkedPullRequest,
    PullRequest,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    create_pull_request,
    list_pull_requests,
    read_issue_pull_request_context,
)
from dreamcatcher.harness_adapters import (
    HarnessSessionIdentifier,
    refuse_reportable_harness_session_identifier,
)
from dreamcatcher.harnesses import find_harness_session_identifier_in_output
from dreamcatcher.state import StateDirectory

# What an assignment's branch is called, before its identifier. The prefix keeps
# dreamcatcher's own branches apart from everyone else's, and from the branches
# that the catcher it replaces left behind.
AGENT_ASSIGNMENT_BRANCH_PREFIX = "dreamcatcher-"

# The file in an assignment's directory saying what the assignment received
# with.
AGENT_ASSIGNMENT_RECORD_NAME = "assignment.json"

# The directory in an assignment's directory holding a directory per round.
AGENT_ROUNDS_DIRECTORY_NAME = "rounds"

USER_POST_DELIVERY_CURSOR_NAME = "watermark"


class AgentAssignmentRoundInput(DreamcatcherDocument):
    """Model the pull request state and user posts delivered to an assignment round."""

    pull_request_state: PullRequestState
    user_posts: list[UserPost]


class PullRequestObservation(DreamcatcherDocument):
    """Model the latest pull request state observed for reporting."""

    state: PullRequestState
    is_draft: bool
    observed_at: AwareDatetime

    @property
    def is_open(self) -> bool:
        """Whether the pull request was open when observed."""
        return self.state is PullRequestState.OPEN


class AgentAssignmentRecord(DreamcatcherDocument):
    """Model the identities and settled settings of an agent assignment.

    The assignment dispatch settles the recipe and identities. The first round
    adds the harness session identifier when the harness reports it, and a retry
    request records its time. Every round reads this record, so later config
    edits do not change an assignment in progress. The latest pull request
    observation supports reporting; scheduling still reads GitHub.
    """

    issue: int
    title: str | None = None
    dispatch_label: str
    branch: str
    worktree: Path
    pull_request: int
    pull_request_observation: PullRequestObservation | None = None
    harness: AgentHarness
    harness_session_identifier: HarnessSessionIdentifier | None = None
    retry_requested_at: AwareDatetime | None = None
    model: str
    effort: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class AgentAssignment:
    """Represent an agent assignment as its persisted state currently reads.

    The directory name is the assignment identifier. The record holds the
    assignment dispatch settings, and the rounds are ordered from oldest to
    newest.

    The user-post delivery cursor is the newest post delivered to the assignment.
    An assignment that has received none has the beginning of time, so the first
    relay from its pull request returns the whole history.
    """

    directory: Path
    record: AgentAssignmentRecord
    rounds: list[AgentRoundRecord] = field(default_factory=list)
    user_post_delivery_cursor: str = ""

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
            round.purpose is AgentAssignmentRoundPurpose.WRAP_UP
            and round.outcome is AgentRoundOutcome.SUCCESSFUL
        )

    def describe_unfinished_round(self) -> str | None:
        """Describe an interrupted or errored final round, if one exists.

        A record with no ending is a round the daemon has not reconciled yet,
        and an interrupted or errored ending says that the work stopped short.
        """
        if not self.rounds:
            return None
        ending = self.rounds[-1].ending
        if ending is None or isinstance(ending, InterruptedAgentRoundEnding):
            return "the last round was interrupted"
        if isinstance(ending, ErroredAgentRoundEnding):
            return f"the last round failed (exit {ending.status})"
        return None

    def compose_round_paths(self, *, number: int) -> AgentRoundPaths:
        """Return the worktree and file paths for a numbered round.

        Every round runs in the assignment's worktree, and writes into a
        directory named by the number of the round it is.

        Round numbers start at one and increase in execution order.
        """
        return AgentRoundPaths(
            worktree=self.record.worktree,
            rounds_directory=self.directory / AGENT_ROUNDS_DIRECTORY_NAME,
            number=number,
        )

    @property
    def next_round_number(self) -> int:
        """The number the assignment's next round will carry."""
        return self.rounds[-1].number + 1 if self.rounds else 1


def read_agent_assignments(*, state: StateDirectory) -> list[AgentAssignment]:
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
        if (directory / AGENT_ASSIGNMENT_RECORD_NAME).exists()
    ]


def read_agent_assignment(
    *, state: StateDirectory, identifier: str
) -> AgentAssignment | None:
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
    if not (directory / AGENT_ASSIGNMENT_RECORD_NAME).exists():
        return None
    return _read_assignment(state=state, directory=directory)


def read_agent_assignments_for_issue(
    *, state: StateDirectory, issue: int
) -> list[AgentAssignment]:
    """Return the assignments at the issue, by identifier."""
    return [
        assignment
        for assignment in read_agent_assignments(state=state)
        if assignment.record.issue == issue
    ]


def find_open_agent_assignments_by_issue(
    *, assignments: list[AgentAssignment]
) -> dict[int, AgentAssignment]:
    """Return each issue's open assignment, keyed by issue."""
    return {
        assignment.record.issue: assignment
        for assignment in assignments
        if not assignment.is_complete
    }


def request_agent_assignment_retry(
    *, assignment: AgentAssignment, at: datetime
) -> None:
    """Record when the user asked a faulted assignment to recover again."""
    path = assignment.directory / AGENT_ASSIGNMENT_RECORD_NAME
    record = read_json(model=AgentAssignmentRecord, path=path)
    write_json(
        document=record.model_copy(update={"retry_requested_at": at}),
        path=path,
    )


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
            or (state.assignments / path.name / AGENT_ASSIGNMENT_RECORD_NAME).exists()
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
    branch = f"{AGENT_ASSIGNMENT_BRANCH_PREFIX}{identifier}"
    try:
        _check_worktree_branch(state=state, identifier=identifier, branch=branch)
        branch_pull_request = _find_branch_pull_request(
            repository=repository, branch=branch
        )
        pull_request_context = _read_issue_pull_request_context(
            repository=repository, issue=issue
        )
        if branch_pull_request is None:
            _refuse_linked_pull_requests(
                linked=pull_request_context.pull_requests,
                branch=branch,
                issue=issue,
            )
        else:
            _adopt_pull_request(
                pull_request=branch_pull_request,
                linked=pull_request_context.pull_requests,
                branch=branch,
                issue=issue,
            )
    except ReportableError as error:
        return str(error)
    return None


@dataclass(frozen=True, kw_only=True)
class AgentAssignmentCreator:
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
    ) -> AgentAssignment:
        """Create and publish the issue's assignment with no rounds run yet.

        The route selects a recipe in response to the requested
        agent harness. The recipe supplies the model, effort, and prompt
        template. Creation fetches main, makes the branch and worktree, adds and
        pushes an empty commit, opens the linked draft pull request, then writes
        the record.

        A retry reuses an incomplete setup that has the expected worktree and
        branch. A failed worktree creation is removed; failures after that point
        leave evidence for a later recovery. An issue with an open local
        assignment cannot receive another.
        """
        open_assignment = find_open_agent_assignments_by_issue(
            assignments=read_agent_assignments(state=self.state)
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
        branch = f"{AGENT_ASSIGNMENT_BRANCH_PREFIX}{identifier}"
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
        title, pull_request = _find_or_create_pull_request(
            repository=self.repository, branch=branch, issue=issue
        )
        record = AgentAssignmentRecord(
            issue=issue,
            title=title,
            dispatch_label=route.label,
            branch=branch,
            worktree=worktree,
            pull_request=pull_request.number,
            pull_request_observation=PullRequestObservation(
                state=pull_request.state,
                is_draft=pull_request.is_draft,
                observed_at=at,
            ),
            harness=selected_harness,
            model=recipe.model,
            effort=recipe.effort,
            prompt=prompts.compose_first_round_prompt(
                template=recipe.prompt, issue=issue
            ),
        )
        directory = self.state.assignments / identifier
        write_json(document=record, path=directory / AGENT_ASSIGNMENT_RECORD_NAME)
        return AgentAssignment(directory=directory, record=record)


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


def _find_or_create_pull_request(
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


def _read_assignment(*, state: StateDirectory, directory: Path) -> AgentAssignment:
    """Return the assignment whose own files sit in this directory."""
    return AgentAssignment(
        directory=directory,
        record=read_json(
            model=AgentAssignmentRecord, path=directory / AGENT_ASSIGNMENT_RECORD_NAME
        ),
        rounds=read_agent_round_records(
            cache=state.document_cache,
            directory=directory / AGENT_ROUNDS_DIRECTORY_NAME,
        ),
        user_post_delivery_cursor=_read_user_post_delivery_cursor(directory=directory),
    )


def _read_user_post_delivery_cursor(*, directory: Path) -> str:
    """Return the time of the newest user post delivered to the assignment.

    A batch is delivered when a round launches with it, and that launch writes
    this file. An assignment that no round has carried the user's words to has no
    file here, so its cursor is the beginning of time.

    Surrounding whitespace is not part of the ISO-8601 cursor.
    """
    path = directory / USER_POST_DELIVERY_CURSOR_NAME
    if not path.exists():
        return ""
    return read_text(path=path).strip()


def advance_user_post_delivery_cursor(
    *, assignment: AgentAssignment, newest: str
) -> None:
    """Record the time of the newest user post delivered to the assignment.

    A round launching with a batch of posts performs this write after it starts.
    Until the write lands, a daemon that dies reads those same posts again on its
    next tick rather than losing them.
    """
    write_text(text=newest, path=assignment.directory / USER_POST_DELIVERY_CURSOR_NAME)


def find_harness_session_identifier(
    *, assignment: AgentAssignment
) -> HarnessSessionIdentifier | None:
    """Return the recorded or recoverable harness session identifier."""
    if assignment.record.harness_session_identifier is not None:
        return assignment.record.harness_session_identifier
    for round_record in reversed(assignment.rounds):
        identifier = find_harness_session_identifier_in_output(
            harness=assignment.record.harness,
            agent_work_identifier=assignment.identifier,
            raw_output=assignment.compose_round_paths(
                number=round_record.number
            ).raw_output,
        )
        if identifier is not None:
            return identifier
    return None


def record_harness_session_identifier(
    *, assignment: AgentAssignment, identifier: str
) -> None:
    """Record the harness session that every round of the assignment continues."""
    safe_identifier = refuse_reportable_harness_session_identifier(
        agent_work_identifier=assignment.identifier, identifier=identifier
    )
    path = assignment.directory / AGENT_ASSIGNMENT_RECORD_NAME
    record = read_json(model=AgentAssignmentRecord, path=path)
    recorded_identifier = record.harness_session_identifier
    if recorded_identifier is not None and recorded_identifier != safe_identifier:
        raise ReportableError(
            f"{assignment.identifier} reported harness session {safe_identifier}, "
            f"but its record names {recorded_identifier}."
        )
    if recorded_identifier == safe_identifier:
        return
    write_json(
        document=record.model_copy(
            update={"harness_session_identifier": safe_identifier}
        ),
        path=path,
    )


def record_agent_assignment_title(*, assignment: AgentAssignment, title: str) -> None:
    """Record the first issue title known for a legacy assignment."""
    path = assignment.directory / AGENT_ASSIGNMENT_RECORD_NAME
    record = read_json(model=AgentAssignmentRecord, path=path)
    if record.title is not None:
        return
    write_json(document=record.model_copy(update={"title": title}), path=path)


def record_pull_request_observation(
    *, assignment: AgentAssignment, pull_request: PullRequest, observed_at: datetime
) -> None:
    """Record a pull request state when it differs from the latest observation."""
    path = assignment.directory / AGENT_ASSIGNMENT_RECORD_NAME
    record = read_json(model=AgentAssignmentRecord, path=path)
    recorded = record.pull_request_observation
    if (
        recorded is not None
        and recorded.state is pull_request.state
        and recorded.is_draft == pull_request.is_draft
    ):
        return
    write_json(
        document=record.model_copy(
            update={
                "pull_request_observation": PullRequestObservation(
                    state=pull_request.state,
                    is_draft=pull_request.is_draft,
                    observed_at=observed_at,
                )
            }
        ),
        path=path,
    )


def _discard_worktree_and_branch(
    *, state: StateDirectory, worktree: Path, branch: str
) -> None:
    """Remove artifacts that a failed worktree creation may have left."""
    with suppress(CommandError):
        remove_worktree(root=state.root, path=worktree)
    with suppress(CommandError):
        delete_branch(root=state.root, branch=branch)
