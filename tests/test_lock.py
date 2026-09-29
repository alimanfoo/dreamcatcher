import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
import pytest
from records import write_daemon_lock

import dreamcatcher.lock as lock_module
from dreamcatcher.documents import read_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.lock import DaemonLockRecord, hold_daemon_lock


def refuse(_: object, /) -> None:
    raise PermissionError("the lock cannot be removed")


def dead_pid() -> int:
    """A pid that no process holds, from ending one that did."""
    child = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


def process_started_at(*, pid: int) -> datetime:
    return datetime.fromtimestamp(psutil.Process(pid).create_time(), tz=UTC)


def test_holding_the_lock_records_the_daemon_and_releasing_removes_it(tmp_path):
    lock = tmp_path / "daemon.pid"
    process_start = process_started_at(pid=os.getpid())

    with hold_daemon_lock(path=lock) as pid:
        assert pid == os.getpid()
        assert read_json(model=DaemonLockRecord, path=lock) == DaemonLockRecord(
            pid=os.getpid(), process_started_at=process_start
        )

    assert not lock.exists()


def test_a_live_daemon_keeps_the_lock(tmp_path):
    lock = tmp_path / "daemon.pid"
    write_daemon_lock(
        path=lock,
        pid=os.getpid(),
        process_started_at=process_started_at(pid=os.getpid()),
    )

    with (
        pytest.raises(ReportableError, match=f"pid {os.getpid()}"),
        hold_daemon_lock(path=lock),
    ):
        pass


def test_a_lock_naming_a_pid_that_is_gone_is_reclaimed(tmp_path):
    lock = tmp_path / "daemon.pid"
    write_daemon_lock(
        path=lock,
        pid=dead_pid(),
        process_started_at=datetime.now(tz=UTC),
    )

    with hold_daemon_lock(path=lock):
        assert read_json(model=DaemonLockRecord, path=lock).pid == os.getpid()


def test_a_lock_naming_a_reused_pid_is_reclaimed(tmp_path):
    lock = tmp_path / "daemon.pid"
    process_start = process_started_at(pid=os.getpid())
    write_daemon_lock(
        path=lock,
        pid=os.getpid(),
        process_started_at=process_start - timedelta(seconds=1),
    )

    with hold_daemon_lock(path=lock):
        assert read_json(model=DaemonLockRecord, path=lock) == DaemonLockRecord(
            pid=os.getpid(), process_started_at=process_start
        )


@pytest.mark.parametrize(
    ("kind", "held"),
    [
        ("an old bare pid", str(os.getpid())),
        ("words", "who knows"),
        ("nothing", ""),
        ("a pid no process could have", "999999999999"),
        ("a pid that is no daemon's", "0"),
    ],
)
def test_an_invalid_lock_is_reported(tmp_path, kind, held):
    lock = tmp_path / "daemon.pid"
    lock.write_text(f"{held}\n", encoding="utf-8")

    with (
        pytest.raises(ReportableError, match=r"daemon\.pid"),
        hold_daemon_lock(path=lock),
    ):
        pass


def test_a_lock_that_cannot_be_read_is_reported(tmp_path, monkeypatch):
    lock = tmp_path / "daemon.pid"

    def refuse_read(self, /, *, follow_symlinks=True):
        raise PermissionError(f"cannot inspect {self}")

    monkeypatch.setattr(Path, "stat", refuse_read)

    with (
        pytest.raises(ReportableError, match=r"cannot read .*daemon\.pid"),
        hold_daemon_lock(path=lock),
    ):
        pass


def test_a_process_identity_that_cannot_be_inspected_is_reported(tmp_path, monkeypatch):
    lock = tmp_path / "daemon.pid"
    write_daemon_lock(
        path=lock,
        pid=os.getpid(),
        process_started_at=process_started_at(pid=os.getpid()),
    )

    def refuse_process_inspection(pid, /):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(psutil, "Process", refuse_process_inspection)

    with (
        pytest.raises(ReportableError, match=f"inspect process {os.getpid()}"),
        hold_daemon_lock(path=lock),
    ):
        pass


def test_the_lock_is_released_when_the_daemon_fails(tmp_path):
    lock = tmp_path / "daemon.pid"

    with pytest.raises(RuntimeError), hold_daemon_lock(path=lock):
        raise RuntimeError("the daemon fell over")

    assert not lock.exists()


def test_a_lock_the_daemon_cannot_write_says_so(tmp_path, monkeypatch):
    def refuse_write(*, document, path):
        raise ReportableError(f"cannot write {path}")

    monkeypatch.setattr(lock_module, "write_json", refuse_write)

    with (
        pytest.raises(ReportableError, match="cannot write"),
        hold_daemon_lock(path=tmp_path / "daemon.pid"),
    ):
        pass


def test_a_release_that_cannot_happen_leaves_the_failure_that_ended_the_run(
    tmp_path, monkeypatch
):
    lock = tmp_path / "daemon.pid"
    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(ReportableError, match="the tick"), hold_daemon_lock(path=lock):
        raise ReportableError("the tick could not write what it decided")
