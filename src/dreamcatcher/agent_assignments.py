"""Create an assignment for an issue, and read back the ones a repo already has.

An assignment is what one dispatch of an issue makes. Its identifier combines
the issue number with the time that the assignment started. The identifier names
its branch, worktree, and file directory. Three worktrees for one issue therefore
read as three assignments at one thing, each with its own pull request.

Nothing here decides which issue to dispatch, or when. A caller that has decided
asks for the assignment.
"""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dreamcatcher import prompts
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
from dreamcatcher.git import add_worktree, delete_branch, fetch, remove_worktree
from dreamcatcher.rounds import Cause, RoundRecord, Workspace
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

# The file in an assignment's directory holding the newest post the assignment has
# been told about.
WATERMARK = "watermark"


class AgentAssignmentRecord(Document):
    """The issue an assignment works on, and the settings it runs its rounds with.

    The dispatch settles all of these, and no later round changes any of
    them. Every round reads them from here rather than from the config, so
    editing the config while an assignment is in flight cannot reach that
    assignment.
    """

    issue: int
    label: str
    branch: str
    worktree: Path
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

    The watermark is the newest post the assignment has been told about. An assignment
    that has been told about none has the beginning of time, so the first peek
    at its pull request returns the whole history.
    """

    directory: Path
    record: AgentAssignmentRecord
    rounds: list[RoundRecord] = field(default_factory=list)
    watermark: str = ""

    @property
    def identifier(self) -> str:
        """The identifier that the branch, worktree, and files all carry."""
        return self.directory.name

    @property
    def has_run_final_round(self) -> bool:
        """Whether the assignment has already run the round that winds it up.

        Any round of the assignment having been the final round is what this
        reads, and no record's ending comes into it. An assignment whose last round
        did not finish is carried on before this is ever asked, and that
        carry-on finishes what the final round started, so by the time the
        question is put the work the final round stood for is done however many
        rounds it took.
        """
        return any(record.cause is Cause.FINAL for record in self.rounds)

    def describe_unfinished_round(self) -> str | None:
        """Return what the assignment's last round left unfinished, or nothing.

        A record with no ending is a round the daemon stopped or outlived, and
        a round that ended with a failing status stopped short of its own
        accord. Both leave the work part done, so both are carried on from
        where they stopped.

        An assignment that has run no round at all has left nothing unfinished. Its
        first round never started, which is another matter, and one that only a
        person can take further.
        """
        if not self.rounds:
            return None
        ending = self.rounds[-1].ending
        if ending is None:
            return "the last round was interrupted"
        if ending.is_failed:
            return f"the last round failed (exit {ending.status})"
        return None

    def workspace(self, *, number: int) -> Workspace:
        """Where the assignment's numbered round ran, and where it wrote.

        Every round runs in the assignment's worktree, and writes into a
        directory named by the number of the round it is.

        An assignment runs one round at a time, and each round is numbered by how
        many the assignment had run before it, so the rounds are numbered from one
        in the order they ran. The place of a record in `rounds` is therefore
        the number of the round it records, which is how a reader of the round
        list finds each round's own files.
        """
        return Workspace(
            worktree=self.record.worktree,
            directory=self.directory / ROUNDS / str(number),
        )

    @property
    def next_workspace(self) -> Workspace:
        """Where the assignment's next round runs, and where it writes."""
        return self.workspace(number=len(self.rounds) + 1)


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

    A worktree whose record is not there is not an assignment either. A creation
    cuts the worktree and then writes the record, so a daemon that died between
    the two leaves one, and it stands for an assignment that ran nothing and opened
    no pull request. Reading it as no assignment leaves its issue free to go
    again, and leaves the worktree itself for whoever wants the disk back. A
    record that is there and will not read is another matter, and says so.
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


def create_agent_assignment(
    *,
    state: StateDirectory,
    route: DispatchRoute,
    named: Harness,
    issue: int,
    at: datetime,
) -> AgentAssignment:
    """Create an assignment for the issue, and return it with no rounds run yet.

    The assignment runs on the harness that this label and the run settle between
    them, with that harness's own model, effort and prompt template.

    This fetches origin's main first, so the branch starts from main as it is
    now.

    Should anything from the worktree onwards fail, the worktree and the
    branch go away again, so a failed creation leaves neither behind. git
    makes the branch before it reaches the worktree, so an add that failed
    has one to take away. The caller hears the failure that stopped the
    creation, not any failure that removing them hits.
    """
    harness = route.choose_harness(named=named)
    recipe = route.assignment_recipes[harness]
    identifier = f"GH{issue}-{at:%Y%m%d-%H%M%S}"
    record = AgentAssignmentRecord(
        issue=issue,
        label=route.label,
        branch=f"{BRANCH_PREFIX}{identifier}",
        worktree=state.worktrees / identifier,
        harness=harness,
        model=recipe.model,
        effort=recipe.effort,
        prompt=prompts.compose_first_round_prompt(template=recipe.prompt, issue=issue),
    )
    directory = state.assignments / identifier
    fetch(root=state.root)
    try:
        add_worktree(root=state.root, path=record.worktree, branch=record.branch)
        write_json(document=record, path=directory / RECORD)
    except ReportableError:
        discard_agent_assignment(state=state, record=record)
        raise
    return AgentAssignment(directory=directory, record=record)


def _read_assignment(*, state: StateDirectory, directory: Path) -> AgentAssignment:
    """Return the assignment whose own files sit in this directory."""
    return AgentAssignment(
        directory=directory,
        record=read_json(model=AgentAssignmentRecord, path=directory / RECORD),
        rounds=state.round_reader.read_records(directory=directory / ROUNDS),
        watermark=_read_watermark(directory=directory),
    )


def _read_watermark(*, directory: Path) -> str:
    """Return the newest post this assignment has been told about.

    An assignment is told about a batch of posts when a round launches with that
    batch, and that launch is what writes this file. So an assignment no round has
    yet carried the user's words to has no file here, and the beginning of time
    is what it has seen.

    Whatever wrote the file may have left a line ending after the timestamp, so
    the surrounding space goes: an ISO-8601 time is the whole value.
    """
    path = directory / WATERMARK
    if not path.exists():
        return ""
    return read_text(path=path).strip()


def advance_assignment_watermark(*, assignment: AgentAssignment, newest: str) -> None:
    """Write the time of the newest post the assignment has now been told about.

    A round launching with a batch of posts as its inbox is what tells the
    assignment about them, and this is that launch's own write. Until it lands the
    assignment has heard nothing, so a daemon that died before the round started
    reads those same posts again on its next tick rather than losing them.
    """
    write_text(text=newest, path=assignment.directory / WATERMARK)


def discard_agent_assignment(
    *, state: StateDirectory, record: AgentAssignmentRecord
) -> None:
    """Take away the worktree and the branch that an assignment was given.

    A creation that failed part way calls this, and so does a dispatch whose
    round would not start. An assignment with no round claims its issue and can
    never advance by itself, so the dispatch takes it away rather than leave
    it, and its issue is free to go again.

    The worktree goes first, because git keeps a branch that a worktree has
    checked out. Either command can fail in its turn, and neither failure
    travels. The failure that stopped the dispatch is the one worth reporting,
    and the caller already holds it.

    The record stays where it is. Nothing reads an assignment's record without a
    worktree beside it, so a record left under `assignments/` costs a reader
    nothing.
    """
    with suppress(CommandError):
        remove_worktree(root=state.root, path=record.worktree)
    with suppress(CommandError):
        delete_branch(root=state.root, branch=record.branch)
