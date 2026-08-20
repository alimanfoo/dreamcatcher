"""What the whole suite shares: the encoding gate, a repo, a config, stand-ins."""

import os
from functools import partial
from pathlib import Path

import fakes
import pytest

from dreamcatcher.commands import run
from dreamcatcher.config import CONFIG_NAME

ARMING = "PYTHONWARNDEFAULTENCODING"

CONFIG_HEAD = """interval = 300

"""

SMITH_CLAUDE = """[[dispatch]]
label = "dream:smith"
[dispatch.claude]
prompt = "/dream:smith GH{issue}"
model = "opus[1m]"
effort = "xhigh"
"""

SMITH_CODEX = """[dispatch.codex]
prompt = "$dream:smith GH{issue}"
model = "gpt-5.6-sol"
effort = "xhigh"
"""

CONFIG = CONFIG_HEAD + SMITH_CLAUDE + SMITH_CODEX


def pytest_configure(config: pytest.Config) -> None:
    """Stop before collection when the interpreter is not arming the gate."""
    if os.environ.get(ARMING) != "1":
        raise pytest.UsageError(
            f"Set {ARMING}=1 when you run pytest. Without it the interpreter "
            "never emits EncodingWarning, so the UTF-8 gate is inert."
        )


def git(*arguments: str, cwd: Path) -> str:
    """Run git in cwd and return its output, through the tool's own runner."""
    return run("git", *arguments, cwd=cwd)


def commit(path: Path, message: str) -> None:
    """Commit everything in the checkout at path, under a throwaway identity."""
    git("add", "--all", cwd=path)
    git(
        "-c",
        "user.name=A Test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--message",
        message,
        cwd=path,
    )


@pytest.fixture
def repo(tmp_path):
    """Return a main checkout of a fresh, empty git repository."""
    git("init", cwd=tmp_path)
    return tmp_path


@pytest.fixture
def upstream(tmp_path):
    """Return a bare repository holding main, standing in for GitHub."""
    bare = tmp_path / "upstream.git"
    git("init", "--bare", "--initial-branch=main", str(bare), cwd=tmp_path)
    seed = tmp_path / "seed"
    git("init", "--initial-branch=main", str(seed), cwd=tmp_path)
    (seed / "README.md").write_text("what the seed holds\n", encoding="utf-8")
    commit(seed, "seed the upstream")
    git("remote", "add", "origin", str(bare), cwd=seed)
    git("push", "origin", "main", cwd=seed)
    return bare


@pytest.fixture
def cloned(upstream, tmp_path):
    """Return a main checkout of upstream, with an origin/main to cut from."""
    checkout = tmp_path / "checkout"
    git("clone", str(upstream), str(checkout), cwd=tmp_path)
    return checkout


@pytest.fixture
def watched(repo):
    """Return a main checkout carrying a valid dreamcatcher.toml."""
    (repo / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    return repo


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """Return a factory that puts a stand-in for a program first on the PATH."""
    directory = tmp_path / "fakes"
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
    return partial(fakes.install, directory)
