"""Show what the sessions are doing, from what the daemon left on the disk.

`scry` is the watch tower. It reads the state directory and never talks to
GitHub or to the daemon, so it answers whether the daemon is alive or dead, and
answers fastest when you most want to look.

What the daemon writes stays plain text, and the colour goes on at the moment of
reading.
"""

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import sleep

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from dreamcatcher.board import Board, Row, Standing, read_board
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
    Standing.NEEDS_YOU: "yellow",
    Standing.WORKING: "green",
    Standing.WAITING: "cyan",
    Standing.STUCK: "red",
    Standing.DONE: "dim",
}

QUEUE = "queued"

# How long a following view waits between looks at what the round has written.
PAUSE = 1.0

# What marks the label of a feed line, which is the harness's own word for what
# it just did.
LABEL = r"^\s*\[[^\]]+\]"

# How far a section's rows are set in from its heading.
INDENT = (0, 0, 0, 2)


def open_console() -> Console:
    """Return the console that scry writes its views to."""
    return Console()


def show_board(
    state: StateDirectory, console: Console, clock: Callable[[], datetime] = now
) -> None:
    """Show every session and every queued issue, sorted by whose turn it is.

    The sections run in the order of whose turn it is, so the reader meets the
    work waiting on them first and the work that is finished last. A section
    with nothing in it is left out rather than shown empty.
    """
    board = read_board(state, clock)
    console.print(_describe_daemon(board))
    _show_rows(console, board, Standing.NEEDS_YOU)
    _show_rows(console, board, Standing.WORKING)
    _show_rows(console, board, Standing.WAITING)
    _show_rows(console, board, Standing.STUCK)
    _show_queue(console, board)
    _show_rows(console, board, Standing.DONE)
    if not board.rows and not board.queued:
        console.print("nothing dispatched yet")


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


def _show_rows(console: Console, board: Board, standing: Standing) -> None:
    """Show the sessions standing there, a row for each."""
    rows = board.list_standing(standing)
    if not rows:
        return
    table = _open_table()
    for row in rows:
        table.add_row(
            Text(row.session.key),
            _render_detail(row, prefix=_describe_round(row)),
        )
    _print_section(console, str(standing), COLOURS[standing], table)


def _describe_round(row: Row) -> str:
    """Return which round is running, or nothing while none is.

    A number says which round only while a round is running. A session between
    rounds has one behind it and another to come, and a bare number there reads
    as either.
    """
    if row.standing is not Standing.WORKING:
        return ""
    return f"round {len(row.session.rounds)}"


