"""Recognise a main checkout, and run the Git commands that agent work needs.

Every command here raises CommandError when git refuses, carrying git's own
words, so no caller has to guess what went wrong. What to do about a creation
that failed part way is the caller's, since only the caller knows how far it
got.
"""

from pathlib import Path

from dreamcatcher.commands import CommandError, run_command
from dreamcatcher.errors import ReportableError


def require_main_checkout(*, root: Path) -> None:
    """Refuse a root that is not a repository's main checkout.

    The tool creates worktrees of its own, so it refuses a linked worktree
    as well as a directory outside any repository.
    """
    if not (root / ".git").is_dir():
        raise ReportableError(
            f"Start dreamcatcher from a repository's main checkout. {root} is not one."
        )


def read_git_author_identity(*, root: Path) -> str:
    """Return the name and email that a commit in the checkout at root would carry.

    When Git has no identity to use, its CommandError says how to set one.
    """
    # Git follows the identity with the commit time and its zone.
    return run_command(
        program="git", arguments=["var", "GIT_AUTHOR_IDENT"], cwd=root
    ).rsplit(maxsplit=2)[0]


def is_file_on_main(*, root: Path, name: str) -> bool:
    """Return whether origin/main holds the named file as the checkout at root has it.

    Git reads the file as it would commit it, so a checkout that writes its line
    endings as CRLF still matches.
    """
    try:
        on_main = run_command(
            program="git",
            arguments=["rev-parse", "--verify", "--quiet", f"origin/main:{name}"],
            cwd=root,
        )
    except CommandError:
        return False
    return on_main == run_command(
        program="git", arguments=["hash-object", "--", name], cwd=root
    )


def fetch_main(*, root: Path) -> None:
    """Bring origin's main branch up to date in the checkout at root."""
    run_command(program="git", arguments=["fetch", "origin", "main"], cwd=root)


def add_worktree(*, root: Path, path: Path, branch: str) -> None:
    """Create a worktree at path, on a new branch cut from origin/main."""
    run_command(
        program="git",
        arguments=["worktree", "add", "-b", branch, str(path), "origin/main"],
        cwd=root,
    )


def add_detached_worktree(*, root: Path, path: Path) -> None:
    """Create a detached worktree at origin/main."""
    run_command(
        program="git",
        arguments=["worktree", "add", "--detach", str(path), "origin/main"],
        cwd=root,
    )


def refresh_detached_worktree(*, root: Path, worktree: Path) -> str:
    """Move a detached worktree to fetched main and return its revision.

    Discard every local change and commit before moving it.
    """
    if not is_linked_worktree(path=worktree):
        raise ReportableError(
            f"Could not refresh detached worktree at {worktree}: "
            "it is not a linked worktree."
        )
    fetch_main(root=root)
    run_command(program="git", arguments=["clean", "-ffdx"], cwd=worktree)
    run_command(
        program="git",
        arguments=["checkout", "--force", "--detach", "origin/main"],
        cwd=worktree,
    )
    _refresh_initialized_submodules(worktree=worktree)
    return _read_worktree_revision(worktree=worktree)


def _refresh_initialized_submodules(*, worktree: Path) -> None:
    """Discard local state from every initialized submodule recursively."""
    listed = run_command(
        program="git", arguments=["ls-files", "--stage", "-z"], cwd=worktree
    )
    for entry in listed.split("\0"):
        if not entry:
            continue
        metadata, relative_path = entry.split("\t", maxsplit=1)
        mode, revision, _ = metadata.split()
        if mode != "160000":
            continue
        submodule = worktree / relative_path
        if not (submodule / ".git").exists():
            continue
        try:
            run_command(
                program="git",
                arguments=["cat-file", "-e", f"{revision}^{{commit}}"],
                cwd=submodule,
            )
        except CommandError:
            run_command(program="git", arguments=["fetch", "origin"], cwd=submodule)
        run_command(program="git", arguments=["clean", "-ffdx"], cwd=submodule)
        run_command(
            program="git",
            arguments=["checkout", "--force", "--detach", revision],
            cwd=submodule,
        )
        _refresh_initialized_submodules(worktree=submodule)


def is_linked_worktree(*, path: Path) -> bool:
    """Return whether the path is a linked worktree."""
    return (path / ".git").is_file()


def _read_worktree_revision(*, worktree: Path) -> str:
    """Return the exact commit checked out in a worktree."""
    return run_command(
        program="git", arguments=["rev-parse", "HEAD"], cwd=worktree
    ).strip()


def read_worktree_branch(*, worktree: Path) -> str:
    """Return the branch checked out in an assignment worktree."""
    return run_command(
        program="git", arguments=["branch", "--show-current"], cwd=worktree
    ).strip()


def has_commits_since_main(*, worktree: Path) -> bool:
    """Return whether the worktree's branch has moved beyond origin/main."""
    count = run_command(
        program="git",
        arguments=["rev-list", "--count", "origin/main..HEAD"],
        cwd=worktree,
    )
    return int(count) > 0


def make_empty_commit(*, worktree: Path, message: str) -> None:
    """Make an empty placeholder commit without running repository hooks.

    The commit gives the draft pull request a branch but holds no files for the
    hooks to check. The agent's later commits still run the hooks.
    """
    run_command(
        program="git",
        arguments=[
            "-c",
            "user.name=dreamcatcher",
            "-c",
            "user.email=noreply@github.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "--allow-empty",
            "--message",
            message,
        ],
        cwd=worktree,
    )


def push_branch(*, root: Path, branch: str) -> None:
    """Push the placeholder branch to origin and set its upstream.

    The assignment setup skips repository hooks because no agent work has
    started. The agent's later pushes still run the hooks.
    """
    run_command(
        program="git",
        arguments=["push", "--no-verify", "--set-upstream", "origin", branch],
        cwd=root,
    )


def remove_worktree(*, root: Path, path: Path) -> None:
    """Remove the worktree at path, whatever is left in it."""
    run_command(
        program="git",
        arguments=["worktree", "remove", "--force", str(path)],
        cwd=root,
    )


def delete_branch(*, root: Path, branch: str) -> None:
    """Delete the branch, merged or not.

    Git keeps a branch that a worktree has checked out, so remove that worktree
    first.
    """
    run_command(
        program="git",
        arguments=["branch", "--delete", "--force", branch],
        cwd=root,
    )
