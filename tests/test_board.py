import os
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from observations import observed_issue
from records import write_agent_assignment, write_feed, write_round, write_tick

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    RoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.board import AgentAssignmentStanding, read_board, read_rows_for_issue
from dreamcatcher.feed import Line
from dreamcatcher.state import (
    NO_ROUND_HAS_RUN,
    IssueFactValue,
    LastTick,
    StateDirectory,
    WaitingAgentAssignment,
)

ASSIGNMENT_ID = "GH13-20260819-184158"

# When the board is read: two hours after everything the tests write down.
LOOKED_AT = PINNED + timedelta(hours=2)

LABEL = "dream:smith"


@pytest.fixture
def state(tmp_path):
    """A state directory holding one assignment, with no round run yet."""
    directory = StateDirectory(root=tmp_path)
    write_agent_assignment(state=directory, identifier=ASSIGNMENT_ID, issue=13)
    return directory


@pytest.fixture
def running(state):
    """That state directory, with a daemon of this process's own pid holding it."""
    state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return state


def ran(
    *,
    state,
    number: int,
    purpose: RoundPurpose = RoundPurpose.IMPLEMENT,
    status: int | None = 0,
):
    """Write down a round of the assignment, ended as the status says.

    A round that ended ran for four minutes, so a line its feed holds landed
    while the round was still going rather than after it had finished.
    """
    started = PINNED + timedelta(minutes=number)
    ending = (
        None
        if status is None
        else compose_agent_round_ending(
            at=started + timedelta(minutes=4), status=status
        )
    )
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=number,
        record=AgentRoundRecord(
            number=number,
            purpose=purpose,
            started=started,
            pid=1,
            ending=ending,
        ),
    )


def said(*, state, number: int, texts: Sequence[str]):
    """Write down what the assignment's numbered round said, a minute after it began.

    A round says nothing before it starts, so a feed line written at the
    pinned hour itself would read as one that landed before its own round.
    """
    at = PINNED + timedelta(minutes=number + 1)
    write_feed(
        directory=state.assignments / ASSIGNMENT_ID,
        number=number,
        lines=[Line(at=at, text=text) for text in texts],
    )


def looked(*, state):
    """Read the board off that state directory, at the pinned looking time."""
    return read_board(state=state, clock=lambda: LOOKED_AT)


def only(*, state):
    """The one row the board found."""
    found = looked(state=state).rows
    assert len(found) == 1
    return found[0]


def rows_at(*, state, issue: int):
    """Read the rows for that issue alone, at the pinned looking time."""
    return read_rows_for_issue(state=state, issue=issue, clock=lambda: LOOKED_AT)


def test_the_rows_for_an_issue_are_its_own_assignments_newest_first(running):
    ran(state=running, number=1)
    other = write_agent_assignment(
        state=running, identifier="GH99-20260819-184158", issue=99
    )
    write_round(
        directory=other,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, pid=1, purpose=RoundPurpose.IMPLEMENT
        ),
    )

    assert [
        row.assignment.record.issue for row in rows_at(state=running, issue=13)
    ] == [13]


def test_an_issue_no_assignment_here_has_holds_no_rows(state):
    assert rows_at(state=state, issue=99) == []


def test_a_look_at_one_issue_leaves_another_assignment_s_feed_unread(running):
    ran(state=running, number=1, status=None)
    said(state=running, number=1, texts=["[Bash] pytest"])
    other = write_agent_assignment(
        state=running, identifier="GH99-20260819-184158", issue=99
    )
    write_round(
        directory=other,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, pid=1, purpose=RoundPurpose.IMPLEMENT
        ),
    )
    # Bytes that are not UTF-8 stand for a feed that a look must not open,
    # since reading this one would report it rather than answer.
    (other / "rounds" / "1" / "feed.txt").write_bytes(b"\xff\n")

    assert rows_at(state=running, issue=13)[0].last_output == "[Bash] pytest"


