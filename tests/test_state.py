import pytest
from conftest import git

from dreamcatcher.errors import ReportableError
from dreamcatcher.state import StateDirectory


def test_bootstrap_creates_a_directory_that_ignores_itself(repo):
    state = StateDirectory(root=repo)

    state.bootstrap()

    assert (state.path / ".gitignore").read_text(encoding="utf-8") == "*\n"
    assert git(arguments=["status", "--porcelain"], cwd=repo) == ""


def test_bootstrap_heals_a_deleted_gitignore(repo):
    state = StateDirectory(root=repo)
    state.bootstrap()
    (state.path / ".gitignore").unlink()

    state.bootstrap()

    assert git(arguments=["status", "--porcelain"], cwd=repo) == ""


def test_bootstrap_says_so_when_a_file_sits_where_the_directory_goes(repo):
    state = StateDirectory(root=repo)
    state.path.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(ReportableError, match="cannot write"):
        state.bootstrap()


def test_the_daemon_files_sit_in_the_state_directory(tmp_path):
    state = StateDirectory(root=tmp_path)

    assert state.path == tmp_path / ".dreamcatcher"
    assert state.lock == state.path / "daemon.pid"
    assert state.last_tick == state.path / "last-tick.json"
    assert state.worktrees == state.path / "worktrees"
    assert state.sessions == state.path / "sessions"


def test_a_path_the_checkout_holds_reads_from_the_checkout(tmp_path):
    state = StateDirectory(root=tmp_path)

    assert state.describe_path(path=state.worktrees / "GH13") == (
        ".dreamcatcher/worktrees/GH13"
    )


def test_a_path_the_checkout_does_not_hold_reads_whole(tmp_path):
    state = StateDirectory(root=tmp_path)
    elsewhere = tmp_path.parent / "another checkout" / "worktrees" / "GH13"

    assert state.describe_path(path=elsewhere) == elsewhere.as_posix()
