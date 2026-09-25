"""Define the Dreamcatcher command-line interface."""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from threading import TIMEOUT_MAX

import dreamcatcher
from dreamcatcher import tui, web
from dreamcatcher.agent_assignments import (
    AgentAssignment,
    read_agent_assignments_for_issue,
    request_agent_assignment_retry,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS, DreamcatcherDaemon
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import (
    IssueConversation,
    read_issue_conversation,
    request_issue_conversation_retry,
)
from dreamcatcher.scheduler import (
    DEFAULT_MAX_AGENTS,
    derive_assignment_fault,
    derive_issue_conversation_fault,
    read_scheduler_record,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.version import DREAMCATCHER_VERSION

# How a view names the issue it is about, as the issue itself is written.
ISSUE_REFERENCE_PATTERN = re.compile(r"gh(\d+)\Z", re.IGNORECASE)
MAX_INTERVAL_SECONDS = int(TIMEOUT_MAX) - 1

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
    parser.add_argument("--version", action="version", version=DREAMCATCHER_VERSION)
    subcommands = parser.add_subparsers(title="verbs", dest="verb", required=True)
    run_parser = subcommands.add_parser(
        "run",
        help="run the dreamcatcher daemon",
        description=(
            "Watch this repository for labelled issue conversations and agent "
            "assignments, and carry every assignment on until its pull request "
            "is ready for you to review. One daemon watches one "
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
        type=_parse_interval,
        default=DEFAULT_INTERVAL_SECONDS,
        metavar="SECONDS",
        help=f"seconds between scheduler ticks (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    run_parser.add_argument(
        "--max-agents",
        type=_parse_positive_integer,
        default=DEFAULT_MAX_AGENTS,
        metavar="N",
        help=f"maximum agents to run at once (default: {DEFAULT_MAX_AGENTS})",
    )
    run_parser.set_defaults(act=_run_daemon)
    retry_parser = subcommands.add_parser(
        "retry",
        help="retry faulted agent work after fixing its problem",
        description=(
            "Clear an assignment or issue conversation fault after you have "
            "fixed what caused its rounds to fail. The daemon may recover it "
            "on the next scheduler tick outside a global cooldown."
        ),
    )
    _add_issue_argument(parser=retry_parser)
    retry_owner_group = retry_parser.add_mutually_exclusive_group()
    retry_owner_group.add_argument(
        "--assignment",
        dest="owner_kind",
        action="store_const",
        const=AgentWorkKind.ASSIGNMENT,
        help="retry the newest assignment at the issue",
    )
    retry_owner_group.add_argument(
        "--conversation",
        dest="owner_kind",
        action="store_const",
        const=AgentWorkKind.CONVERSATION,
        help="retry the issue conversation",
    )
    retry_parser.set_defaults(act=_retry_agent_work)
    web_parser = subcommands.add_parser(
        "web",
        help="serve the local status report in a web browser",
        description=(
            "Serve this repository's local status report on loopback, open it "
            "in the default browser, and keep serving until you interrupt it. "
            "The view reads only the local state directory and never contacts "
            "GitHub."
        ),
    )
    web_parser.add_argument(
        "--port",
        type=_parse_port,
        metavar="PORT",
        help="listen on this port exactly instead of choosing one for the repository",
    )
    web_parser.set_defaults(act=_show_web)
    status_parser = subcommands.add_parser(
        "status",
        help="show the instance, conversation, issue, and assignment status",
        description=(
            "Show instance and daemon facts, each conversation and assignment, "
            "available issues in dispatch order, and blocked issues. It refreshes "
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
    conversation_parser = subcommands.add_parser(
        "conversation",
        help="show one issue conversation, in detail",
        description=(
            "Show an issue conversation's chosen settings, session, worktree, "
            "code revision, and rounds. It keeps up until the conversation "
            "becomes inactive, enters fault, or needs attention. "
            + HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " "
            + HELP_WHEN_NOTHING_WATCHES
        ),
    )
    _add_issue_argument(parser=conversation_parser)
    conversation_parser.set_defaults(act=_show_conversation)
    feed_parser = subcommands.add_parser(
        "feed",
        help="show what the agent said, as it says it",
        description=(
            "Show the agent's actions and outputs from every round of "
            "the selected assignment or conversation, and keep showing what "
            "arrives until that work is over, enters fault, or needs attention. "
            + HELP_WHEN_NOTHING_WATCHES
        ),
    )
    _add_issue_argument(parser=feed_parser)
    owner_group = feed_parser.add_mutually_exclusive_group(required=True)
    owner_group.add_argument(
        "--assignment",
        dest="owner_kind",
        action="store_const",
        const=AgentWorkKind.ASSIGNMENT,
        help="show the newest assignment at the issue",
    )
    owner_group.add_argument(
        "--conversation",
        dest="owner_kind",
        action="store_const",
        const=AgentWorkKind.CONVERSATION,
        help="show the issue conversation",
    )
    feed_parser.add_argument(
        "--round",
        type=int,
        metavar="N",
        help=(
            "show the feed of that round alone, ending when that round "
            "ends. The selected work's detail view lists its round numbers"
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


def _parse_interval(value: str, /) -> int:
    """Return an interval that the process can wait; argparse calls positionally."""
    interval = _parse_positive_integer(value)
    if interval > MAX_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(
            f"must be no greater than {MAX_INTERVAL_SECONDS}"
        )
    return interval


def _parse_port(value: str, /) -> int:
    """Return a valid TCP port; argparse calls this converter positionally."""
    port = _parse_positive_integer(value)
    if port > web.WEB_MAX_PORT:
        raise argparse.ArgumentTypeError(f"must be no greater than {web.WEB_MAX_PORT}")
    return port


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
        harness=AgentHarness(arguments.harness),
        interval=arguments.interval,
        max_agents=arguments.max_agents,
    ).run()


def _retry_agent_work(*, arguments: argparse.Namespace) -> None:
    """Clear one agent-work owner's fault so the daemon may recover it."""
    state = _find_state_directory(root=Path.cwd())
    owner = _select_retry_owner(
        state=state,
        issue=arguments.issue,
        owner_kind=arguments.owner_kind,
    )
    current_time = read_current_time()
    scheduler_record = read_scheduler_record(state=state, at=current_time)
    most_recent_cooldown_ended = (
        None
        if scheduler_record is None
        else scheduler_record.most_recent_cooldown_ended
    )
    if isinstance(owner, AgentAssignment):
        is_faulted = derive_assignment_fault(
            assignment=owner,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
    else:
        is_faulted = derive_issue_conversation_fault(
            conversation=owner,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
    if not is_faulted:
        raise ReportableError(f"{owner.identifier} is not in fault.")
    if isinstance(owner, AgentAssignment):
        request_agent_assignment_retry(assignment=owner, at=current_time)
    else:
        request_issue_conversation_retry(conversation=owner, at=current_time)
    print(f"{owner.identifier} can recover on the next scheduler tick.")


def _select_retry_owner(
    *, state: StateDirectory, issue: int, owner_kind: AgentWorkKind | None
) -> AgentAssignment | IssueConversation:
    """Return the requested local work owner, refusing an ambiguous issue."""
    assignments = read_agent_assignments_for_issue(state=state, issue=issue)
    assignment = assignments[-1] if assignments else None
    conversation = read_issue_conversation(state=state, issue=issue)
    if owner_kind is AgentWorkKind.ASSIGNMENT:
        if assignment is None:
            raise ReportableError(f"GH{issue} has no assignment to retry.")
        return assignment
    if owner_kind is AgentWorkKind.CONVERSATION:
        if conversation is None:
            raise ReportableError(f"GH{issue} has no issue conversation to retry.")
        return conversation
    if assignment is not None and conversation is not None:
        raise ReportableError(
            f"GH{issue} has both an assignment and an issue conversation. "
            "Choose --assignment or --conversation."
        )
    if assignment is not None:
        return assignment
    if conversation is not None:
        return conversation
    raise ReportableError(
        f"GH{issue} has no assignment or issue conversation to retry."
    )


def _show_status(*, arguments: argparse.Namespace) -> None:
    tui.show_status_view(
        state=_find_state_directory(root=Path.cwd()), console=tui.open_tui_console()
    )


def _show_web(*, arguments: argparse.Namespace) -> None:
    web.serve_web(
        state=_find_state_directory(root=Path.cwd()),
        port=arguments.port,
    )


def _show_assignment(*, arguments: argparse.Namespace) -> None:
    tui.show_assignment_view(
        state=_find_state_directory(root=Path.cwd()),
        issue=arguments.issue,
        console=tui.open_tui_console(),
    )


def _show_conversation(*, arguments: argparse.Namespace) -> None:
    tui.show_conversation_view(
        state=_find_state_directory(root=Path.cwd()),
        issue=arguments.issue,
        console=tui.open_tui_console(),
    )


def _show_feed(*, arguments: argparse.Namespace) -> None:
    tui.show_feed_view(
        state=_find_state_directory(root=Path.cwd()),
        selection=tui.FeedSelection(
            issue=arguments.issue,
            owner_kind=arguments.owner_kind,
        ),
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
