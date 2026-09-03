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

    def boundary(self, number: int, cause: str) -> str:
        """Return the line that opens a round, saying what caused it."""
        return self._stamp([f"round {number}: {cause}"], is_subagent=False)

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
        stamp = f"{self.clock().astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"
        return "".join(f"{stamp}  {indent}{content}\n" for content in contents)
