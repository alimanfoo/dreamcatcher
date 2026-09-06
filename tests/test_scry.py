"""Render every board a state directory can hold, and read back the goldens.

The goldens are the review surface: read one as the person running `scry` would
read it, and judge the view by it rather than by the code that wrote it.

Each state directory here is fabricated, so the clock, the console's width and
the daemon's pid are all pinned and every run and every platform renders the
same text.
"""

from datetime import timedelta
from io import StringIO

import psutil
import pytest
from clocks import PINNED
from conftest import FIXTURES, LABEL
from records import write_feed, write_round, write_session, write_tick
from rich.console import Console

from dreamcatcher.documents import write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import Line
from dreamcatcher.rounds import Cause, Ending, RoundRecord
from dreamcatcher.scry import (
    PAUSE,
    show_board,
    show_feed,
    show_round,
    show_session,
)
from dreamcatcher.state import (
    NO_ROUND_HAS_RUN,
    CandidateIssue,
    LastTick,
    StateDirectory,
    WaitingSession,
)

# When a view is rendered: two hours after the last thing on the disk happened.
LOOKED_AT = PINNED + timedelta(hours=2)

# How wide the console is, so a line wraps in the same place every run.
WIDTH = 100

# The pid the fabricated lock names, and the one the stand-in psutil says is
# alive. A real pid would differ from run to run and no golden could hold it.
DAEMON_PID = 4242

STAMP = "20260819-184158"

# What one round of a session said, as its feed holds it. A subagent's lines
# are set in from the rest, and a line that is not a feed line at all is what a
# harness printed on its stderr.
SAID = (
    Line(PINNED + timedelta(minutes=1), "[session] model opus[1m], id 7f3c9a"),
    Line(PINNED + timedelta(minutes=2), "I will read the issue first."),
    Line(PINNED + timedelta(minutes=2), "[Read] specs/2026-08-17-skeleton/plan.md"),
    Line(PINNED + timedelta(minutes=3), "  [Bash] ls"),
    Line(PINNED + timedelta(minutes=3), "[failed] no such file or directory"),
    Line(
        PINNED + timedelta(minutes=5),
        "[usage] $0.1772, 455 output, 8 input, 123529 cache read, 8606 cache write",
    ),
    Line(PINNED + timedelta(minutes=5), "[result] success"),
)

# What a tick writes down against an issue carrying two mapped labels.
DOUBLE_LABELLED = "carries more than one mapped label: dream:less, dream:smith"


@pytest.fixture
def daemon(monkeypatch):
    """Answer that the fabricated daemon, and nothing else, is still running."""
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == DAEMON_PID)


def written(state, issue: int, *records: RoundRecord):
    """Write a session for the issue, with these rounds behind it."""
    directory = write_session(state, f"GH{issue}-{STAMP}", issue)
    for number, record in enumerate(records, start=1):
        write_round(directory, number, record)
    return directory


def ended(minute: int, status: int = 0, cause: Cause = Cause.DISPATCH):
    """A round that started that minute past the pinned hour and ran for four."""
    started = PINNED + timedelta(minutes=minute)
    return RoundRecord(
        started=started,
        pid=1,
        cause=cause,
        ending=Ending(at=started + timedelta(minutes=4), status=status),
    )


def running(minute: int, cause: Cause = Cause.DISPATCH):
    """A round that started that minute past the pinned hour and is still going."""
    return RoundRecord(started=PINNED + timedelta(minutes=minute), pid=1, cause=cause)


def holding(state):
    """Write the lock, so the board reads a daemon as holding this repo."""
    write_text(f"{DAEMON_PID}\n", state.lock)


def fabricate_nothing(state):
    """A state directory a daemon has bootstrapped and nothing else."""
    state.bootstrap()


