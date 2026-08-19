"""Refuse to run the suite unless the EncodingWarning gate is armed."""

import os

import pytest

ARMING = "PYTHONWARNDEFAULTENCODING"


def pytest_configure(config: pytest.Config) -> None:
    """Stop before collection when the interpreter is not arming the gate."""
    if os.environ.get(ARMING) != "1":
        raise pytest.UsageError(
            f"Set {ARMING}=1 when you run pytest. Without it the interpreter "
            "never emits EncodingWarning, so the UTF-8 gate is inert."
        )
