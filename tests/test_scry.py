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
from dreamcatcher.feed import Line
from dreamcatcher.rounds import Cause, Ending, RoundRecord
from dreamcatcher.scry import open_console, show_board
from dreamcatcher.state import (
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
    """A round that started that minute past the pinned hour and ended well."""
    started = PINNED + timedelta(minutes=minute)
    return RoundRecord(
        started=started, pid=1, cause=cause, ending=Ending(at=started, status=status)
    )


def running(minute: int = 0):
    """A round that started and has recorded no ending."""
    return RoundRecord(
        started=PINNED + timedelta(minutes=minute), pid=1, cause=Cause.POSTS
    )


def holding(state):
    """Write the lock, so the board reads a daemon as holding this repo."""
    write_text(f"{DAEMON_PID}\n", state.lock)


def fabricate_nothing(state):
    """A state directory a daemon has bootstrapped and nothing else."""
    state.bootstrap()


def fabricate_everything(state):
    """A daemon running, with a session in every standing and a queue behind."""
    holding(state)
    write_feed(written(state, 13, running()), 1, Line(PINNED, "[Bash] pytest"))
    write_feed(written(state, 20, ended(1)), 1, Line(PINNED, "[Bash] git push"))
    written(state, 31, ended(1))
    written(state, 35, ended(1, status=2))
    written(state, 9, ended(1))
    written(state, 12, ended(1), ended(2, cause=Cause.FINAL))
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
    write_feed(written(state, 13, running()), 1, Line(PINNED, "[Bash] pytest"))
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
    write_tick(state, LastTick(at=PINNED + timedelta(hours=1, minutes=58)))


BOARDS = {
    "nothing": fabricate_nothing,
    "everything": fabricate_everything,
    "dead-daemon": fabricate_a_dead_daemon,
    "at-cap": fabricate_the_cap,
    "repeat-attempts": fabricate_repeat_attempts,
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


def test_the_console_scry_opens_writes_where_the_user_is_looking(capsys, tmp_path):
    show_board(StateDirectory(tmp_path), open_console())

    assert "nothing dispatched yet" in capsys.readouterr().out
