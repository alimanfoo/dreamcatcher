"""Show what the sessions are doing, from what the daemon left on the disk.

`scry` is the watch tower. It reads the state directory and never talks to
GitHub or to the daemon, so it answers whether the daemon is alive or dead, and
answers fastest when you most want to look.

rich renders every view here, and nowhere else, so what the daemon writes stays
plain text and the colour is put on at the moment of reading.
"""

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from time import sleep

from rich.console import Console, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from dreamcatcher.board import Attempt, Board, Standing, read_board
from dreamcatcher.clock import now
from dreamcatcher.documents import read_text
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
    """Return an empty table whose columns fit whatever a section puts in them."""
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="bold")
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
    """Show the newest attempt at the issue, with the older ones beneath it.

    An issue that has been dispatched more than once has an attempt for each
    dispatch. The newest is the one still going, or the one that got furthest,
    so it is the one the view is about.
    """
    attempts = _find_attempts(read_board(state, clock), issue)
    newest = attempts[0]
    console.print(Text(f"GH{issue}, attempt {newest.attempt} of {newest.attempts}"))
    console.print(
        Text(f"{newest.standing}, {newest.detail}", style=COLOURS[newest.standing])
    )
    _show_vitals(console, state, newest)
    _show_rounds(console, newest)
    _show_hand_resume(console, state, newest)
    _show_older_attempts(console, attempts[1:])


def _show_vitals(console: Console, state: StateDirectory, attempt: Attempt) -> None:
    """Show what the dispatch settled, which every round of the session runs with."""
    record = attempt.session.record
    table = _open_table()
    for name, value in (
        ("key", attempt.session.key),
        ("label", record.label),
        ("branch", record.branch),
        ("worktree", _under_the_checkout(state, record.worktree)),
        ("harness", record.harness),
        ("model", record.model),
        ("effort", record.effort),
    ):
        table.add_row(Text(name), Text(str(value)))
    _print_section(console, "session", "blue", table)
    _print_section(console, "first prompt", "blue", Text(record.prompt))


def _show_rounds(console: Console, attempt: Attempt) -> None:
    """Show the rounds the session has run, oldest first."""
    rounds = attempt.session.rounds
    if not rounds:
        return
    table = _open_table()
    for number, record in enumerate(rounds, start=1):
        is_running = attempt.standing is Standing.WORKING and number == len(rounds)
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


def _show_hand_resume(
    console: Console, state: StateDirectory, attempt: Attempt
) -> None:
    """Show how to carry the session on by hand, when there is one to carry on.

    A round of the daemon's own is talking to the harness already, so there is
    nothing to take over until it has finished. A session that has run no round
    at all has no harness session behind it either, so there is nothing to
    take over there and never will be.
    """
    if attempt.standing is Standing.WORKING or not attempt.session.rounds:
        return
    worktree = _under_the_checkout(state, attempt.session.record.worktree)
    command = " ".join(ADAPTERS[attempt.session.record.harness].build_hand_resume())
    _print_section(
        console, "take it over yourself", "blue", Text(f"cd {worktree}\n{command}")
    )


def _show_older_attempts(console: Console, older: list[Attempt]) -> None:
    """Show the attempts at this issue that came before, newest first."""
    if not older:
        return
    table = _open_table()
    for attempt in older:
        table.add_row(
            Text(attempt.session.key),
            Text(str(attempt.standing)),
            Text(attempt.detail),
        )
    _print_section(console, "older attempts", "blue", table)


def _under_the_checkout(state: StateDirectory, path: Path) -> str:
    """Return the path as it reads from the checkout, the one way everywhere."""
    return path.relative_to(state.root).as_posix()


def show_round(
    state: StateDirectory,
    issue: int,
    number: int,
    console: Console,
    clock: Callable[[], datetime] = now,
) -> None:
    """Show the feed of one round of the issue's newest attempt.

    The round list of the session view is where a reader finds the number.
    """
    session = _find_attempts(read_board(state, clock), issue)[0].session
    if not 1 <= number <= len(session.rounds):
        raise ReportableError(
            f"GH{issue} has run {describe_count(len(session.rounds), 'round')}, "
            f"so it has no round {number}."
        )
    for painted in _compose_feed(session, [number]):
        console.print(painted)


def show_feed(
    state: StateDirectory,
    issue: int,
    console: Console,
    wait: Callable[[float], None] = sleep,
    clock: Callable[[], datetime] = now,
) -> None:
    """Show every round of the issue's newest attempt, and follow what arrives.

    Reading a session that is over and watching one that is going are the same
    view in two tenses, so this shows what is there and then keeps showing what
    lands until no round is running.

    Every look reads the session again, so a round that starts while the view
    is going is shown as it arrives, and not only the rounds it opened with.
    """
    shown = 0
    while True:
        attempt = _find_attempts(read_board(state, clock), issue)[0]
        session = attempt.session
        painted = _compose_feed(session, range(1, len(session.rounds) + 1))
        for line in painted[shown:]:
            console.print(line)
        shown = len(painted)
        if attempt.standing is not Standing.WORKING:
            return
        wait(PAUSE)


def _find_attempts(board: Board, issue: int) -> list[Attempt]:
    """Return the attempts at the issue, newest first, or refuse if there are none."""
    attempts = [one for one in board.attempts if one.session.record.issue == issue]
    if not attempts:
        raise ReportableError(f"No session here for GH{issue}.")
    return attempts


def _compose_feed(session: Session, numbers: Iterable[int]) -> list[Text]:
    """Return the lines these rounds of the session read as, in order.

    Each round opens with the line that says what caused it, stamped with the
    time that round started, and the rounds are set apart by a blank line. A
    feed holds one round, so the stitch between them is the reader's and lands
    in no file.
    """
    painted: list[Text] = []
    for number in numbers:
        record = session.rounds[number - 1]
        if painted:
            painted.append(Text())
        boundary = compose_round_boundary(number, record.cause, record.started)
        painted.append(_paint(boundary, Text(boundary.text, style="bold")))
        painted.extend(
            _paint_written(written)
            for written in _read_feed(session.workspace(number).feed)
        )
    return painted


def _read_feed(path: Path) -> list[str]:
    """Return the lines the feed at path holds whole, without their endings.

    A round writes its feed a line at a time as it goes, so a round that has
    said nothing yet has no feed, and a line with no ending on it is a write
    still landing. The next look shows that one whole.
    """
    if not path.exists():
        return []
    written = read_text(path)
    lines = written.splitlines()
    if lines and not written.endswith("\n"):
        lines.pop()
    return lines


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
    return Text(describe_time(line.at), style="dim") + Text(GAP) + said
