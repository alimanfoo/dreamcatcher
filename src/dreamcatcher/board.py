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
class Attempt:
    """One session on the board: which attempt it is, and how it is doing.

    Three sessions for one issue are three attempts at one thing, and the
    numbers say so: the oldest attempt is the first, and the newest is the
    last.

    The detail is what the row says beside the standing, in the words the disk
    put it in.
    """

    session: Session
    standing: Standing
    detail: str
    attempt: int
    attempts: int


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
    attempts: list[Attempt]
    queued: list[QueuedIssue]

    def list_standing(self, standing: Standing) -> list[Attempt]:
        """Return the attempts standing there, in the order the board reads them.

        Work that is done reads by when its last round started, most recent
        first, since the last thing to run is the one you were waiting for.
        Everything else reads by issue, with the newest attempt at an issue
        ahead of the older ones.
        """
        found = [one for one in self.attempts if one.standing is standing]
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
        attempts=look.list_attempts(sessions),
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

    def list_attempts(self, sessions: list[Session]) -> list[Attempt]:
        """Return every session as an attempt at its issue, newest attempt first.

        A session's key opens with its issue and closes with the time it was
        cut, so sorting by key puts the attempts at one issue together and in
        the order they were made. The board shows the newest of them first, and
        each says which of how many it is.
        """
        by_issue: dict[int, list[Session]] = {}
        for session in sorted(sessions, key=lambda one: one.key):
            by_issue.setdefault(session.record.issue, []).append(session)
        found = []
        for issue in sorted(by_issue):
            made = by_issue[issue]
            for attempt, session in reversed(list(enumerate(made, start=1))):
                found.append(self._read_attempt(session, attempt, len(made)))
        return found

    def _read_attempt(self, session: Session, attempt: int, attempts: int) -> Attempt:
        """Return the session as one attempt at its issue, where it stands."""
        standing, detail = self._judge_standing(session)
        return Attempt(
            session=session,
            standing=standing,
            detail=detail,
            attempt=attempt,
            attempts=attempts,
        )

    def _judge_standing(self, session: Session) -> tuple[Standing, str]:
        """Return where the session's own rounds put it, and what its row says.

        The records answer first, and they answer whatever the daemon is doing.
        A round that recorded no ending is running while a daemon is there to
        run it, and interrupted once that daemon has gone, because a round
        cannot outlive its daemon.
        """
        unfinished = session.describe_unfinished_round()
        if unfinished is not None:
            if self.daemon_pid is not None and session.rounds[-1].ending is None:
                return Standing.WORKING, self._describe_live_round(session)
            return Standing.WAITING, unfinished
        if session.has_run_final_round:
            return Standing.DONE, describe_count(len(session.rounds), "round")
        return self._judge_wait(session)

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

    def _describe_live_round(self, session: Session) -> str:
        """Return what the running round last said, and how long ago it said it."""
        line = self._read_last_said(session)
        if line is None:
            return f"round {len(session.rounds)} has said nothing yet"
        return f"{line.text.strip()}, {describe_span(self.at - line.at)} ago"

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
    still calls it eligible, and by the time anyone reads the board it has an
    attempt of its own to read instead.
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
