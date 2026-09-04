import pytest
from clocks import PINNED
from conftest import CONFIG, commit, git
from records import write_round

from dreamcatcher.commands import CommandError
from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.errors import ReportableError
from dreamcatcher.rounds import RoundRecord, Workspace
from dreamcatcher.sessions import SessionRecord, create_session, read_sessions
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
    assert session.record.worktree == state.worktrees / KEY
    assert (session.record.worktree / "README.md").exists()


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

    assert session.record.branch == BRANCH
    assert BRANCH in git("branch", "--list", BRANCH, cwd=state.root)
    assert (session.record.worktree / "later.txt").exists()


def test_a_session_records_what_it_was_dispatched_with(state, mapping):
    session = create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert written(state) == session.record
    assert session.record.issue == 12
    assert session.record.label == "dream:smith"
    assert session.record.harness == Harness.CLAUDE
    assert session.record.model == "opus[1m]"
    assert session.record.effort == "xhigh"
    assert session.record.prompt.startswith("/dream:smith GH12\n")


def test_a_session_runs_on_the_harness_the_run_named(state, mapping):
    session = create_session(state, mapping, Harness.CODEX, 12, PINNED)

    assert session.record.harness == Harness.CODEX
    assert session.record.model == "gpt-5.6-sol"
    assert session.record.prompt.startswith("$dream:smith GH12\n")


def test_a_new_session_has_run_no_rounds_and_its_next_is_its_first(state, mapping):
    session = create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert session.rounds == []
    assert session.next_workspace == Workspace(
        session.record.worktree, state.sessions / KEY / "rounds" / "1"
    )


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


def test_a_state_directory_with_no_worktrees_holds_no_sessions(state):
    assert read_sessions(state) == []


def test_a_session_reads_back_as_it_was_dispatched(state, mapping):
    created = create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert read_sessions(state) == [created]


def test_a_sessions_rounds_read_back_in_the_order_they_ran(state, mapping):
    create_session(state, mapping, Harness.CLAUDE, 12, PINNED)
    later = PINNED.replace(minute=50)
    directory = state.sessions / KEY
    write_round(directory, 2, RoundRecord(started=later, pid=1, cause="dispatched"))
    write_round(
        directory,
        1,
        RoundRecord(started=PINNED, pid=1, cause="dispatched", ended=later, status=0),
    )

    read = read_sessions(state)[0]

    assert [record.started for record in read.rounds] == [PINNED, later]
    assert read.next_workspace.directory == state.sessions / KEY / "rounds" / "3"


def test_every_session_of_the_repo_reads_back_by_key(state, mapping):
    create_session(state, mapping, Harness.CLAUDE, 12, PINNED)
    create_session(state, mapping, Harness.CLAUDE, 3, PINNED)

    assert [session.key for session in read_sessions(state)] == [
        "GH12-20260819-184158",
        "GH3-20260819-184158",
    ]


def test_a_file_left_among_the_worktrees_is_not_a_session(state, mapping):
    created = create_session(state, mapping, Harness.CLAUDE, 12, PINNED)
    (state.worktrees / ".DS_Store").write_text("a file browser\n", encoding="utf-8")

    assert read_sessions(state) == [created]


def test_a_session_record_that_will_not_read_names_the_file(state, mapping):
    create_session(state, mapping, Harness.CLAUDE, 12, PINNED)
    (state.sessions / KEY / "session.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ReportableError, match=r"session\.json is not valid"):
        read_sessions(state)
