"""Pin the terminal that a test shows a view in, and what its waits do."""

from typing import Literal, TextIO

from rich.console import Console

# How wide the console is, so a line wraps in the same place every run.
WIDTH = 100

# How tall the console is, so a picture is cut in the same place every run. A
# view on the alternate screen fills the screen and cuts what does not fit, and
# no picture a test draws is this tall.
HEIGHT = 40


def create_pinned_console(
    *,
    written_to: TextIO,
    width: int = WIDTH,
    is_terminal: bool = False,
    term: str = "xterm",
    color_system: Literal["standard"] | None = None,
) -> Console:
    """Return a console that renders the same text wherever it runs.

    Every setting rich would otherwise take from the shell or the platform is
    named here. An environment of its own is what pins the shell's share of
    them, since a shell exporting FORCE_COLOR would make it write escape
    codes, one exporting LINES would say how tall the screen a view fills is,
    and one exporting TERM as dumb would stop it writing a control code at
    all. A legacy Windows console would take a column off its width, and
    saying it has no colour system pins the colour, so a console that says it
    is a terminal, which is what makes a view follow, still writes plain text.
    Naming the standard colour system is how a test asks for colour.

    Naming the terminal is how a test asks for the dumb one, which is a
    terminal a reader watches and rich can draw no picture into.
    """
    return Console(
        file=written_to,
        width=width,
        height=HEIGHT,
        force_terminal=is_terminal,
        color_system=color_system,
        legacy_windows=False,
        _environ={"TERM": term},
    )


def refuse_to_wait(seconds: float, /):
    """Fail the test, since a view with nothing more to show must never wait.

    A view that reaches it has gone on looking, and a wait that let it would
    let it look for ever, so the test would hang rather than fail.
    """
    raise AssertionError("the view waited for something that was not coming")
