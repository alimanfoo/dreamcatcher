import pytest
from clocks import PINNED
from conftest import CONFIG, commit, git

from dreamcatcher.commands import CommandError
from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.errors import ReportableError
from dreamcatcher.sessions import SessionRecord, create_session
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
    """The dispatch mapping of the one label that the config maps."""
    return read_config(checkout).dispatch[0]


def written(state):
    """Return the record that the session wrote about itself."""
    record = state.sessions / KEY / "session.json"
    return SessionRecord.model_validate_json(record.read_text(encoding="utf-8"))


def test_a_session_cuts_a_worktree_of_its_own_under_the_state_directory(state, mapping):
    session = create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert session.key == KEY
    assert session.worktree == state.worktrees / KEY
    assert (session.worktree / "README.md").exists()


def test_a_session_cuts_a_branch_of_its_own_from_origins_main_as_it_is_now(
    state, mapping
):
    # Move origin's main on, then leave the checkout believing what it knew
    # before. Only a fetch of its own brings the creation the newer main.
    known = git("rev-parse", "origin/main", cwd=state.root).strip()
    (state.root / "later.txt").write_text("main moved on\n", encoding="utf-8")
    commit(state.root, "move main on")
    git("push", "origin", "main", cwd=state.root)
    git("update-ref", "refs/remotes/origin/main", known, cwd=state.root)

    session = create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert session.branch == BRANCH
    assert BRANCH in git("branch", "--list", BRANCH, cwd=state.root)
    assert (session.worktree / "later.txt").exists()


def test_a_session_records_what_it_was_dispatched_with(state, mapping):
    session = create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert written(state) == session
    assert session.issue == 12
    assert session.label == "dream:smith"
    assert session.harness == Harness.CLAUDE
    assert session.model == "opus[1m]"
    assert session.effort == "xhigh"
    assert session.prompt.startswith("/dream:smith GH12\n")


def test_a_session_runs_on_the_harness_the_run_named(state, mapping):
    session = create_session(state, mapping, Harness.CODEX, 12, PINNED)

    assert session.harness == Harness.CODEX
    assert session.model == "gpt-5.6-sol"
    assert session.prompt.startswith("$dream:smith GH12\n")


def test_a_session_git_cannot_cut_leaves_no_branch_behind(state, mapping):
    # git makes the branch, then finds something already in the worktree's
    # place and stops. The worktree it never made cannot be removed, so the
    # back-out takes what git did leave.
    occupied = state.worktrees / KEY
    occupied.mkdir(parents=True)
    (occupied / "in the way.txt").write_text("not ours\n", encoding="utf-8")

    with pytest.raises(CommandError):
        create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert git("branch", "--list", BRANCH, cwd=state.root) == ""


def test_a_session_that_cannot_record_leaves_no_worktree_and_no_branch(state, mapping):
    state.sessions.mkdir(parents=True)
    (state.sessions / KEY).write_text("something else is here\n", encoding="utf-8")

    with pytest.raises(ReportableError, match="cannot write"):
        create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert not (state.worktrees / KEY).exists()
    assert git("branch", "--list", BRANCH, cwd=state.root) == ""
