import pytest
from clocks import PINNED
from conftest import CONFIG, git

from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.errors import ReportableError
from dreamcatcher.sessions import Session, create
from dreamcatcher.state import StateDirectory

KEY = "GH12-20260819-184158"

BRANCH = f"dreamcatcher-{KEY}"


@pytest.fixture
def checkout(cloned):
    """A main checkout with an origin to cut from and a config to dispatch by."""
    (cloned / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    return cloned


@pytest.fixture
def state(checkout):
    """The state directory of that checkout."""
    return StateDirectory(checkout)


@pytest.fixture
def mapping(checkout):
    """The dispatch mapping of the one label the config maps."""
    return read_config(checkout).dispatch[0]


def written(state):
    """Return what the session recorded about its own dispatch."""
    record = state.sessions / KEY / "session.json"
    return Session.model_validate_json(record.read_text(encoding="utf-8"))


def test_a_session_cuts_a_worktree_of_its_own_under_the_state_directory(state, mapping):
    session = create(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert session.key == KEY
    assert session.worktree == state.worktrees / KEY
    assert (session.worktree / "README.md").exists()


def test_a_session_cuts_a_branch_of_its_own_from_origins_main_as_it_is_now(
    state, mapping
):
    git("update-ref", "-d", "refs/remotes/origin/main", cwd=state.root)

    session = create(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert session.branch == BRANCH
    assert BRANCH in git("branch", "--list", BRANCH, cwd=state.root)


def test_a_session_records_what_its_dispatch_fixed(state, mapping):
    session = create(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert written(state) == session
    assert session.issue == 12
    assert session.label == "dream:smith"
    assert session.harness == Harness.CLAUDE
    assert session.model == "opus[1m]"
    assert session.effort == "xhigh"
    assert session.prompt.startswith("/dream:smith GH12\n")


def test_a_session_runs_on_the_harness_the_run_named(state, mapping):
    session = create(state, mapping, Harness.CODEX, 12, PINNED)

    assert session.harness == Harness.CODEX
    assert session.model == "gpt-5.6-sol"
    assert session.prompt.startswith("$dream:smith GH12\n")


def test_a_session_that_cannot_record_leaves_no_worktree_and_no_branch(state, mapping):
    state.sessions.mkdir(parents=True)
    (state.sessions / KEY).write_text("something else is here\n", encoding="utf-8")

    with pytest.raises(ReportableError, match="cannot write"):
        create(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert not (state.worktrees / KEY).exists()
    assert git("branch", "--list", BRANCH, cwd=state.root) == ""
