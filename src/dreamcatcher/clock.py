"""Provide the shared clock and wait types."""

from collections.abc import Callable
from datetime import UTC, datetime

import psutil

# How the daemon and a view wait between refreshes. What they hold is
# `time.sleep`, whose argument is positional, so this stays a
# Callable where a callback this project implements itself would take a
# keyword-only protocol.
type WaitForSeconds = Callable[[float], None]


def read_current_time() -> datetime:
    """Return the time now, in UTC."""
    return datetime.now(UTC)


def read_boot_time() -> datetime:
    """Return when the machine last booted, in UTC.

    The operating system works this out from the time now and how long it has
    been up, so two readings can differ by a second.
    """
    return datetime.fromtimestamp(psutil.boot_time(), UTC)
