"""Format shared time, duration, and count values for display."""

from datetime import UTC, datetime, timedelta

# How a time is written wherever the tool writes one.
UTC_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24


def describe_time(*, at: datetime) -> str:
    """Return the time in Dreamcatcher's UTC timestamp format."""
    return f"{at.astimezone(UTC):{UTC_TIMESTAMP_FORMAT}}"


def describe_span(*, span: timedelta) -> str:
    """Return the duration in its largest useful units.

    A span of hours or more carries the next unit down as well, since the hour
    alone would round a whole working day away.
    """
    seconds = int(span.total_seconds())
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds}s"
    minutes = seconds // SECONDS_PER_MINUTE
    if minutes < MINUTES_PER_HOUR:
        return f"{minutes}m"
    hours = minutes // MINUTES_PER_HOUR
    if hours < HOURS_PER_DAY:
        return f"{hours}h {minutes % MINUTES_PER_HOUR}m"
    return f"{hours // HOURS_PER_DAY}d {hours % HOURS_PER_DAY}h"


def describe_count(*, number: int, noun: str) -> str:
    """Return a count with the noun pluralized when needed.

    The noun is one that takes an s, which every noun the tool counts is: a
    round, a post, an assignment.
    """
    if number == 1:
        return f"{number} {noun}"
    return f"{number} {noun}s"
