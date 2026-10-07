"""Enforce one running daemon per checkout with an operating-system file lock.

The kernel releases the lock when the daemon's process ends, however it ends, so
a held lock always means a live daemon. A daemon also checks that its lock path
still names the file that it acquired, because removing that path lets another
process lock a replacement file.
"""

import os
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _HeldDaemonLock:
    """A daemon lock and the identity of the file that it holds."""

    path: Path
    _acquired_file: os.stat_result

    def ensure_held(self) -> None:
        """Raise ReportableError unless the path still names the acquired file."""
        try:
            current_file = self.path.stat()
        except FileNotFoundError:
            raise ReportableError(f"the daemon lock at {self.path} was lost.") from None
        except OSError as error:
            raise ReportableError(
                f"cannot check the daemon lock {self.path}: {error}"
            ) from error
        if not os.path.samestat(self._acquired_file, current_file):
            raise ReportableError(f"the daemon lock at {self.path} was lost.")


@contextmanager
def hold_daemon_lock(*, path: Path) -> Generator[_HeldDaemonLock, None, None]:
    """Hold the daemon lock and release it when the caller exits.

    Yield a checker that the caller invokes after each wait and before doing
    more work, so a replaced lock file ends the daemon run.

    Raise ReportableError when another daemon holds it, or when the filesystem
    cannot lock the file.
    """
    acquired_file: list[os.stat_result] = []
    lock = _create_daemon_lock(
        path=path,
        timeout=_DAEMON_ACQUIRE_TIMEOUT_SECONDS,
        on_acquired=lambda descriptor: acquired_file.append(os.fstat(descriptor)),
    )
    try:
        lock.acquire()
    except Timeout as error:
        raise ReportableError(
            "dreamcatcher is already running in this checkout."
        ) from error
    except (OSError, ExceptionGroup) as error:
        raise ReportableError(f"cannot lock {path}: {error}") from error
    try:
        yield _HeldDaemonLock(path=path, _acquired_file=acquired_file[0])
    finally:
        # The kernel releases the lock when the process ends, so a release that
        # fails costs nothing. Letting the failure out would replace whatever
        # ended the daemon run, and the user would read the wrong one.
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


def _create_daemon_lock(
    *,
    path: Path,
    timeout: float,
    on_acquired: Callable[[int], None] | None = None,
) -> BaseFileLock:
    # A soft lock outlives a daemon that dies, which is the false answer that
    # this lock exists to prevent, so a filesystem that cannot lock files fails.
    return FileLock(
        path,
        timeout=timeout,
        poll_interval=_POLL_INTERVAL_SECONDS,
        fallback_to_soft=False,
        on_acquired=on_acquired,
    )
