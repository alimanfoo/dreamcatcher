from pathlib import Path

import pytest
from conftest import commit, git

from dreamcatcher.commands import CommandError
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    add_detached_worktree,
    add_worktree,
    delete_branch,
    fetch_main,
    has_commits_since_main,
    make_empty_commit,
    push_branch,
    read_worktree_branch,
    read_worktree_revision,
    refresh_detached_worktree,
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

    fetch_main(root=cloned)

    assert git(arguments=["rev-parse", "origin/main"], cwd=cloned).strip()


def test_a_worktree_lands_where_it_is_asked_for_on_its_own_branch(cloned):
    path = assignment_worktree(root=cloned)

    add_worktree(root=cloned, path=path, branch=BRANCH)

    assert (path / "README.md").exists()
    assert BRANCH in git(arguments=["branch", "--list", BRANCH], cwd=cloned)
    assert path in worktrees(root=cloned)
    assert read_worktree_branch(worktree=path) == BRANCH


def test_a_detached_worktree_lands_at_origins_main_revision(cloned):
    path = cloned / ".dreamcatcher" / "v3" / "conversation-worktrees" / "GH8"

    add_detached_worktree(root=cloned, path=path)

    assert path in worktrees(root=cloned)
    assert read_worktree_branch(worktree=path) == ""
    assert (
        read_worktree_revision(worktree=path)
        == git(arguments=["rev-parse", "origin/main"], cwd=cloned).strip()
    )


def test_a_clean_detached_worktree_refreshes_to_fetched_main(cloned):
    path = cloned / ".dreamcatcher" / "v3" / "conversation-worktrees" / "GH8"
    add_detached_worktree(root=cloned, path=path)
    earlier_revision = read_worktree_revision(worktree=path)
    (cloned / "README.md").write_bytes(b"what changed\n")
    commit(path=cloned, message="change main")
    git(arguments=["push", "origin", "main"], cwd=cloned)

    revision = refresh_detached_worktree(root=cloned, worktree=path)

    assert revision != earlier_revision
    assert revision == git(arguments=["rev-parse", "origin/main"], cwd=cloned).strip()
    assert read_worktree_revision(worktree=path) == revision
    assert (path / "README.md").read_text(encoding="utf-8") == "what changed\n"


def test_a_refresh_discards_non_conflicting_local_changes(cloned):
    path = cloned / ".dreamcatcher" / "v3" / "conversation-worktrees" / "GH8"
    add_detached_worktree(root=cloned, path=path)
    earlier_revision = read_worktree_revision(worktree=path)
    unexpected = path / "unexpected.txt"
    unexpected.write_bytes(b"discard this\n")
    (cloned / "README.md").write_bytes(b"what changed\n")
    commit(path=cloned, message="change main")
    git(arguments=["push", "origin", "main"], cwd=cloned)

    revision = refresh_detached_worktree(root=cloned, worktree=path)

    assert revision != earlier_revision
    assert not unexpected.exists()
    assert (path / "README.md").read_text(encoding="utf-8") == "what changed\n"


def test_a_refresh_discards_a_conflicting_local_change(cloned):
    path = cloned / ".dreamcatcher" / "v3" / "conversation-worktrees" / "GH8"
    add_detached_worktree(root=cloned, path=path)
    earlier_revision = read_worktree_revision(worktree=path)
    readme = path / "README.md"
    readme.write_bytes(b"local experiment\n")
    (cloned / "README.md").write_bytes(b"what main holds now\n")
    commit(path=cloned, message="change main")
    git(arguments=["push", "origin", "main"], cwd=cloned)

    revision = refresh_detached_worktree(root=cloned, worktree=path)

    assert revision != earlier_revision
    assert readme.read_text(encoding="utf-8") == "what main holds now\n"


def test_a_missing_linked_worktree_is_not_refreshed(cloned):
    path = cloned / ".dreamcatcher" / "v3" / "conversation-worktrees" / "GH8"
    path.mkdir(parents=True)

    with pytest.raises(ReportableError, match="it is not a linked worktree"):
        refresh_detached_worktree(root=cloned, worktree=path)

    assert read_worktree_branch(worktree=cloned) == "main"


