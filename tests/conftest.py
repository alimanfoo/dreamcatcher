"""What the whole suite shares: the encoding gate, a repo, a config, stand-ins."""

import json
import os
import shutil
import sys
from collections.abc import Sequence
from contextlib import suppress
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import fakes
import psutil
import pytest
from clocks import PINNED

from dreamcatcher.commands import run_command, spawn_command
from dreamcatcher.config import _DREAMCATCHER_CONFIG_NAME

ARMING = "PYTHONWARNDEFAULTENCODING"
REGENERATE_VIEW_GOLDENS_OPTION = "--regenerate-view-goldens"


# The directory holding everything the suite reads back from a recording: the
# streams a harness wrote, and what gh answered about a pull request.
FIXTURES = Path(__file__).parent / "fixtures"

# The repository the tests say gh names this checkout as.
REPOSITORY = "alimanfoo/dreamcatcher"

# The pull request the tests ask gh about, and the account that wrote every
# post on it that the recording of it holds.
PULL_REQUEST = 52

POSTED_BY = "alimanfoo"

DAEMON_PID = 4242

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

# The assignment label that the blocks below map, as the tests name it.
ASSIGNMENT_LABEL = "dream:smith"

# When the tests say an issue was filed, and a time after it.
FILED = "2026-08-19T18:41:58Z"

LATER = "2026-08-20T09:00:00Z"

SMITH_CLAUDE = """[[assignment]]
label = "dream:smith"
[assignment.claude]
prompt = "/dream:smith GH{issue}"
model = "opus[1m]"
effort = "xhigh"
"""

SMITH_CODEX = """[assignment.codex]
prompt = "$dream:smith GH{issue}"
model = "gpt-5.6-sol"
effort = "xhigh"
"""

CONFIG = SMITH_CLAUDE + SMITH_CODEX


@pytest.fixture
def daemon(monkeypatch):
    """Answer that the fabricated daemon, and nothing else, is still running."""

    def fabricated_process(pid, /):
        if pid != DAEMON_PID:
            raise psutil.NoSuchProcess(pid)
        return SimpleNamespace(create_time=lambda: PINNED.timestamp())

    monkeypatch.setattr(psutil, "Process", fabricated_process)


