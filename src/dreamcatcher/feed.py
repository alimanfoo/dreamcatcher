"""One feed for every harness: what a line can say, and how it reads.

A harness adapter turns what its CLI streams into the events here, and the
renderer turns those into the lines of `feed.txt`. So a reader sees the same
feed whichever harness ran, and an adapter never writes a line itself.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath

from dreamcatcher.clock import now

# A note's detail can be as long as a whole file, so the line is clipped. The
# figure is the port's, wide enough for a command or a path.
WIDTH = 200

# What a subagent's lines are set in from, so the main thread stays easy to
# follow. It sits after the timestamp, which keeps the timestamps in a column.
INDENT = "  "


@dataclass(frozen=True)
class Note:
    """One line saying what happened: a tool call, a failure, a mark.

    The label is the harness's own word for it, so `[Edit]` and `[Bash]` name
    the tool that ran. A note with no detail marks that something happened and
    has nothing to add, which is all Claude's stream carries about thinking.
    """

    label: str
    detail: str = ""
    subagent: bool = False


@dataclass(frozen=True)
class Prose:
    """Text the feed keeps whole: what the agent said, or a line as it came.

    A note is clipped because its detail is a summary of something structured.
    Prose is not, because the words are the point.
    """

    text: str
    subagent: bool = False


type Event = Note | Prose


@dataclass(frozen=True)
class Renderer:
    """Turns the events of one round into the lines a reader reads.

    Every line opens with the time it was written. That is what makes silence
    legible: a reader, and later the board, can tell a round that is thinking
    from one that has hung.
    """

    directory: PurePath
    clock: Callable[[], datetime] = now

    def boundary(self, number: int, cause: str) -> str:
        """Return the line that opens a round, saying what caused it."""
        return self._written([f"round {number}: {cause}"], subagent=False)

    def render(self, event: Event) -> str:
        """Return the feed lines the event becomes, or nothing when it has none."""
        if isinstance(event, Note):
            return self._written([self._noted(event)], event.subagent)
        return self._written(
            [line for line in event.text.splitlines() if line.strip()],
            event.subagent,
        )

    def _noted(self, note: Note) -> str:
        """Return the one line a note becomes."""
        detail = self._shorten(note.detail)
        return f"[{note.label}] {detail}" if detail else f"[{note.label}]"

    def _shorten(self, detail: str) -> str:
        """Return the detail as one clipped line, without the round's directory."""
        inside = detail.removeprefix(str(self.directory))
        one_line = " ".join(
            (inside.lstrip("/\\") if inside != detail else detail).split()
        )
        if len(one_line) > WIDTH:
            return f"{one_line[:WIDTH]} ..."
        return one_line

    def _written(self, contents: list[str], subagent: bool) -> str:
        """Return the contents as timestamped lines, indented for a subagent."""
        indent = INDENT if subagent else ""
        stamp = f"{self.clock().astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"
        return "".join(f"{stamp}  {indent}{content}\n" for content in contents)
