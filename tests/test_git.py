from pathlib import Path

import pytest
from conftest import git

from dreamcatcher.commands import CommandError
from dreamcatcher.git import (
    add_worktree,
    delete_branch,
    fetch,
    has_commits_since_main,
    make_empty_commit,
    push_branch,
    remove_worktree,
)

BRANCH = "dreamcatcher-GH8-20260820-000456"


def assignment_worktree(*, root):
    return root / ".dreamcatcher" / "worktrees" / "GH8-20260820-000456"


def worktrees(*, root):
    """The path of every worktree of the checkout at root.

    git prints a path with forward slashes on Windows too, so these come back as
    paths rather than as text. Comparing the text would pass whatever git said.
    """
    listed = git(arguments=["worktree", "list", "--porcelain"], cwd=root)
    return [
        Path(line.removeprefix("worktree "))
        for line in listed.splitlines()
        if line.startswith("worktree ")
    ]


def test_a_fetch_brings_origins_main_back(cloned):
    git(arguments=["update-ref", "-d", "refs/remotes/origin/main"], cwd=cloned)

    fetch(root=cloned)

    assert git(arguments=["rev-parse", "origin/main"], cwd=cloned).strip()


def test_a_worktree_lands_where_it_is_asked_for_on_its_own_branch(cloned):
    path = assignment_worktree(root=cloned)

    add_worktree(root=cloned, path=path, branch=BRANCH)

    assert (path / "README.md").exists()
    assert BRANCH in git(arguments=["branch", "--list", BRANCH], cwd=cloned)
    assert path in worktrees(root=cloned)


def test_a_worktree_git_refuses_says_what_git_said(cloned):
    path = assignment_worktree(root=cloned)
    add_worktree(root=cloned, path=path, branch=BRANCH)

    with pytest.raises(CommandError) as error:
        add_worktree(root=cloned, path=path, branch=BRANCH)

    assert "git worktree add" in str(error.value)
    assert BRANCH in str(error.value)


def test_an_empty_commit_moves_the_assignment_branch_beyond_main(cloned):
    path = assignment_worktree(root=cloned)
    add_worktree(root=cloned, path=path, branch=BRANCH)

    assert not has_commits_since_main(worktree=path)

    make_empty_commit(worktree=path, message="GH8")

    assert has_commits_since_main(worktree=path)


def test_a_pushed_assignment_branch_is_visible_at_origin(cloned):
    path = assignment_worktree(root=cloned)
    add_worktree(root=cloned, path=path, branch=BRANCH)
    make_empty_commit(worktree=path, message="GH8")

    push_branch(root=cloned, branch=BRANCH)

    remote = git(arguments=["ls-remote", "--heads", "origin", BRANCH], cwd=cloned)
    assert f"refs/heads/{BRANCH}" in remote


def test_a_removed_worktree_leaves_the_disk_and_the_list(cloned):
    path = assignment_worktree(root=cloned)
    add_worktree(root=cloned, path=path, branch=BRANCH)

    remove_worktree(root=cloned, path=path)

    assert not path.exists()
    assert path not in worktrees(root=cloned)


def test_removing_a_worktree_that_was_never_made_says_what_git_said(cloned):
    with pytest.raises(CommandError) as error:
        remove_worktree(root=cloned, path=assignment_worktree(root=cloned))

    assert "git worktree remove" in str(error.value)


def test_a_deleted_branch_leaves_the_branch_list(cloned):
    path = assignment_worktree(root=cloned)
    add_worktree(root=cloned, path=path, branch=BRANCH)
    remove_worktree(root=cloned, path=path)

    delete_branch(root=cloned, branch=BRANCH)

    assert git(arguments=["branch", "--list", BRANCH], cwd=cloned) == ""


def test_a_branch_a_worktree_holds_is_not_deleted_quietly(cloned):
    add_worktree(root=cloned, path=assignment_worktree(root=cloned), branch=BRANCH)

    with pytest.raises(CommandError) as error:
        delete_branch(root=cloned, branch=BRANCH)

    assert "git branch --delete" in str(error.value)
