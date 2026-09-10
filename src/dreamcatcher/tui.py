"""Show what the sessions are doing, from what the daemon left on the disk.

This is the terminal interface, and the whole of it. It holds the three views
a reader reaches through a verb of the command line: the board, one session,
and one session's feed. It reads the state directory and never talks to GitHub
or to the daemon, so it answers whether the daemon is alive or dead, and
answers fastest when you most want to look.

The board and one session are pictures of a state, so each is drawn over the
one before it. A feed is a log, so it is printed as it is read, and the reader
keeps their scrollback.

What the daemon writes stays plain text, and the colour goes on at the moment of
reading.
"""

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from time import sleep
from typing import NamedTuple

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from dreamcatcher.board import (
    Board,
    SessionRow,
    SessionStanding,
    read_board,
    read_rows_for_issue,
)
from dreamcatcher.clock import now
from dreamcatcher.documents import read_lines_from
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import GAP, Line, compose_round_boundary, read_feed_line
from dreamcatcher.harnesses import ADAPTERS
from dreamcatcher.rounds import RoundRecord
from dreamcatcher.sessions import Session
from dreamcatcher.state import StateDirectory
from dreamcatcher.words import describe_count, describe_span, describe_time

# What each section of the board is set in, so a reader finds the one they
# came for without reading the words.
COLOURS = {
    SessionStanding.NEEDS_YOU: "yellow",
    SessionStanding.WORKING: "green",
    SessionStanding.WAITING: "cyan",
    SessionStanding.STUCK: "red",
    SessionStanding.DONE: "dim",
}

QUEUE = "queued"

# The standings at which a view of that session ends. A session standing at
# either of them has no round coming, so a view of it has seen the last of what
# it will ever show.
STANDINGS_THAT_END_A_VIEW = (SessionStanding.DONE, SessionStanding.STUCK)

# How long a following view waits between looks at what the round has written.
PAUSE = 1.0

# What marks the label of a feed line, which is the harness's own word for what
# it just did.
LABEL = r"^\s*\[[^\]]+\]"

# How far a section's rows are set in from its heading.
INDENT = (0, 0, 0, 2)


def open_console() -> Console:
    """Return the console that the views are written to."""
    return Console()


class _Picture(NamedTuple):
    """A view as one look found it: what to draw, and whether the view is over.

    A view is over when nothing more can reach it. That is not the same as the
    last look, because `_keep_looking` takes one more after it.
    """

    shown: RenderableType
    is_over: bool


def _repaint(
    console: Console, look: Callable[[], _Picture], wait: Callable[[float], None]
) -> None:
    """Draw what each look finds over the one before, until the view is over.

    A picture of a state has a current value rather than a history, so rich's
    Live holds one place on the screen and every look is drawn into it. A place
    on the screen is as tall as the screen, so a picture that outgrows it is
    cut at the bottom, which takes the sections a reader came for last: the
    board is sorted by whose turn it is, so what goes first is what is done.

    This decides where a look is drawn, and `_keep_looking` decides how long to
    go on looking. A view nobody is watching has no place to hold, so the one
    look it takes is printed as anything else is.
    """
    if not console.is_terminal:
        console.print(look().shown)
        return
    with Live(console=console, auto_refresh=False) as live:

        def draw() -> bool:
            """Draw what this look found, and say whether the view is over."""
            found = look()
            live.update(found.shown, refresh=True)
            return found.is_over

        _keep_looking(console, draw, wait)


def _keep_looking(
    console: Console, look: Callable[[], bool], wait: Callable[[float], None]
) -> None:
    """Look again and again, until the view has seen the last of what it shows.

    A look shows where the view stands now and answers whether the view is
    over, which is to say whether anything more can reach it.

    Nobody is watching a console that is no terminal: the view is being piped,
    redirected or captured, and a view that stayed on the screen could be none
    of those. So one look is the last look there, and the reader is asked for
    no flag to say so.

    A round records its ending as soon as its own child has gone, and whatever
    it was still writing lands after that, so a view that finds itself over
    looks once more before it ends. Nothing was going before the view opened,
    so a view that opens on something already over ends on its first look and
    never waits.

    The reader ends a view that is still going by interrupting it, which is how
    they say they have seen enough, so it ends without a word.
    """
    was_over = True
    with suppress(KeyboardInterrupt):
        while True:
            is_over = look()
            if (is_over and was_over) or not console.is_terminal:
                return
            was_over = is_over
            wait(PAUSE)


