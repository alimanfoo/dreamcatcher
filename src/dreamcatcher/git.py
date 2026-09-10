"""Run the git commands that make and unmake a session's worktree.

Every one of these raises CommandError when git refuses, carrying git's own
words, so no caller has to guess what went wrong. What to do about a creation
that failed part way is the caller's, since only the caller knows how far it
got.
"""

from pathlib import Path

from dreamcatcher.commands import run


def fetch(root: Path) -> None:
    """Bring origin's main branch up to date in the checkout at root."""
    run(program="git", arguments=["fetch", "origin", "main"], cwd=root)


def add_worktree(root: Path, path: Path, branch: str) -> None:
    """Create a worktree at path, on a new branch cut from origin/main."""
    run(
        program="git",
        arguments=["worktree", "add", "-b", branch, str(path), "origin/main"],
        cwd=root,
    )


def remove_worktree(root: Path, path: Path) -> None:
    """Remove the worktree at path, whatever is left in it."""
    run(
        program="git",
        arguments=["worktree", "remove", "--force", str(path)],
        cwd=root,
    )


def delete_branch(root: Path, branch: str) -> None:
    """Delete the branch, merged or not.

    git keeps a branch a worktree has checked out, so remove that worktree
    first.
    """
    run(
        program="git",
        arguments=["branch", "--delete", "--force", branch],
        cwd=root,
    )
