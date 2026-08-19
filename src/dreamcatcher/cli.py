"""The dreamcatcher command line."""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

import dreamcatcher
from dreamcatcher.config import Harness
from dreamcatcher.daemon import Daemon
from dreamcatcher.errors import DreamcatcherError


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for the dreamcatcher command line."""
    parser = argparse.ArgumentParser(
        prog="dreamcatcher", description=dreamcatcher.__doc__
    )
    parser.add_argument("--version", action="version", version=version("dreamcatcher"))
    verbs = parser.add_subparsers(title="verbs", dest="verb", required=True)
    running = verbs.add_parser("run", help="run the dreamcatcher daemon")
    running.add_argument(
        "--harness",
        # The names, not the members. Some Python versions render a rejected
        # choice with repr(), which turns a member into <Harness.CLAUDE: ...>.
        choices=[harness.value for harness in Harness],
        help="the harness to run rounds with, in place of the configured one",
    )
    running.set_defaults(act=run)
    scrying = verbs.add_parser("scry", help="see what the agent sessions are doing")
    scrying.set_defaults(act=scry)
    return parser


def run(args: argparse.Namespace) -> int:
    """Run the daemon on the repo the current directory is a checkout of."""
    chosen = Harness(args.harness) if args.harness is not None else None
    Daemon.for_checkout(Path.cwd(), chosen).run()
    return 0


def scry(args: argparse.Namespace) -> int:
    """Show what the agent sessions are doing."""
    print(f"dreamcatcher {args.verb} is not implemented yet.", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the verb that the arguments name, and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        return args.act(args)
    except DreamcatcherError as error:
        print(error, file=sys.stderr)
        return 1
