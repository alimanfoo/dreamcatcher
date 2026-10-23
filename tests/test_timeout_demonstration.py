"""A temporary test that hangs on purpose, to show the per-test timeout firing.

Remove this file once CI has shown the timeout on every platform.
"""

import threading

import pytest


@pytest.fixture
def _teardown_marker():
    yield
    print("teardown ran")


@pytest.mark.timeout(15)
@pytest.mark.usefixtures("_teardown_marker")
def test_a_test_that_waits_forever_is_stopped_by_the_timeout():
    threading.Event().wait()
