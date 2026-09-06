"""Read the time, in one place, so every record and every feed line agrees.

How long ago something happened is here too, since a reader of a record and a
reader of a feed both want it in the same words.
"""

from datetime import UTC, datetime, timedelta

# How a time is written wherever the tool writes one.
STAMP = "%Y-%m-%dT%H:%M:%SZ"

# How many of the smaller unit make one of the next unit up.
MINUTE = 60
HOUR = 60
DAY = 24


def now() -> datetime:
    """Return the time now, in UTC."""
    return datetime.now(UTC)


def describe_time(at: datetime) -> str:
    """Return the time as the tool writes one, in UTC whatever it was read in."""
    return f"{at.astimezone(UTC):{STAMP}}"


def describe_span(span: timedelta) -> str:
    """Return how long that is, in the largest unit that says it.

    A span of hours or more carries the next unit down as well, since the hour
    alone would round a whole working day away.
    """
    seconds = int(span.total_seconds())
    if seconds < MINUTE:
        return f"{seconds}s"
    minutes = seconds // MINUTE
    if minutes < HOUR:
        return f"{minutes}m"
    hours = minutes // HOUR
    if hours < DAY:
        return f"{hours}h {minutes % HOUR}m"
    return f"{hours // DAY}d {hours % DAY}h"