def test_a_state_directory_nothing_has_run_in_yet_holds_an_empty_board(tmp_path):
    board = read_board(state=StateDirectory(root=tmp_path), clock=lambda: LOOKED_AT)

    assert board.at == LOOKED_AT
    assert board.daemon_pid is None
    assert board.tick is None
    assert board.rows == []
    assert board.queued == []


def test_the_daemon_holding_the_repo_is_the_one_the_lock_names(running):
    assert looked(state=running).daemon_pid == os.getpid()


def test_a_round_a_running_daemon_has_not_ended_is_the_agent_working(running):
    ran(state=running, number=1, status=None)
    said(state=running, number=1, texts=["[Bash] pytest"])

    row = only(state=running)

    assert row.standing is AgentAssignmentStanding.WORKING
    assert row.detail == "running 1h 59m, last output 1h 58m ago"
    assert row.last_output == "[Bash] pytest"


def test_a_running_round_that_has_said_nothing_yet_says_that(running):
    ran(state=running, number=1, status=None)

    row = only(state=running)

    assert row.detail == "running 1h 59m, has said nothing yet"
    assert row.last_output is None


def test_a_round_with_no_daemon_left_to_run_it_is_waiting(state):
    ran(state=state, number=1, status=None)

    assert only(state=state).standing is AgentAssignmentStanding.WAITING
    assert only(state=state).detail == "the last round was interrupted"


def test_a_round_that_failed_waits_with_the_status_it_failed_with(running):
    ran(state=running, number=1, status=2)

    assert only(state=running).standing is AgentAssignmentStanding.WAITING
    assert only(state=running).detail == "the last round failed (exit 2)"


def test_an_assignment_whose_wrap_up_succeeded_is_done(state):
    ran(state=state, number=1)
    ran(state=state, number=2, purpose=RoundPurpose.WRAP_UP)

    assert only(state=state).standing is AgentAssignmentStanding.DONE
    assert only(state=state).detail == "2 rounds"


def test_an_assignment_whose_wrap_up_failed_is_waiting_to_recover(running):
    ran(
        state=running,
        number=1,
        purpose=RoundPurpose.WRAP_UP,
        status=2,
    )

    assert only(state=running).standing is AgentAssignmentStanding.WAITING
    assert only(state=running).detail == "the last round failed (exit 2)"


def test_an_assignment_done_in_one_round_counts_that_round_as_one(state):
    ran(state=state, number=1, purpose=RoundPurpose.WRAP_UP)

    assert only(state=state).detail == "1 round"


def test_an_assignment_the_tick_found_nothing_to_do_for_needs_you(state):
    ran(state=state, number=1)
    said(state=state, number=1, texts=["[Bash] pytest"])
    write_tick(state=state, tick=LastTick(at=PINNED))

    assert only(state=state).standing is AgentAssignmentStanding.NEEDS_YOU
    assert only(state=state).detail == "idle 1h 58m"


def test_an_assignment_that_wrote_no_feed_at_all_is_idle_for_who_knows_how_long(state):
    ran(state=state, number=1)

    assert only(state=state).standing is AgentAssignmentStanding.NEEDS_YOU
    assert only(state=state).detail == "idle"


def test_an_assignment_the_tick_left_waiting_says_what_it_waits_on(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=LastTick(
            at=PINNED,
            waiting=[
                WaitingAgentAssignment(
                    assignment=ASSIGNMENT_ID, issue=13, reason="1 new post to answer"
                )
            ],
        ),
    )

    assert only(state=state).standing is AgentAssignmentStanding.WAITING
    assert only(state=state).detail == "1 new post to answer"


def test_a_stuck_assignment_says_where_to_read_what_it_did(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=LastTick(
            at=PINNED,
            waiting=[
                WaitingAgentAssignment(
                    assignment=ASSIGNMENT_ID,
                    issue=13,
                    reason="no pull request has been opened on it",
                    is_stuck=True,
                )
            ],
        ),
    )

    assert only(state=state).standing is AgentAssignmentStanding.STUCK
    assert only(state=state).detail == (
        "no pull request has been opened on it "
        f"(.dreamcatcher/assignments/{ASSIGNMENT_ID}/rounds/1/feed.txt)"
    )


