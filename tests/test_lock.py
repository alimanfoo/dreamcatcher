import os
import subprocess
import sys

import pytest

from dreamcatcher.lock import AlreadyRunningError, hold


def dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


def test_holding_the_lock_records_the_daemon_and_releasing_removes_it(tmp_path):
    lock = tmp_path / "daemon.pid"

    with hold(lock):
        assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())

    assert not lock.exists()


def test_a_live_daemon_keeps_the_lock(tmp_path):
    lock = tmp_path / "daemon.pid"
    lock.write_text(f"{os.getpid()}\n", encoding="utf-8")

    with pytest.raises(AlreadyRunningError, match=f"pid {os.getpid()}"), hold(lock):
        pass


def test_a_lock_naming_a_pid_that_is_gone_is_reclaimed(tmp_path):
    lock = tmp_path / "daemon.pid"
    lock.write_text(f"{dead_pid()}\n", encoding="utf-8")

    with hold(lock):
        assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_a_lock_nobody_can_read_is_reclaimed(tmp_path):
    lock = tmp_path / "daemon.pid"
    lock.write_text("who knows\n", encoding="utf-8")

    with hold(lock):
        assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_the_lock_is_released_when_the_daemon_fails(tmp_path):
    lock = tmp_path / "daemon.pid"

    with pytest.raises(RuntimeError), hold(lock):
        raise RuntimeError("the daemon fell over")

    assert not lock.exists()
