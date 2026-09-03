"""Create a session for an issue, and record what its dispatch fixed.

A session is one attempt at one issue. It gets a key of its own: the issue's
number, and the time the attempt started. That key names its branch, its
worktree, and the directory that holds its own files. So three worktrees for
one issue read as three attempts at one thing, each with its own pull request.

Nothing here decides which issue to dispatch, or when. A caller that has decided
asks for the session.
"""

from contextlib import suppress
from datetime import datetime
from pathlib import Path

from dreamcatcher import prompts
from dreamcatcher.commands import CommandError
from dreamcatcher.config import DispatchMapping, Harness
from dreamcatcher.documents import Document, write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import add_worktree, delete_branch, fetch, remove_worktree
from dreamcatcher.state import StateDirectory

# What a session's branch is called, before its key. The prefix keeps
# dreamcatcher's own branches apart from everyone else's, and from the branches
# that the catcher it replaces left behind.
BRANCH_PREFIX = "dreamcatcher-"

# The file in a session's directory holding what its dispatch fixed.
RECORD = "session.json"


class Session(Document):
    """What one session's dispatch fixed, which nothing changes afterwards.

    Every round of the session reads these rather than the config, so editing
    the config while a session is in flight cannot reach it.
    """

    issue: int
    label: str
    branch: str
    worktree: Path
    harness: Harness
    model: str
    effort: str
    prompt: str

    @property
    def key(self) -> str:
        """The key that the branch, the worktree and the files all carry.

        The worktree is the one place it is written down, since it is the
        directory the key names.
        """
        return self.worktree.name


def create(
    state: StateDirectory,
    mapping: DispatchMapping,
    named: Harness,
    issue: int,
    at: datetime,
) -> Session:
    """Create a session for the issue, and return what its dispatch fixed.

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
    session = Session(
        issue=issue,
        label=mapping.label,
        branch=f"{BRANCH_PREFIX}{key}",
        worktree=state.worktrees / key,
        harness=harness,
        model=settings.model,
        effort=settings.effort,
        prompt=prompts.first_round(settings.prompt, issue),
    )
    fetch(state.root)
    try:
        add_worktree(state.root, session.worktree, session.branch)
        write_json(session, state.sessions / key / RECORD)
    except ReportableError:
        _back_out(state.root, session.worktree, session.branch)
        raise
    return session


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
