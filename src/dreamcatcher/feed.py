"""One feed for every harness: what a line can say, and how it reads.

A feed holds a line for each thing that happened, stamped with the time it
happened. `Line` is that line, both as `feed.txt` holds it and as a reader
of `feed.txt` reads it back.

A harness adapter turns what its CLI streams into the events here, and the
renderer turns those events into lines. So a reader sees the same feed
whichever harness ran, and an adapter never writes a line itself.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath

from dreamcatcher.clock import now
from dreamcatcher.documents import read_last_line
from dreamcatcher.words import STAMP, describe_time

# A note's detail can be as long as a whole file, so the line is clipped. The
# figure is the port's, wide enough for a command or a path.
WIDTH = 200

# What a subagent's lines are set in from, so the main thread stays easy to
# follow. It sits after the timestamp, which keeps the timestamps in a column.
INDENT = "  "

# What sits between a line's stamp and what the line says.
GAP = "  "


@dataclass(frozen=True)
class Line:
    """One line of a feed: when it was written, and what it says.

    The text is everything the line holds after its stamp, so a subagent's
    line keeps the indent that sets it in from the rest.
    """

    at: datetime
    text: str

    def render(self) -> str:
        """Return the line as a feed holds it, the line ending included."""
        return f"{describe_time(self.at)}{GAP}{self.text}\n"


def compose_round_boundary(number: int, cause: str, at: datetime) -> Line:
    """Return the line that opens a round, saying what caused it.

    A feed holds one round, so nothing writes this line as the round runs.
    Whoever reads a whole session's rounds in order writes it between them,
    stamped with the time that round started.
    """
    return Line(at, f"round {number}: {cause}")


def read_feed_line(written: str) -> Line | None:
    """Return what one written line says, or nothing when it is not a line.

    Every line a feed holds opens with its stamp, so anything else is the end
    of a write that never landed whole.
    """
    stamp, gap, text = written.partition(GAP)
    if not gap:
        return None
    try:
        at = datetime.strptime(stamp, STAMP).replace(tzinfo=UTC)
    except ValueError:
        return None
    return Line(at, text)


def read_last_feed_line(path: Path) -> Line | None:
    """Return the last line the feed at path holds, or nothing when it holds none.

    The board asks this of every session it shows, so the end of the file is
    what it reads, however long the round has been writing.
    """
    written = read_last_line(path)
    if written is None:
        return None
    return read_feed_line(written)


@dataclass(frozen=True)
class Note:
    """One line saying what happened: a tool call, a failure, a mark.

    A note with no detail says that something happened and nothing more.
    """

    label: str
    detail: str = ""
    is_subagent: bool = False


@dataclass(frozen=True)
class Prose:
    """Text the feed keeps whole: what the agent said, or a line as it came.

    A note is clipped because its detail is a summary of something structured.
    Prose is not, because the words are the point.
    """

    text: str
    is_subagent: bool = False


type Event = Note | Prose


@dataclass(frozen=True)
class Renderer:
    """Turns the events of one round into the lines a reader reads.

    Every line opens with the time it was written. That is what makes silence
    legible: a reader, and later the board, can tell a round that is thinking
    from one that has hung.
    """

    worktree: PurePath
    clock: Callable[[], datetime] = now

    def render(self, event: Event) -> str:
        """Return the feed lines the event becomes, or nothing when it has none."""
        if isinstance(event, Note):
            return self._stamp([self._render_note(event)], event.is_subagent)
        return self._stamp(
            [line for line in event.text.splitlines() if line.strip()],
            event.is_subagent,
        )

    def _render_note(self, note: Note) -> str:
        """Return the one line a note becomes."""
        detail = self._shorten(note.detail)
        return f"[{note.label}] {detail}" if detail else f"[{note.label}]"

    def _shorten(self, detail: str) -> str:
        """Return the detail as one clipped line, without the worktree's path."""
        one_line = " ".join(self._strip_worktree(detail).split())
        if len(one_line) > WIDTH:
            return f"{one_line[:WIDTH]} ..."
        return one_line

    def _strip_worktree(self, detail: str) -> str:
        """Return the detail with the path of the round's worktree off its front.

        The separator has to be there, so a sibling directory whose name starts
        the same way keeps its whole path. Either separator counts: a path
        arrives written the way the harness that reported it writes them.
        """
        for separator in ("/", "\\"):
            start = f"{self.worktree}{separator}"
            if detail.startswith(start):
                return detail[len(start) :]
        return detail

    def _stamp(self, contents: list[str], is_subagent: bool) -> str:
        """Return the contents as timestamped lines, indented for a subagent."""
        indent = INDENT if is_subagent else ""
        at = self.clock()
        return "".join(Line(at, f"{indent}{content}").render() for content in contents)
