import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock

import pytest
from filelock import BaseFileLock

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


def test_the_lock_is_held_until_the_daemon_releases_it(tmp_path):
    lock = tmp_path / "daemon.lock"

    with hold_daemon_lock(path=lock) as held_lock:
        held_lock.ensure_held()
        assert is_daemon_lock_held(path=lock)

    assert not is_daemon_lock_held(path=lock)


def test_a_lock_whose_path_is_replaced_reports_that_it_was_lost(tmp_path, monkeypatch):
    lock = tmp_path / "daemon.lock"

    with hold_daemon_lock(path=lock) as held_lock:
        if sys.platform == "win32":
            # Windows prevents removing an open lock file, so stand another
            # file in for the replacement that POSIX permits.
            replacement = tmp_path / "replacement.lock"
            replacement.touch()
            stat = Path.stat

            def stat_replacement(path, /, *, follow_symlinks=True):
                """Stand in for Path.stat, which passes its path by position."""
                target = replacement if path == lock else path
                return stat(target, follow_symlinks=follow_symlinks)

            monkeypatch.setattr(Path, "stat", stat_replacement)
        else:
            lock.unlink()
            lock.touch()

        with pytest.raises(ReportableError, match=r"daemon lock .* was lost"):
            held_lock.ensure_held()


def test_a_lock_whose_path_disappears_reports_that_it_was_lost(tmp_path, monkeypatch):
    lock = tmp_path / "daemon.lock"

    with hold_daemon_lock(path=lock) as held_lock:
        if sys.platform == "win32":
            # Windows prevents removing an open lock file, so make its stat
            # report the missing path that POSIX permits.
            stat = Path.stat

            def stat_missing(path, /, *, follow_symlinks=True):
                """Stand in for Path.stat, which passes its path by position."""
                if path == lock:
                    raise FileNotFoundError(lock)
                return stat(path, follow_symlinks=follow_symlinks)

            monkeypatch.setattr(Path, "stat", stat_missing)
        else:
            lock.unlink()

        with pytest.raises(ReportableError, match=r"daemon lock .* was lost"):
            held_lock.ensure_held()


def test_a_lock_that_cannot_be_checked_says_so(tmp_path, monkeypatch):
    lock = tmp_path / "daemon.lock"

    with hold_daemon_lock(path=lock) as held_lock:
        monkeypatch.setattr(
            Path,
            "stat",
            Mock(side_effect=PermissionError("the lock cannot be read")),
        )

        with pytest.raises(ReportableError, match=r"cannot check .* cannot be read"):
            held_lock.ensure_held()


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
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline() == "held\n"
            assert is_daemon_lock_held(path=lock)
        finally:
            holder.kill()
            holder.wait()

    deadline = time.monotonic() + _RELEASE_DEADLINE_SECONDS
    while is_daemon_lock_held(path=lock) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not is_daemon_lock_held(path=lock)


def test_a_daemon_that_starts_while_the_lock_is_briefly_held_waits_for_it(tmp_path):
    lock = tmp_path / "daemon.lock"
    is_held = Event()

    def hold_briefly():
        with hold_daemon_lock(path=lock):
            is_held.set()
            time.sleep(0.1)

    holder = Thread(target=hold_briefly)
    holder.start()
    is_held.wait()

    with hold_daemon_lock(path=lock):
        assert is_daemon_lock_held(path=lock)
    holder.join()


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


def test_a_release_that_cannot_happen_leaves_the_failure_that_ended_the_run(
    tmp_path, monkeypatch
):
    def refuse_release(self, /, *, force=False):
        raise PermissionError("the lock cannot be released")

    monkeypatch.setattr(BaseFileLock, "release", refuse_release)

    with (
        pytest.raises(ReportableError, match="the tick"),
        hold_daemon_lock(path=tmp_path / "daemon.lock"),
    ):
        raise ReportableError("the tick could not write what it decided")
