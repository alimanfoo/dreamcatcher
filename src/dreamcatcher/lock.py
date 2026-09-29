"""Enforce one running daemon per repository with a process identity file."""

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

import psutil
from pydantic import AwareDatetime, PositiveInt

from dreamcatcher.documents import DreamcatcherDocument, read_json, write_json
from dreamcatcher.errors import ReportableError


class DaemonLockRecord(DreamcatcherDocument):
    """Record the process identity that holds the daemon lock."""

    pid: PositiveInt
    started_at: AwareDatetime


@contextmanager
def hold_daemon_lock(*, path: Path) -> Iterator[int]:
    """Hold the daemon lock and release it when the caller exits.

    Raise ReportableError when a live daemon holds it.

    Reclaim a stale lock, one no live daemon holds.
    """
    daemon_pid = read_daemon_pid(path=path)
    if daemon_pid is not None:
        raise ReportableError(f"dreamcatcher is already running as pid {daemon_pid}.")
    pid = os.getpid()
    write_json(
        document=DaemonLockRecord(
            pid=pid,
            started_at=_read_process_start_time(pid=pid),
        ),
        path=path,
    )
    try:
        yield pid
    finally:
        # A release that cannot happen costs nothing, because the next run
        # reclaims a lock naming a dead pid. Letting the failure out would
        # replace whatever ended the run, and the user would read the wrong one.
        with suppress(OSError):
            path.unlink()


def read_daemon_pid(*, path: Path) -> int | None:
    """Return the PID when the lock names the same live process, otherwise None.

    A missing or malformed file, a PID with no process, and a PID that the
    system reused for another process are stale.
    """
    try:
        record = read_json(model=DaemonLockRecord, path=path)
        started_at = _read_process_start_time(pid=record.pid)
    except (OSError, OverflowError, psutil.Error, ReportableError):
        return None
    return record.pid if record.started_at == started_at else None


def _read_process_start_time(*, pid: int) -> datetime:
    return datetime.fromtimestamp(psutil.Process(pid).create_time(), tz=UTC)
