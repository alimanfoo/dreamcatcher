"""Read the time, in one place, so every record and every feed line agrees."""

from datetime import UTC, datetime


def now() -> datetime:
    """Return the time now, in UTC."""
    return datetime.now(UTC)