def test_a_stuck_assignment_that_ran_no_round_has_no_feed_to_point_at(state):
    write_tick(
        state=state,
        tick=LastTick(
            at=PINNED,
            waiting=[
                WaitingAgentAssignment(
                    assignment=ASSIGNMENT_ID,
                    issue=13,
                    reason=NO_ROUND_HAS_RUN,
                    is_stuck=True,
                )
            ],
        ),
    )

    assert only(state=state).standing is AgentAssignmentStanding.STUCK
    assert only(state=state).detail == "no round has run yet"


def test_an_assignment_no_tick_has_weighed_and_no_round_has_run_is_waiting(state):
    assert only(state=state).standing is AgentAssignmentStanding.WAITING
    assert only(state=state).detail == NO_ROUND_HAS_RUN


def test_the_assignments_at_one_issue_read_as_assignments_newest_first(state):
    write_agent_assignment(state=state, identifier="GH13-20260820-090000", issue=13)
    write_agent_assignment(state=state, identifier="GH9-20260819-184158", issue=9)

    rows = looked(state=state).rows

    assert [row.assignment.identifier for row in rows] == [
        "GH9-20260819-184158",
        "GH13-20260820-090000",
        "GH13-20260819-184158",
    ]


def test_the_work_that_is_done_reads_most_recent_first(state):
    write_agent_assignment(state=state, identifier="GH9-20260819-184158", issue=9)
    ran(state=state, number=1, purpose=RoundPurpose.WRAP_UP)
    write_round(
        directory=state.assignments / "GH9-20260819-184158",
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED + timedelta(hours=1),
            pid=1,
            purpose=RoundPurpose.WRAP_UP,
            ending=compose_agent_round_ending(at=PINNED + timedelta(hours=1), status=0),
        ),
    )

    done = looked(state=state).list_rows_for_standing(
        standing=AgentAssignmentStanding.DONE
    )

    assert [row.assignment.record.issue for row in done] == [9, 13]


def test_the_assignments_in_one_standing_come_back_in_the_boards_own_order(state):
    write_agent_assignment(state=state, identifier="GH9-20260819-184158", issue=9)

    waiting = looked(state=state).list_rows_for_standing(
        standing=AgentAssignmentStanding.WAITING
    )

    assert [row.assignment.record.issue for row in waiting] == [9, 13]


def test_the_queue_reads_each_issues_turn_off_its_place(state):
    write_tick(
        state=state,
        tick=LastTick(
            at=PINNED,
            issue_observations=[
                observed_issue(issue=20),
                observed_issue(issue=21),
                observed_issue(issue=22),
                observed_issue(
                    issue=23,
                    values={"blocked": IssueFactValue.TRUE},
                    evidence={"blocked": "blocked by GH20"},
                ),
                observed_issue(issue=24, dispatch_labels=()),
            ],
        ),
    )

    assert [(one.issue, one.reason) for one in looked(state=state).queued] == [
        (20, "next"),
        (21, "behind 1 other"),
        (22, "behind 2 others"),
        (23, "blocked by GH20"),
    ]


def test_an_issue_an_assignment_here_already_claims_is_not_queued(state):
    write_tick(
        state=state,
        tick=LastTick(
            at=PINNED,
            issue_observations=[
                observed_issue(issue=13),
                observed_issue(issue=20),
            ],
        ),
    )

    assert [(one.issue, one.reason) for one in looked(state=state).queued] == [
        (20, "next")
    ]


def test_a_completed_assignment_no_longer_claims_its_issue_on_the_board(state):
    ran(state=state, number=1, purpose=RoundPurpose.WRAP_UP)
    write_tick(
        state=state,
        tick=LastTick(
            at=PINNED,
            issue_observations=[
                observed_issue(issue=13),
                observed_issue(issue=20),
            ],
        ),
    )

    assert [(one.issue, one.reason) for one in looked(state=state).queued] == [
        (13, "next"),
        (20, "behind 1 other"),
    ]
