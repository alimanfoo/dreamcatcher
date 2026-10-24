"""Define the dreamcatcher command-line interface."""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from threading import TIMEOUT_MAX

import dreamcatcher
from dreamcatcher import repository_setup, tui, web
from dreamcatcher.agent_assignments import cancel_assignment
from dreamcatcher.agent_rounds import request_agent_round_stop
from dreamcatcher.agent_work import (
    AgentWork,
    find_agent_work,
    parse_agent_work_identifier,
    read_agent_work_at_issue,
    request_agent_work_retry,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS, DreamcatcherDaemon
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler import DEFAULT_MAX_AGENTS
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import read_agent_work_status, read_dreamcatcher_daemon_status
from dreamcatcher.version import DREAMCATCHER_VERSION

# How a command names an issue, as the issue itself is written.
_ISSUE_REFERENCE_PATTERN = re.compile(r"gh(\d+)\Z", re.IGNORECASE | re.ASCII)
_MAX_INTERVAL_SECONDS = int(TIMEOUT_MAX) - 1

# How a command names the agent work it acts on. An issue number names the one
# piece of agent work at that issue, and an agent work identifier names that
# exact work.
type _AgentWorkReference = int | str

# The help that says what a view does to the terminal it runs in, which every
# view that draws a picture over the one before gives.
_HELP_WHEN_A_VIEW_TAKES_THE_SCREEN = (
    "It takes the whole terminal while it runs, and gives it back when it ends."
)

# The help that says what a view does when nothing is watching it, which every
# command gives.
_HELP_WHEN_NOTHING_WATCHES = (
    "Piped, redirected or captured, it shows what is there once and returns."
)


def _build_cli_parser() -> argparse.ArgumentParser:
    """Return the parser for the dreamcatcher command line.

    Each command shows one view, or runs the daemon, and every argument
    belongs to the command that takes it. So a command's own --help describes
    the whole of what that command does, and argparse does all the refusing: a
    command given an argument it does not take, or given none of the arguments
    it requires, is refused with that command's own usage line above the
    message. Nothing here has to check an argument against the command it
    arrived with.
    """
    parser = argparse.ArgumentParser(
        prog="dreamcatcher", description=dreamcatcher.__doc__
    )
    parser.add_argument("--version", action="version", version=DREAMCATCHER_VERSION)

    # A command that finds more than one piece of agent work at an issue reads
    # dest to name itself in the commands it suggests, and argparse names it
    # when a bare invocation omits the command.
    subcommands = parser.add_subparsers(title="commands", dest="command", required=True)
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
            "Watch this repository for labelled issue conversations, agent "
            "assignments and campaigns, and carry every assignment through "
            "review until its pull request is merged or closed and its wrap-up "
            "round succeeds. "
            "One daemon runs per checkout, so a second daemon here refuses while "
            "the first is alive. The command opens and serves the web interface "
            "for the same lifetime unless --noweb is present."
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
    run_parser.add_argument(
        "--noweb",
        action="store_false",
        dest="should_serve_web",
        help="run the daemon without opening or serving the web interface",
    )
    run_parser.set_defaults(act=_run_daemon)
    retry_parser = subcommands.add_parser(
        "retry",
        help="retry faulted agent work after fixing its problem",
        description=(
            "Clear the current fault of the selected agent work after you have "
            "fixed what caused its rounds to fail. The daemon may run it again "
            "on the next scheduler update outside a global cooldown."
        ),
    )
    _add_agent_work_argument(parser=retry_parser)
    retry_parser.set_defaults(act=_retry_agent_work)
    stop_parser = subcommands.add_parser(
        "stop",
        help="stop one running round of agent work",
        description=(
            "Request a stop for the current round of the selected agent work. "
            "The round must be running under the daemon and have a resumable "
            "harness session."
        ),
    )
    _add_agent_work_argument(parser=stop_parser)
    stop_parser.set_defaults(act=_stop_agent_work)
    cancel_parser = subcommands.add_parser(
        "cancel",
        help="cancel one assignment to finish its pull request by hand",
        description=(
            "Cancel the selected assignment, so that you can finish its pull "
            "request by hand. dreamcatcher asks a running round to "
            "stop, runs no further rounds for the assignment, and treats its "
            "open pull request as work outside dreamcatcher. The worktree and "
            "branch stay in place. A cancel cannot be undone, and it does not "
            "need the daemon to be running."
        ),
    )
    _add_agent_work_argument(parser=cancel_parser)
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
        help="show the instance, its agent work, and the labels waiting for work",
        description=(
            "Show instance and daemon facts, each assignment, conversation and "
            "campaign, and each dispatch label that no open work answers, in "
            "dispatch order, with why no work has started. It "
            "refreshes automatically "
            "until you interrupt it. "
            + _HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " "
            + _HELP_WHEN_NOTHING_WATCHES
        ),
    )
    status_parser.set_defaults(act=_show_status)
    view_parser = subcommands.add_parser(
        "view",
        help="show one piece of agent work in detail",
        description=(
            "Show an overview of the agent work that you name: what its work "
            "record holds, its harness session, worktree and rounds, and the "
            "command that resumes the harness session by hand. An assignment's "
            "overview also gives its pull request and branch. It stays on that "
            "work, and keeps up until the work ends, as an assignment does after "
            "a successful wrap-up or a cancel. Interrupt it to end it sooner. "
            + _HELP_WHEN_A_VIEW_TAKES_THE_SCREEN
            + " Ended work stays on the screen for you to read. "
            "Interrupt work that is still going and nothing is left behind. "
            + _HELP_WHEN_NOTHING_WATCHES
        ),
    )
    _add_agent_work_argument(parser=view_parser)
    view_parser.set_defaults(act=_show_agent_work)
    feed_parser = subcommands.add_parser(
        "feed",
        help="show what the agent said, as it says it",
        description=(
            "Show the agent's actions and outputs from every round of "
            "the selected assignment, conversation or campaign, and keep "
            "showing what arrives until the work ends. " + _HELP_WHEN_NOTHING_WATCHES
        ),
    )
    _add_agent_work_argument(parser=feed_parser)
    feed_parser.add_argument(
        "--round",
        type=int,
        metavar="N",
        help=(
            "show the feed of that round alone, ending when that round "
            "ends. The view of the selected work lists its round numbers"
        ),
    )
    feed_parser.set_defaults(act=_show_feed)
    return parser


