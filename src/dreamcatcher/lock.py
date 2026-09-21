"""Enforce one running daemon per repository with a PID file."""

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import psutil

from dreamcatcher.documents import write_text
from dreamcatcher.errors import ReportableError


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
    write_text(text=f"{pid}\n", path=path)
    try:
        yield pid
    finally:
        # A release that cannot happen costs nothing, because the next run
        # reclaims a lock naming a dead pid. Letting the failure out would
        # replace whatever ended the run, and the user would read the wrong one.
        with suppress(OSError):
            path.unlink()


def read_daemon_pid(*, path: Path) -> int | None:
    """Return the PID when the lock names a live process, otherwise None.

    The check cannot distinguish the daemon from another process that reused
    its PID. A missing or malformed file and a PID with no process are stale.
    """
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        is_alive = pid > 0 and psutil.pid_exists(pid)
    except (OSError, ValueError, OverflowError):
        return None
    return pid if is_alive else None
