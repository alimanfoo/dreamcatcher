"""Create a session for an issue, and read back the ones a repo already has.

A session is one attempt at one issue. It gets a key of its own: the issue's
number, and the time the attempt started. That key names its branch, its
worktree, and the directory that holds its own files. So three worktrees for
one issue read as three attempts at one thing, each with its own pull request.

Nothing here decides which issue to dispatch, or when. A caller that has decided
asks for the session.
"""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dreamcatcher import prompts
from dreamcatcher.commands import CommandError
from dreamcatcher.config import DispatchMapping, Harness
from dreamcatcher.documents import Document, read_json, write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import add_worktree, delete_branch, fetch, remove_worktree
from dreamcatcher.rounds import RoundRecord, Workspace, read_round_records
from dreamcatcher.state import StateDirectory

# What a session's branch is called, before its key. The prefix keeps
# dreamcatcher's own branches apart from everyone else's, and from the branches
# that the catcher it replaces left behind.
BRANCH_PREFIX = "dreamcatcher-"

# The file in a session's directory saying what the session was dispatched
# with.
RECORD = "session.json"

# The directory in a session's directory holding a directory per round.
ROUNDS = "rounds"


class SessionRecord(Document):
    """The issue a session works on, and the settings it runs its rounds with.

    The dispatch settles all of these, and no later round changes any of
    them. Every round reads them from here rather than from the config, so
    editing the config while a session is in flight cannot reach that
    session.
    """

    issue: int
    label: str
    branch: str
    worktree: Path
    harness: Harness
    model: str
    effort: str
    prompt: str


@dataclass(frozen=True)
class Session:
    """One attempt at one issue, as it stands.

    The directory is where the session keeps its own files, and it is named by
    the session's key, so the key is written down in one place alone. The
    record says what the dispatch settled, and the rounds are what the session
    has run so far, oldest first.
    """

    directory: Path
    record: SessionRecord
    rounds: list[RoundRecord] = field(default_factory=list)

    @property
    def key(self) -> str:
        """The key that the branch, the worktree and the files all carry."""
        return self.directory.name

    @property
    def next_workspace(self) -> Workspace:
        """Where the session's next round runs, and where it writes.

        Every round runs in the session's worktree, and writes into a
        directory named by the number of the round it is.
        """
        return Workspace(
            self.record.worktree, self.directory / ROUNDS / str(len(self.rounds) + 1)
        )


def read_sessions(state: StateDirectory) -> list[Session]:
    """Return every session the state directory holds, by key.

    A worktree under `worktrees/` is what says a session exists, since that is
    the one place a session of this daemon's can be. The session's own files
    sit under `sessions/`, in a directory the same key names.

    A state directory with no worktrees in it yet holds no sessions, so this
    answers with nothing rather than failing. Anything under `worktrees/` that
    is not a directory is not a worktree, which is what keeps a file a file
    browser left there from reading as a session.

    A worktree whose record is not there is not a session either. A creation
    cuts the worktree and then writes the record, so a daemon that died between
    the two leaves one, and it stands for a session that ran nothing and opened
    no pull request. Reading it as no session leaves its issue free to go
    again, and leaves the worktree itself for whoever wants the disk back. A
    record that is there and will not read is another matter, and says so.
    """
    if not state.worktrees.is_dir():
        return []
    directories = [
        state.sessions / worktree.name
        for worktree in sorted(state.worktrees.iterdir())
        if worktree.is_dir()
    ]
    return [
        _read_session(directory)
        for directory in directories
        if (directory / RECORD).exists()
    ]


def create_session(
    state: StateDirectory,
    mapping: DispatchMapping,
    named: Harness,
    issue: int,
    at: datetime,
) -> Session:
    """Create a session for the issue, and return it with no rounds run yet.

    The session runs on the harness that this label and the run settle between
    them, with that harness's own model, effort and prompt template.

    This fetches origin's main first, so the branch starts from main as it is
    now.

    Should anything from the worktree onwards fail, the worktree and the
    branch go away again, so a failed creation leaves neither behind. git
    makes the branch before it reaches the worktree, so an add that failed
    has one to take away. The caller hears the failure that stopped the
    creation, not any failure that removing them hits.
    """
    harness = mapping.choose_harness(named)
    settings = mapping.harness_settings[harness]
    key = f"GH{issue}-{at:%Y%m%d-%H%M%S}"
    record = SessionRecord(
        issue=issue,
        label=mapping.label,
        branch=f"{BRANCH_PREFIX}{key}",
        worktree=state.worktrees / key,
        harness=harness,
        model=settings.model,
        effort=settings.effort,
        prompt=prompts.compose_first_round_prompt(settings.prompt, issue),
    )
    directory = state.sessions / key
    fetch(state.root)
    try:
        add_worktree(state.root, record.worktree, record.branch)
        write_json(record, directory / RECORD)
    except ReportableError:
        _back_out(state.root, record.worktree, record.branch)
        raise
    return Session(directory=directory, record=record)


def _read_session(directory: Path) -> Session:
    """Return the session whose own files sit in this directory."""
    return Session(
        directory=directory,
        record=read_json(SessionRecord, directory / RECORD),
        rounds=read_round_records(directory / ROUNDS),
    )


def _back_out(root: Path, worktree: Path, branch: str) -> None:
    """Take away the worktree and the branch that a failed creation made.

    The worktree goes first, because git keeps a branch that a worktree has
    checked out. Either command can fail in its turn, and neither failure
    travels. The failure that stopped the creation is the one worth reporting,
    and the caller already holds it.
    """
    with suppress(CommandError):
        remove_worktree(root, worktree)
    with suppress(CommandError):
        delete_branch(root, branch)
