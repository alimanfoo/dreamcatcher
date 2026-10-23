from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import commit, run_git

from dreamcatcher.commands import CommandError
from dreamcatcher.git import (
    _add_detached_worktree,
    _read_worktree_revision,
    add_worktree,
    delete_branch,
    fetch_main,
    has_commits_since_main,
    make_empty_commit,
    push_branch,
    refresh_detached_worktree,
    remove_worktree,
)

BRANCH = "dreamcatcher-GH8-20260820-000456"


def compose_assignment_worktree(*, root):
    return root / ".dreamcatcher" / "worktrees" / "GH8-20260820-000456"


def list_worktrees(*, root):
    """The path of every worktree of the checkout at root.

    git prints a path with forward slashes on Windows too, so these come back as
    paths rather than as text. Comparing the text would pass whatever git said.
    """
    listed = run_git(arguments=["worktree", "list", "--porcelain"], cwd=root)
    return [
        Path(line.removeprefix("worktree "))
        for line in listed.splitlines()
        if line.startswith("worktree ")
    ]


def read_checked_out_branch(*, worktree) -> str:
    """Return the branch checked out in a worktree, or nothing when detached."""
    return run_git(arguments=["branch", "--show-current"], cwd=worktree).strip()


def test_a_fetch_brings_origins_main_back(cloned_repo):
    run_git(arguments=["update-ref", "-d", "refs/remotes/origin/main"], cwd=cloned_repo)

    fetch_main(root=cloned_repo)

    assert run_git(arguments=["rev-parse", "origin/main"], cwd=cloned_repo).strip()


def test_a_worktree_lands_where_it_is_asked_for_on_its_own_branch(cloned_repo):
    path = compose_assignment_worktree(root=cloned_repo)

    add_worktree(root=cloned_repo, path=path, branch=BRANCH)

    assert (path / "README.md").exists()
    assert BRANCH in run_git(arguments=["branch", "--list", BRANCH], cwd=cloned_repo)
    assert path in list_worktrees(root=cloned_repo)
    assert read_checked_out_branch(worktree=path) == BRANCH


def test_a_detached_worktree_lands_at_origins_main_revision(cloned_repo):
    path = cloned_repo / ".dreamcatcher" / "detached-worktree"

    _add_detached_worktree(root=cloned_repo, path=path)

    assert path in list_worktrees(root=cloned_repo)
    assert read_checked_out_branch(worktree=path) == ""
    assert (
        _read_worktree_revision(worktree=path)
        == run_git(arguments=["rev-parse", "origin/main"], cwd=cloned_repo).strip()
    )


def test_a_clean_detached_worktree_refreshes_to_fetched_main(cloned_repo):
    path = cloned_repo / ".dreamcatcher" / "detached-worktree"
    _add_detached_worktree(root=cloned_repo, path=path)
    earlier_revision = _read_worktree_revision(worktree=path)
    (cloned_repo / "README.md").write_bytes(b"what changed\n")
    commit(path=cloned_repo, message="change main")
    run_git(arguments=["push", "origin", "main"], cwd=cloned_repo)

    revision = refresh_detached_worktree(root=cloned_repo, worktree=path)

    assert revision != earlier_revision
    assert (
        revision
        == run_git(arguments=["rev-parse", "origin/main"], cwd=cloned_repo).strip()
    )
    assert _read_worktree_revision(worktree=path) == revision
    assert (path / "README.md").read_text(encoding="utf-8") == "what changed\n"


def test_a_refresh_discards_non_conflicting_local_changes(cloned_repo):
    path = cloned_repo / ".dreamcatcher" / "detached-worktree"
    _add_detached_worktree(root=cloned_repo, path=path)
    earlier_revision = _read_worktree_revision(worktree=path)
    unexpected = path / "unexpected.txt"
    unexpected.write_bytes(b"discard this\n")
    (cloned_repo / "README.md").write_bytes(b"what changed\n")
    commit(path=cloned_repo, message="change main")
    run_git(arguments=["push", "origin", "main"], cwd=cloned_repo)

    revision = refresh_detached_worktree(root=cloned_repo, worktree=path)

    assert revision != earlier_revision
    assert not unexpected.exists()
    assert (path / "README.md").read_text(encoding="utf-8") == "what changed\n"


def test_a_refresh_discards_a_conflicting_local_change(cloned_repo):
    path = cloned_repo / ".dreamcatcher" / "detached-worktree"
    _add_detached_worktree(root=cloned_repo, path=path)
    earlier_revision = _read_worktree_revision(worktree=path)
    readme = path / "README.md"
    readme.write_bytes(b"local experiment\n")
    (cloned_repo / "README.md").write_bytes(b"what main holds now\n")
    commit(path=cloned_repo, message="change main")
    run_git(arguments=["push", "origin", "main"], cwd=cloned_repo)

    revision = refresh_detached_worktree(root=cloned_repo, worktree=path)

    assert revision != earlier_revision
    assert readme.read_text(encoding="utf-8") == "what main holds now\n"


