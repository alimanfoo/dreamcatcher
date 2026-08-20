from datetime import UTC

from dreamcatcher.clock import now


def test_the_clock_reads_in_utc():
    assert now().tzinfo is UTC
