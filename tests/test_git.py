import pytest
from conftest import git

from dreamcatcher.commands import CommandError
from dreamcatcher.git import add_worktree, discard_worktree, fetch

BRANCH = "dreamcatcher-GH8-20260820-000456"


def session_worktree(root):
    return root / ".dreamcatcher" / "worktrees" / "GH8-20260820-000456"


def test_a_fetch_brings_origins_main_back(cloned):
    git("update-ref", "-d", "refs/remotes/origin/main", cwd=cloned)

    fetch(cloned)

    assert git("rev-parse", "origin/main", cwd=cloned).strip()


def test_a_worktree_lands_where_it_is_asked_for_on_its_own_branch(cloned):
    path = session_worktree(cloned)

    add_worktree(cloned, path, BRANCH)

    assert (path / "README.md").exists()
    assert BRANCH in git("branch", "--list", BRANCH, cwd=cloned)
    assert str(path) in git("worktree", "list", cwd=cloned)


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
    assert str(path) not in git("worktree", "list", cwd=cloned)


def test_discarding_what_was_never_made_leaves_no_complaint(cloned):
    discard_worktree(cloned, session_worktree(cloned), BRANCH)