def test_a_missing_worktree_is_added_at_fetched_main(cloned_repo):
    path = cloned_repo / ".dreamcatcher" / "detached-worktree"
    (cloned_repo / "README.md").write_bytes(b"what changed\n")
    commit(path=cloned_repo, message="change main")
    run_git(arguments=["push", "origin", "main"], cwd=cloned_repo)

    revision = refresh_detached_worktree(root=cloned_repo, worktree=path)

    assert path in list_worktrees(root=cloned_repo)
    assert read_checked_out_branch(worktree=path) == ""
    assert (
        revision
        == run_git(arguments=["rev-parse", "origin/main"], cwd=cloned_repo).strip()
    )
    assert (path / "README.md").read_text(encoding="utf-8") == "what changed\n"


def test_a_refresh_discards_an_unexpected_detached_commit(cloned_repo):
    path = cloned_repo / ".dreamcatcher" / "detached-worktree"
    _add_detached_worktree(root=cloned_repo, path=path)
    unexpected_file = path / "unexpected.txt"
    unexpected_file.write_bytes(b"local file\n")
    (path / "README.md").write_bytes(b"local change\n")
    commit(path=path, message="unexpected work")
    unexpected = _read_worktree_revision(worktree=path)

    revision = refresh_detached_worktree(root=cloned_repo, worktree=path)

    assert revision != unexpected
    assert (
        revision
        == run_git(arguments=["rev-parse", "origin/main"], cwd=cloned_repo).strip()
    )
    assert _read_worktree_revision(worktree=path) == revision
    assert not unexpected_file.exists()
    assert (path / "README.md").read_text(encoding="utf-8") == "what the seed holds\n"


def test_a_refresh_discards_changes_inside_a_submodule(cloned_repo, tmp_path):
    source = tmp_path / "dependency-source"
    run_git(arguments=["init", "--initial-branch=main", str(source)], cwd=tmp_path)
    (source / "tracked.txt").write_bytes(b"recorded\n")
    commit(path=source, message="seed dependency")
    run_git(
        arguments=[
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(source),
            "dependency",
        ],
        cwd=cloned_repo,
    )
    commit(path=cloned_repo, message="add dependency")
    run_git(arguments=["push", "origin", "main"], cwd=cloned_repo)
    path = cloned_repo / ".dreamcatcher" / "detached-worktree"
    _add_detached_worktree(root=cloned_repo, path=path)
    run_git(
        arguments=[
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
        ],
        cwd=path,
    )
    dependency = path / "dependency"
    (dependency / "tracked.txt").write_bytes(b"local change\n")
    unexpected = dependency / "unexpected.txt"
    unexpected.write_bytes(b"local file\n")
    commit(path=dependency, message="unexpected dependency work")
    untracked = dependency / "untracked.txt"
    untracked.write_bytes(b"untracked\n")
    (source / "tracked.txt").write_bytes(b"advanced\n")
    commit(path=source, message="advance dependency")
    advanced = run_git(arguments=["rev-parse", "HEAD"], cwd=source).strip()
    run_git(arguments=["fetch", "origin"], cwd=cloned_repo / "dependency")
    run_git(arguments=["checkout", advanced], cwd=cloned_repo / "dependency")
    commit(path=cloned_repo, message="advance dependency")
    run_git(arguments=["push", "origin", "main"], cwd=cloned_repo)
    run_git(arguments=["config", "fetch.recurseSubmodules", "false"], cwd=cloned_repo)
    with pytest.raises(CommandError):
        run_git(arguments=["cat-file", "-e", f"{advanced}^{{commit}}"], cwd=dependency)

    refresh_detached_worktree(root=cloned_repo, worktree=path)

    assert (dependency / "tracked.txt").read_text(encoding="utf-8") == "advanced\n"
    assert not unexpected.exists()
    assert not untracked.exists()


def test_a_refresh_discards_an_ignored_file(cloned_repo):
    ignored = "generated.txt"
    (cloned_repo / ".gitignore").write_bytes(f"{ignored}\n".encode())
    commit(path=cloned_repo, message="ignore generated file")
    run_git(arguments=["push", "origin", "main"], cwd=cloned_repo)
    path = cloned_repo / ".dreamcatcher" / "detached-worktree"
    _add_detached_worktree(root=cloned_repo, path=path)
    generated = path / ignored
    generated.write_bytes(b"discard this\n")
    (cloned_repo / "README.md").write_bytes(b"what changed\n")
    commit(path=cloned_repo, message="change main")
    run_git(arguments=["push", "origin", "main"], cwd=cloned_repo)

    refresh_detached_worktree(root=cloned_repo, worktree=path)

    assert not generated.exists()
    assert (path / "README.md").read_text(encoding="utf-8") == "what changed\n"


