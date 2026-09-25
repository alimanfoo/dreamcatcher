"""Format shared timestamps, durations, and count values."""

from datetime import UTC, datetime, timedelta, tzinfo

# How a time is written wherever the tool writes one.
UTC_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DISPLAY_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24


def format_utc_timestamp(*, at: datetime) -> str:
    """Format a timestamp for persistent storage in UTC."""
    return f"{at.astimezone(UTC):{UTC_TIMESTAMP_FORMAT}}"


def describe_time(*, at: datetime, zone: tzinfo | None) -> str:
    """Describe a time in the given zone without a zone suffix.

    None selects the machine's local zone, including the offset at the time
    being described.
    """
    return f"{at.astimezone(zone):{DISPLAY_TIME_FORMAT}}"


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


def describe_countdown(
    *, at: datetime, since: datetime | None, span_seconds: int | None
) -> str | None:
    """Describe the time remaining until span_seconds after since.

    Returns None when since or span_seconds is absent, so a caller with
    nothing to count down from can leave the fact out rather than show it.
    The remaining time floors at zero rather than reading negative once
    span_seconds has fully elapsed.
    """
    if since is None or span_seconds is None:
        return None
    elapsed = at - since
    remaining = max(timedelta(), timedelta(seconds=span_seconds) - elapsed)
    return describe_span(span=remaining)


def describe_count(*, number: int, noun: str) -> str:
    """Return a count with the noun pluralized when needed.

    The noun is one that takes an s, which every noun the tool counts is: a
    round, a post, an assignment.
    """
    if number == 1:
        return f"{number} {noun}"
    return f"{number} {noun}s"