def _add_agent_work_argument(*, parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "work",
        type=_parse_agent_work_reference,
        metavar="GH<n>|IDENTIFIER",
        help=(
            "an issue as GH123, for the one piece of agent work at it, or an "
            "agent work identifier such as GH123-20260912-192458-assignment, "
            "for that exact work"
        ),
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
    """Run the command that the arguments name, and return the exit status."""
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
    daemon = DreamcatcherDaemon(
        root=Path.cwd(),
        preferred_harness=AgentHarness(arguments.harness),
        interval=arguments.interval,
        max_agents=arguments.max_agents,
    )
    if not arguments.should_serve_web:
        daemon.run()
        return
    daemon.run(
        companion=web.serve_web_in_background(state=daemon.state),
    )


def _retry_agent_work(*, arguments: argparse.Namespace) -> None:
    """Clear the fault of the selected agent work."""
    state = _find_state_directory(root=Path.cwd())
    work = _select_agent_work(state=state, arguments=arguments)
    status = read_agent_work_status(
        state=state, work=work, daemon=read_dreamcatcher_daemon_status(state=state)
    )
    if not status.is_in_fault:
        raise ReportableError(f"{work.identifier} is not in fault.")
    request_agent_work_retry(work=work, at=read_current_time())
    print(f"{work.identifier} can run again on a later scheduler update.")


def _stop_agent_work(*, arguments: argparse.Namespace) -> None:
    """Request a stop for the selected agent work's live round."""
    state = _find_state_directory(root=Path.cwd())
    work = _select_agent_work(state=state, arguments=arguments)
    paths = read_agent_work_status(
        state=state, work=work, daemon=read_dreamcatcher_daemon_status(state=state)
    ).stoppable_round_paths
    if paths is None:
        raise ReportableError(
            f"{work.identifier} has no running round that can be stopped."
        )
    request_agent_round_stop(paths=paths)
    print(f"Requested a stop for {work.identifier} round {paths.number}.")


def _cancel_assignment(*, arguments: argparse.Namespace) -> None:
    """Cancel the selected assignment so the user can take it over."""
    state = _find_state_directory(root=Path.cwd())
    work = _select_agent_work(state=state, arguments=arguments)
    if work.record.kind is not AgentWorkKind.ASSIGNMENT:
        raise ReportableError(f"{work.identifier} is not an assignment.")
    if not cancel_assignment(assignment=work, at=read_current_time()):
        raise ReportableError(f"{work.identifier} has already ended.")
    print(f"{work.identifier} is cancelled.")


def _show_status(*, arguments: argparse.Namespace) -> None:
    tui.show_status_view(
        state=_find_state_directory(root=Path.cwd()), console=tui.open_tui_console()
    )


def _show_web(*, arguments: argparse.Namespace) -> None:
    web.serve_web(
        state=_find_state_directory(root=Path.cwd()),
        port=arguments.port,
    )


def _show_agent_work(*, arguments: argparse.Namespace) -> None:
    state = _find_state_directory(root=Path.cwd())
    tui.show_agent_work_view(
        state=state,
        work=_select_agent_work(state=state, arguments=arguments),
        console=tui.open_tui_console(),
    )


def _show_feed(*, arguments: argparse.Namespace) -> None:
    state = _find_state_directory(root=Path.cwd())
    tui.show_feed_view(
        state=state,
        work=_select_agent_work(state=state, arguments=arguments),
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


def _select_agent_work(
    *, state: StateDirectory, arguments: argparse.Namespace
) -> AgentWork:
    """Return the one piece of agent work that the command's reference names.

    An issue names the one piece of agent work at it, of any kind, ended or not.
    When the issue has more than one, the ReportableError gives the command
    again for each piece, by its identifier, in identifier order.
    """
    reference: _AgentWorkReference = arguments.work
    if isinstance(reference, str):
        work = find_agent_work(state=state, identifier=reference)
        if work is None:
            raise ReportableError(f"No agent work here is named {reference}.")
        return work
    match read_agent_work_at_issue(state=state, issue=reference):
        case []:
            raise ReportableError(f"No agent work here for GH{reference}.")
        case [work]:
            return work
        case every_work:
            commands = "".join(
                f"\n  dreamcatcher {arguments.command} {work.identifier}"
                for work in every_work
            )
            raise ReportableError(
                f"GH{reference} has more than one piece of agent work. "
                f"Run one of these:{commands}"
            )


def _parse_agent_work_reference(text: str, /) -> _AgentWorkReference:
    """Return the issue number or agent work identifier that the argument names.

    argparse is what calls this, as the type behind the work argument, and it
    passes the text positionally, so the parameter is positional-only.
    """
    reference_match = _ISSUE_REFERENCE_PATTERN.match(text)
    if reference_match is not None:
        return int(reference_match.group(1))
    identifier = parse_agent_work_identifier(text=text)
    if identifier is None:
        raise argparse.ArgumentTypeError(
            "name an issue as GH123, or agent work by its identifier as "
            f"GH123-20260912-192458-assignment, not as {text}"
        )
    return identifier
