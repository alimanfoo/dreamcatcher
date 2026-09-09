"""What each session and each queued issue is doing, read off the disk.

The board answers "whose turn is it". Every session stands somewhere, and every
labelled issue the last tick weighed has a place in the queue.

Nothing here asks GitHub. What the daemon left behind is the whole story: the
lock says whether a daemon is running, the round records say what each session
has run, and `last-tick.json` says what the records alone cannot, which is
whatever the daemon had to ask GitHub to learn.

Nothing here renders anything either. A caller that has read the board shows
it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dreamcatcher.clock import now
from dreamcatcher.documents import read_json
from dreamcatcher.feed import Line, read_last_feed_line
from dreamcatcher.lock import read_daemon_pid
from dreamcatcher.sessions import Session, read_sessions
from dreamcatcher.state import (
    NO_ROUND_HAS_RUN,
    LastTick,
    StateDirectory,
    WaitingSession,
)
from dreamcatcher.words import describe_count, describe_span


class Standing(StrEnum):
    """Where a session stands, which is the section of the board it reads in.

    The words are the board's own headings, so the section a reader looks under
    and the standing a session is in are one thing.

    A session needs you when the daemon has nothing left to do for it: every
    round it has run finished, its pull request is open, and the agent has
    answered everything posted on it. The next move is the user's, and that
    move is to read the pull request.

    A session is working while a round of its own is running. It is waiting
    when it has a round to run that no daemon has launched yet, and stuck when
    no tick can move it on however long it waits, so that only a person can. It
    is done once it has run the round that winds it up.
    """

    NEEDS_YOU = "needs you"
    WORKING = "agent working"
    WAITING = "waiting"
    STUCK = "stuck"
    DONE = "done"


@dataclass(frozen=True)
class Row:
    """One session on the board, and how it is doing.

    An issue dispatched three times has three sessions at one thing. The board
    reads the newest of them first.

    The detail is what the row says beside the standing, in the words the disk
    put it in. A working session keeps its latest output separate so the view
    can set it apart from that status.
    """

    session: Session
    standing: Standing
    detail: str
    last_output: str | None


@dataclass(frozen=True)
class QueuedIssue:
    """A labelled issue the last tick weighed, and why it has not gone yet.

    An issue with nothing in its way is waiting its turn, and the reason is
    where in the queue that turn is.
    """

    issue: int
    label: str
    reason: str


@dataclass(frozen=True)
class Board:
    """Every session and every queued issue, as one look at the disk found them.

    The pid is the daemon holding this repo, and nothing holds it when no
    daemon is running. The tick is the last one a daemon wrote down, and a
    state directory none has ticked in has none.
    """

    at: datetime
    daemon_pid: int | None
    tick: LastTick | None
    rows: list[Row]
    queued: list[QueuedIssue]

    def list_standing(self, standing: Standing) -> list[Row]:
        """Return the rows standing there, in the order the board reads them.

        Work that is done reads by when its last round started, most recent
        first, since the last thing to run is the one you were waiting for.
        Everything else reads by issue, with the newest session at an issue
        ahead of the older ones.
        """
        found = [one for one in self.rows if one.standing is standing]
        if standing is Standing.DONE:
            return sorted(
                found, key=lambda one: one.session.rounds[-1].started, reverse=True
            )
        return found


def read_board(state: StateDirectory, clock: Callable[[], datetime] = now) -> Board:
    """Return what the state directory says every session and issue is doing."""
    tick = read_json(LastTick, state.last_tick) if state.last_tick.exists() else None
    look = _Look(
        state=state,
        at=clock(),
        daemon_pid=read_daemon_pid(state.lock),
        waits={} if tick is None else {one.session: one for one in tick.waiting},
    )
    sessions = read_sessions(state)
    return Board(
        at=look.at,
        daemon_pid=look.daemon_pid,
        tick=tick,
        rows=look.list_rows(sessions),
        queued=_list_queue(tick, {session.record.issue for session in sessions}),
    )


@dataclass(frozen=True)
class _Look:
    """What one look at the state directory knows before it judges anything.

    Reading the board is one look, so the time it reads, the daemon it found
    and what the last tick said travel together rather than down every call.
    """

    state: StateDirectory
    at: datetime
    daemon_pid: int | None
    waits: dict[str, WaitingSession]

    def list_rows(self, sessions: list[Session]) -> list[Row]:
        """Return a row for every session, the newest session at an issue first.

        A session's key closes with the time the session was cut, so sorting by
        key backwards puts the newest session at an issue ahead of the older
        ones. Sorting that by issue keeps each issue's sessions in the order it
        left them, because a sort in Python holds what it does not reorder.
        """
        newest_first = sorted(sessions, key=lambda one: one.key, reverse=True)
        return [
            self._read_row(session)
            for session in sorted(newest_first, key=lambda one: one.record.issue)
        ]

    def _read_row(self, session: Session) -> Row:
        """Return the session as one row of the board, where it stands."""
        standing, detail, last_output = self._judge_standing(session)
        return Row(
            session=session,
            standing=standing,
            detail=detail,
            last_output=last_output,
        )

    def _judge_standing(self, session: Session) -> tuple[Standing, str, str | None]:
        """Return where the session's own rounds put it, and what its row says.

        The records answer first, and they answer whatever the daemon is doing.
        A round that recorded no ending is running while a daemon is there to
        run it, and interrupted once that daemon has gone, because a round
        cannot outlive its daemon.
        """
        unfinished = session.describe_unfinished_round()
        if unfinished is not None:
            if self.daemon_pid is not None and not session.rounds[-1].is_complete:
                detail, last_output = self._describe_live_round(session)
                return Standing.WORKING, detail, last_output
            return Standing.WAITING, unfinished, None
        if session.has_run_final_round:
            return Standing.DONE, describe_count(len(session.rounds), "round"), None
        standing, detail = self._judge_wait(session)
        return standing, detail, None

    def _judge_wait(self, session: Session) -> tuple[Standing, str]:
        """Return what the last tick left a session its rounds say nothing about.

        Whether a pull request is open, and whether it carries anything new,
        are what the daemon had to ask GitHub, so the tick's own record is the
        only place they are written down. A session the tick wrote nothing
        about is one it found nothing to do for, which leaves it to the user.
        """
        wait = self.waits.get(session.key)
        if wait is None:
            if not session.rounds:
                return Standing.STUCK, NO_ROUND_HAS_RUN
            return Standing.NEEDS_YOU, self._describe_idle(session)
        if wait.is_stuck:
            return Standing.STUCK, self._point_at_feed(session, wait.reason)
        return Standing.WAITING, wait.reason

    def _describe_live_round(self, session: Session) -> tuple[str, str | None]:
        """Return what the running round last said, and how long ago it said it."""
        line = self._read_last_said(session)
        if line is None:
            return "has said nothing yet", None
        return f"last output {describe_span(self.at - line.at)} ago", line.text.strip()

    def _describe_idle(self, session: Session) -> str:
        """Return how long it is since the session last said anything."""
        line = self._read_last_said(session)
        if line is None:
            return "idle"
        return f"idle {describe_span(self.at - line.at)}"

    def _read_last_said(self, session: Session) -> Line | None:
        """Return the last line the session's last round wrote to its feed."""
        return read_last_feed_line(session.workspace(len(session.rounds)).feed)

    def _point_at_feed(self, session: Session, reason: str) -> str:
        """Return what the session waits on, and where to read what it did.

        A stuck session moves no further until a person reads what happened, so
        its row says where that reading is.
        """
        if not session.rounds:
            return reason
        feed = session.workspace(len(session.rounds)).feed
        return f"{reason} ({self.state.describe_path(feed)})"


def _list_queue(tick: LastTick | None, claimed: set[int]) -> list[QueuedIssue]:
    """Return the labelled issues the last tick weighed, in the order they go.

    An issue a session here already claims is not queued: it is that session.
    The tick that dispatched it weighed it before it had one, so its own record
    still calls it eligible, and by the time anyone reads the board it has a
    row of its own to read instead.
    """
    if tick is None:
        return []
    queued = []
    ahead = 0
    for candidate in tick.candidates:
        if candidate.issue in claimed:
            continue
        reason = candidate.reason
        if reason is None:
            reason = _describe_place(ahead)
            ahead += 1
        queued.append(
            QueuedIssue(issue=candidate.issue, label=candidate.label, reason=reason)
        )
    return queued


def _describe_place(ahead: int) -> str:
    """Return where an issue with this many issues ahead of it stands."""
    if ahead == 0:
        return "next"
    return f"behind {describe_count(ahead, 'other')}"
