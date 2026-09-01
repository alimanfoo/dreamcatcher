import os

import pytest
from clocks import Ticking

from dreamcatcher.config import CONFIG_NAME, Harness
from dreamcatcher.daemon import Daemon
from dreamcatcher.errors import ReportableError
from dreamcatcher.state import LastTick, StateDirectory


class Waiting:
    """A wait that lets the daemon tick, then interrupts it like a user would."""

    def __init__(self, ticks: int) -> None:
        self.ticks = ticks
        self.waited: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)
        if len(self.waited) == self.ticks:
            raise KeyboardInterrupt


def idling(root, ticks: int = 2) -> tuple[Daemon, Waiting, Ticking]:
    waiting = Waiting(ticks)
    ticking = Ticking(step=300)
    return Daemon(root, Harness.CLAUDE, clock=ticking, wait=waiting), waiting, ticking


def test_the_daemon_ticks_on_the_interval_until_the_user_interrupts(watched):
    daemon, waiting, _ = idling(watched)

    daemon.run()

    assert waiting.waited == [300, 300]


def test_every_tick_records_when_it_ran(watched):
    daemon, _, ticking = idling(watched)

    daemon.run()

    recorded = daemon.state.last_tick.read_text(encoding="utf-8")
    assert len(ticking.readings) == 2
    assert LastTick.model_validate_json(recorded).at == ticking.readings[-1]


def test_the_daemon_bootstraps_the_state_directory_and_releases_the_lock(watched):
    daemon, _, _ = idling(watched)

    daemon.run()

    assert (daemon.state.path / ".gitignore").exists()
    assert not daemon.state.lock.exists()


def test_a_second_daemon_refuses_while_the_first_holds_the_repo(watched):
    daemon, _, _ = idling(watched)
    daemon.state.bootstrap()
    daemon.state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")

    with pytest.raises(ReportableError, match=f"pid {os.getpid()}"):
        daemon.run()


def test_the_daemon_runs_the_harness_it_was_given(watched):
    assert Daemon(watched, Harness.CODEX).harness is Harness.CODEX


def test_a_checkout_with_no_config_names_the_file_it_needs(repo):
    with pytest.raises(ReportableError, match=CONFIG_NAME):
        Daemon(repo, Harness.CLAUDE)


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path):
    with pytest.raises(ReportableError, match="main checkout"):
        Daemon(tmp_path, Harness.CLAUDE)


def test_a_linked_worktree_is_refused(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")

    with pytest.raises(ReportableError, match="main checkout"):
        Daemon(tmp_path, Harness.CLAUDE)


def test_the_state_directory_sits_in_the_checkout(watched):
    daemon = Daemon(watched, Harness.CLAUDE)

    assert daemon.state == StateDirectory(watched)
