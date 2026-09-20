import pytest
from conftest import git

from dreamcatcher.errors import ReportableError
from dreamcatcher.state import StateDirectory


def test_bootstrap_creates_a_directory_that_ignores_itself(repo):
    state = StateDirectory(root=repo)

    legacy_state_hint = state.bootstrap()

    assert (state.path.parent / ".gitignore").read_text(encoding="utf-8") == "*\n"
    assert git(arguments=["status", "--porcelain"], cwd=repo) == ""
    assert legacy_state_hint is None


def test_bootstrap_heals_a_deleted_gitignore(repo):
    state = StateDirectory(root=repo)
    state.bootstrap()
    (state.path.parent / ".gitignore").unlink()

    state.bootstrap()

    assert git(arguments=["status", "--porcelain"], cwd=repo) == ""


def test_bootstrap_says_so_when_a_file_sits_where_the_directory_goes(repo):
    state = StateDirectory(root=repo)
    state.path.parent.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(ReportableError, match="cannot write"):
        state.bootstrap()


def test_bootstrap_reports_state_from_an_earlier_format(repo):
    state = StateDirectory(root=repo)
    legacy_path = state.path.parent / "repository"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"legacy")

    legacy_state_hint = state.bootstrap()

    assert legacy_state_hint == (
        "Legacy state in .dreamcatcher/ belongs to an earlier format and can be "
        "deleted."
    )


def test_bootstrap_ignores_current_state_and_the_shared_lock(repo):
    state = StateDirectory(root=repo)
    state.path.mkdir(parents=True)
    state.lock.write_bytes(b"123\n")

    assert state.bootstrap() is None


def test_the_daemon_files_use_the_versioned_root_and_shared_lock(tmp_path):
    state = StateDirectory(root=tmp_path)

    assert state.path == tmp_path / ".dreamcatcher" / "v3"
    assert state.lock == state.path.parent / "daemon.pid"
    assert state.repository == state.path / "repository"
    assert state.max_agents == state.path / "max-agents"
    assert state.scheduler_record == state.path / "scheduler.json"
    assert state.worktrees == state.path / "worktrees"
    assert state.assignments == state.path / "assignments"


def test_a_path_the_checkout_holds_reads_from_the_checkout(tmp_path):
    state = StateDirectory(root=tmp_path)

    assert state.describe_path(path=state.worktrees / "GH13") == (
        ".dreamcatcher/v3/worktrees/GH13"
    )


def test_a_path_the_checkout_does_not_hold_reads_whole(tmp_path):
    state = StateDirectory(root=tmp_path)
    elsewhere = tmp_path.parent / "another checkout" / "worktrees" / "GH13"

    assert state.describe_path(path=elsewhere) == elsewhere.as_posix()