def test_a_refresh_discards_an_unexpected_detached_commit(cloned):
    path = cloned / ".dreamcatcher" / "v3" / "conversation-worktrees" / "GH8"
    add_detached_worktree(root=cloned, path=path)
    unexpected_file = path / "unexpected.txt"
    unexpected_file.write_bytes(b"local file\n")
    (path / "README.md").write_bytes(b"local change\n")
    commit(path=path, message="unexpected work")
    unexpected = read_worktree_revision(worktree=path)

    revision = refresh_detached_worktree(root=cloned, worktree=path)

    assert revision != unexpected
    assert revision == git(arguments=["rev-parse", "origin/main"], cwd=cloned).strip()
    assert read_worktree_revision(worktree=path) == revision
    assert not unexpected_file.exists()
    assert (path / "README.md").read_text(encoding="utf-8") == "what the seed holds\n"


def test_a_refresh_discards_changes_inside_a_submodule(cloned, tmp_path):
    source = tmp_path / "dependency-source"
    git(arguments=["init", "--initial-branch=main", str(source)], cwd=tmp_path)
    (source / "tracked.txt").write_bytes(b"recorded\n")
    commit(path=source, message="seed dependency")
    git(
        arguments=[
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(source),
            "dependency",
        ],
        cwd=cloned,
    )
    commit(path=cloned, message="add dependency")
    git(arguments=["push", "origin", "main"], cwd=cloned)
    path = cloned / ".dreamcatcher" / "v3" / "conversation-worktrees" / "GH8"
    add_detached_worktree(root=cloned, path=path)
    git(
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

    refresh_detached_worktree(root=cloned, worktree=path)

    assert (dependency / "tracked.txt").read_text(encoding="utf-8") == "recorded\n"
    assert not unexpected.exists()
    assert not untracked.exists()


def test_a_refresh_discards_an_ignored_file(cloned):
    ignored = "generated.txt"
    (cloned / ".gitignore").write_bytes(f"{ignored}\n".encode())
    commit(path=cloned, message="ignore generated file")
    git(arguments=["push", "origin", "main"], cwd=cloned)
    path = cloned / ".dreamcatcher" / "v3" / "conversation-worktrees" / "GH8"
    add_detached_worktree(root=cloned, path=path)
    generated = path / ignored
    generated.write_bytes(b"discard this\n")
    (cloned / "README.md").write_bytes(b"what changed\n")
    commit(path=cloned, message="change main")
    git(arguments=["push", "origin", "main"], cwd=cloned)

    refresh_detached_worktree(root=cloned, worktree=path)

    assert not generated.exists()
    assert (path / "README.md").read_text(encoding="utf-8") == "what changed\n"


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
    git(arguments=["config", "user.name", ""], cwd=path)
    git(arguments=["config", "user.email", ""], cwd=path)
    git(arguments=["config", "commit.gpgsign", "true"], cwd=path)

    assert not has_commits_since_main(worktree=path)

    make_empty_commit(worktree=path, message="GH8")

    assert has_commits_since_main(worktree=path)
    assert git(arguments=["log", "-1", "--format=%an <%ae>"], cwd=path).strip() == (
        "dreamcatcher <noreply@github.com>"
    )


def test_a_pushed_assignment_branch_is_visible_at_origin(cloned):
    path = assignment_worktree(root=cloned)
    add_worktree(root=cloned, path=path, branch=BRANCH)
    make_empty_commit(worktree=path, message="GH8")

    push_branch(root=cloned, branch=BRANCH)

    remote = git(arguments=["ls-remote", "--heads", "origin", BRANCH], cwd=cloned)
    assert f"refs/heads/{BRANCH}" in remote


def test_an_assignment_worktree_can_push_to_origin(cloned):
    path = assignment_worktree(root=cloned)
    add_worktree(root=cloned, path=path, branch=BRANCH)
    make_empty_commit(worktree=path, message="GH8")

    git(arguments=["push", "origin", BRANCH], cwd=path)

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
