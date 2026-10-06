"""Define the dreamcatcher command-line interface."""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from threading import TIMEOUT_MAX

import dreamcatcher
from dreamcatcher import repository_setup, tui, web
from dreamcatcher.agent_assignments import (
    cancel_assignment,
    read_assignments_for_issue,
)
from dreamcatcher.agent_rounds import request_agent_round_stop
from dreamcatcher.agent_work import request_agent_work_retry
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS, DreamcatcherDaemon
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import read_conversation
from dreamcatcher.scheduler import (
    DEFAULT_MAX_AGENTS,
    derive_agent_work_fault,
    read_scheduler_record,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    read_assignment_statuses_for_issue,
    read_conversation_status,
    read_dreamcatcher_daemon_status,
)
from dreamcatcher.version import DREAMCATCHER_VERSION

# How a view names the issue it is about, as the issue itself is written.
_ISSUE_REFERENCE_PATTERN = re.compile(r"gh(\d+)\Z", re.IGNORECASE)
_MAX_INTERVAL_SECONDS = int(TIMEOUT_MAX) - 1

# The help that says what a view does to the terminal it runs in, which the two
# views that draw a picture over the one before give.
_HELP_WHEN_A_VIEW_TAKES_THE_SCREEN = (
    "It takes the whole terminal while it runs, and gives it back when it ends."
)

# The help that says what a view does when nothing is watching it, which every
# verb gives.
_HELP_WHEN_NOTHING_WATCHES = (
    "Piped, redirected or captured, it shows what is there once and returns."
)


def _build_cli_parser() -> argparse.ArgumentParser:
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
    init_parser = subcommands.add_parser(
        "init",
        help="prepare this checkout for the dreamcatcher daemon",
        description=(
            "Check what dreamcatcher run needs in this repository's main "
            "checkout, and put in place what is missing. It checks that gh is "
            "signed in with push access, that Git can commit and that origin/main "
            "can be fetched. It writes a default dreamcatcher.toml when there is "
            "none, checks that each harness the file uses is signed in, installs "
            "the dream plugin for each of those harnesses at user scope, and "
            "creates the labels the file names. It never commits or pushes. "
            "Running it again repeats the checks and leaves alone what is "
            "already in place."
        ),
    )
    init_parser.set_defaults(act=_set_up_repository)
    run_parser = subcommands.add_parser(
        "run",
        help="run the dreamcatcher daemon",
        description=(
            "Watch this repository for labelled issue conversations and agent "
            "assignments, and carry every assignment through review until its "
            "pull request is merged or closed and its wrap-up round succeeds. "
            "One daemon runs per checkout, so a second daemon here refuses while "
            "the first is alive."
        ),
    )
    run_parser.add_argument(
        "--harness",
        required=True,
        # The names, not the members. Some Python versions render a rejected
        # choice with repr(), which turns a member into <AgentHarness.CLAUDE: ...>.
        choices=[harness.value for harness in AgentHarness],
        help=(
            "the preferred harness, used by every label whose route has a recipe for it"
        ),
    )
    run_parser.add_argument(
        "--interval",
        type=_parse_interval,
        default=DEFAULT_INTERVAL_SECONDS,
        metavar="SECONDS",
        help=f"seconds between scheduler updates (default: {DEFAULT_INTERVAL_SECONDS})",
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
        help="retry faulted work at an issue after fixing its problem",
        description=(
            "Clear the current faults of the newest assignment and issue "
            "conversation after you have fixed what caused their rounds to "
            "fail. The daemon may recover them on the next scheduler update "
            "outside a global cooldown."
        ),
    )
    _add_issue_argument(parser=retry_parser)
    retry_parser.set_defaults(act=_retry_agent_work)
    stop_parser = subcommands.add_parser(
        "stop",
        help="stop one running assignment or conversation round",
        description=(
            "Request a stop for the current round of the selected agent work. "
            "The round must be running under the daemon and have a resumable "
            "harness session."
        ),
    )
    _add_issue_argument(parser=stop_parser)
    _add_agent_work_selector(parser=stop_parser)
    stop_parser.set_defaults(act=_stop_agent_work)
    cancel_parser = subcommands.add_parser(
        "cancel",
        help="cancel an issue's newest assignment to finish its pull request by hand",
        description=(
            "Cancel the newest assignment at the issue, so that you can finish "
            "its pull request by hand. dreamcatcher asks a running round to "
            "stop, runs no further rounds for the assignment, and treats its "
            "open pull request as work outside dreamcatcher. The worktree and "
            "branch stay in place. A cancel cannot be undone, and it does not "
            "need the daemon to be running."
        ),
    )
    _add_issue_argument(parser=cancel_parser)
    cancel_parser.set_defaults(act=_cancel_assignment)
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
            "failed assignment setups, available issues in dispatch order, blocked "
            "issues, and assignment routing conflicts. It refreshes automatically "
            "until you interrupt it. "
            + _HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " "
            + _HELP_WHEN_NOTHING_WATCHES
        ),
    )
    status_parser.set_defaults(act=_show_status)
    assignment_parser = subcommands.add_parser(
        "assignment",
        help="show one issue's newest assignment, in detail",
        description=(
            "Show an overview of the newest assignment at the issue: what "
            "its assignment dispatch settled, the rounds it has run, the command that "
            "resumes the harness session by hand, and the older assignments "
            "at the same issue. It keeps up until the assignment ends after a "
            "successful wrap-up or a cancel. Interrupt it to end it sooner. "
            + _HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " An ended assignment stays on the screen for you to read. "
            "Interrupt one that is still going and nothing is left behind. "
            + _HELP_WHEN_NOTHING_WATCHES
        ),
    )
    _add_issue_argument(parser=assignment_parser)
    assignment_parser.set_defaults(act=_show_assignment)
    conversation_parser = subcommands.add_parser(
        "conversation",
        help="show one issue conversation, in detail",
        description=(
            "Show an issue conversation's chosen settings, harness session, worktree, "
            "code revision, and rounds. It keeps up while the status report "
            "lists the conversation. "
            + _HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " "
            + _HELP_WHEN_NOTHING_WATCHES
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
            "arrives until an assignment ends or the status report stops listing "
            "a conversation. " + _HELP_WHEN_NOTHING_WATCHES
        ),
    )
    _add_issue_argument(parser=feed_parser)
    _add_agent_work_selector(parser=feed_parser)
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


