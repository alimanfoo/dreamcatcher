"""The dreamcatcher command line."""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version

import dreamcatcher

DEFAULT_VERB = "run"


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for the dreamcatcher command line."""
    parser = argparse.ArgumentParser(
        prog="dreamcatcher", description=dreamcatcher.__doc__
    )
    parser.add_argument("--version", action="version", version=version("dreamcatcher"))
    verbs = parser.add_subparsers(title="verbs", dest="verb")
    verbs.add_parser(DEFAULT_VERB, help="watch the repository and run agent rounds")
    verbs.add_parser("scry", help="show what the sessions are doing")
    parser.set_defaults(verb=DEFAULT_VERB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the verb that the arguments name, and return the exit status."""
    args = build_parser().parse_args(argv)
    print(f"dreamcatcher {args.verb} is not implemented yet.", file=sys.stderr)
    return 1
