"""What the whole suite shares: the encoding gate, a repo, a config, stand-ins."""

import json
import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from functools import partial
from pathlib import Path

import fakes
import psutil
import pytest

from dreamcatcher.commands import run, spawn
from dreamcatcher.config import CONFIG_NAME

ARMING = "PYTHONWARNDEFAULTENCODING"

CONFIG_HEAD = """interval = 300

"""

# The directory holding everything the suite reads back from a recording: the
# streams a harness wrote, and what gh answered about a pull request.
FIXTURES = Path(__file__).parent / "fixtures"

# The repository the tests say gh names this checkout as.
REPOSITORY = "alimanfoo/dreamcatcher"

# The pull request the tests ask gh about, and the account that wrote every
# post on it that the recording of it holds.
PULL_REQUEST = 52

POSTED_BY = "alimanfoo"

# When the tests say the user posted on that pull request, and the piece of the
# diff that they wrote an inline comment against.
POSTED_AT = "2026-09-03T22:19:55Z"

HUNK = (
    '@@ -0,0 +1,3 @@\n+"""Carry what the user posts."""\n'
    "+\n+from dreamcatcher import github"
)

# Where gh keeps each of the three lists that a pull request's posts arrive in.
# Each is named as the recording of it is named.
POST_LIST_PATHS = {
    "conversation": f"repos/{REPOSITORY}/issues/{PULL_REQUEST}/comments?per_page=100",
    "reviews": f"repos/{REPOSITORY}/pulls/{PULL_REQUEST}/reviews?per_page=100",
    "inline-comments": f"repos/{REPOSITORY}/pulls/{PULL_REQUEST}/comments?per_page=100",
}

# The label that the dispatch blocks below map, as the tests name it.
LABEL = "dream:smith"

# When the tests say an issue was filed, and a time after it.
FILED = "2026-08-19T18:41:58Z"

LATER = "2026-08-20T09:00:00Z"

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


def streamed(**fields: object) -> str:
    """Return the line a harness streams one event as."""
    return json.dumps(fields)


def listing(*, issues: Sequence[tuple[int, str]]) -> str:
    """Return what gh answers an issue listing with."""
    return json.dumps(
        [{"number": number, "createdAt": created} for number, created in issues]
    )


def comment(**fields: object) -> dict:
    """What gh answers one comment on the pull request's conversation with."""
    return {
        "id": 1,
        "user": {"login": POSTED_BY},
        "created_at": POSTED_AT,
        "body": "have another look at the filter",
    } | fields


def review(**fields: object) -> dict:
    """What gh answers one review with."""
    return {
        "id": 2,
        "user": {"login": POSTED_BY},
        "submitted_at": POSTED_AT,
        "body": "",
        "state": "COMMENTED",
    } | fields


def inline_comment(**fields: object) -> dict:
    """What gh answers one comment on a line of the diff with."""
    return {
        "id": 3,
        "user": {"login": POSTED_BY},
        "created_at": POSTED_AT,
        "body": "this reads the watermark twice",
        "path": "src/dreamcatcher/relay.py",
        "subject_type": "line",
        "side": "RIGHT",
        "line": 3,
        "diff_hunk": HUNK,
    } | fields


def pull_requests(*, listed: Sequence[tuple[int, str]]) -> str:
    """Return what gh answers a pull request listing with."""
    return json.dumps([{"number": number, "state": state} for number, state in listed])


def pull_request(*, state: str, number: int = PULL_REQUEST) -> str:
    """Return what gh answers when reading one pull request."""
    return json.dumps({"number": number, "state": state})


def pages(*, posts: Sequence[dict]) -> str:
    """Return what gh answers a paginated list with: one page holding these."""
    return json.dumps([list(posts)])


def recorded_posts(*, source: str) -> str:
    """Return what gh answered for one post list of the recorded pull request."""
    recording = FIXTURES / "github" / f"pull-request-{PULL_REQUEST}" / f"{source}.json"
    return recording.read_text(encoding="utf-8")


def git(*, arguments: Sequence[str], cwd: Path) -> str:
    """Run git in cwd and return its output, through the tool's own runner."""
    return run(program="git", arguments=arguments, cwd=cwd)


def gone(*, pid: int) -> bool:
    """Wait a while for the process at pid to end, and say whether it did."""
    # A process that outstays the wait is a process that is still there, which
    # is the answer, not a failure.
    with suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
        psutil.Process(pid).wait(timeout=30)
    return not psutil.pid_exists(pid)


def commit(*, path: Path, message: str) -> None:
    """Commit everything in the checkout at path, under a throwaway identity."""
    git(arguments=["add", "--all"], cwd=path)
    git(
        arguments=[
            "-c",
            "user.name=A Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--message",
            message,
        ],
        cwd=path,
    )


