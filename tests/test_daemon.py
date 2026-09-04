import os
import sys

import psutil
import pytest
from clocks import PINNED, Ticking
from conftest import CONFIG_HEAD, SMITH_CLAUDE, dead_pid, gone
from records import write_round, write_session

from dreamcatcher.commands import spawn
from dreamcatcher.config import CONFIG_NAME, Harness
from dreamcatcher.daemon import Daemon
from dreamcatcher.errors import ReportableError
from dreamcatcher.rounds import RoundRecord
from dreamcatcher.state import LastTick, StateDirectory

KEY = "GH13-20260819-184158"

# What every round the tests here write down says woke it.
CAUSE = "dispatched"


@pytest.fixture
def left_running(watched):
    """A process standing in for a round that outlived the daemon that ran it."""
    child = spawn(sys.executable, "-c", "import time; time.sleep(60)", cwd=watched)
    yield child
    child.kill()


@pytest.fixture
def harnesses(fake):
    """Both harness CLIs on the PATH, so a run gets past its startup check."""
    return {program: fake(program) for program in ("claude", "codex")}


@pytest.fixture
def alone(fake, stand_ins, monkeypatch):
    """Return a factory installing these stand-ins and nothing else at all.

    A harness the developer installed for their own use sits on the PATH of
    the machine the suite runs on, and would answer a startup check that a
    test means to fail. So the PATH holds the stand-ins alone.
    """

    def install(*programs: str) -> None:
        for program in programs:
            fake(program)
        monkeypatch.setenv("PATH", str(stand_ins))

    return install


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


def test_the_daemon_ticks_on_the_interval_until_the_user_interrupts(watched, harnesses):
    daemon, waiting, _ = idling(watched)

    daemon.run()

    assert waiting.waited == [300, 300]


def test_every_tick_records_when_it_ran(watched, harnesses):
    daemon, _, ticking = idling(watched)

    daemon.run()

    recorded = daemon.state.last_tick.read_text(encoding="utf-8")
    assert len(ticking.readings) == 2
    assert LastTick.model_validate_json(recorded).at == ticking.readings[-1]


def test_the_daemon_bootstraps_the_state_directory_and_releases_the_lock(
    watched, harnesses
):
    daemon, _, _ = idling(watched)

    daemon.run()

    assert (daemon.state.path / ".gitignore").exists()
    assert not daemon.state.lock.exists()


def test_a_second_daemon_refuses_while_the_first_holds_the_repo(watched, harnesses):
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


def test_a_run_refuses_when_a_harness_it_could_dispatch_to_is_not_installed(
    watched, alone
):
    alone("claude")
    daemon, _, _ = idling(watched)

    with pytest.raises(ReportableError, match="codex is not on the PATH"):
        daemon.run()


def test_a_run_refuses_when_the_harness_it_was_named_is_not_installed(repo, alone):
    (repo / CONFIG_NAME).write_text(CONFIG_HEAD + SMITH_CLAUDE, encoding="utf-8")
    alone("claude")

    with pytest.raises(ReportableError, match="codex is not on the PATH"):
        Daemon(repo, Harness.CODEX, wait=Waiting(1)).run()


def test_a_round_the_daemon_before_this_one_left_running_is_ended(
    watched, harnesses, left_running
):
    directory = write_session(StateDirectory(watched), KEY, 13)
    write_round(
        directory, 1, RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE)
    )
    daemon, _, _ = idling(watched)

    daemon.run()

    assert gone(left_running.pid)


def test_a_round_that_recorded_an_ending_is_left_running_by_the_sweep(
    watched, harnesses, left_running
):
    directory = write_session(StateDirectory(watched), KEY, 13)
    write_round(
        directory,
        1,
        RoundRecord(
            started=PINNED,
            pid=left_running.pid,
            cause=CAUSE,
            ended=PINNED,
            status=0,
        ),
    )
    write_round(directory, 2, RoundRecord(started=PINNED, pid=dead_pid(), cause=CAUSE))
    daemon, _, _ = idling(watched)

    daemon.run()

    assert psutil.pid_exists(left_running.pid)
