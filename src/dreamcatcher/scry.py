"""Show what the sessions are doing, from what the daemon left on the disk.

`scry` is the watch tower. It reads the state directory and never talks to
GitHub or to the daemon, so it answers whether the daemon is alive or dead, and
answers fastest when you most want to look.

rich renders every view here, and nowhere else, so what the daemon writes stays
plain text and the colour is put on at the moment of reading.
"""

from collections.abc import Callable
from datetime import datetime

from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from dreamcatcher.board import Board, Standing, read_board
from dreamcatcher.clock import describe_span, now
from dreamcatcher.state import StateDirectory

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
    _show_attempts(console, board, Standing.NEEDS_YOU)
    _show_attempts(console, board, Standing.WORKING)
    _show_attempts(console, board, Standing.WAITING)
    _show_attempts(console, board, Standing.STUCK)
    _show_queue(console, board)
    _show_attempts(console, board, Standing.DONE)
    if not board.attempts and not board.queued:
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


def _show_attempts(console: Console, board: Board, standing: Standing) -> None:
    """Show the sessions standing there, a row for each."""
    attempts = board.list_standing(standing)
    if not attempts:
        return
    table = _open_table()
    for attempt in attempts:
        table.add_row(
            Text(f"GH{attempt.session.record.issue}"),
            Text(f"attempt {attempt.attempt} of {attempt.attempts}"),
            Text(attempt.detail),
        )
    _print_section(console, str(standing), COLOURS[standing], table)


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
    """Return an empty table of the three columns every section shows."""
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_column()
    return table


def _print_section(console: Console, heading: str, colour: str, table: Table) -> None:
    """Print one section of the board, under its own heading."""
    console.print()
    console.print(Text(heading, style=f"bold {colour}"))
    console.print(Padding(table, INDENT, expand=False))
