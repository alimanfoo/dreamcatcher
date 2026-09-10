"""The dreamcatcher command line."""

import argparse
import re
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

import dreamcatcher
from dreamcatcher import scry
from dreamcatcher.config import Harness
from dreamcatcher.daemon import Daemon
from dreamcatcher.errors import ReportableError
from dreamcatcher.state import StateDirectory

# How a view names the issue it is about, as the issue itself is written.
ISSUE = re.compile(r"gh(\d+)\Z", re.IGNORECASE)


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for the dreamcatcher command line."""
    parser = argparse.ArgumentParser(
        prog="dreamcatcher", description=dreamcatcher.__doc__
    )
    parser.add_argument("--version", action="version", version=version("dreamcatcher"))
    verbs = parser.add_subparsers(title="verbs", dest="verb", required=True)
    run_parser = verbs.add_parser("run", help="run the dreamcatcher daemon")
    run_parser.add_argument(
        "--harness",
        required=True,
        # The names, not the members. Some Python versions render a rejected
        # choice with repr(), which turns a member into <Harness.CLAUDE: ...>.
        choices=[harness.value for harness in Harness],
        help="the harness to run this repo's rounds with",
    )
    scry_parser = verbs.add_parser("scry", help="see what the agent sessions are doing")
    scry_parser.add_argument(
        "issue",
        nargs="?",
        type=_read_issue,
        metavar="GH<n>",
        help="the issue to show one session of, rather than the whole board",
    )
    # A feed reads either as it arrives or as it stands, and never as both.
    tense = scry_parser.add_mutually_exclusive_group()
    tense.add_argument(
        "--follow",
        action="store_true",
        help="show the session's whole feed, and what arrives while you watch",
    )
    tense.add_argument(
        "--round",
        type=int,
        metavar="N",
        help="show the feed of that round of the session, as it stands",
    )
    # How this verb refuses what its own arguments cannot mean. Refusing
    # through its own parser is what puts the verb's usage above the message,
    # where a reader finds the arguments the message names.
    scry_parser.set_defaults(refuse=scry_parser.error)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the verb that the arguments name, and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        if args.verb == "scry":
            _scry(args)
        else:
            Daemon(Path.cwd(), Harness(args.harness)).run()
    except ReportableError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def _scry(args: argparse.Namespace) -> None:
    """Show the view the arguments ask for, from the checkout we are in.

    The board is what a reader wants most of the time, so it is what `scry`
    alone shows. Naming an issue narrows the view to one session, and the two
    feed views narrow it further, to what that session's agent said.
    """
    _refuse_a_feed_of_nothing(args)
    state = _find_state(Path.cwd())
    console = scry.open_console()
    if args.issue is None:
        scry.show_board(state, console)
    elif args.follow:
        scry.show_feed(state, args.issue, console)
    elif args.round is not None:
        scry.show_feed(state, args.issue, console, round_number=args.round)
    else:
        scry.show_session(state, args.issue, console)


def _refuse_a_feed_of_nothing(args: argparse.Namespace) -> None:
    """Refuse a feed view that was given no session to show the feed of.

    This comes before anything is read off the disk, so a reader who asked for
    the wrong thing hears that rather than hearing about the directory.
    """
    if args.issue is None and (args.follow or args.round is not None):
        args.refuse("--follow and --round each need an issue, as in: scry GH123")


def _find_state(root: Path) -> StateDirectory:
    """Return the state directory here, or say there is nothing here to show.

    `scry` reads what a daemon left on the disk, and a daemon leaves it in the
    checkout it watches. So a directory with no state directory in it is one
    the reader did not mean to be in.
    """
    state = StateDirectory(root)
    if not state.path.is_dir():
        raise ReportableError(
            f"dreamcatcher has nothing to show in {root}. Run scry from the "
            f"checkout that dreamcatcher run watches."
        )
    return state


def _read_issue(given: str) -> int:
    """Return the issue number the argument names, as GH123 names issue 123."""
    found = ISSUE.match(given)
    if found is None:
        raise argparse.ArgumentTypeError(f"name an issue as GH123, not as {given}")
    return int(found.group(1))