def fabricate_everything(state):
    """A daemon running, with a session in every standing and a queue behind."""
    holding(state)
    directory = written(state, 13, ended(1), running(30, cause=Cause.POSTS))
    write_feed(directory, 1, *SAID)
    write_feed(directory, 2, Line(PINNED + timedelta(minutes=31), "[Bash] pytest"))
    write_feed(written(state, 20, ended(1)), 1, Line(PINNED, "[Bash] git push"))
    written(state, 31, ended(1))
    written(state, 35, ended(1, status=2))
    written(state, 9, ended(1))
    written(state, 12, ended(1), ended(2, cause=Cause.FINAL))
    written(state, 44)
    write_tick(
        state,
        LastTick(
            at=PINNED + timedelta(hours=1, minutes=58),
            launched=f"GH13-{STAMP}",
            candidates=[
                CandidateIssue(issue=50, label=LABEL),
                CandidateIssue(issue=51, label=LABEL),
                CandidateIssue(issue=52, label=LABEL, reason="blocked by GH50"),
                CandidateIssue(issue=53, label=LABEL, reason=DOUBLE_LABELLED),
            ],
            waiting=[
                WaitingSession(
                    session=f"GH31-{STAMP}", issue=31, reason="1 new post to answer"
                ),
                WaitingSession(
                    session=f"GH35-{STAMP}",
                    issue=35,
                    reason="the last round failed (exit 2)",
                ),
                WaitingSession(
                    session=f"GH9-{STAMP}",
                    issue=9,
                    reason="no pull request has been opened on it",
                    is_stuck=True,
                ),
                WaitingSession(
                    session=f"GH44-{STAMP}",
                    issue=44,
                    reason=NO_ROUND_HAS_RUN,
                    is_stuck=True,
                ),
            ],
        ),
    )


def fabricate_a_dead_daemon(state):
    """The same sessions, with the daemon that was running them gone."""
    fabricate_everything(state)
    state.lock.unlink()


def fabricate_the_cap(state):
    """A daemon at its cap, which peeked at nothing and holds every session."""
    holding(state)
    write_feed(written(state, 13, running(30)), 1, Line(PINNED, "[Bash] pytest"))
    written(state, 20, ended(1))
    hold = "at cap: 1 of 1 rounds running"
    write_tick(
        state,
        LastTick(
            at=PINNED + timedelta(hours=1, minutes=58),
            hold=hold,
            waiting=[WaitingSession(session=f"GH20-{STAMP}", issue=20, reason=hold)],
        ),
    )


def fabricate_repeat_attempts(state):
    """Three attempts at one issue, so a repeat dispatch reads as one thing."""
    for stamp, rounds in (
        ("20260817-090000", (ended(1), ended(2, cause=Cause.FINAL))),
        ("20260818-090000", (ended(1), ended(2, cause=Cause.FINAL))),
        ("20260819-184158", (ended(1),)),
    ):
        directory = write_session(state, f"GH13-{stamp}", 13)
        for number, record in enumerate(rounds, start=1):
            write_round(directory, number, record)
        write_feed(directory, len(rounds), Line(PINNED, "[Bash] git push"))
    write_tick(state, LastTick(at=PINNED + timedelta(hours=1, minutes=58)))


BOARDS = {
    "nothing": fabricate_nothing,
    "everything": fabricate_everything,
    "dead-daemon": fabricate_a_dead_daemon,
    "at-cap": fabricate_the_cap,
    "repeat-attempts": fabricate_repeat_attempts,
}


# The feed view each fabricated state directory is worth reading, by the issue
# whose newest attempt it shows.
FEEDS = {
    "feed-working": (fabricate_everything, 13),
    "feed-older-attempts": (fabricate_repeat_attempts, 13),
}


# The session view each fabricated state directory is worth reading, by the
# issue whose newest attempt it shows.
SESSIONS = {
    "session-working": (fabricate_everything, 13),
    "session-older-attempts": (fabricate_repeat_attempts, 13),
    "session-stuck": (fabricate_everything, 9),
    "session-never-started": (fabricate_everything, 44),
}


def rendered(state) -> str:
    """Return the board that state directory renders as, on a pinned console."""
    written_to = StringIO()
    show_board(
        state,
        Console(file=written_to, width=WIDTH),
        clock=lambda: LOOKED_AT,
    )
    return written_to.getvalue()


@pytest.mark.parametrize("name", sorted(BOARDS))
def test_a_state_directory_renders_as_its_golden_board(name, tmp_path, daemon):
    state = StateDirectory(tmp_path)
    BOARDS[name](state)

    board = rendered(state)

    assert board == (FIXTURES / "board" / f"{name}.txt").read_text(encoding="utf-8")


def viewed(state, issue: int) -> str:
    """Return the session view that issue renders as, on a pinned console."""
    written_to = StringIO()
    show_session(
        state, issue, Console(file=written_to, width=WIDTH), clock=lambda: LOOKED_AT
    )
    return written_to.getvalue()


@pytest.mark.parametrize("name", sorted(SESSIONS))
def test_a_session_renders_as_its_golden_view(name, tmp_path, daemon):
    state = StateDirectory(tmp_path)
    fabricate, issue = SESSIONS[name]
    fabricate(state)

    view = viewed(state, issue)

    assert view == (FIXTURES / "board" / f"{name}.txt").read_text(encoding="utf-8")


