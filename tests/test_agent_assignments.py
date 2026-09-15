from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import CONFIG, commit, git
from records import write_agent_assignment, write_round

from dreamcatcher.agent_assignments import (
    WATERMARK,
    AgentAssignmentRecord,
    advance_assignment_watermark,
    create_agent_assignment,
    read_agent_assignments,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.documents import write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.rounds import Cause, Ending, RoundRecord, Workspace
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH12-20260819-184158"

BRANCH = f"dreamcatcher-{ASSIGNMENT_ID}"


@pytest.fixture
def checkout(cloned):
    """A main checkout with an origin to cut from and a config to dispatch by."""
    (cloned / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    return cloned


@pytest.fixture
def state(checkout):
    """The state directory of that checkout."""
    return StateDirectory(root=checkout)


@pytest.fixture
def fabricated(tmp_path):
    """A state directory holding records alone, with no checkout behind it."""
    return StateDirectory(root=tmp_path)


@pytest.fixture
def route(checkout):
    """The dispatch route of the one label that the config maps."""
    return read_config(root=checkout).dispatch[0]


def written(*, state):
    """Return the record that the assignment wrote about itself."""
    record = state.assignments / ASSIGNMENT_ID / "assignment.json"
    return AgentAssignmentRecord.model_validate_json(record.read_text(encoding="utf-8"))


def test_an_assignment_cuts_a_worktree_of_its_own_under_the_state_directory(
    state, route
):
    assignment = create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )

    assert assignment.identifier == ASSIGNMENT_ID
    assert assignment.record.worktree == state.worktrees / ASSIGNMENT_ID
    assert (assignment.record.worktree / "README.md").exists()


def test_an_assignment_cuts_a_branch_of_its_own_from_origins_main_as_it_is_now(
    state, route
):
    # Move origin's main on, then leave the checkout believing what it knew
    # before. Only a fetch of its own brings the creation the newer main.
    known = git(arguments=["rev-parse", "origin/main"], cwd=state.root).strip()
    (state.root / "later.txt").write_text("main moved on\n", encoding="utf-8")
    commit(path=state.root, message="move main on")
    git(arguments=["push", "origin", "main"], cwd=state.root)
    git(arguments=["update-ref", "refs/remotes/origin/main", known], cwd=state.root)

    assignment = create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )

    assert assignment.record.branch == BRANCH
    assert BRANCH in git(arguments=["branch", "--list", BRANCH], cwd=state.root)
    assert (assignment.record.worktree / "later.txt").exists()


def test_an_assignment_records_what_it_was_dispatched_with(state, route):
    assignment = create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )

    assert written(state=state) == assignment.record
    assert assignment.record.issue == 12
    assert assignment.record.label == "dream:smith"
    assert assignment.record.harness == Harness.CLAUDE
    assert assignment.record.model == "opus[1m]"
    assert assignment.record.effort == "xhigh"
    assert assignment.record.prompt.startswith("/dream:smith GH12\n")


def test_an_assignment_runs_on_the_harness_the_run_named(state, route):
    assignment = create_agent_assignment(
        state=state, route=route, named=Harness.CODEX, issue=12, at=PINNED
    )

    assert assignment.record.harness == Harness.CODEX
    assert assignment.record.model == "gpt-5.6-sol"
    assert assignment.record.prompt.startswith("$dream:smith GH12\n")


def test_a_new_assignment_has_run_no_rounds_and_its_next_is_its_first(state, route):
    assignment = create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )

    assert assignment.rounds == []
    assert assignment.next_workspace == Workspace(
        worktree=assignment.record.worktree,
        directory=state.assignments / ASSIGNMENT_ID / "rounds" / "1",
    )


def standing(*, state, rounds: Sequence[RoundRecord]):
    """Return the assignment that these rounds leave behind, read back from disk."""
    directory = write_agent_assignment(state=state, identifier=ASSIGNMENT_ID, issue=12)
    for number, record in enumerate(rounds, start=1):
        write_round(directory=directory, number=number, record=record)
    return read_agent_assignments(state=state)[0]


def ended(*, status, minute=0):
    """Return a round that started that minute past the hour and ended."""
    started = PINNED + timedelta(minutes=minute)
    return RoundRecord(
        started=started,
        pid=1,
        cause=Cause.DISPATCH,
        ending=Ending(at=started, status=status),
    )


