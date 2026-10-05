import subprocess
import sys
import time

import pytest

from dreamcatcher.errors import ReportableError
from dreamcatcher.lock import hold_daemon_lock, is_daemon_lock_held

# A daemon stand-in that holds the lock until it is killed.
_HOLD_UNTIL_KILLED = """
import sys, time
from pathlib import Path
from dreamcatcher.lock import hold_daemon_lock
with hold_daemon_lock(path=Path(sys.argv[1])):
    print("held", flush=True)
    time.sleep(60)
"""

# Windows releases a dead process's locks after a delay that depends on the
# system's load, so a probe waits up to this long for it.
_RELEASE_DEADLINE_SECONDS = 5


def test_the_lock_is_held_until_the_daemon_exits(tmp_path):
    lock = tmp_path / "daemon.lock"

    with hold_daemon_lock(path=lock):
        assert is_daemon_lock_held(path=lock)

    assert not is_daemon_lock_held(path=lock)


def test_a_missing_lock_is_not_held_and_the_probe_leaves_it_missing(tmp_path):
    lock = tmp_path / "daemon.lock"

    assert not is_daemon_lock_held(path=lock)
    assert not lock.exists()


def test_a_second_daemon_refuses_while_the_first_holds_the_lock(tmp_path):
    lock = tmp_path / "daemon.lock"

    with (
        hold_daemon_lock(path=lock),
        pytest.raises(ReportableError, match="already running"),
        hold_daemon_lock(path=lock),
    ):
        pass


def test_a_daemon_that_is_killed_leaves_the_lock_free(tmp_path):
    lock = tmp_path / "daemon.lock"
    with subprocess.Popen(
        [sys.executable, "-c", _HOLD_UNTIL_KILLED, str(lock)],
        stdout=subprocess.PIPE,
        encoding="utf-8",
    ) as holder:
        assert holder.stdout is not None
        assert holder.stdout.readline() == "held\n"
        assert is_daemon_lock_held(path=lock)

        holder.kill()
        holder.wait()

    deadline = time.monotonic() + _RELEASE_DEADLINE_SECONDS
    while is_daemon_lock_held(path=lock) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not is_daemon_lock_held(path=lock)


def test_the_lock_is_released_when_the_daemon_fails(tmp_path):
    lock = tmp_path / "daemon.lock"

    with pytest.raises(RuntimeError), hold_daemon_lock(path=lock):
        raise RuntimeError("the daemon fell over")

    assert not is_daemon_lock_held(path=lock)


def test_a_lock_that_cannot_be_taken_says_so(tmp_path):
    lock = tmp_path / "daemon.lock"
    lock.mkdir()

    with (
        pytest.raises(ReportableError, match=r"cannot lock .*daemon\.lock"),
        hold_daemon_lock(path=lock),
    ):
        pass


def test_a_lock_that_cannot_be_probed_says_so(tmp_path):
    lock = tmp_path / "daemon.lock"
    lock.mkdir()

    with pytest.raises(ReportableError, match=r"cannot probe .*daemon\.lock"):
        is_daemon_lock_held(path=lock)