def followed(state, issue: int, wait=lambda seconds: None) -> str:
    """Return the feed view that issue renders as, on a pinned console."""
    written_to = StringIO()
    show_feed(
        state,
        issue,
        Console(file=written_to, width=WIDTH),
        wait=wait,
        clock=lambda: LOOKED_AT,
    )
    return written_to.getvalue()


@pytest.mark.parametrize("name", sorted(FEEDS))
def test_a_feed_renders_as_its_golden_view(name, tmp_path, daemon):
    state = StateDirectory(tmp_path)
    fabricate, issue = FEEDS[name]
    fabricate(state)

    feed = followed(state, issue, wait=lambda seconds: state.lock.unlink())

    assert feed == (FIXTURES / "board" / f"{name}.txt").read_text(encoding="utf-8")


def test_a_following_view_waits_while_a_round_is_still_running(tmp_path, daemon):
    state = StateDirectory(tmp_path)
    fabricate_everything(state)
    waits = []

    def wait(seconds):
        waits.append(seconds)
        state.lock.unlink()

    followed(state, 13, wait=wait)

    assert waits == [PAUSE]


def test_a_round_that_starts_while_the_view_is_going_arrives_in_it(tmp_path, daemon):
    state = StateDirectory(tmp_path)
    fabricate_everything(state)
    directory = state.sessions / f"GH13-{STAMP}"

    def wait(seconds):
        write_round(directory, 3, running(60, cause=Cause.CARRY_ON))
        write_feed(directory, 3, Line(PINNED, "[Bash] git push"))
        state.lock.unlink()

    feed = followed(state, 13, wait=wait)

    assert "round 3: carried on" in feed
    assert feed.count("round 1: dispatched") == 1


def test_a_view_of_a_session_no_daemon_is_running_never_waits(tmp_path):
    state = StateDirectory(tmp_path)
    fabricate_a_dead_daemon(state)
    waits = []

    followed(state, 13, wait=waits.append)

    assert waits == []


def test_a_write_that_never_landed_waits_for_the_look_that_shows_it_whole(
    tmp_path, daemon
):
    state = StateDirectory(tmp_path)
    fabricate_everything(state)
    feed = state.sessions / f"GH13-{STAMP}" / "rounds" / "2" / "feed.txt"

    def wait(seconds):
        feed.write_text(
            feed.read_text(encoding="utf-8") + "2026-08-19T18:41:58Z  [Grep] pypro",
            encoding="utf-8",
        )
        state.lock.unlink()

    assert "[Grep]" not in followed(state, 13, wait=wait)


def test_a_line_the_view_cannot_read_reaches_the_reader_as_it_was_written(
    tmp_path, daemon
):
    state = StateDirectory(tmp_path)
    fabricate_everything(state)
    write_text(
        "the harness said something else\n",
        state.sessions / f"GH13-{STAMP}" / "rounds" / "2" / "feed.txt",
    )

    feed = followed(state, 13, wait=lambda seconds: state.lock.unlink())

    assert "the harness said something else" in feed


def viewed_round(state, issue: int, number: int) -> str:
    """Return the view of one round of that issue, on a pinned console."""
    written_to = StringIO()
    show_round(
        state,
        issue,
        number,
        Console(file=written_to, width=WIDTH),
        clock=lambda: LOOKED_AT,
    )
    return written_to.getvalue()


def test_one_round_of_a_session_reads_on_its_own(tmp_path, daemon):
    state = StateDirectory(tmp_path)
    fabricate_everything(state)

    assert viewed_round(state, 13, 2) == (
        "2026-08-19T19:11:58Z  round 2: new posts\n"
        "2026-08-19T19:12:58Z  [Bash] pytest\n"
    )


def test_a_round_that_wrote_no_feed_shows_the_line_that_opens_it(tmp_path, daemon):
    state = StateDirectory(tmp_path)
    fabricate_everything(state)

    assert viewed_round(state, 12, 1) == "2026-08-19T18:42:58Z  round 1: dispatched\n"


def test_a_round_the_session_never_ran_says_how_many_it_did(tmp_path, daemon):
    state = StateDirectory(tmp_path)
    fabricate_everything(state)

    with pytest.raises(ReportableError, match="has run 2 rounds"):
        viewed_round(state, 13, 7)


def test_an_issue_no_session_here_has_says_so(tmp_path):
    with pytest.raises(ReportableError, match="GH99"):
        viewed(StateDirectory(tmp_path), 99)
