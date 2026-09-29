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
    """The process identity that holds the daemon lock."""

    pid: PositiveInt
    process_started_at: AwareDatetime


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
            process_started_at=_read_process_start_time(pid=pid),
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

    A missing file, a PID with no process, and a PID that the system reused for
    another process are stale. Raise ReportableError when the document is
    invalid or the process identity cannot be inspected.
    """
    try:
        record = read_json(model=DaemonLockRecord, path=path)
    except ReportableError:
        try:
            path.stat()
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError:
            pass
        raise
    try:
        process_started_at = _read_process_start_time(pid=record.pid)
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return None
    except (OSError, OverflowError, psutil.Error) as error:
        raise ReportableError(
            f"cannot inspect process {record.pid}: {error}"
        ) from error
    return record.pid if record.process_started_at == process_started_at else None


def _read_process_start_time(*, pid: int) -> datetime:
    return datetime.fromtimestamp(psutil.Process(pid).create_time(), tz=UTC)
