from datetime import UTC

from dreamcatcher.clock import read_current_time


def test_the_clock_reads_in_utc():
    assert read_current_time().tzinfo is UTC
