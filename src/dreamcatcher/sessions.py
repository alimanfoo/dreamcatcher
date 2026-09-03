"""Cut a session for an issue, and record what its dispatch fixed.

A session is one attempt at one issue. It gets a key of its own, the issue's
number and the time the attempt started, and that key names its branch, its
worktree, and the directory holding its own files. So three worktrees for one
issue read as three attempts at one thing, each with its own pull request.

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
# the catcher it replaces left behind.
BRANCH_PREFIX = "dreamcatcher-"

# The file in a session's directory holding what its dispatch fixed.
RECORD = "session.json"


class Session(Document):
    """What one session's dispatch fixed, which nothing changes afterwards.

    Every round of the session reads these rather than the config, so editing
    the config while a session is in flight cannot reach it.
    """

    key: str
    issue: int
    label: str
    branch: str
    worktree: Path
    harness: Harness
    model: str
    effort: str
    prompt: str


def create(
    state: StateDirectory,
    mapping: DispatchMapping,
    named: Harness,
    issue: int,
    at: datetime,
) -> Session:
    """Cut a session for the issue, and return what its dispatch fixed.

    The session runs on the harness that the label and the harness the run
    named settle between them, with that harness's own model, effort and prompt
    template.

    The branch is cut from origin's main as it is now, so the fetch comes
    first. Should the record then fail to land, the worktree and the branch go
    with it, and the failure that started the back-out is the one reported.
    """
    harness = mapping.choose_harness(named)
    settings = mapping.harness_settings[harness]
    key = f"GH{issue}-{at:%Y%m%d-%H%M%S}"
    session = Session(
        key=key,
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
    add_worktree(state.root, session.worktree, session.branch)
    try:
        write_json(session, state.sessions / key / RECORD)
    except ReportableError:
        _back_out(state.root, session.worktree, session.branch)
        raise
    return session


def _back_out(root: Path, worktree: Path, branch: str) -> None:
    """Take away the worktree and the branch that a failed creation made.

    The worktree goes first, because git keeps a branch that a worktree has
    checked out. Either command can fail in its turn, and neither failure
    travels: the one worth reporting is the failure that started the back-out.
    """
    with suppress(CommandError):
        remove_worktree(root, worktree)
    with suppress(CommandError):
        delete_branch(root, branch)
