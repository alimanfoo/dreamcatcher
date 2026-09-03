"""The dreamcatcher command line."""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

import dreamcatcher
from dreamcatcher.config import Harness
from dreamcatcher.daemon import Daemon
from dreamcatcher.errors import ReportableError


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
    verbs.add_parser("scry", help="see what the agent sessions are doing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the verb that the arguments name, and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        if args.verb == "scry":
            print("dreamcatcher scry is not implemented yet.", file=sys.stderr)
            return 1
        Daemon(Path.cwd(), Harness(args.harness)).run()
    except ReportableError as error:
        print(error, file=sys.stderr)
        return 1
    return 0
