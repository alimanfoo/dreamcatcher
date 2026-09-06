"""How the tool says a value in words, so every view says it the same way."""

from datetime import UTC, datetime, timedelta

# How a time is written wherever the tool writes one.
STAMP = "%Y-%m-%dT%H:%M:%SZ"

# How many of the smaller unit make one of the next unit up.
MINUTE = 60
HOUR = 60
DAY = 24


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


def describe_count(number: int, noun: str) -> str:
    """Return how many of the noun that is, in words that read for one.

    The noun is one that takes an s, which every noun the tool counts is: a
    round, a post, an attempt.
    """
    if number == 1:
        return f"{number} {noun}"
    return f"{number} {noun}s"
