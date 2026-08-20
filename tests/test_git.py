from pathlib import Path

import pytest
from conftest import git

from dreamcatcher.commands import CommandError
from dreamcatcher.git import add_worktree, discard_worktree, fetch

BRANCH = "dreamcatcher-GH8-20260820-000456"


def session_worktree(root):
    return root / ".dreamcatcher" / "worktrees" / "GH8-20260820-000456"


def worktrees(root):
    """The path of every worktree of the checkout at root.

    git prints a path with forward slashes on Windows too, so these come back as
    paths rather than as text. Comparing the text would pass whatever git said.
    """
    listed = git("worktree", "list", "--porcelain", cwd=root)
    return [
        Path(line.removeprefix("worktree "))
        for line in listed.splitlines()
        if line.startswith("worktree ")
    ]


def test_a_fetch_brings_origins_main_back(cloned):
    git("update-ref", "-d", "refs/remotes/origin/main", cwd=cloned)

    fetch(cloned)

    assert git("rev-parse", "origin/main", cwd=cloned).strip()


def test_a_worktree_lands_where_it_is_asked_for_on_its_own_branch(cloned):
    path = session_worktree(cloned)

    add_worktree(cloned, path, BRANCH)

    assert (path / "README.md").exists()
    assert BRANCH in git("branch", "--list", BRANCH, cwd=cloned)
    assert path in worktrees(cloned)


def test_a_worktree_git_refuses_says_what_git_said(cloned):
    path = session_worktree(cloned)
    add_worktree(cloned, path, BRANCH)

    with pytest.raises(CommandError) as error:
        add_worktree(cloned, path, BRANCH)

    assert "git worktree add" in str(error.value)
    assert BRANCH in str(error.value)


def test_discarding_a_worktree_takes_its_branch_with_it(cloned):
    path = session_worktree(cloned)
    add_worktree(cloned, path, BRANCH)

    discard_worktree(cloned, path, BRANCH)

    assert not path.exists()
    assert git("branch", "--list", BRANCH, cwd=cloned) == ""
    assert path not in worktrees(cloned)


def test_discarding_what_was_never_made_leaves_no_complaint(cloned):
    discard_worktree(cloned, session_worktree(cloned), BRANCH)