def test_a_worktree_git_refuses_says_what_git_said(cloned_repo):
    path = compose_assignment_worktree(root=cloned_repo)
    add_worktree(root=cloned_repo, path=path, branch=BRANCH)

    with pytest.raises(CommandError) as error:
        add_worktree(root=cloned_repo, path=path, branch=BRANCH)

    assert "git worktree add" in str(error.value)
    assert BRANCH in str(error.value)


def test_an_empty_commit_moves_the_assignment_branch_beyond_main(cloned_repo):
    path = compose_assignment_worktree(root=cloned_repo)
    add_worktree(root=cloned_repo, path=path, branch=BRANCH)
    run_git(arguments=["config", "user.name", "A User"], cwd=path)
    run_git(arguments=["config", "user.email", "a.user@example.com"], cwd=path)
    run_git(arguments=["config", "commit.gpgsign", "true"], cwd=path)

    assert not has_commits_since_main(worktree=path)

    make_empty_commit(worktree=path, message="GH8 [skip ci]")

    assert has_commits_since_main(worktree=path)
    assert run_git(arguments=["log", "-1", "--format=%an <%ae>"], cwd=path).strip() == (
        "A User <a.user@example.com>"
    )
    assert run_git(arguments=["log", "-1", "--format=%s"], cwd=path).strip() == (
        "GH8 [skip ci]"
    )


def test_an_empty_commit_skips_repository_hooks(tmp_path, monkeypatch):
    command = Mock()
    monkeypatch.setattr("dreamcatcher.git.run_command", command)

    make_empty_commit(worktree=tmp_path, message="GH8")

    command.assert_called_once_with(
        program="git",
        arguments=[
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "--allow-empty",
            "--message",
            "GH8",
        ],
        cwd=tmp_path,
    )


def test_a_pushed_assignment_branch_is_visible_at_origin(cloned_repo):
    path = compose_assignment_worktree(root=cloned_repo)
    add_worktree(root=cloned_repo, path=path, branch=BRANCH)
    make_empty_commit(worktree=path, message="GH8")

    push_branch(root=cloned_repo, branch=BRANCH)

    remote = run_git(
        arguments=["ls-remote", "--heads", "origin", BRANCH], cwd=cloned_repo
    )
    assert f"refs/heads/{BRANCH}" in remote


def test_publishing_the_placeholder_branch_skips_repository_hooks(
    tmp_path, monkeypatch
):
    command = Mock()
    monkeypatch.setattr("dreamcatcher.git.run_command", command)

    push_branch(root=tmp_path, branch=BRANCH)

    command.assert_called_once_with(
        program="git",
        arguments=["push", "--no-verify", "--set-upstream", "origin", BRANCH],
        cwd=tmp_path,
    )


def test_an_assignment_worktree_can_push_to_origin(cloned_repo):
    path = compose_assignment_worktree(root=cloned_repo)
    add_worktree(root=cloned_repo, path=path, branch=BRANCH)
    make_empty_commit(worktree=path, message="GH8")

    run_git(arguments=["push", "origin", BRANCH], cwd=path)

    remote = run_git(
        arguments=["ls-remote", "--heads", "origin", BRANCH], cwd=cloned_repo
    )
    assert f"refs/heads/{BRANCH}" in remote


def test_a_removed_worktree_leaves_the_disk_and_the_list(cloned_repo):
    path = compose_assignment_worktree(root=cloned_repo)
    add_worktree(root=cloned_repo, path=path, branch=BRANCH)

    remove_worktree(root=cloned_repo, path=path)

    assert not path.exists()
    assert path not in list_worktrees(root=cloned_repo)


def test_removing_a_worktree_that_was_never_made_says_what_git_said(cloned_repo):
    with pytest.raises(CommandError) as error:
        remove_worktree(
            root=cloned_repo, path=compose_assignment_worktree(root=cloned_repo)
        )

    assert "git worktree remove" in str(error.value)


def test_a_deleted_branch_leaves_the_branch_list(cloned_repo):
    path = compose_assignment_worktree(root=cloned_repo)
    add_worktree(root=cloned_repo, path=path, branch=BRANCH)
    remove_worktree(root=cloned_repo, path=path)

    delete_branch(root=cloned_repo, branch=BRANCH)

    assert run_git(arguments=["branch", "--list", BRANCH], cwd=cloned_repo) == ""


def test_a_branch_a_worktree_holds_is_not_deleted_quietly(cloned_repo):
    add_worktree(
        root=cloned_repo,
        path=compose_assignment_worktree(root=cloned_repo),
        branch=BRANCH,
    )

    with pytest.raises(CommandError) as error:
        delete_branch(root=cloned_repo, branch=BRANCH)

    assert "git branch --delete" in str(error.value)