def show_board(
    state: StateDirectory,
    console: Console,
    clock: Callable[[], datetime] = now,
    wait: Callable[[float], None] = sleep,
) -> None:
    """Show every session and every queued issue, and keep on showing them.

    A board always has something more to show: a daemon can start, a tick can
    dispatch, a round can begin. So a board is never over, and a reader
    watching one ends it by interrupting it. A console that is no terminal has
    nobody watching, so there the board is drawn once and this returns.
    """
    _repaint(console, lambda: _look_at_board(state, clock), wait)


def _look_at_board(state: StateDirectory, clock: Callable[[], datetime]) -> _Picture:
    """Return the board as it stands, which no look ever finds over.

    A daemon can start, a tick can dispatch, a round can begin, so a later look
    can always find what this one did not. The picture answers `is_over` as
    False for that reason, and that is what keeps a board on the screen until
    the reader interrupts it.
    """
    return _Picture(_render_board(read_board(state, clock)), is_over=False)


def _render_board(board: Board) -> RenderableType:
    """Return every session and every queued issue, sorted by whose turn it is.

    The sections run in the order of whose turn it is, so the reader meets the
    work waiting on them first and the work that is finished last. A section
    with nothing in it is left out rather than shown empty.
    """
    return _render_parts(
        _describe_daemon(board),
        _render_rows(board, SessionStanding.NEEDS_YOU),
        _render_rows(board, SessionStanding.WORKING),
        _render_rows(board, SessionStanding.WAITING),
        _render_rows(board, SessionStanding.STUCK),
        _render_queue(board),
        _render_rows(board, SessionStanding.DONE),
        _describe_nothing_dispatched(board),
    )


def _render_parts(*parts: RenderableType | None) -> RenderableType:
    """Return the parts of a view that have something to say, as one renderable.

    A part with nothing to say answers nothing, so it is left out rather than
    shown empty. The board and one session both compose themselves through
    this, so what that means is written down once.
    """
    return Group(*(part for part in parts if part is not None))


def _describe_daemon(board: Board) -> Text:
    """Return the line saying whether a daemon is running, and when it last ran.

    A daemon that has gone leaves everything it wrote behind, so the age of the
    last tick is what says how much of the board is stale.
    """
    daemon = (
        "no daemon running"
        if board.daemon_pid is None
        else f"daemon running as pid {board.daemon_pid}"
    )
    if board.tick is None:
        return Text(f"{daemon}, no tick recorded")
    ticked = describe_span(board.at - board.tick.at)
    held = "" if board.tick.hold is None else f", {board.tick.hold}"
    return Text(f"{daemon}, last tick {ticked} ago{held}")


def _render_rows(board: Board, standing: SessionStanding) -> RenderableType | None:
    """Return the sessions standing there, a row for each, or nothing if none do."""
    rows = board.list_rows_for_standing(standing)
    if not rows:
        return None
    table = _open_table()
    for row in rows:
        table.add_row(
            Text(row.session.key),
            _render_detail(row, prefix=_describe_round(row)),
        )
    return _render_section(str(standing), COLOURS[standing], table)


def _describe_round(row: SessionRow) -> str:
    """Return which round is running, or nothing while none is.

    A number says which round only while a round is running. A session between
    rounds has one behind it and another to come, and a bare number there reads
    as either.
    """
    if row.standing is not SessionStanding.WORKING:
        return ""
    return f"round {len(row.session.rounds)}"


