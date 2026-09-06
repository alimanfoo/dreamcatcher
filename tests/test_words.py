from datetime import timedelta

import pytest
from clocks import PINNED

from dreamcatcher.words import describe_count, describe_span, describe_time


def test_a_time_is_written_the_one_way_the_tool_writes_one():
    assert describe_time(PINNED) == "2026-08-19T18:41:58Z"


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


@pytest.mark.parametrize(
    ("number", "described"),
    [(0, "0 rounds"), (1, "1 round"), (2, "2 rounds")],
)
def test_a_count_reads_for_one_or_for_more_than_one(number, described):
    assert describe_count(number, "round") == described
