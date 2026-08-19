"""Keep one daemon per repo, with a pid file the daemon holds while it runs."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psutil

from dreamcatcher.errors import DreamcatcherError


class AlreadyRunningError(DreamcatcherError):
    """A daemon is running on this repo already."""


@contextmanager
def hold(path: Path) -> Iterator[None]:
    """Hold the lock at path, and release it however the caller ends.

    Raise AlreadyRunningError when a live daemon holds it. A lock naming a pid that
    is gone is stale, and so is one nobody can read, so both are reclaimed.
    """
    running = _holder(path)
    if running is not None:
        raise AlreadyRunningError(f"dreamcatcher is already running as pid {running}.")
    path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _holder(path: Path) -> int | None:
    """Return the pid of the daemon holding the lock, if one still is."""
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if psutil.pid_exists(pid) else None