def _render_detail(
    row: SessionRow,
    prefix: str = "",
    continuation_indent: int = 0,
    style: str = "",
) -> RenderableType:
    """Render a row's detail behind its prefix, latest output beneath it."""
    detail = Text(", ".join(filter(None, (prefix, row.detail))), style=style)
    if row.last_output is None:
        return detail
    output = Padding(
        Text(row.last_output), (0, 0, 0, continuation_indent), expand=False
    )
    return Group(detail, output)


def _render_queue(board: Board) -> RenderableType | None:
    """Return the labelled issues waiting to be dispatched, or nothing if none are."""
    if not board.queued:
        return None
    table = _open_table()
    for queued in board.queued:
        table.add_row(
            Text(f"GH{queued.issue}"), Text(queued.label), Text(queued.reason)
        )
    return _render_section(QUEUE, "blue", table)


def _describe_nothing_dispatched(board: Board) -> Text | None:
    """Return the line for a board with nothing on it, or nothing while it has.

    A board with no session and no queued issue would otherwise be the daemon's
    line and blank space, which reads as a view that failed rather than as a
    repo nothing has been dispatched in.
    """
    if board.rows or board.queued:
        return None
    return Text("nothing dispatched yet")


def _open_table() -> Table:
    """Return an empty table whose columns fit whatever a section puts in them.

    The first column names a session or an issue, which is what a reader picks
    a row out by, so it folds onto another line rather than being cut short.
    Two sessions at one issue differ only in the time in their keys, and a cut
    that reached that far would leave the rows reading the same.
    """
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="bold", overflow="fold")
    return table


def _render_section(heading: str, colour: str, body: RenderableType) -> RenderableType:
    """Return one section of a view, set in under its own heading.

    A blank line opens the section, which sets it apart from the section above
    and from the line that opens the view.
    """
    return Group(
        Text(),
        Text(heading, style=f"bold {colour}"),
        Padding(body, INDENT, expand=False),
    )


def show_session(
    state: StateDirectory,
    issue: int,
    console: Console,
    clock: Callable[[], datetime] = now,
    wait: Callable[[float], None] = sleep,
) -> None:
    """Show the newest session at the issue, and keep on showing it.

    A session between rounds has another round coming, so the view stays open
    through the gap and shows that round as it starts. A session that has run
    its final round, and a stuck session, have no round coming, so either one
    ends the view. A console that is no terminal has nobody watching, so there
    the session is drawn once and this returns.
    """
    _repaint(console, lambda: _look_at_session(state, issue, clock), wait)


def _look_at_session(
    state: StateDirectory, issue: int, clock: Callable[[], datetime]
) -> _Picture:
    """Return the newest session at the issue as it stands, and whether it is over.

    One look reads the issue's rows once, and takes both what it draws and
    where the session stands from them.
    """
    rows = _find_rows_for_issue(state, issue, clock)
    return _Picture(
        _render_session(state, rows),
        is_over=rows[0].standing in STANDINGS_THAT_END_A_VIEW,
    )


def _render_session(state: StateDirectory, rows: list[SessionRow]) -> RenderableType:
    """Return the newest of these sessions, with the older ones beneath it.

    An issue that has been dispatched more than once has a session for each
    dispatch. The newest is the one still going, or the one that got furthest,
    so it is the one the view is about.
    """
    newest = rows[0]
    return _render_parts(
        Text(newest.session.key),
        _render_detail(
            newest,
            prefix=str(newest.standing),
            continuation_indent=INDENT[3],
            style=COLOURS[newest.standing],
        ),
        _render_vitals(state, newest),
        _render_rounds(newest),
        _render_hand_resume(state, newest),
        _render_older_sessions(rows[1:]),
    )


def _render_vitals(state: StateDirectory, row: SessionRow) -> RenderableType:
    """Return what the dispatch settled, which every round of the session runs with."""
    record = row.session.record
    table = _open_table()
    for name, value in (
        ("label", record.label),
        ("branch", record.branch),
        ("worktree", state.describe_path(record.worktree)),
        ("harness", record.harness),
        ("model", record.model),
        ("effort", record.effort),
    ):
        table.add_row(Text(name), Text(str(value)))
    return _render_section("session", "blue", table)