def running(*, minute=0):
    """Return a round that started that minute past the hour and is still going."""
    return RoundRecord(
        started=PINNED + timedelta(minutes=minute), pid=1, cause=Cause.DISPATCH
    )


def test_a_round_an_assignment_has_run_is_found_by_the_number_it_ran_as(fabricated):
    assignment = standing(
        state=fabricated, rounds=[ended(status=0), ended(status=0, minute=1)]
    )

    assert assignment.workspace(number=2) == Workspace(
        worktree=assignment.record.worktree,
        directory=fabricated.assignments / ASSIGNMENT_ID / "rounds" / "2",
    )


def test_an_assignment_that_has_run_no_round_has_left_nothing_unfinished(fabricated):
    assignment = standing(state=fabricated, rounds=[])

    assert assignment.describe_unfinished_round() is None
    assert not assignment.has_run_final_round


def test_an_assignment_whose_last_round_was_interrupted_says_so(fabricated):
    assignment = standing(state=fabricated, rounds=[running()])

    assert assignment.describe_unfinished_round() == "the last round was interrupted"


def test_an_assignment_whose_last_round_failed_says_the_status_it_failed_with(
    fabricated,
):
    assignment = standing(state=fabricated, rounds=[ended(status=2)])

    assert assignment.describe_unfinished_round() == "the last round failed (exit 2)"


def test_an_assignment_whose_last_round_ended_well_has_left_nothing_unfinished(
    fabricated,
):
    assignment = standing(
        state=fabricated, rounds=[ended(status=1), ended(status=0, minute=1)]
    )

    assert assignment.describe_unfinished_round() is None


def test_an_assignment_that_has_run_its_final_round_says_so(fabricated):
    assignment = standing(
        state=fabricated,
        rounds=[
            ended(status=0),
            RoundRecord(
                started=PINNED + timedelta(minutes=1),
                pid=1,
                cause=Cause.FINAL,
                ending=Ending(at=PINNED + timedelta(minutes=1), status=0),
            ),
        ],
    )

    assert assignment.has_run_final_round


def endings(*, state):
    """Return how each round of the state directory's one assignment ended."""
    return [record.ending for record in read_agent_assignments(state=state)[0].rounds]


def test_a_second_read_does_not_open_a_round_record_it_has_already_read(fabricated):
    directory = write_agent_assignment(
        state=fabricated, identifier=ASSIGNMENT_ID, issue=12
    )
    write_round(directory=directory, number=1, record=ended(status=0))
    write_round(directory=directory, number=2, record=running(minute=1))
    read_agent_assignments(state=fabricated)

    # Rewriting the first round's record puts something there that only a read
    # of that file could find. A reader that has read it does not look again.
    write_round(directory=directory, number=1, record=ended(status=2))

    assert endings(state=fabricated) == [ended(status=0).ending, None]


def test_a_second_read_carries_an_ending_that_landed_since_the_first(fabricated):
    directory = write_agent_assignment(
        state=fabricated, identifier=ASSIGNMENT_ID, issue=12
    )
    write_round(directory=directory, number=1, record=running())
    read_agent_assignments(state=fabricated)

    write_round(directory=directory, number=1, record=ended(status=0))

    assert endings(state=fabricated) == [ended(status=0).ending]


def test_a_second_read_finds_a_round_that_has_started_since_the_first(fabricated):
    directory = write_agent_assignment(
        state=fabricated, identifier=ASSIGNMENT_ID, issue=12
    )
    write_round(directory=directory, number=1, record=ended(status=0))
    read_agent_assignments(state=fabricated)

    write_round(directory=directory, number=2, record=running(minute=1))

    read = read_agent_assignments(state=fabricated)[0]

    assert [record.started for record in read.rounds] == [
        PINNED,
        PINNED + timedelta(minutes=1),
    ]


def test_a_round_that_ended_as_a_later_round_started_reads_back_ended(fabricated):
    directory = write_agent_assignment(
        state=fabricated, identifier=ASSIGNMENT_ID, issue=12
    )
    write_round(directory=directory, number=1, record=running())
    read_agent_assignments(state=fabricated)

    # The first round ended, and the round that carried its work on started,
    # so the record that ended is no longer the assignment's newest.
    write_round(directory=directory, number=1, record=ended(status=0))
    write_round(directory=directory, number=2, record=running(minute=1))

    assert endings(state=fabricated) == [ended(status=0).ending, None]