def _render_detail(
    row: Row,
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


def _show_queue(console: Console, board: Board) -> None:
    """Show the labelled issues waiting to be dispatched, a row for each."""
    if not board.queued:
        return
    table = _open_table()
    for queued in board.queued:
        table.add_row(
            Text(f"GH{queued.issue}"), Text(queued.label), Text(queued.reason)
        )
    _print_section(console, QUEUE, "blue", table)


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


def _print_section(
    console: Console, heading: str, colour: str, body: RenderableType
) -> None:
    """Print one section of a view, set in under its own heading."""
    console.print()
    console.print(Text(heading, style=f"bold {colour}"))
    console.print(Padding(body, INDENT, expand=False))


def show_session(
    state: StateDirectory,
    issue: int,
    console: Console,
    clock: Callable[[], datetime] = now,
) -> None:
    """Show the newest session at the issue, with the older ones beneath it.

    An issue that has been dispatched more than once has a session for each
    dispatch. The newest is the one still going, or the one that got furthest,
    so it is the one the view is about.
    """
    rows = _find_rows(read_board(state, clock), issue)
    newest = rows[0]
    console.print(Text(newest.session.key))
    console.print(
        _render_detail(
            newest,
            prefix=str(newest.standing),
            continuation_indent=INDENT[3],
            style=COLOURS[newest.standing],
        )
    )
    _show_vitals(console, state, newest)
    _show_rounds(console, newest)
    _show_hand_resume(console, state, newest)
    _show_older_sessions(console, rows[1:])


def _show_vitals(console: Console, state: StateDirectory, row: Row) -> None:
    """Show what the dispatch settled, which every round of the session runs with."""
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
    _print_section(console, "session", "blue", table)
    _print_section(console, "first prompt", "blue", Text(record.prompt))


def _show_rounds(console: Console, row: Row) -> None:
    """Show the rounds the session has run, oldest first."""
    rounds = row.session.rounds
    if not rounds:
        return
    table = _open_table()
    for number, record in enumerate(rounds, start=1):
        is_running = row.standing is Standing.WORKING and number == len(rounds)
        table.add_row(
            Text(str(number)),
            Text(record.cause),
            Text(describe_time(record.started)),
            Text(_describe_run(record)),
            Text(_describe_ending(record, is_running)),
        )
    _print_section(console, "rounds", "blue", table)


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


def _show_hand_resume(console: Console, state: StateDirectory, row: Row) -> None:
    """Show how to carry the session on by hand, when there is one to carry on.

    A round of the daemon's own is talking to the harness already, so there is
    nothing to take over until it has finished. A session that has run no round
    at all has no harness session behind it either, so there is nothing to
    take over there and never will be.
    """
    if row.standing is Standing.WORKING or not row.session.rounds:
        return
    worktree = state.describe_path(row.session.record.worktree)
    command = " ".join(ADAPTERS[row.session.record.harness].build_hand_resume())
    _print_section(
        console, "take it over yourself", "blue", Text(f"cd {worktree}\n{command}")
    )


def _show_older_sessions(console: Console, older: list[Row]) -> None:
    """Show the sessions at this issue that came before, newest first."""
    if not older:
        return
    table = _open_table()
    for row in older:
        table.add_row(
            Text(row.session.key),
            Text(str(row.standing)),
            _render_detail(row),
        )
    _print_section(console, "older sessions", "blue", table)


def show_round(
    state: StateDirectory,
    issue: int,
    number: int,
    console: Console,
    clock: Callable[[], datetime] = now,
) -> None:
    """Show the feed of one round of the issue's newest session.

    The round list of the session view is where a reader finds the number.
    """
    session = _find_rows(read_board(state, clock), issue)[0].session
    if not 1 <= number <= len(session.rounds):
        raise ReportableError(
            f"{session.key} has run {describe_count(len(session.rounds), 'round')}, "
            f"so it has no round {number}."
        )
    _Feed(console).show(session, [number])


def show_feed(
    state: StateDirectory,
    issue: int,
    console: Console,
    wait: Callable[[float], None] = sleep,
    clock: Callable[[], datetime] = now,
) -> None:
    """Show every round of the issue's newest session, and follow what arrives.

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

    A round records its ending as soon as its own child has gone, and whatever
    it was still writing lands after that, so a session that ends while the
    view is going gets one more look before the view ends too. A session that
    had already ended when the view opened gets no extra look and no wait.

    The reader ends a view of a session that is still going by interrupting it,
    which is how they say they have seen enough, so it ends without a word.
    """
    feed = _Feed(console)
    # Nothing was going before the view opened, so a session that has already
    # ended when it opens ends the view on its first look.
    was_over = True
    with suppress(KeyboardInterrupt):
        while True:
            row = _find_rows(read_board(state, clock), issue)[0]
            session = row.session
            feed.show(session, range(1, len(session.rounds) + 1))
            is_over = row.standing in (Standing.DONE, Standing.STUCK)
            if is_over and was_over:
                return
            was_over = is_over
            wait(PAUSE)


def _find_rows(board: Board, issue: int) -> list[Row]:
    """Return the rows for the issue, newest session first, or refuse if none."""
    rows = [one for one in board.rows if one.session.record.issue == issue]
    if not rows:
        raise ReportableError(f"No session here for GH{issue}.")
    return rows


@dataclass(frozen=True)
class _Feed:
    """A session's feed as it reads on a console, and how far it has been read.

    A feed only grows, so a later look at one reads each round on from where
    the last look stopped and shows what arrived. The rounds a position is held
    for are the rounds already shown, so a round that has started since the
    last look is the one that opens with the line saying what caused it.
    """

    console: Console
    positions: dict[int, int] = field(default_factory=dict)

    def show(self, session: Session, numbers: Iterable[int]) -> None:
        """Show what these rounds of the session have said since the last look."""
        for number in numbers:
            if number not in self.positions:
                self._open_round(session.rounds[number - 1], number)
            self._show_arrived(session.workspace(number).feed, number)

    def _open_round(self, record: RoundRecord, number: int) -> None:
        """Show the line that opens a round, saying what caused it.

        A feed holds one round, so the stitch between two of them lands in no
        file and is the reader's. The rounds are set apart by a blank line,
        which is why the first round of a view opens without one.
        """
        if self.positions:
            self.console.print()
        boundary = compose_round_boundary(number, record.cause, record.started)
        self.console.print(_paint(boundary, Text(boundary.text, style="bold")))
        self.positions[number] = 0

    def _show_arrived(self, feed: Path, number: int) -> None:
        """Show the lines this round has written since the last look at it."""
        written, position = read_lines_from(feed, self.positions[number])
        for line in written:
            self.console.print(_paint_written(line))
        self.positions[number] = position


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
