from conftest import git

from dreamcatcher.state import StateDirectory


def test_bootstrap_creates_a_directory_that_ignores_itself(repo):
    state = StateDirectory(repo)

    state.bootstrap()

    assert (state.path / ".gitignore").read_text(encoding="utf-8") == "*\n"
    assert git("status", "--porcelain", cwd=repo) == ""


def test_bootstrap_heals_a_deleted_gitignore(repo):
    state = StateDirectory(repo)
    state.bootstrap()
    (state.path / ".gitignore").unlink()

    state.bootstrap()

    assert git("status", "--porcelain", cwd=repo) == ""


def test_the_daemon_files_sit_in_the_state_directory(tmp_path):
    state = StateDirectory(tmp_path)

    assert state.path == tmp_path / ".dreamcatcher"
    assert state.lock == state.path / "daemon.pid"
    assert state.last_tick == state.path / "last-tick.json"