def test_an_assignment_git_cannot_cut_leaves_no_branch_behind(state, route):
    # git makes the branch, then finds something already in the worktree's
    # place and stops. The worktree it never made cannot be removed, so the
    # back-out takes what git did leave.
    occupied = state.worktrees / ASSIGNMENT_ID
    occupied.mkdir(parents=True)
    (occupied / "in the way.txt").write_text("not ours\n", encoding="utf-8")

    with pytest.raises(CommandError):
        create_agent_assignment(
            state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
        )

    assert git(arguments=["branch", "--list", BRANCH], cwd=state.root) == ""


def test_an_assignment_that_cannot_record_leaves_no_worktree_and_no_branch(
    state, route
):
    state.assignments.mkdir(parents=True)
    (state.assignments / ASSIGNMENT_ID).write_text(
        "something else is here\n", encoding="utf-8"
    )

    with pytest.raises(ReportableError, match="cannot write"):
        create_agent_assignment(
            state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
        )

    assert not (state.worktrees / ASSIGNMENT_ID).exists()
    assert git(arguments=["branch", "--list", BRANCH], cwd=state.root) == ""


def test_a_state_directory_with_no_worktrees_holds_no_assignments(state):
    assert read_agent_assignments(state=state) == []


def test_an_assignment_reads_back_as_it_was_dispatched(state, route):
    created = create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )

    assert read_agent_assignments(state=state) == [created]


def test_an_assignment_no_round_has_told_anything_yet_has_seen_no_post(state, route):
    create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )

    assert read_agent_assignments(state=state)[0].watermark == ""


def test_an_assignment_reads_back_the_newest_post_it_has_been_told_about(state, route):
    create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )
    write_text(
        text="2026-09-03T22:31:51Z\n",
        path=state.assignments / ASSIGNMENT_ID / WATERMARK,
    )

    assert read_agent_assignments(state=state)[0].watermark == "2026-09-03T22:31:51Z"


def test_an_assignment_told_about_a_batch_of_posts_reads_the_newest_of_them_back(
    state, route
):
    created = create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )

    advance_assignment_watermark(assignment=created, newest="2026-09-03T22:31:51Z")

    assert read_agent_assignments(state=state)[0].watermark == "2026-09-03T22:31:51Z"


def test_an_assignments_rounds_read_back_in_the_order_they_ran(state, route):
    create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )
    later = PINNED.replace(minute=50)
    directory = state.assignments / ASSIGNMENT_ID
    write_round(
        directory=directory,
        number=2,
        record=RoundRecord(started=later, pid=1, cause=Cause.DISPATCH),
    )
    write_round(
        directory=directory,
        number=1,
        record=RoundRecord(
            started=PINNED,
            pid=1,
            cause=Cause.DISPATCH,
            ending=Ending(at=later, status=0),
        ),
    )

    read = read_agent_assignments(state=state)[0]

    assert [record.started for record in read.rounds] == [PINNED, later]
    assert (
        read.next_workspace.directory
        == state.assignments / ASSIGNMENT_ID / "rounds" / "3"
    )


def test_every_assignment_of_the_repo_reads_back_by_identifier(state, route):
    create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )
    create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=3, at=PINNED
    )

    assert [
        assignment.identifier for assignment in read_agent_assignments(state=state)
    ] == [
        "GH12-20260819-184158",
        "GH3-20260819-184158",
    ]


def test_a_file_left_among_the_worktrees_is_not_an_assignment(state, route):
    created = create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )
    (state.worktrees / ".DS_Store").write_text("a file browser\n", encoding="utf-8")

    assert read_agent_assignments(state=state) == [created]


def test_a_worktree_with_no_record_beside_it_is_not_an_assignment(state, route):
    created = create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )
    (state.worktrees / "GH3-20260819-184158").mkdir()

    assert read_agent_assignments(state=state) == [created]


def test_an_assignment_record_that_will_not_read_names_the_file(state, route):
    create_agent_assignment(
        state=state, route=route, named=Harness.CLAUDE, issue=12, at=PINNED
    )
    (state.assignments / ASSIGNMENT_ID / "assignment.json").write_text(
        "{}", encoding="utf-8"
    )

    with pytest.raises(ReportableError, match=r"assignment\.json is not valid"):
        read_agent_assignments(state=state)