def _add_agent_work_selector(*, parser: argparse.ArgumentParser) -> None:
    owner_group = parser.add_mutually_exclusive_group(required=True)
    owner_group.add_argument(
        "--assignment",
        dest="work_kind",
        action="store_const",
        const=AgentWorkKind.ASSIGNMENT,
        help="select the newest assignment at the issue",
    )
    owner_group.add_argument(
        "--conversation",
        dest="work_kind",
        action="store_const",
        const=AgentWorkKind.CONVERSATION,
        help="select the issue conversation",
    )


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
    if interval > _MAX_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(
            f"must be no greater than {_MAX_INTERVAL_SECONDS}"
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
    arguments = _build_cli_parser().parse_args(argv)
    try:
        arguments.act(arguments=arguments)
    except ReportableError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def _set_up_repository(*, arguments: argparse.Namespace) -> None:
    repository_setup.set_up_repository(root=Path.cwd())


def _run_daemon(*, arguments: argparse.Namespace) -> None:
    DreamcatcherDaemon(
        root=Path.cwd(),
        harness=AgentHarness(arguments.harness),
        interval=arguments.interval,
        max_agents=arguments.max_agents,
    ).run()


def _retry_agent_work(*, arguments: argparse.Namespace) -> None:
    """Clear every current fault at an issue so the daemon may recover it."""
    state = _find_state_directory(root=Path.cwd())
    issue_assignments = read_assignments_for_issue(state=state, issue=arguments.issue)
    assignment = issue_assignments[-1] if issue_assignments else None
    conversation = read_conversation(state=state, issue=arguments.issue)
    current_time = read_current_time()
    scheduler_record = read_scheduler_record(state=state, at=current_time)
    most_recent_cooldown_ended = (
        None
        if scheduler_record is None
        else scheduler_record.most_recent_cooldown_ended
    )
    retried: list[str] = []
    if assignment is not None and derive_agent_work_fault(
        rounds=assignment.rounds,
        retry_requested_at=assignment.retry_requested_at,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
    ):
        request_agent_work_retry(work=assignment, at=current_time)
        retried.append(assignment.identifier)
    if conversation is not None and derive_agent_work_fault(
        rounds=conversation.rounds,
        retry_requested_at=conversation.retry_requested_at,
        most_recent_cooldown_ended=most_recent_cooldown_ended,
    ):
        if retried:
            try:
                request_agent_work_retry(work=conversation, at=current_time)
            except ReportableError as failure:
                recovered = ", ".join(retried)
                raise ReportableError(
                    f"{recovered} can recover on a later scheduler update, but "
                    f"{conversation.identifier} could not be retried: {failure}"
                ) from failure
        else:
            request_agent_work_retry(work=conversation, at=current_time)
        retried.append(conversation.identifier)
    if not retried:
        raise ReportableError(f"GH{arguments.issue} has no agent work in fault.")
    print(f"{', '.join(retried)} can recover on a later scheduler update.")


def _stop_agent_work(*, arguments: argparse.Namespace) -> None:
    """Request a stop for the selected agent work's live round."""
    state = _find_state_directory(root=Path.cwd())
    daemon = read_dreamcatcher_daemon_status(state=state)
    if arguments.work_kind is AgentWorkKind.ASSIGNMENT:
        statuses = read_assignment_statuses_for_issue(
            state=state, issue=arguments.issue, daemon=daemon
        )
        paths = None if not statuses else statuses[0].stoppable_round_paths
        work_description = "newest assignment"
    else:
        status = read_conversation_status(
            state=state, issue=arguments.issue, daemon=daemon
        )
        paths = None if status is None else status.stoppable_round_paths
        work_description = "issue conversation"
    if paths is None:
        raise ReportableError(
            f"The {work_description} at GH{arguments.issue} has no running round "
            "that can be stopped."
        )
    request_agent_round_stop(paths=paths)
    print(
        f"Requested a stop for {work_description} round {paths.number} "
        f"at GH{arguments.issue}."
    )


def _cancel_assignment(*, arguments: argparse.Namespace) -> None:
    """Cancel the newest assignment at an issue so the user can take it over."""
    state = _find_state_directory(root=Path.cwd())
    issue_assignments = read_assignments_for_issue(state=state, issue=arguments.issue)
    if not issue_assignments:
        raise ReportableError(f"GH{arguments.issue} has no assignment.")
    assignment = issue_assignments[-1]
    cancel_assignment(assignment=assignment, at=read_current_time())
    print(
        f"{assignment.identifier} is cancelled. Finish pull request "
        f"#{assignment.record.pull_request} by hand."
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
        issue=arguments.issue,
        work_kind=arguments.work_kind,
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
    reference_match = _ISSUE_REFERENCE_PATTERN.match(issue_reference)
    if reference_match is None:
        raise argparse.ArgumentTypeError(
            f"name an issue as GH123, not as {issue_reference}"
        )
    return int(reference_match.group(1))
