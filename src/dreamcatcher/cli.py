"""The dreamcatcher command line."""

import argparse
import re
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

import dreamcatcher
from dreamcatcher import tui
from dreamcatcher.config import Harness
from dreamcatcher.daemon import Daemon
from dreamcatcher.errors import ReportableError
from dreamcatcher.state import StateDirectory

# How a view names the issue it is about, as the issue itself is written.
ISSUE = re.compile(r"gh(\d+)\Z", re.IGNORECASE)

# The help that says when a view of one assignment ends, which the assignment view
# and the feed both give, since a reader reads one verb's help and no other.
HELP_WHEN_A_VIEW_ENDS = (
    "It ends once the assignment has run its final round, and on a stuck "
    "assignment, which only you can move on. Interrupt it to end it sooner."
)

# The help that says what a view does to the terminal it runs in, which the two
# views that draw a picture over the one before give.
HELP_WHEN_A_VIEW_TAKES_THE_SCREEN = (
    "It takes the whole terminal while it runs, and gives it back when it ends."
)

# The help that says what a view does when nothing is watching it, which every
# verb gives.
HELP_WHEN_NOTHING_WATCHES = (
    "Piped, redirected or captured, it shows what is there once and returns."
)


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for the dreamcatcher command line.

    Each verb shows one view, or runs the daemon, and every argument belongs
    to the verb that takes it. So a verb's own --help describes the whole of
    what that verb does, and argparse does all the refusing: a verb given an
    argument it does not take, or given none of the arguments it requires,
    is refused with that verb's own usage line above the message. Nothing
    here has to check an argument against the verb it arrived with.
    """
    parser = argparse.ArgumentParser(
        prog="dreamcatcher", description=dreamcatcher.__doc__
    )
    parser.add_argument("--version", action="version", version=version("dreamcatcher"))
    verbs = parser.add_subparsers(title="verbs", dest="verb", required=True)
    run_parser = verbs.add_parser(
        "run",
        help="run the dreamcatcher daemon",
        description=(
            "Watch this repository for labelled issues, dispatch an agent "
            "assignment for each, and carry every assignment on until its pull "
            "request is ready for you to review. One daemon watches one "
            "repo, so a second run on this one refuses while the first is "
            "alive."
        ),
    )
    run_parser.add_argument(
        "--harness",
        required=True,
        # The names, not the members. Some Python versions render a rejected
        # choice with repr(), which turns a member into <Harness.CLAUDE: ...>.
        choices=[harness.value for harness in Harness],
        help="the harness to run this repo's rounds with",
    )
    run_parser.set_defaults(act=_run)
    board_parser = verbs.add_parser(
        "board",
        help="show an overview of every assignment and every queued issue",
        description=(
            "Show every assignment and every queued issue, a section per "
            "standing, in the order of whose turn it is. It keeps up until "
            "you interrupt it. "
            + HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " "
            + HELP_WHEN_NOTHING_WATCHES
        ),
    )
    board_parser.set_defaults(act=_show_board)
    assignment_parser = verbs.add_parser(
        "assignment",
        help="show one issue's newest assignment, in detail",
        description=(
            "Show an overview of the newest assignment at the issue: what "
            "its dispatch settled, the rounds it has run, the command that "
            "takes the harness session over by hand, and the older assignments at the "
            "same issue. It keeps up for as long as the assignment has another "
            "round coming. "
            + HELP_WHEN_A_VIEW_ENDS
            + " "
            + HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " An assignment that is over stays on the screen for you to read. "
            "Interrupt one that is still going and nothing is left behind. "
            + HELP_WHEN_NOTHING_WATCHES
        ),
    )
    _take_an_issue(parser=assignment_parser)
    assignment_parser.set_defaults(act=_show_assignment)
    feed_parser = verbs.add_parser(
        "feed",
        help="show what the agent said, as it says it",
        description=(
            "Show the agent's actions and outputs from every round of "
            "the issue's newest assignment, and keep showing what arrives for "
            "as long as the assignment has another round coming. "
            + HELP_WHEN_A_VIEW_ENDS
            + " "
            + HELP_WHEN_NOTHING_WATCHES
        ),
    )
    _take_an_issue(parser=feed_parser)
    feed_parser.add_argument(
        "--round",
        type=int,
        metavar="N",
        help=(
            "show the feed of that round alone, ending when that round "
            "ends. The assignment view's round list is where you find the "
            "number"
        ),
    )
    feed_parser.set_defaults(act=_show_feed)
    return parser


def _take_an_issue(*, parser: argparse.ArgumentParser) -> None:
    """Give the verb the issue it shows, written as the issue itself is."""
    parser.add_argument(
        "issue",
        type=_read_issue,
        metavar="GH<n>",
        help="the issue to show",
    )


def main(*, argv: Sequence[str] | None = None) -> int:
    """Run the verb that the arguments name, and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        args.act(args=args)
    except ReportableError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def _run(*, args: argparse.Namespace) -> None:
    """Run a daemon on the checkout we are in."""
    Daemon(root=Path.cwd(), harness=Harness(args.harness)).run()


def _show_board(*, args: argparse.Namespace) -> None:
    """Show the board of the checkout we are in."""
    tui.show_board(state=_find_state(root=Path.cwd()), console=tui.open_console())


def _show_assignment(*, args: argparse.Namespace) -> None:
    """Show the issue's newest assignment, from the checkout we are in."""
    tui.show_assignment(
        state=_find_state(root=Path.cwd()), issue=args.issue, console=tui.open_console()
    )


def _show_feed(*, args: argparse.Namespace) -> None:
    """Show the issue's feed, from the checkout we are in."""
    tui.show_feed(
        state=_find_state(root=Path.cwd()),
        issue=args.issue,
        console=tui.open_console(),
        round_number=args.round,
    )


def _find_state(*, root: Path) -> StateDirectory:
    """Return the state directory here, or say there is nothing here to show.

    A view reads what a daemon left on the disk, and a daemon leaves it in the
    checkout it watches. So a directory with no state directory in it is one
    the reader did not mean to be in.
    """
    state = StateDirectory(root=root)
    if not state.path.is_dir():
        raise ReportableError(
            f"dreamcatcher has nothing to show in {root}. Run this from the "
            f"checkout that dreamcatcher run watches."
        )
    return state


def _read_issue(given: str, /) -> int:
    """Return the issue number the argument names, as GH123 names issue 123.

    argparse is what calls this, as the type behind the issue argument, and it
    passes the text positionally, so the parameter is positional-only.
    """
    found = ISSUE.match(given)
    if found is None:
        raise argparse.ArgumentTypeError(f"name an issue as GH123, not as {given}")
    return int(found.group(1))
