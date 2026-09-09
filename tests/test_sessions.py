from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import CONFIG, commit, git
from records import write_round, write_session

from dreamcatcher.commands import CommandError
from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.documents import write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.rounds import Cause, Ending, RoundRecord, Workspace
from dreamcatcher.sessions import (
    WATERMARK,
    SessionRecord,
    advance_watermark,
    create_session,
    read_sessions,
)
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
def fabricated(tmp_path):
    """A state directory holding records alone, with no checkout behind it."""
    return StateDirectory(tmp_path)


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


def standing(state, *rounds):
    """Return the session that these rounds leave behind, read back from disk."""
    directory = write_session(state, KEY, 12)
    for number, record in enumerate(rounds, start=1):
        write_round(directory, number, record)
    return read_sessions(state)[0]


def ended(status, minute=0):
    """Return a round that started that minute past the hour and ended."""
    started = PINNED + timedelta(minutes=minute)
    return RoundRecord(
        started=started,
        pid=1,
        cause=Cause.DISPATCH,
        ending=Ending(at=started, status=status),
    )


def running(minute=0):
    """Return a round that started that minute past the hour and is still going."""
    return RoundRecord(
        started=PINNED + timedelta(minutes=minute), pid=1, cause=Cause.DISPATCH
    )


def test_a_round_a_session_has_run_is_found_by_the_number_it_ran_as(fabricated):
    session = standing(fabricated, ended(0), ended(0, minute=1))

    assert session.workspace(2) == Workspace(
        session.record.worktree, fabricated.sessions / KEY / "rounds" / "2"
    )


def test_a_session_that_has_run_no_round_has_left_nothing_unfinished(fabricated):
    session = standing(fabricated)

    assert session.describe_unfinished_round() is None
    assert not session.has_run_final_round


def test_a_session_whose_last_round_was_interrupted_says_so(fabricated):
    session = standing(fabricated, running())

    assert session.describe_unfinished_round() == "the last round was interrupted"


def test_a_session_whose_last_round_failed_says_the_status_it_failed_with(fabricated):
    session = standing(fabricated, ended(2))

    assert session.describe_unfinished_round() == "the last round failed (exit 2)"


def test_a_session_whose_last_round_ended_well_has_left_nothing_unfinished(fabricated):
    session = standing(fabricated, ended(1), ended(0, minute=1))

    assert session.describe_unfinished_round() is None


def test_a_session_that_has_run_its_final_round_says_so(fabricated):
    session = standing(
        fabricated,
        ended(0),
        RoundRecord(
            started=PINNED + timedelta(minutes=1),
            pid=1,
            cause=Cause.FINAL,
            ending=Ending(at=PINNED + timedelta(minutes=1), status=0),
        ),
    )

    assert session.has_run_final_round


def endings(state):
    """Return how each round of the state directory's one session ended."""
    return [record.ending for record in read_sessions(state)[0].rounds]


def test_a_second_read_does_not_open_a_round_record_it_has_already_read(fabricated):
    directory = write_session(fabricated, KEY, 12)
    write_round(directory, 1, ended(0))
    write_round(directory, 2, running(minute=1))
    read_sessions(fabricated)

    # Rewriting the first round's record puts something there that only a read
    # of that file could find. A reader that has read it does not look again.
    write_round(directory, 1, ended(2))

    assert endings(fabricated) == [ended(0).ending, None]


def test_a_second_read_carries_an_ending_that_landed_since_the_first(fabricated):
    directory = write_session(fabricated, KEY, 12)
    write_round(directory, 1, running())
    read_sessions(fabricated)

    write_round(directory, 1, ended(0))

    assert endings(fabricated) == [ended(0).ending]


def test_a_second_read_finds_a_round_that_has_started_since_the_first(fabricated):
    directory = write_session(fabricated, KEY, 12)
    write_round(directory, 1, ended(0))
    read_sessions(fabricated)

    write_round(directory, 2, running(minute=1))

    read = read_sessions(fabricated)[0]

    assert [record.started for record in read.rounds] == [
        PINNED,
        PINNED + timedelta(minutes=1),
    ]


def test_a_round_that_ended_as_a_later_round_started_reads_back_ended(fabricated):
    directory = write_session(fabricated, KEY, 12)
    write_round(directory, 1, running())
    read_sessions(fabricated)

    # The first round ended, and the round that carried its work on started,
    # so the record that ended is no longer the session's newest.
    write_round(directory, 1, ended(0))
    write_round(directory, 2, running(minute=1))

    assert endings(fabricated) == [ended(0).ending, None]


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


def test_a_session_no_round_has_told_anything_yet_has_seen_no_post(state, mapping):
    create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    assert read_sessions(state)[0].watermark == ""


def test_a_session_reads_back_the_newest_post_it_has_been_told_about(state, mapping):
    create_session(state, mapping, Harness.CLAUDE, 12, PINNED)
    write_text("2026-09-03T22:31:51Z\n", state.sessions / KEY / WATERMARK)

    assert read_sessions(state)[0].watermark == "2026-09-03T22:31:51Z"


def test_a_session_told_about_a_batch_of_posts_reads_the_newest_of_them_back(
    state, mapping
):
    created = create_session(state, mapping, Harness.CLAUDE, 12, PINNED)

    advance_watermark(created, "2026-09-03T22:31:51Z")

    assert read_sessions(state)[0].watermark == "2026-09-03T22:31:51Z"


def test_a_sessions_rounds_read_back_in_the_order_they_ran(state, mapping):
    create_session(state, mapping, Harness.CLAUDE, 12, PINNED)
    later = PINNED.replace(minute=50)
    directory = state.sessions / KEY
    write_round(directory, 2, RoundRecord(started=later, pid=1, cause=Cause.DISPATCH))
    write_round(
        directory,
        1,
        RoundRecord(
            started=PINNED,
            pid=1,
            cause=Cause.DISPATCH,
            ending=Ending(at=later, status=0),
        ),
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


def test_a_worktree_with_no_record_beside_it_is_not_a_session(state, mapping):
    created = create_session(state, mapping, Harness.CLAUDE, 12, PINNED)
    (state.worktrees / "GH3-20260819-184158").mkdir()

    assert read_sessions(state) == [created]


def test_a_session_record_that_will_not_read_names_the_file(state, mapping):
    create_session(state, mapping, Harness.CLAUDE, 12, PINNED)
    (state.sessions / KEY / "session.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ReportableError, match=r"session\.json is not valid"):
        read_sessions(state)
