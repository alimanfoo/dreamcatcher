import os
from datetime import timedelta

import pytest
from clocks import PINNED
from records import write_feed, write_round, write_session, write_tick

from dreamcatcher.board import Standing, read_board, read_rows
from dreamcatcher.feed import Line
from dreamcatcher.rounds import Cause, Ending, RoundRecord
from dreamcatcher.state import (
    NO_ROUND_HAS_RUN,
    CandidateIssue,
    LastTick,
    StateDirectory,
    WaitingSession,
)

KEY = "GH13-20260819-184158"

# When the board is read: two hours after everything the tests write down.
LOOKED_AT = PINNED + timedelta(hours=2)

LABEL = "dream:smith"


@pytest.fixture
def state(tmp_path):
    """A state directory holding one session, with no round run yet."""
    directory = StateDirectory(tmp_path)
    write_session(directory, KEY, 13)
    return directory


@pytest.fixture
def running(state):
    """That state directory, with a daemon of this process's own pid holding it."""
    state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return state


def ran(state, number: int, cause: Cause = Cause.DISPATCH, status: int | None = 0):
    """Write down a round of the session, ended as the status says."""
    started = PINNED + timedelta(minutes=number)
    ending = None if status is None else Ending(at=started, status=status)
    write_round(
        state.sessions / KEY,
        number,
        RoundRecord(started=started, pid=1, cause=cause, ending=ending),
    )


def said(state, number: int, *texts: str):
    """Write down what the session's numbered round said, at the pinned time."""
    write_feed(state.sessions / KEY, number, *(Line(PINNED, text) for text in texts))


def looked(state):
    """Read the board off that state directory, at the pinned looking time."""
    return read_board(state, clock=lambda: LOOKED_AT)


def only(state):
    """The one row the board found."""
    found = looked(state).rows
    assert len(found) == 1
    return found[0]


def rows_at(state, issue: int):
    """Read the rows for that issue alone, at the pinned looking time."""
    return read_rows(state, issue, clock=lambda: LOOKED_AT)


def test_the_rows_for_an_issue_are_its_own_sessions_newest_first(running):
    ran(running, 1)
    other = write_session(running, "GH99-20260819-184158", 99)
    write_round(other, 1, RoundRecord(started=PINNED, pid=1, cause=Cause.DISPATCH))

    assert [row.session.record.issue for row in rows_at(running, 13)] == [13]


def test_an_issue_no_session_here_has_holds_no_rows(state):
    assert rows_at(state, 99) == []


def test_a_look_at_one_issue_leaves_another_session_s_feed_unread(running):
    ran(running, 1, status=None)
    said(running, 1, "[Bash] pytest")
    other = write_session(running, "GH99-20260819-184158", 99)
    write_round(other, 1, RoundRecord(started=PINNED, pid=1, cause=Cause.DISPATCH))
    # Bytes that are not UTF-8 stand for a feed that a look must not open,
    # since reading this one would report it rather than answer.
    (other / "rounds" / "1" / "feed.txt").write_bytes(b"\xff\n")

    assert rows_at(running, 13)[0].last_output == "[Bash] pytest"


def test_a_state_directory_nothing_has_run_in_yet_holds_an_empty_board(tmp_path):
    board = read_board(StateDirectory(tmp_path), clock=lambda: LOOKED_AT)

    assert board.at == LOOKED_AT
    assert board.daemon_pid is None
    assert board.tick is None
    assert board.rows == []
    assert board.queued == []


def test_the_daemon_holding_the_repo_is_the_one_the_lock_names(running):
    assert looked(running).daemon_pid == os.getpid()


def test_a_round_a_running_daemon_has_not_ended_is_the_agent_working(running):
    ran(running, 1, status=None)
    said(running, 1, "[Bash] pytest")

    row = only(running)

    assert row.standing is Standing.WORKING
    assert row.detail == "last output 2h 0m ago"
    assert row.last_output == "[Bash] pytest"


def test_a_running_round_that_has_said_nothing_yet_says_that(running):
    ran(running, 1, status=None)

    row = only(running)

    assert row.detail == "has said nothing yet"
    assert row.last_output is None


def test_a_round_with_no_daemon_left_to_run_it_is_waiting(state):
    ran(state, 1, status=None)

    assert only(state).standing is Standing.WAITING
    assert only(state).detail == "the last round was interrupted"


def test_a_round_that_failed_waits_with_the_status_it_failed_with(running):
    ran(running, 1, status=2)

    assert only(running).standing is Standing.WAITING
    assert only(running).detail == "the last round failed (exit 2)"


def test_a_session_whose_final_round_has_run_is_done(state):
    ran(state, 1)
    ran(state, 2, Cause.FINAL)

    assert only(state).standing is Standing.DONE
    assert only(state).detail == "2 rounds"


