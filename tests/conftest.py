"""What the whole suite shares: the encoding gate, and a git repository."""

import os
import subprocess
from pathlib import Path

import pytest

ARMING = "PYTHONWARNDEFAULTENCODING"


def pytest_configure(config: pytest.Config) -> None:
    """Stop before collection when the interpreter is not arming the gate."""
    if os.environ.get(ARMING) != "1":
        raise pytest.UsageError(
            f"Set {ARMING}=1 when you run pytest. Without it the interpreter "
            "never emits EncodingWarning, so the UTF-8 gate is inert."
        )


def git(*arguments: str, cwd: Path) -> str:
    """Run git in cwd and return its output, forcing UTF-8 both ways."""
    finished = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        capture_output=True,
        check=True,
        encoding="utf-8",
    )
    return finished.stdout


@pytest.fixture
def repo(tmp_path):
    """Return a main checkout of a fresh, empty git repository."""
    git("init", cwd=tmp_path)
    return tmp_path
