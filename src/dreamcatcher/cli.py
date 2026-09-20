"""Define the Dreamcatcher command-line interface."""

import argparse
import re
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

import dreamcatcher
from dreamcatcher import tui
from dreamcatcher.agent_assignments import (
    read_agent_assignments_for_issue,
    request_agent_assignment_retry,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import (
    DEFAULT_INTERVAL_SECONDS,
    DaemonRunSettings,
    DreamcatcherDaemon,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.scheduler import (
    DEFAULT_MAX_AGENTS,
    derive_assignment_fault,
    read_scheduler_record,
)
from dreamcatcher.state import StateDirectory

# How a view names the issue it is about, as the issue itself is written.
ISSUE_REFERENCE_PATTERN = re.compile(r"gh(\d+)\Z", re.IGNORECASE)

# The help that says when a view of one assignment ends, which the assignment view
# and the feed both give, since a reader reads one verb's help and no other.
HELP_WHEN_A_VIEW_ENDS = (
    "It ends once the assignment has completed a wrap-up round successfully, "
    "and while an assignment is in fault. "
    "Interrupt it to end it sooner."
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


def build_cli_parser() -> argparse.ArgumentParser:
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
    subcommands = parser.add_subparsers(title="verbs", dest="verb", required=True)
    run_parser = subcommands.add_parser(
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
        # choice with repr(), which turns a member into <AgentHarness.CLAUDE: ...>.
        choices=[harness.value for harness in AgentHarness],
        help="the harness to run this repo's rounds with",
    )
    run_parser.add_argument(
        "--interval",
        type=_parse_positive_integer,
        default=DEFAULT_INTERVAL_SECONDS,
        metavar="SECONDS",
        help=f"seconds between scheduler ticks (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    run_parser.add_argument(
        "--max-agents",
        type=_parse_positive_integer,
        default=DEFAULT_MAX_AGENTS,
        metavar="N",
        help=f"maximum agent rounds to run at once (default: {DEFAULT_MAX_AGENTS})",
    )
    run_parser.set_defaults(act=_run_daemon)
    retry_parser = subcommands.add_parser(
        "retry",
        help="retry a faulted assignment after fixing its problem",
        description=(
            "Clear the newest assignment's fault after you have fixed what "
            "caused its rounds to fail. The daemon may recover it on the next "
            "scheduler tick outside a global cooldown."
        ),
    )
    _add_issue_argument(parser=retry_parser)
    retry_parser.set_defaults(act=_retry_assignment)
    status_parser = subcommands.add_parser(
        "status",
        help="show the instance, issue, and agent-assignment status",
        description=(
            "Show instance and daemon facts, each agent assignment's status, "
            "and available issues in dispatch order. It refreshes "
            "automatically until you interrupt it. "
            + HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " "
            + HELP_WHEN_NOTHING_WATCHES
        ),
    )
    status_parser.set_defaults(act=_show_status)
    assignment_parser = subcommands.add_parser(
        "assignment",
        help="show one issue's newest assignment, in detail",
        description=(
            "Show an overview of the newest assignment at the issue: what "
            "its dispatch settled, the rounds it has run, the command that "
            "resumes the harness session by hand, and the older assignments "
            "at the same issue. It keeps up for as long as the assignment has "
            "another round coming. "
            + HELP_WHEN_A_VIEW_ENDS
            + " "
            + HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " An assignment that is over stays on the screen for you to read. "
            "Interrupt one that is still going and nothing is left behind. "
            + HELP_WHEN_NOTHING_WATCHES
        ),
    )
    _add_issue_argument(parser=assignment_parser)
    assignment_parser.set_defaults(act=_show_assignment)
    feed_parser = subcommands.add_parser(
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
    _add_issue_argument(parser=feed_parser)
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


def _add_issue_argument(*, parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "issue",
        type=_parse_issue_reference,
        metavar="GH<n>",
        help="the issue to use",
    )


def _parse_positive_integer(value: str, /) -> int:
    """Return a positive integer; argparse calls this converter positionally."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main(*, argv: Sequence[str] | None = None) -> int:
    """Run the verb that the arguments name, and return the exit status."""
    arguments = build_cli_parser().parse_args(argv)
    try:
        arguments.act(arguments=arguments)
    except ReportableError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def _run_daemon(*, arguments: argparse.Namespace) -> None:
    DreamcatcherDaemon(
        root=Path.cwd(),
        settings=DaemonRunSettings(
            harness=AgentHarness(arguments.harness),
            interval=arguments.interval,
            max_agents=arguments.max_agents,
        ),
    ).run()


def _retry_assignment(*, arguments: argparse.Namespace) -> None:
    """Clear the newest assignment's fault so the daemon may recover it."""
    state = _find_state_directory(root=Path.cwd())
    issue_assignments = read_agent_assignments_for_issue(
        state=state, issue=arguments.issue
    )
    if not issue_assignments:
        raise ReportableError(f"GH{arguments.issue} has no assignment to retry.")
    assignment = issue_assignments[-1]
    scheduler_record = read_scheduler_record(state=state)
    most_recent_cooldown_ended = (
        None
        if scheduler_record is None
        else scheduler_record.most_recent_cooldown_ended
    )
    if not derive_assignment_fault(
        assignment=assignment,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
    ):
        raise ReportableError(f"{assignment.identifier} is not in fault.")
    request_agent_assignment_retry(assignment=assignment, at=read_current_time())
    print(f"{assignment.identifier} can recover on the next scheduler tick.")


def _show_status(*, arguments: argparse.Namespace) -> None:
    tui.show_status_view(
        state=_find_state_directory(root=Path.cwd()), console=tui.open_tui_console()
    )


def _show_assignment(*, arguments: argparse.Namespace) -> None:
    tui.show_assignment_view(
        state=_find_state_directory(root=Path.cwd()),
        issue=arguments.issue,
        console=tui.open_tui_console(),
    )


def _show_feed(*, arguments: argparse.Namespace) -> None:
    tui.show_feed_view(
        state=_find_state_directory(root=Path.cwd()),
        issue=arguments.issue,
        console=tui.open_tui_console(),
        round_number=arguments.round,
    )


def _find_state_directory(*, root: Path) -> StateDirectory:
    """Return the state directory here, or say there is nothing here to show.

    A view reads what a daemon left on the disk, and a daemon leaves it in the
    checkout it watches. So a directory with no state directory in it is one
    the reader did not mean to be in.
    """
    state_directory = StateDirectory(root=root)
    if not state_directory.path.is_dir():
        raise ReportableError(
            f"dreamcatcher has nothing to show in {root}. Run this from the "
            f"checkout that dreamcatcher run watches."
        )
    return state_directory


def _parse_issue_reference(issue_reference: str, /) -> int:
    """Return the issue number the argument names, as GH123 names issue 123.

    argparse is what calls this, as the type behind the issue argument, and it
    passes the text positionally, so the parameter is positional-only.
    """
    reference_match = ISSUE_REFERENCE_PATTERN.match(issue_reference)
    if reference_match is None:
        raise argparse.ArgumentTypeError(
            f"name an issue as GH123, not as {issue_reference}"
        )
    return int(reference_match.group(1))
