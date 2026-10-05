"""Provide shared Rich rendering and live-view behavior for terminal views."""

from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from dreamcatcher.clock import WaitForSeconds
from dreamcatcher.status import (
    ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
    CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER,
)

ASSIGNMENT_STATUS_STYLES = dict(
    zip(
        ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
        ("yellow", "red", "green", "cyan", "magenta", "dim", "dim"),
        strict=True,
    )
)

CONVERSATION_STATUS_STYLES = dict(
    zip(
        CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER,
        ("yellow", "red", "green", "cyan", "magenta", "dim"),
        strict=True,
    )
)

_VIEW_REFRESH_INTERVAL = 1.0
SECTION_PADDING = (0, 0, 0, 2)


def open_tui_console() -> Console:
    """Return a console that follows the terminal's current dimensions.

    Tests may supply a console with fixed dimensions for stable output.
    """
    return Console()


@dataclass(frozen=True, kw_only=True)
class ViewSnapshot:
    """Capture one rendered view and whether to stop refreshing it.

    An active view refreshes once more after first reaching its stopping
    condition, so that output following a round's terminal record can arrive.
    """

    renderable: RenderableType
    should_stop_refreshing: bool


def refresh_live_view(
    *,
    console: Console,
    read_snapshot: Callable[[], ViewSnapshot],
    wait: WaitForSeconds,
) -> None:
    """Redraw snapshots in a terminal until the view ends.

    A terminal uses its alternate screen and prints the final snapshot after a
    completed view ends. An interrupted active view leaves no final snapshot.

    A non-terminal or dumb terminal prints one snapshot and returns.
    """
    if not console.is_terminal or console.is_dumb_terminal:
        console.print(read_snapshot().renderable)
        return
    last_snapshot = ViewSnapshot(renderable="", should_stop_refreshing=False)
    with Live(console=console, auto_refresh=False, screen=True) as live:

        def refresh_live_display() -> bool:
            """Draw the current snapshot and return whether refreshing should stop."""
            nonlocal last_snapshot
            last_snapshot = read_snapshot()
            live.update(last_snapshot.renderable, refresh=True)
            return last_snapshot.should_stop_refreshing

        refresh_until_view_ends(
            console=console, refresh_view=refresh_live_display, wait=wait
        )
    if last_snapshot.should_stop_refreshing:
        console.print(last_snapshot.renderable)


def refresh_until_view_ends(
    *, console: Console, refresh_view: Callable[[], bool], wait: WaitForSeconds
) -> None:
    """Refresh until the view ends.

    The extra refresh lets output that follows a round's terminal record arrive.
    A view that is already over returns after its first refresh, and a
    non-terminal console always takes one refresh. KeyboardInterrupt ends an
    active view quietly.
    """
    should_stop_after_previous_refresh = True
    with suppress(KeyboardInterrupt):
        while True:
            should_stop_refreshing = refresh_view()
            if (
                should_stop_refreshing and should_stop_after_previous_refresh
            ) or not console.is_terminal:
                return
            should_stop_after_previous_refresh = should_stop_refreshing
            wait(_VIEW_REFRESH_INTERVAL)


def combine_renderable_parts(
    *, parts: Sequence[RenderableType | None]
) -> RenderableType:
    """Combine the renderable parts that are present."""
    return Group(*(part for part in parts if part is not None))


def render_latest_output(*, latest_output: str | None) -> Text | None:
    """Render agent work's latest output as one dimmed line."""
    if latest_output is None:
        return None
    return Text(
        latest_output,
        style="dim",
        overflow="ellipsis",
        no_wrap=True,
    )


def create_table(*, columns: int) -> Table:
    """Return a table whose cells fold instead of truncating.

    The first column names an assignment or an issue, which is what a reader picks
    a row out by, so it folds onto another line rather than being cut short.
    Two assignments at one issue differ only in the time in their identifiers,
    and a cut that reached that far would leave the rows reading the same.
    """
    table = Table(box=None, show_header=False, pad_edge=False)
    for number in range(columns):
        table.add_column(
            style="bold" if number == 0 else "",
            overflow="fold",
        )
    return table


def render_section(*, heading: str, body: RenderableType) -> RenderableType:
    """Render a named, indented terminal section."""
    return Group(
        Text(),
        Text(heading, style="bold blue"),
        Padding(body, SECTION_PADDING, expand=False),
    )
