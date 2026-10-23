"""Render every harness's output as one shared feed format.

A feed records each event with the time that dreamcatcher rendered it.

A harness adapter turns what its CLI streams into the events here, and the
renderer turns those events into lines. So a reader sees the same feed
whichever harness ran, and an adapter never writes a line itself.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath

from dreamcatcher.clock import read_current_time
from dreamcatcher.documents import read_last_line
from dreamcatcher.words import UTC_TIMESTAMP_FORMAT, format_utc_timestamp

# A note's detail can be as long as a whole file, so the line is clipped, at a
# width that holds a command or a path.
_FEED_LINE_WIDTH = 200

# What sits between a line's stamp and what the line says.
FEED_TIMESTAMP_GAP = "  "

_FEED_NOTE_PATTERN = re.compile(r"^\[([^\]]+)\](?: (.*))?$")


@dataclass(frozen=True, kw_only=True)
class FeedLine:
    """Model one timestamped line of a feed.

    The text is everything the line holds after its stamp. Parsed lines also
    carry their semantic parts while keeping the exact text that was written.
    """

    at: datetime
    text: str
    label: str | None = None
    detail: str = ""

    def render(self) -> str:
        """Return the line as a feed holds it, the line ending included."""
        return f"{format_utc_timestamp(at=self.at)}{FEED_TIMESTAMP_GAP}{self.text}\n"


def compose_agent_round_boundary(
    *,
    number: int,
    trigger: str,
    at: datetime,
    detail: str | None = None,
) -> FeedLine:
    """Return the line that opens a round, saying what woke it.

    A feed holds one round, so nothing writes this line as the round runs.
    Whoever reads the rounds of a piece of agent work in order writes it between
    them, stamped with the time that round started.
    """
    description = trigger if detail is None else f"{trigger}; {detail}"
    return FeedLine(at=at, text=f"round {number}: {description}")


def read_feed_line(*, written_line: str) -> FeedLine | None:
    """Return what one written line says, or nothing when it is not a line.

    Every line a feed holds opens with its stamp, so anything else is the end
    of a write that never landed whole.
    """
    timestamp, gap, text = written_line.partition(FEED_TIMESTAMP_GAP)
    if not gap:
        return None
    try:
        at = datetime.strptime(timestamp, UTC_TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None
    parsed_contents = text.removesuffix("\n")
    note = _FEED_NOTE_PATTERN.fullmatch(parsed_contents)
    return FeedLine(
        at=at,
        text=text,
        label=None if note is None else note.group(1),
        detail=parsed_contents if note is None else note.group(2) or "",
    )


def read_last_feed_line(*, path: Path) -> FeedLine | None:
    """Return the last line the feed at path holds, or nothing when it holds none."""
    written_line = read_last_line(path=path)
    if written_line is None:
        return None
    return read_feed_line(written_line=written_line)


@dataclass(frozen=True, kw_only=True)
class FeedNote:
    """Model a labelled event with optional summary detail.

    A note with no detail says that something happened and nothing more.
    """

    label: str
    detail: str = ""


@dataclass(frozen=True, kw_only=True)
class FeedProse:
    """Model prose that the feed preserves without clipping.

    A note is clipped because its detail is a summary of something structured.
    FeedProse is not, because the words are the point.
    """

    text: str


type FeedEvent = FeedNote | FeedProse


@dataclass(frozen=True, kw_only=True)
class FeedRenderer:
    """Render one round's events as timestamped feed lines.

    Each rendered line records its time so that a reader can distinguish recent
    activity from prolonged silence.
    """

    worktree: PurePath
    clock: Callable[[], datetime] = read_current_time

    def render(self, *, event: FeedEvent) -> str:
        """Return the feed lines the event becomes, or nothing when it has none."""
        if isinstance(event, FeedNote):
            return self._render_timestamped_lines(
                contents=[self._render_note(note=event)]
            )
        return self._render_timestamped_lines(
            contents=[line for line in event.text.splitlines() if line.strip()]
        )

    def _render_note(self, *, note: FeedNote) -> str:
        """Return the one line a note becomes."""
        detail = self._shorten_note_detail(detail=note.detail)
        return f"[{note.label}] {detail}" if detail else f"[{note.label}]"

    def _shorten_note_detail(self, *, detail: str) -> str:
        """Return the detail as one clipped line with worktree paths abbreviated."""
        one_line = " ".join(self._abbreviate_worktree_paths(detail=detail).split())
        if len(one_line) > _FEED_LINE_WIDTH:
            return f"{one_line[:_FEED_LINE_WIDTH]} ..."
        return one_line

    def _abbreviate_worktree_paths(self, *, detail: str) -> str:
        """Return the detail with each worktree path marked as ``<worktree>``.

        A match is the whole detail, a descendant at a directory separator, or
        a complete quoted or unquoted command argument. A different path that
        contains the same suffix and a sibling whose name starts the same way
        both stay whole.
        """
        worktree = re.escape(str(self.worktree))
        flags = 0
        if self.worktree.drive:
            worktree = worktree.replace(re.escape("\\"), r"[/\\]")
            flags = re.IGNORECASE
        path_or_descendant = rf"(?<![\w./\\-]){worktree}(?=$|[/\\])"
        command_argument = (
            rf"(?<!\S){worktree}(?=\s)"
            rf"|(?<='){worktree}(?=')"
            rf'|(?<="){worktree}(?=")'
        )
        return re.sub(
            rf"{path_or_descendant}|{command_argument}",
            "<worktree>",
            detail,
            flags=flags,
        )

    def _render_timestamped_lines(self, *, contents: list[str]) -> str:
        """Return the contents as lines stamped with the one time."""
        written_at = self.clock()
        return "".join(
            FeedLine(at=written_at, text=content).render() for content in contents
        )
