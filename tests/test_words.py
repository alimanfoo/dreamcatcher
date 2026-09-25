from datetime import timedelta

import pytest
from clocks import DISPLAY_TIME_ZONE, PINNED

from dreamcatcher.words import (
    describe_count,
    describe_countdown,
    describe_span,
    describe_time,
    format_utc_timestamp,
)


def test_a_utc_timestamp_is_written_the_one_way_the_tool_stores_one():
    assert format_utc_timestamp(at=PINNED) == "2026-08-19T18:41:58Z"


def test_a_time_is_described_in_the_given_zone_without_a_suffix():
    assert describe_time(at=PINNED, zone=DISPLAY_TIME_ZONE) == "2026-08-20 02:41:58"


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
    assert describe_span(span=span) == described


@pytest.mark.parametrize(
    ("number", "described"),
    [(0, "0 rounds"), (1, "1 round"), (2, "2 rounds")],
)
def test_a_count_reads_for_one_or_for_more_than_one(number, described):
    assert describe_count(number=number, noun="round") == described


def test_a_countdown_reads_the_time_left_before_the_span_elapses():
    described = describe_countdown(
        at=PINNED + timedelta(seconds=80), since=PINNED, span_seconds=120
    )

    assert described == "40s"


def test_a_countdown_floors_at_zero_once_the_span_has_passed():
    described = describe_countdown(
        at=PINNED + timedelta(seconds=121), since=PINNED, span_seconds=120
    )

    assert described == "0s"


@pytest.mark.parametrize(
    ("since", "span_seconds"), [(None, 120), (PINNED, None), (None, None)]
)
def test_a_countdown_is_unknown_without_both_a_start_and_a_span(since, span_seconds):
    assert describe_countdown(at=PINNED, since=since, span_seconds=span_seconds) is None
