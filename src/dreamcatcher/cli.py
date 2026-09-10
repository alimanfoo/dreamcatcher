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
            "session for each, and carry every session on until its pull "
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
        help="show an overview of every session and every queued issue",
        description=(
            "Show every session and every queued issue, a section per "
            "standing, in the order of whose turn it is. It stays on the "
            "screen and keeps up until you interrupt it. Piped, redirected "
            "or captured, it shows the board once and returns."
        ),
    )
    board_parser.set_defaults(act=_show_board)
    session_parser = verbs.add_parser(
        "session",
        help="show one issue's newest session, in detail",
        description=(
            "Show an overview of the newest session at the issue: what "
            "its dispatch settled, the rounds it has run, the command that "
            "takes the session over by hand, and the older sessions at the "
            "same issue. It stays on the screen and keeps up for as long as "
            "the session has another round coming. It ends once the session "
            "has run its final round, and on a stuck session, which only you "
            "can move on. Interrupt it to end it sooner. Piped, redirected "
            "or captured, it shows the session once and returns."
        ),
    )
    _take_an_issue(session_parser)
    session_parser.set_defaults(act=_show_session)
    feed_parser = verbs.add_parser(
        "feed",
        help="show what the agent said, as it says it",
        description=(
            "Show the agent's actions and outputs from every round of "
            "the issue's newest session, and keep showing what arrives for "
            "as long as the session has another round coming. It ends once "
            "the session has run its final round, and on a stuck session, "
            "which only you can move on. Interrupt it to end it sooner. "
            "Piped, redirected or captured, it shows the feed once and "
            "returns."
        ),
    )
    _take_an_issue(feed_parser)
    feed_parser.add_argument(
        "--round",
        type=int,
        metavar="N",
        help=(
            "show the feed of that round alone, ending when that round "
            "ends. The session view's round list is where you find the "
            "number"
        ),
    )
    feed_parser.set_defaults(act=_show_feed)
    return parser


def _take_an_issue(parser: argparse.ArgumentParser) -> None:
    """Give the verb the issue it shows, written as the issue itself is."""
    parser.add_argument(
        "issue",
        type=_read_issue,
        metavar="GH<n>",
        help="the issue to show",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the verb that the arguments name, and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        args.act(args)
    except ReportableError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def _run(args: argparse.Namespace) -> None:
    """Run a daemon on the checkout we are in."""
    Daemon(Path.cwd(), Harness(args.harness)).run()


def _show_board(args: argparse.Namespace) -> None:
    """Show the board of the checkout we are in."""
    tui.show_board(_find_state(Path.cwd()), tui.open_console())


def _show_session(args: argparse.Namespace) -> None:
    """Show the issue's newest session, from the checkout we are in."""
    tui.show_session(_find_state(Path.cwd()), args.issue, tui.open_console())


def _show_feed(args: argparse.Namespace) -> None:
    """Show the issue's feed, from the checkout we are in."""
    tui.show_feed(
        _find_state(Path.cwd()),
        args.issue,
        tui.open_console(),
        round_number=args.round,
    )


def _find_state(root: Path) -> StateDirectory:
    """Return the state directory here, or say there is nothing here to show.

    A view reads what a daemon left on the disk, and a daemon leaves it in the
    checkout it watches. So a directory with no state directory in it is one
    the reader did not mean to be in.
    """
    state = StateDirectory(root)
    if not state.path.is_dir():
        raise ReportableError(
            f"dreamcatcher has nothing to show in {root}. Run this from the "
            f"checkout that dreamcatcher run watches."
        )
    return state


def _read_issue(given: str) -> int:
    """Return the issue number the argument names, as GH123 names issue 123."""
    found = ISSUE.match(given)
    if found is None:
        raise argparse.ArgumentTypeError(f"name an issue as GH123, not as {given}")
    return int(found.group(1))
