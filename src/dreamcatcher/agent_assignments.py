"""Create an assignment for an issue, and read back the ones a repo already has.

An assignment is what one dispatch of an issue makes. Its identifier combines
the issue number with the time that the assignment started. The identifier names
its branch, worktree, and file directory. Three worktrees for one issue therefore
read as three assignments at one thing, each with its own pull request.

Creation prepares and publishes the assignment's branch, opens its linked draft
pull request, then records the assignment. Nothing here decides which
issue to dispatch, or when. A caller that has decided asks for the assignment.
"""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dreamcatcher import prompts
from dreamcatcher.agent_rounds import (
    AgentRoundPaths,
    AgentRoundRecord,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    RoundOutcome,
    RoundPurpose,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import DispatchRoute, Harness
from dreamcatcher.documents import (
    Document,
    read_json,
    read_text,
    write_json,
    write_text,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    add_worktree,
    delete_branch,
    fetch,
    has_commits_since_main,
    is_assignment_worktree,
    make_empty_commit,
    push_branch,
    read_worktree_branch,
    remove_worktree,
)
from dreamcatcher.github import (
    LinkedPullRequest,
    PullRequest,
    PullRequestState,
    Unknown,
    create_pull_request,
    list_linked_pull_requests,
    list_pull_requests,
)
from dreamcatcher.state import StateDirectory

# What an assignment's branch is called, before its identifier. The prefix keeps
# dreamcatcher's own branches apart from everyone else's, and from the branches
# that the catcher it replaces left behind.
BRANCH_PREFIX = "dreamcatcher-"

# The file in an assignment's directory saying what the assignment was dispatched
# with.
RECORD = "assignment.json"

# The directory in an assignment's directory holding a directory per round.
ROUNDS = "rounds"

USER_POST_DELIVERY_CURSOR = "watermark"


class AgentAssignmentRecord(Document):
    """The issue an assignment works on, and the settings it runs its rounds with.

    The dispatch settles all of these, including the pull request identity, and
    no later round changes any of them. Every round reads them from here rather
    than from the config, so editing the config while an assignment is in flight
    cannot reach that assignment. Mutable pull request state stays on GitHub.
    """

    issue: int
    label: str
    branch: str
    worktree: Path
    pull_request: int
    harness: Harness
    model: str
    effort: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class AgentAssignment:
    """One assignment at one issue, as it stands.

    The directory is where the assignment keeps its own files, and its own name is
    the assignment's identifier, which is how a reader of the disk finds one. The record
    says what the dispatch settled, and the rounds are what the assignment has run
    so far, oldest first.

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
            round.purpose is RoundPurpose.WRAP_UP
            and round.outcome is RoundOutcome.SUCCESSFUL
        )

    def describe_unfinished_round(self) -> str | None:
        """Return what the assignment's last round left unfinished, or nothing.

        A record with no ending is a round the daemon has not reconciled yet,
        and an interrupted or errored ending says that the work stopped short.
        Each is recovered from where it stopped.

        An assignment that has run no round at all has left nothing unfinished.
        Its first round never started, which is another matter: the scheduler
        retries that recorded assignment before it starts ordinary work.
        """
        if not self.rounds:
            return None
        ending = self.rounds[-1].ending
        if ending is None or isinstance(ending, InterruptedAgentRoundEnding):
            return "the last round was interrupted"
        if isinstance(ending, ErroredAgentRoundEnding):
            return f"the last round failed (exit {ending.status})"
        return None

    def round_paths(self, *, number: int) -> AgentRoundPaths:
        """Where the assignment's numbered round ran, and where it wrote.

        Every round runs in the assignment's worktree, and writes into a
        directory named by the number of the round it is.

        An assignment runs one round at a time, and each round is numbered by how
        many the assignment had run before it, so the rounds are numbered from one
        in the order they ran. The place of a record in `rounds` is therefore
        the number of the round it records, which is how a reader of the round
        list finds each round's own files.
        """
        return AgentRoundPaths(
            worktree=self.record.worktree,
            rounds_directory=self.directory / ROUNDS,
            number=number,
        )

    @property
    def next_round_number(self) -> int:
        """The number the assignment's next round will carry."""
        return self.rounds[-1].number + 1 if self.rounds else 1


def read_agent_assignments(*, state: StateDirectory) -> list[AgentAssignment]:
    """Return every assignment the state directory holds, by identifier.

    A worktree under `worktrees/` is what says an assignment exists, since that is
    the one place an assignment of this daemon's can be. The assignment's own files
    sit under `assignments/`, in a directory with the same identifier.

    The state directory is also what the round records are read through, so a
    process that reads the same one again reads only the records that can have
    changed since.

    A state directory with no worktrees in it yet holds no assignments, so this
    answers with nothing rather than failing. Anything under `worktrees/` that
    is not a directory is not a worktree, which is what keeps a file a file
    browser left there from reading as an assignment.

    A worktree whose record is not there is not an assignment either. Assignment
    creation may leave such a worktree when it is interrupted, and a later
    creation attempt reconciles it. A record that is there and will not read is
    another matter, and says so.
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
        if (directory / RECORD).exists()
    ]


def read_agent_assignments_for_issue(
    *, state: StateDirectory, issue: int
) -> list[AgentAssignment]:
    """Return the assignments at the issue, by identifier."""
    return [
        assignment
        for assignment in read_agent_assignments(state=state)
        if assignment.record.issue == issue
    ]


def inspect_incomplete_assignment_setups(
    *, state: StateDirectory, repository: str
) -> dict[int, str | None]:
    """Return each incomplete setup's recovery obstacle, when it has one.

    A setup with no obstacle is safe for assignment creation to resume. This
    boundary owns that decision, so eligibility only has to distinguish a
    recoverable local setup from a pull request owned elsewhere.
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
    found: dict[int, list[str]] = {}
    for path in state.worktrees.glob("GH*-*"):
        if (
            not is_assignment_worktree(path=path)
            or (state.assignments / path.name / RECORD).exists()
        ):
            continue
        issue = int(path.name.split("-", maxsplit=1)[0].removeprefix("GH"))
        found.setdefault(issue, []).append(path.name)
    return found


def _inspect_incomplete_assignment_setup(
    *,
    state: StateDirectory,
    repository: str,
    issue: int,
    identifiers: list[str],
) -> str | None:
    """Return what prevents this issue's incomplete setup from recovery."""
    if len(identifiers) > 1:
        named = ", ".join(sorted(identifiers))
        return f"GH{issue} has several incomplete assignment setups: {named}."
    identifier = identifiers[0]
    branch = f"{BRANCH_PREFIX}{identifier}"
    try:
        _check_worktree_branch(state=state, identifier=identifier, branch=branch)
        found = _find_branch_pull_request(repository=repository, branch=branch)
        linked = _read_linked_pull_requests(repository=repository, issue=issue)
        if found is None:
            _refuse_linked_pull_requests(linked=linked, branch=branch, issue=issue)
        else:
            _adopt_pull_request(
                pull_request=found,
                linked=linked,
                branch=branch,
                issue=issue,
            )
    except ReportableError as error:
        return str(error)
    return None


@dataclass(frozen=True, kw_only=True)
class AgentAssignmentCreator:
    """Create assignment records in one repository and state directory."""

    state: StateDirectory
    repository: str

    def create(
        self,
        *,
        route: DispatchRoute,
        named: Harness,
        issue: int,
        at: datetime,
    ) -> AgentAssignment:
        """Create the issue's durable assignment with no rounds run yet.

        The assignment runs on the harness that the route and this daemon
        select, with that harness's model, effort, and prompt template. Creation
        fetches main, makes the branch and worktree, adds and pushes an empty
        commit, opens the linked draft pull request, then writes the record.

        A retry reuses an incomplete setup identified by its worktree and
        branch. Only a failed worktree creation is removed immediately, because
        later setup steps leave recoverable evidence. An issue that already has
        an open local assignment cannot receive another.
        """
        open_assignments = [
            assignment
            for assignment in read_agent_assignments_for_issue(
                state=self.state, issue=issue
            )
            if not assignment.is_complete
        ]
        if open_assignments:
            raise ReportableError(
                f"GH{issue} already has open assignment "
                f"{open_assignments[0].identifier}."
            )
        harness = route.choose_harness(named=named)
        recipe = route.assignment_recipes[harness]
        fetch(root=self.state.root)
        identifier = _find_incomplete_assignment(state=self.state, issue=issue) or (
            f"GH{issue}-{at:%Y%m%d-%H%M%S}"
        )
        branch = f"{BRANCH_PREFIX}{identifier}"
        worktree = self.state.worktrees / identifier
        if is_assignment_worktree(path=worktree):
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
        pull_request = _find_or_create_pull_request(
            repository=self.repository, branch=branch, issue=issue
        )
        record = AgentAssignmentRecord(
            issue=issue,
            label=route.label,
            branch=branch,
            worktree=worktree,
            pull_request=pull_request,
            harness=harness,
            model=recipe.model,
            effort=recipe.effort,
            prompt=prompts.compose_first_round_prompt(
                template=recipe.prompt, issue=issue
            ),
        )
        directory = self.state.assignments / identifier
        write_json(document=record, path=directory / RECORD)
        return AgentAssignment(directory=directory, record=record)


def _find_incomplete_assignment(*, state: StateDirectory, issue: int) -> str | None:
    """Return the identifier of this issue's incomplete assignment setup."""
    found = _find_incomplete_assignment_identifiers(state=state).get(issue, [])
    if len(found) > 1:
        identifiers = ", ".join(sorted(found))
        raise ReportableError(
            f"GH{issue} has several incomplete assignment setups: {identifiers}."
        )
    return found[0] if found else None


def _check_worktree_branch(
    *, state: StateDirectory, identifier: str, branch: str
) -> None:
    """Require an incomplete setup's worktree to have its assignment branch."""
    checked_out = read_worktree_branch(worktree=state.worktrees / identifier)
    if checked_out != branch:
        raise ReportableError(
            f"cannot reconcile {identifier}: its worktree has branch "
            f"{checked_out}, not {branch}."
        )


def _find_or_create_pull_request(*, repository: str, branch: str, issue: int) -> int:
    """Return the branch's existing pull request or create its draft."""
    found = _find_branch_pull_request(repository=repository, branch=branch)
    linked = _read_linked_pull_requests(repository=repository, issue=issue)
    if found is not None:
        return _adopt_pull_request(
            pull_request=found, linked=linked, branch=branch, issue=issue
        )
    _refuse_linked_pull_requests(linked=linked, branch=branch, issue=issue)
    return _create_assignment_pull_request(
        repository=repository, branch=branch, issue=issue
    )


def _find_branch_pull_request(*, repository: str, branch: str) -> PullRequest | None:
    """Return the sole pull request on a recovery branch, when it has one."""
    found = list_pull_requests(repository=repository, branch=branch)
    if isinstance(found, Unknown):
        raise ReportableError(
            f"cannot reconcile the pull request for {branch}: {found.reason}"
        )
    if len(found) > 1:
        raise ReportableError(f"{branch} has more than one pull request.")
    return found[0] if found else None


def _read_linked_pull_requests(
    *, repository: str, issue: int
) -> list[LinkedPullRequest]:
    """Return the issue's open linked pull requests or report why they are unknown."""
    linked = list_linked_pull_requests(repository=repository, issue=issue)
    if isinstance(linked, Unknown):
        raise ReportableError(
            f"cannot tell whether another pull request claims GH{issue}: "
            f"{linked.reason}"
        )
    return linked


def _adopt_pull_request(
    *,
    pull_request: PullRequest,
    linked: list[LinkedPullRequest],
    branch: str,
    issue: int,
) -> int:
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
    if pull_request.number not in {one.number for one in linked}:
        raise ReportableError(
            f"cannot reconcile {branch}: pull request #{pull_request.number} "
            f"is not linked to GH{issue}."
        )
    unrelated = [one for one in linked if one.number != pull_request.number]
    _refuse_linked_pull_requests(linked=unrelated, branch=branch, issue=issue)
    return pull_request.number


def _refuse_linked_pull_requests(
    *, linked: list[LinkedPullRequest], branch: str, issue: int
) -> None:
    """Refuse open linked pull requests not owned by the recovery branch."""
    if linked:
        named = ", ".join(f"#{pull_request.number}" for pull_request in linked)
        raise ReportableError(
            f"cannot create a pull request for {branch}: GH{issue} already has "
            f"an open linked pull request ({named})."
        )


def _create_assignment_pull_request(*, repository: str, branch: str, issue: int) -> int:
    """Create and return the assignment branch's open draft pull request."""
    created = create_pull_request(repository=repository, branch=branch, issue=issue)
    if isinstance(created, Unknown):
        raise ReportableError(
            f"cannot read the pull request created for {branch}: {created.reason}"
        )
    if created.state is not PullRequestState.OPEN or not created.is_draft:
        raise ReportableError(
            f"pull request #{created.number} for {branch} was not created as "
            "an open draft."
        )
    return created.number


def _read_assignment(*, state: StateDirectory, directory: Path) -> AgentAssignment:
    """Return the assignment whose own files sit in this directory."""
    return AgentAssignment(
        directory=directory,
        record=read_json(model=AgentAssignmentRecord, path=directory / RECORD),
        rounds=state.round_reader.read_records(directory=directory / ROUNDS),
        user_post_delivery_cursor=_read_user_post_delivery_cursor(directory=directory),
    )


def _read_user_post_delivery_cursor(*, directory: Path) -> str:
    """Return the newest user post delivered to this assignment.

    A batch is delivered when a round launches with it, and that launch writes
    this file. An assignment that no round has carried the user's words to has no
    file here, so its cursor is the beginning of time.

    Whatever wrote the file may have left a line ending after the timestamp, so
    the surrounding space goes: an ISO-8601 time is the whole value.
    """
    path = directory / USER_POST_DELIVERY_CURSOR
    if not path.exists():
        return ""
    return read_text(path=path).strip()


def advance_user_post_delivery_cursor(
    *, assignment: AgentAssignment, newest: str
) -> None:
    """Write the time of the newest user post delivered to the assignment.

    A round launching with a batch of posts performs this write after it starts.
    Until the write lands, a daemon that dies reads those same posts again on its
    next tick rather than losing them.
    """
    write_text(text=newest, path=assignment.directory / USER_POST_DELIVERY_CURSOR)


def _discard_worktree_and_branch(
    *, state: StateDirectory, worktree: Path, branch: str
) -> None:
    """Remove artifacts that a failed worktree creation may have left."""
    with suppress(CommandError):
        remove_worktree(root=state.root, path=worktree)
    with suppress(CommandError):
        delete_branch(root=state.root, branch=branch)
