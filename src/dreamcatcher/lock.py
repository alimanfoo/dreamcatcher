"""Enforce one running daemon per repository with an operating-system file lock.

The kernel releases the lock when the daemon's process ends, however it ends, so
a held lock always means a live daemon.
"""

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from filelock import BaseFileLock, FileLock, Timeout

from dreamcatcher.errors import ReportableError

# A reader probes by taking the lock for an instant. A daemon that starts during
# a probe waits this long for the lock rather than refusing.
_DAEMON_ACQUIRE_TIMEOUT_SECONDS = 1.0

# Two readers that probe at once can each find the lock held. A probe holds the
# lock for well under a millisecond, so a probe that keeps trying this long only
# rarely mistakes another probe for a daemon.
_PROBE_TIMEOUT_SECONDS = 0.02

_POLL_INTERVAL_SECONDS = 0.005


@contextmanager
def hold_daemon_lock(*, path: Path) -> Iterator[None]:
    """Hold the daemon lock and release it when the caller exits.

    Raise ReportableError when another daemon holds it, or when the filesystem
    cannot lock the file.
    """
    lock = _create_daemon_lock(
        path=path,
        timeout=_DAEMON_ACQUIRE_TIMEOUT_SECONDS,
    )
    try:
        lock.acquire()
    except Timeout as error:
        raise ReportableError(
            "dreamcatcher is already running in this checkout."
        ) from error
    except OSError as error:
        raise ReportableError(f"cannot lock {path}: {error}") from error
    try:
        yield
    finally:
        # The kernel releases the lock when the process ends, so a release that
        # fails costs nothing. Letting the failure out would replace whatever
        # ended the run, and the user would read the wrong one.
        with suppress(OSError):
            lock.release()


def is_daemon_lock_held(*, path: Path) -> bool:
    """Return whether a daemon holds the lock.

    A missing file means that no daemon is running, so a reader never creates
    one. Raise ReportableError when the lock cannot be probed.
    """
    probe = _create_daemon_lock(
        path=path,
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    try:
        if not path.exists():
            return False
        with probe:
            return False
    except Timeout:
        return True
    except OSError as error:
        raise ReportableError(f"cannot probe the lock {path}: {error}") from error


def _create_daemon_lock(*, path: Path, timeout: float) -> BaseFileLock:
    # A soft lock outlives a daemon that dies, which is the false answer that
    # this lock exists to prevent, so a filesystem that cannot lock files fails.
    return FileLock(
        path,
        timeout=timeout,
        poll_interval=_POLL_INTERVAL_SECONDS,
        fallback_to_soft=False,
    )