def _render_rounds(row: SessionRow) -> RenderableType | None:
    """Return the rounds the session has run, oldest first.

    A session that has run none answers nothing.
    """
    rounds = row.session.rounds
    if not rounds:
        return None
    table = _open_table()
    for number, record in enumerate(rounds, start=1):
        is_running = row.standing is SessionStanding.WORKING and number == len(rounds)
        table.add_row(
            Text(str(number)),
            Text(record.cause),
            Text(describe_time(record.started)),
            Text(_describe_run(record)),
            Text(_describe_ending(record, is_running)),
        )
    return _render_section("rounds", "blue", table)


def _describe_run(record: RoundRecord) -> str:
    """Return how long the round ran, or nothing while it is still running."""
    if record.ending is None:
        return ""
    return f"ran {describe_span(record.ending.at - record.started)}"


def _describe_ending(record: RoundRecord, is_running: bool) -> str:
    """Return how the round ended, or what it is doing instead.

    A round that recorded no ending never finished. It is running when a daemon
    is still there to run it, and interrupted once that daemon has gone, since
    a round cannot outlive its daemon.
    """
    if record.ending is not None:
        return f"exit {record.ending.status}"
    return "running" if is_running else "interrupted"


def _render_hand_resume(
    state: StateDirectory, row: SessionRow
) -> RenderableType | None:
    """Return how to carry the session on by hand, when there is one to carry on.

    A round of the daemon's own is talking to the harness already, so there is
    nothing to take over until it has finished. A session that has run no round
    at all has no harness session behind it either, so there is nothing to
    take over there and never will be.
    """
    if row.standing is SessionStanding.WORKING or not row.session.rounds:
        return None
    worktree = state.describe_path(row.session.record.worktree)
    command = " ".join(ADAPTERS[row.session.record.harness].build_hand_resume())
    return _render_section(
        "take it over yourself", "blue", Text(f"cd {worktree}\n{command}")
    )


def _render_older_sessions(older: list[SessionRow]) -> RenderableType | None:
    """Return the sessions at this issue that came before, newest first.

    A session that is the only one at its issue has none, and answers nothing.
    """
    if not older:
        return None
    table = _open_table()
    for row in older:
        table.add_row(
            Text(row.session.key),
            Text(str(row.standing)),
            _render_detail(row),
        )
    return _render_section("older sessions", "blue", table)


def show_feed(
    state: StateDirectory,
    issue: int,
    console: Console,
    round_number: int | None = None,
    wait: Callable[[float], None] = sleep,
) -> None:
    """Show what the issue's newest session said, and follow what arrives.

    Naming a round narrows the view to that one round, and everything below is
    about the view of the whole session, which is what a reader gets when they
    name no round.

    Neither view reads a clock, unlike the board and the session view, which
    say how long ago something happened. Every line a feed shows carries the
    time it was written, so what a feed shows is the same whenever it is read.

    Reading a session that is over and watching one that is going are the same
    view in two tenses, so this shows what is there and then keeps showing what
    lands for as long as the session has another round coming.

    A session between rounds is still going, so the view stays open through the
    gaps: while the session waits for a round that no daemon has launched yet,
    while its pull request waits for the reader to post on it, and while the
    daemon that was running it is stopped and started again.

    A session that has run its final round has nothing more to say, and a stuck
    session says nothing more until a person moves it on, so either one ends
    the view rather than have it wait for a round that is not coming.

    Every look reads the session again, so a round that starts while the view
    is going is shown as it arrives, and not only the rounds it opened with.

    A console that is no terminal has nobody watching, so there either view
    shows what is there once and returns.
    """
    if round_number is not None:
        _show_one_round(state, issue, round_number, console, wait)
        return
    view = _FeedView(console)

    def look() -> bool:
        """Show what the session said since the last look, and say if it is over."""
        row = _find_rows_for_issue(state, issue)[0]
        session = row.session
        view.show_what_arrived(session, range(1, len(session.rounds) + 1))
        return row.standing in STANDINGS_THAT_END_A_VIEW

    _keep_looking(console, look, wait)


