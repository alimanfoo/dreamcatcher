import os
import subprocess
import sys
from pathlib import Path

import pytest

from dreamcatcher.errors import ReportableError
from dreamcatcher.lock import hold_daemon_lock


def refuse(_: object, /) -> None:
    raise PermissionError("the lock cannot be removed")


def dead_pid() -> int:
    """A pid that no process holds, from ending one that did."""
    child = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


def test_holding_the_lock_records_the_daemon_and_releasing_removes_it(tmp_path):
    lock = tmp_path / "daemon.pid"

    with hold_daemon_lock(path=lock):
        assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())

    assert not lock.exists()


def test_a_live_daemon_keeps_the_lock(tmp_path):
    lock = tmp_path / "daemon.pid"
    lock.write_text(f"{os.getpid()}\n", encoding="utf-8")

    with (
        pytest.raises(ReportableError, match=f"pid {os.getpid()}"),
        hold_daemon_lock(path=lock),
    ):
        pass


def test_a_lock_naming_a_pid_that_is_gone_is_reclaimed(tmp_path):
    lock = tmp_path / "daemon.pid"
    lock.write_text(f"{dead_pid()}\n", encoding="utf-8")

    with hold_daemon_lock(path=lock):
        assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


@pytest.mark.parametrize(
    ("kind", "held"),
    [
        ("words", "who knows"),
        ("nothing", ""),
        ("a pid no process could have", "999999999999"),
        ("a pid that is no daemon's", "0"),
    ],
)
def test_a_lock_nobody_can_read_as_a_live_pid_is_reclaimed(tmp_path, kind, held):
    lock = tmp_path / "daemon.pid"
    lock.write_text(f"{held}\n", encoding="utf-8")

    with hold_daemon_lock(path=lock):
        assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_the_lock_is_released_when_the_daemon_fails(tmp_path):
    lock = tmp_path / "daemon.pid"

    with pytest.raises(RuntimeError), hold_daemon_lock(path=lock):
        raise RuntimeError("the daemon fell over")

    assert not lock.exists()


def test_a_lock_the_daemon_cannot_write_says_so(tmp_path):
    with (
        pytest.raises(ReportableError, match="cannot write"),
        hold_daemon_lock(path=tmp_path),
    ):
        pass


def test_a_release_that_cannot_happen_leaves_the_failure_that_ended_the_run(
    tmp_path, monkeypatch
):
    lock = tmp_path / "daemon.pid"
    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(ReportableError, match="the tick"), hold_daemon_lock(path=lock):
        raise ReportableError("the tick could not write what it decided")
