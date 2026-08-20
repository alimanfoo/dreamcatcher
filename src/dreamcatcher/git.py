"""Run the git commands that make and unmake a session's worktree."""

from contextlib import suppress
from pathlib import Path

from dreamcatcher.commands import CommandError, run


def fetch(root: Path) -> None:
    """Bring origin's main branch up to date in the checkout at root."""
    run("git", "fetch", "origin", "main", cwd=root)


def add_worktree(root: Path, path: Path, branch: str) -> None:
    """Create a worktree at path, on a new branch cut from origin/main."""
    run("git", "worktree", "add", "-b", branch, str(path), "origin/main", cwd=root)


def discard_worktree(root: Path, path: Path, branch: str) -> None:
    """Remove the worktree at path and delete its branch, leaving nothing behind.

    This backs out a creation that failed part way, so either half may never
    have been made. A half that is already gone is the outcome this wants. The
    caller is reporting the failure that led here, so neither removal raises.
    """
    with suppress(CommandError):
        run("git", "worktree", "remove", "--force", str(path), cwd=root)
    with suppress(CommandError):
        run("git", "branch", "--delete", "--force", branch, cwd=root)