def test_a_session_done_in_one_round_counts_that_round_as_one(state):
    ran(state, 1, Cause.FINAL)

    assert only(state).detail == "1 round"


def test_a_session_the_tick_found_nothing_to_do_for_needs_you(state):
    ran(state, 1)
    said(state, 1, "[Bash] pytest")
    write_tick(state, LastTick(at=PINNED))

    assert only(state).standing is Standing.NEEDS_YOU
    assert only(state).detail == "idle 2h 0m"


def test_a_session_that_wrote_no_feed_at_all_is_idle_for_who_knows_how_long(state):
    ran(state, 1)

    assert only(state).standing is Standing.NEEDS_YOU
    assert only(state).detail == "idle"


def test_a_session_the_tick_left_waiting_says_what_it_waits_on(state):
    ran(state, 1)
    write_tick(
        state,
        LastTick(
            at=PINNED,
            waiting=[
                WaitingSession(session=KEY, issue=13, reason="1 new post to answer")
            ],
        ),
    )

    assert only(state).standing is Standing.WAITING
    assert only(state).detail == "1 new post to answer"


def test_a_stuck_session_says_where_to_read_what_it_did(state):
    ran(state, 1)
    write_tick(
        state,
        LastTick(
            at=PINNED,
            waiting=[
                WaitingSession(
                    session=KEY,
                    issue=13,
                    reason="no pull request has been opened on it",
                    is_stuck=True,
                )
            ],
        ),
    )

    assert only(state).standing is Standing.STUCK
    assert only(state).detail == (
        "no pull request has been opened on it "
        f"(.dreamcatcher/sessions/{KEY}/rounds/1/feed.txt)"
    )


def test_a_stuck_session_that_ran_no_round_has_no_feed_to_point_at(state):
    write_tick(
        state,
        LastTick(
            at=PINNED,
            waiting=[
                WaitingSession(
                    session=KEY,
                    issue=13,
                    reason=NO_ROUND_HAS_RUN,
                    is_stuck=True,
                )
            ],
        ),
    )

    assert only(state).standing is Standing.STUCK
    assert only(state).detail == "no round has run yet"


def test_a_session_no_tick_has_weighed_and_no_round_has_run_is_stuck(state):
    assert only(state).standing is Standing.STUCK
    assert only(state).detail == NO_ROUND_HAS_RUN


def test_the_sessions_at_one_issue_read_as_sessions_newest_first(state):
    write_session(state, "GH13-20260820-090000", 13)
    write_session(state, "GH9-20260819-184158", 9)

    rows = looked(state).rows

    assert [row.session.key for row in rows] == [
        "GH9-20260819-184158",
        "GH13-20260820-090000",
        "GH13-20260819-184158",
    ]


def test_the_work_that_is_done_reads_most_recent_first(state):
    write_session(state, "GH9-20260819-184158", 9)
    ran(state, 1, Cause.FINAL)
    write_round(
        state.sessions / "GH9-20260819-184158",
        1,
        RoundRecord(
            started=PINNED + timedelta(hours=1),
            pid=1,
            cause=Cause.FINAL,
            ending=Ending(at=PINNED + timedelta(hours=1), status=0),
        ),
    )

    done = looked(state).list_standing(Standing.DONE)

    assert [row.session.record.issue for row in done] == [9, 13]


def test_the_sessions_in_one_standing_come_back_in_the_boards_own_order(state):
    write_session(state, "GH9-20260819-184158", 9)

    waiting = looked(state).list_standing(Standing.STUCK)

    assert [row.session.record.issue for row in waiting] == [9, 13]


def test_the_queue_reads_each_issues_turn_off_its_place(state):
    write_tick(
        state,
        LastTick(
            at=PINNED,
            candidates=[
                CandidateIssue(issue=20, label=LABEL),
                CandidateIssue(issue=21, label=LABEL),
                CandidateIssue(issue=22, label=LABEL),
                CandidateIssue(issue=23, label=LABEL, reason="blocked by GH20"),
            ],
        ),
    )

    assert [(one.issue, one.reason) for one in looked(state).queued] == [
        (20, "next"),
        (21, "behind 1 other"),
        (22, "behind 2 others"),
        (23, "blocked by GH20"),
    ]


def test_an_issue_a_session_here_already_claims_is_not_queued(state):
    write_tick(
        state,
        LastTick(
            at=PINNED,
            candidates=[
                CandidateIssue(issue=13, label=LABEL),
                CandidateIssue(issue=20, label=LABEL),
            ],
        ),
    )

    assert [(one.issue, one.reason) for one in looked(state).queued] == [(20, "next")]
