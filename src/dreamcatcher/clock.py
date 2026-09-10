"""Read the time and wait on it, in one place, so everything here agrees."""

from collections.abc import Callable
from datetime import UTC, datetime

# How the daemon and a view wait between one look and the next. What they
# hold is `time.sleep`, whose argument is positional, so this stays a
# Callable where a callback this project implements itself would take a
# keyword-only protocol.
type Wait = Callable[[float], None]


def now() -> datetime:
    """Return the time now, in UTC."""
    return datetime.now(UTC)
