"""Keep one daemon per repo, with a pid file the daemon holds while it runs."""

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import psutil

from dreamcatcher.documents import write_text
from dreamcatcher.errors import ReportableError


@contextmanager
def hold(path: Path) -> Iterator[None]:
    """Hold the lock at path, and release it however the caller ends.

    Raise ReportableError when a live daemon holds it.

    Reclaim a stale lock, one no live daemon holds.
    """
    running = read_daemon_pid(path)
    if running is not None:
        raise ReportableError(f"dreamcatcher is already running as pid {running}.")
    write_text(f"{os.getpid()}\n", path)
    try:
        yield
    finally:
        # A release that cannot happen costs nothing, because the next run
        # reclaims a lock naming a dead pid. Letting the failure out would
        # replace whatever ended the run, and the user would read the wrong one.
        with suppress(OSError):
            path.unlink()


def read_daemon_pid(path: Path) -> int | None:
    """Return the pid of the daemon holding the lock, if one still is.

    A lock nobody can read as a live pid is stale. That covers a file that is
    not there, one holding something other than a pid, and one holding a number
    no process could have.
    """
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        alive = pid > 0 and psutil.pid_exists(pid)
    except (OSError, ValueError, OverflowError):
        return None
    return pid if alive else None