def _show_one_round(
    state: StateDirectory,
    issue: int,
    number: int,
    console: Console,
    wait: Callable[[float], None],
) -> None:
    """Show one round of the issue's newest session, until that round ends.

    One named round is all this shows, so it ends when that round has, rather
    than stay open for the round after it.

    The round list of the session view is where a reader finds the number, so
    a number no round of the session carries is the reader's mistake, and is
    the one thing this turns into words for them.
    """
    view = _FeedView(console)

    def look() -> bool:
        """Show what the round said since the last look, and say if it has ended."""
        session = _find_rows_for_issue(state, issue)[0].session
        if not 1 <= number <= len(session.rounds):
            raise ReportableError(
                f"{session.key} has run "
                f"{describe_count(len(session.rounds), 'round')}, "
                f"so it has no round {number}."
            )
        view.show_what_arrived(session, [number])
        return session.rounds[number - 1].is_complete

    _keep_looking(console, look, wait)


def _find_rows_for_issue(
    state: StateDirectory, issue: int, clock: Callable[[], datetime] = now
) -> list[SessionRow]:
    """Return the rows for the issue, newest session first, or refuse if none.

    A view of one issue reads that issue's rows rather than the whole board,
    so it never pays for a session it does not show. This is the one place
    that turns an issue with no session behind it into words for the reader.
    """
    rows = read_rows_for_issue(state, issue, clock)
    if not rows:
        raise ReportableError(f"No session here for GH{issue}.")
    return rows


@dataclass(frozen=True)
class _FeedView:
    """A session's feed on a console, and how far each round of it has been read.

    A feed only grows, so a later look at one reads each round on from where
    the last look stopped and shows what arrived. The rounds a position is held
    for are the rounds already shown, so a round that has started since the
    last look is the one that opens with its own heading.
    """

    console: Console
    positions: dict[int, int] = field(default_factory=dict)

    def show_what_arrived(self, session: Session, round_numbers: Iterable[int]) -> None:
        """Show what these rounds of the session have said since the last look."""
        for round_number in round_numbers:
            if round_number not in self.positions:
                self._show_round_heading(session, round_number)
            self._show_new_lines(session, round_number)

    def _show_round_heading(self, session: Session, round_number: int) -> None:
        """Show the line that opens a round, saying what caused it.

        A feed holds one round, so the stitch between two of them lands in no
        file and is the reader's. A blank line sets each round apart from the
        one before, which is why the first round of a view opens without one.
        """
        if self.positions:
            self.console.print()
        record = session.rounds[round_number - 1]
        heading = compose_round_boundary(round_number, record.cause, record.started)
        self.console.print(_paint(heading, Text(heading.text, style="bold")))
        self.positions[round_number] = 0

    def _show_new_lines(self, session: Session, round_number: int) -> None:
        """Show the lines this round has written since the last look at it."""
        feed = session.workspace(round_number).feed
        lines, position = read_lines_from(feed, self.positions[round_number])
        for line in lines:
            self.console.print(_paint_written(line))
        self.positions[round_number] = position


def _paint_written(written: str) -> Text:
    """Return one line of a feed as it reads on a console.

    A line the reader cannot parse reaches the reader as it was written, since
    showing what the feed holds is the whole point of showing it.
    """
    line = read_feed_line(written)
    if line is None:
        return Text(written)
    said = Text(line.text)
    said.highlight_regex(LABEL, "cyan")
    return _paint(line, said)


def _paint(line: Line, said: Text) -> Text:
    """Return the line with its stamp set back, so the words stand out."""
    return Text.assemble((describe_time(line.at), "dim"), GAP, said)
