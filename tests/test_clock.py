from datetime import UTC, timedelta

import pytest

from dreamcatcher.clock import describe_span, now


def test_the_clock_reads_in_utc():
    assert now().tzinfo is UTC


@pytest.mark.parametrize(
    ("span", "described"),
    [
        (timedelta(seconds=0), "0s"),
        (timedelta(seconds=59), "59s"),
        (timedelta(minutes=1), "1m"),
        (timedelta(minutes=59, seconds=59), "59m"),
        (timedelta(hours=2, minutes=5), "2h 5m"),
        (timedelta(hours=23, minutes=59), "23h 59m"),
        (timedelta(days=1), "1d 0h"),
        (timedelta(days=9, hours=7), "9d 7h"),
    ],
)
def test_a_span_reads_in_the_largest_unit_that_says_it(span, described):
    assert describe_span(span) == described