@pytest.fixture
def repo(tmp_path):
    """Return a main checkout of a fresh, empty git repository."""
    git(arguments=["init"], cwd=tmp_path)
    return tmp_path


@pytest.fixture
def upstream(tmp_path):
    """Return a bare repository holding main, standing in for GitHub."""
    bare = tmp_path / "upstream.git"
    git(arguments=["init", "--bare", "--initial-branch=main", str(bare)], cwd=tmp_path)
    seed = tmp_path / "seed"
    git(arguments=["init", "--initial-branch=main", str(seed)], cwd=tmp_path)
    (seed / "README.md").write_text("what the seed holds\n", encoding="utf-8")
    commit(path=seed, message="seed the upstream")
    git(arguments=["remote", "add", "origin", str(bare)], cwd=seed)
    git(arguments=["push", "origin", "main"], cwd=seed)
    return bare


@pytest.fixture
def cloned(upstream, tmp_path):
    """Return a main checkout of upstream, with an origin/main to cut from."""
    checkout = tmp_path / "checkout"
    git(arguments=["clone", str(upstream), str(checkout)], cwd=tmp_path)
    return checkout


@pytest.fixture
def watched(repo):
    """Return a main checkout carrying a valid dreamcatcher.toml."""
    (repo / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    return repo


@pytest.fixture
def stand_ins(tmp_path):
    """The directory holding the stand-in programs that a test installs."""
    return tmp_path / "fakes"


@pytest.fixture
def fake(stand_ins, monkeypatch):
    """Return a factory that puts a stand-in for a program first on the PATH."""
    monkeypatch.setenv("PATH", f"{stand_ins}{os.pathsep}{os.environ['PATH']}")
    return partial(fakes.install, directory=stand_ins)


@pytest.fixture
def left_running(tmp_path):
    """A process standing in for a round left without a recorded ending."""
    child = spawn(
        program=sys.executable,
        arguments=["-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    yield child
    with suppress(OSError):
        child.process.kill()
    child.process.wait()


@pytest.fixture
def gh_with_no_posts(fake):
    """A gh answering each of a pull request's three post lists with no posts.

    A test scripts over the one list it is about, so it carries only the posts
    that it is about.
    """
    stand_in = fake(program="gh")
    for path in POST_LIST_PATHS.values():
        stand_in.replies(stdout=pages(posts=[]), to=f"api {path}")
    return stand_in


@pytest.fixture
def gh_with_recorded_posts(fake):
    """A gh answering each post list with what a real pull request answered."""
    stand_in = fake(program="gh")
    for source, path in POST_LIST_PATHS.items():
        stand_in.replies(stdout=recorded_posts(source=source), to=f"api {path}")
    return stand_in


@pytest.fixture
def harnesses(fake):
    """Both harness CLIs on the PATH, so a run gets past its startup check."""
    return {program: fake(program=program) for program in ("claude", "codex")}


def configure(*, root, head: str = CONFIG_HEAD) -> None:
    """Write a config for that checkout, with this ahead of its one route."""
    (root / CONFIG_NAME).write_text(head + SMITH_CLAUDE + SMITH_CODEX, encoding="utf-8")


@pytest.fixture
def gh(fake):
    """A gh that identifies the instance and offers no work."""
    stand_in = fake(program="gh")
    stand_in.replies(stdout=json.dumps({"nameWithOwner": REPOSITORY}), to="repo view")
    stand_in.replies(stdout=json.dumps({"login": POSTED_BY}), to="api user")
    stand_in.replies(stdout="[]", to="issue list")
    stand_in.replies(
        stdout=json.dumps({"closedByPullRequestsReferences": []}), to="issue view"
    )
    stand_in.replies(stdout="[]", to="pr list")
    stand_in.replies(
        stdout=f"https://github.com/alimanfoo/dreamcatcher/pull/{PULL_REQUEST}\n",
        to="pr create",
    )
    stand_in.replies(
        stdout=json.dumps({"number": PULL_REQUEST, "state": "OPEN"}), to="pr view"
    )
    stand_in.replies(stdout="[]", to="api")
    return stand_in


@pytest.fixture
def offered(gh):
    """Return gh offering one labelled issue that is free to dispatch."""
    gh.replies(stdout=listing(issues=[(8, FILED)]), to="issue list")
    return gh


@pytest.fixture
def dispatching(cloned, offered, harnesses):
    """Return a checkout that can dispatch a labelled issue."""
    configure(root=cloned)
    harnesses["claude"].streams(lines=[fakes.Line(text="what the round said\n")])
    return cloned