def pytest_addoption(parser: pytest.Parser, /) -> None:
    """Add the view-golden regeneration option that pytest calls by position."""
    parser.addoption(
        REGENERATE_VIEW_GOLDENS_OPTION,
        action="store_true",
        help="rewrite every rendered-view golden before checking it",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Stop before collection when the interpreter is not arming the gate."""
    if os.environ.get(ARMING) != "1":
        raise pytest.UsageError(
            f"Set {ARMING}=1 when you run pytest. Without it the interpreter "
            "never emits EncodingWarning, so the UTF-8 gate is inert."
        )


def assert_matches_view_golden(
    *, rendered: str, path: Path, config: pytest.Config
) -> None:
    """Check a rendered view, rewriting its golden when explicitly requested."""
    if config.getoption(REGENERATE_VIEW_GOLDENS_OPTION):
        path.write_bytes(rendered.encode("utf-8"))
    assert rendered == path.read_text(encoding="utf-8")


def streamed(**fields: object) -> str:
    """Return the line a harness streams one event as."""
    return json.dumps(fields)


def listing(*, issues: Sequence[tuple[int, str]]) -> str:
    """Return what gh answers an issue listing with."""
    return json.dumps(
        [
            {
                "number": number,
                "title": f"Issue {number}",
                "createdAt": created,
                "state": "OPEN",
                "assignees": [{"login": POSTED_BY}],
                "labels": [{"name": ASSIGNMENT_LABEL}],
            }
            for number, created in issues
        ]
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
        "body": "this reads the delivery cursor twice",
        "path": "src/dreamcatcher/relay.py",
        "subject_type": "line",
        "side": "RIGHT",
        "line": 3,
        "diff_hunk": HUNK,
    } | fields


def pull_requests(*, listed: Sequence[tuple[int, str]]) -> str:
    """Return what gh answers a pull request listing with."""
    return json.dumps(
        [
            {"number": number, "state": state, "isDraft": state == "OPEN"}
            for number, state in listed
        ]
    )


def pull_request(
    *, state: str, number: int = PULL_REQUEST, is_draft: bool = False
) -> str:
    """Return what gh answers when reading one pull request."""
    return json.dumps({"number": number, "state": state, "isDraft": is_draft})


def pages(*, items: Sequence[dict]) -> str:
    """Return what gh answers a paginated list with: one page holding these."""
    return json.dumps([list(items)])


def recorded_posts(*, source: str) -> str:
    """Return what gh answered for one post list of the recorded pull request."""
    recording = FIXTURES / "github" / f"pull-request-{PULL_REQUEST}" / f"{source}.json"
    return recording.read_text(encoding="utf-8")


def git(*, arguments: Sequence[str], cwd: Path) -> str:
    """Run git in cwd and return its output, through the tool's own runner."""
    return run_command(program="git", arguments=arguments, cwd=cwd)


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


@pytest.fixture(scope="session")
def seeded_upstream(tmp_path_factory):
    """Build the immutable bare repository that each test copies."""
    directory = tmp_path_factory.mktemp("seeded-upstream")
    bare = directory / "upstream.git"
    git(
        arguments=["init", "--bare", "--initial-branch=main", str(bare)],
        cwd=directory,
    )
    seed = directory / "seed"
    git(arguments=["init", "--initial-branch=main", str(seed)], cwd=directory)
    (seed / "README.md").write_text("what the seed holds\n", encoding="utf-8")
    commit(path=seed, message="seed the upstream")
    git(arguments=["remote", "add", "origin", str(bare)], cwd=seed)
    git(arguments=["push", "origin", "main"], cwd=seed)
    return bare


@pytest.fixture(scope="session")
def seeded_checkout(seeded_upstream, tmp_path_factory):
    """Build the immutable checkout that each test copies."""
    directory = tmp_path_factory.mktemp("seeded-checkout")
    checkout = directory / "checkout"
    git(arguments=["clone", str(seeded_upstream), str(checkout)], cwd=directory)
    return checkout


@pytest.fixture
def cloned(seeded_checkout, seeded_upstream, tmp_path):
    """Return a main checkout of upstream, with an origin/main to cut from."""
    upstream = tmp_path / "upstream.git"
    shutil.copytree(seeded_upstream, upstream)
    checkout = tmp_path / "checkout"
    shutil.copytree(seeded_checkout, checkout)
    git(arguments=["remote", "set-url", "origin", str(upstream)], cwd=checkout)
    return checkout


@pytest.fixture
def watched(repo):
    """Return a main checkout carrying a valid dreamcatcher.toml."""
    (repo / _DREAMCATCHER_CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
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
    child = spawn_command(
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
        stand_in.replies(stdout=pages(items=[]), to=f"api {path}")
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


def configure(*, root, head: str = "") -> None:
    """Write a config for that checkout, with this ahead of its one route."""
    (root / _DREAMCATCHER_CONFIG_NAME).write_text(
        head + SMITH_CLAUDE + SMITH_CODEX, encoding="utf-8"
    )


@pytest.fixture
def gh(fake):
    """A gh that identifies the instance and offers no work."""
    stand_in = fake(program="gh")
    stand_in.replies(stdout=json.dumps({"nameWithOwner": REPOSITORY}), to="repo view")
    stand_in.replies(stdout=json.dumps({"login": POSTED_BY}), to="api user")
    stand_in.replies(stdout="[]", to="issue list")
    stand_in.replies(
        stdout=json.dumps(
            {
                "number": 8,
                "closedByPullRequestsReferences": [],
                "title": "The issue title",
            }
        ),
        to="issue view",
    )
    stand_in.replies(stdout="[]", to="pr list")
    stand_in.replies(
        stdout=f"https://github.com/alimanfoo/dreamcatcher/pull/{PULL_REQUEST}\n",
        to="pr create",
    )
    stand_in.replies(stdout=pull_request(state="OPEN", is_draft=True), to="pr view")
    stand_in.replies(stdout=pages(items=[]), to="api")
    return stand_in


@pytest.fixture
def offered(gh):
    """Return gh offering one labelled issue that is free for assignment."""
    gh.replies(stdout=listing(issues=[(8, FILED)]), to="issue list")
    return gh


@pytest.fixture
def ready_repo(cloned, offered, harnesses):
    """Return a checkout that can create an assignment for a labelled issue."""
    configure(root=cloned)
    harnesses["claude"].streams(
        lines=[
            fakes.Line(
                text=streamed(
                    type="system",
                    subtype="init",
                    model="claude-opus-5",
                    session_id="abc-123",
                )
                + "\n"
            ),
            fakes.Line(text="what the round said\n"),
        ]
    )
    return cloned
