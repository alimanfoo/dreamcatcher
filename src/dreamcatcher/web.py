"""Render Dreamcatcher status reports as local web pages."""

import errno
import logging
import re
import zlib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, tzinfo
from functools import partial
from pathlib import Path
from typing import Protocol, cast
from webbrowser import open as open_browser

from flask import Flask, Response, render_template, request
from werkzeug.serving import BaseWSGIServer

from dreamcatcher.agent_rounds import (
    AgentRoundPaths,
    AgentRoundRecord,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.documents import is_complete_line_position, read_lines_from
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import (
    compose_agent_round_boundary,
    read_feed_line,
)
from dreamcatcher.issue_conversations import IssueConversation
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
    CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER,
    STATUSES_THAT_END_A_VIEW,
    AgentAssignmentStatus,
    AgentAssignmentStatusValue,
    AgentRoundStatus,
    DreamcatcherStatusReport,
    IssueConversationStatus,
    IssueFactValue,
    IssueObservation,
    read_agent_assignment_status,
    read_dreamcatcher_daemon_status,
    read_issue_conversation_status,
    read_repository,
    read_status_report,
)
from dreamcatcher.words import describe_countdown, describe_time

WEB_HOST = "127.0.0.1"
WEB_BASE_PORT = 8100
WEB_PORT_RANGE = 400
WEB_MAX_PORT = 65535
_ISSUE_REFERENCE_PATTERN = re.compile(r"(?<!\w)(?:GH|#)(\d+)\b(?!-)")
_FEED_CURSOR_PATTERN = re.compile(r"(?P<round>0|[1-9]\d*):(?P<position>\d+)")
_GIT_REVISION_PATTERN = re.compile(r"\b[0-9a-f]{40}\b")
_HTMX_STOP_POLLING_STATUS = 286
_DEFAULT_WEB_THEME = "matrix"
_WEB_THEME_MARKS = {_DEFAULT_WEB_THEME: "phosphor", "nature": "ink"}
_WEB_THEMES = tuple(_WEB_THEME_MARKS)


class _WebServerBindError(Exception):
    def __init__(self, *, error: OSError) -> None:
        super().__init__(str(error))
        self.error = error


class _InvalidFeedCursorError(Exception):
    pass


class _ExclusiveWebServer(BaseWSGIServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        """Bind exclusively while preserving failures for the caller."""
        try:
            super().server_bind()
        except OSError as error:
            raise _WebServerBindError(error=error) from error


class WebServerRunner(Protocol):
    """Run a bound local web server until the process should stop."""

    def __call__(self, *, server: BaseWSGIServer) -> None:
        """Run the server, which has already started listening."""
        ...


@dataclass(frozen=True, kw_only=True)
class WebFact:
    """Represent one labelled fact on a web page."""

    label: str
    value: str
    is_warning: bool = False


@dataclass(frozen=True, kw_only=True)
class WebAssignmentCard:
    """Represent the values rendered in one assignment card."""

    identifier: str
    issue: int
    title: str | None
    status: str
    status_label: str
    detail: str
    dispatch_label: str
    harness: str
    model: str
    effort: str
    pull_request: int
    pull_request_state: str | None
    latest_output: str | None


@dataclass(frozen=True, kw_only=True)
class WebConversationCard:
    """Represent the values rendered in one issue-conversation card."""

    issue: int
    title: str
    status: str
    detail: str
    settings: str | None
    latest_output: str | None


@dataclass(frozen=True, kw_only=True)
class WebAgentRound:
    """Represent one round row on an agent-work page."""

    number: int
    purpose: str
    is_recovery: bool
    started: str
    duration: str
    outcome: str
    revision: str | None
    revision_description: str | None = None


@dataclass(frozen=True, kw_only=True)
class WebFeedLine:
    """Represent one stored feed line on an assignment page."""

    timestamp: str | None
    label: str | None
    detail: str
    is_subagent: bool = False
    is_boundary: bool = False


@dataclass(frozen=True, kw_only=True)
class WebFeedRound:
    """Represent one round's boundary and stored feed lines."""

    number: int
    lines: tuple[WebFeedLine, ...]


@dataclass(frozen=True, kw_only=True)
class WebAgentFeed:
    """Represent a complete agent feed and the cursor after its last line."""

    rounds: tuple[WebFeedRound, ...]
    cursor: str


@dataclass(frozen=True, kw_only=True)
class WebFeedCursor:
    """Identify the next feed byte to read within an assignment round."""

    round_number: int
    position: int


@dataclass(frozen=True, kw_only=True)
class WebAgentTail:
    """Represent one incremental agent-feed response."""

    cursor: str
    feed_rounds: tuple[WebFeedRound, ...]
    status: str
    status_label: str
    detail: str | None
    rounds: tuple[WebAgentRound, ...]
    has_empty_feed_placeholder: bool


@dataclass(frozen=True, kw_only=True)
class WebAgentTailContext:
    """Provide status values alongside one incremental feed read."""

    status: str
    status_label: str
    rounds: tuple[WebAgentRound, ...]
    detail: str | None = None


@dataclass(frozen=True, kw_only=True)
class WebAssignmentView:
    """Represent every value that the assignment template lays out."""

    repository: str
    github_repository_url: str | None
    daemon_state: str
    daemon_summary: str
    identifier: str
    issue: int
    title: str | None
    status: str
    status_label: str
    detail: str
    pull_request: int
    pull_request_state: str | None
    dispatch_label: str
    harness: str
    model: str
    effort: str
    rounds: tuple[WebAgentRound, ...]
    hand_resume_worktree: str | None
    hand_resume_command: str | None
    feed_rounds: tuple[WebFeedRound, ...]
    feed_cursor: str


@dataclass(frozen=True, kw_only=True)
class WebIssueRow:
    """Represent one available or blocked issue row."""

    issue: int
    title: str | None
    labels: str
    status: str
    evidence: tuple[str | int, ...]


@dataclass(frozen=True, kw_only=True)
class WebConversationView:
    """Represent every value that the conversation template lays out."""

    repository: str
    github_repository_url: str | None
    daemon_state: str
    daemon_summary: str
    issue: int
    title: str
    status: str
    detail: str
    facts: tuple[WebFact, ...]
    rounds: tuple[WebAgentRound, ...]
    feed_rounds: tuple[WebFeedRound, ...]
    feed_cursor: str


@dataclass(frozen=True, kw_only=True)
class WebHomeView:
    """Represent every value that the home template lays out."""

    repository: str
    github_repository_url: str | None
    daemon_state: str
    daemon_summary: str
    instance_facts: tuple[WebFact, ...]
    cooldown_message: str | None
    conversations: tuple[WebConversationCard, ...]
    active_assignments: tuple[WebAssignmentCard, ...]
    complete_assignments: tuple[WebAssignmentCard, ...]
    failed_setups: tuple[IssueObservation, ...]
    available_issues: tuple[WebIssueRow, ...]
    blocked_issues: tuple[WebIssueRow, ...]


class _WebFeedOwner(Protocol):
    """Provide the saved rounds and paths that a web feed reads."""

    @property
    def rounds(self) -> list[AgentRoundRecord]:
        """The saved round records in their run order."""
        ...

    def compose_round_paths(self, *, number: int) -> AgentRoundPaths:
        """Return the paths of one numbered round."""
        ...


@dataclass(frozen=True, kw_only=True)
class _WebRoundFeed:
    """Pair one saved round with the feed it wrote."""

    record: AgentRoundRecord
    feed: Path


def create_app(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime] = read_current_time,
    zone: tzinfo | None = None,
) -> Flask:
    """Create the read-only web application for one local state directory.

    Page times use the machine's local zone when zone is None.
    """
    app = Flask(__name__)
    app.config["TRUSTED_HOSTS"] = [WEB_HOST, "localhost"]
    _configure_web_theme(app=app)
    routes = (
        ("/", "show_home", partial(_show_home, state=state, clock=clock, zone=zone)),
        (
            "/assignments/<identifier>",
            "show_assignment",
            partial(_show_assignment, state=state, clock=clock, zone=zone),
        ),
        (
            "/assignments/<identifier>/tail",
            "show_assignment_tail",
            partial(_show_assignment_tail, state=state, clock=clock, zone=zone),
        ),
        (
            "/conversations/<int:issue>",
            "show_conversation",
            partial(_show_conversation, state=state, clock=clock, zone=zone),
        ),
        (
            "/conversations/<int:issue>/tail",
            "show_conversation_tail",
            partial(_show_conversation_tail, state=state, clock=clock, zone=zone),
        ),
    )
    for rule, endpoint, view_func in routes:
        app.add_url_rule(rule, endpoint=endpoint, view_func=view_func, methods=["GET"])
    app.register_error_handler(ReportableError, _show_reportable_error)
    return app


def _show_home(
    *, state: StateDirectory, clock: Callable[[], datetime], zone: tzinfo | None
) -> str:
    """Render the local status overview."""
    report = read_status_report(state=state, clock=clock)
    return render_template(
        "home.html", view=_compose_home_view(report=report, zone=zone)
    )


def _show_assignment(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    identifier: str,
) -> str | tuple[str, int]:
    """Render one assignment page, or a missing response."""
    status = read_agent_assignment_status(
        state=state,
        identifier=identifier,
        clock=clock,
    )
    if status is None:
        return (
            render_template(
                "error.html",
                message=f"No agent assignment here has identifier {identifier}.",
            ),
            404,
        )
    return render_template(
        "assignment.html",
        view=_compose_assignment_view(state=state, status=status, zone=zone),
    )


def _show_assignment_tail(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    identifier: str,
) -> str | tuple[str, int]:
    """Render assignment feed output written after the requested cursor."""
    status = read_agent_assignment_status(
        state=state,
        identifier=identifier,
        clock=clock,
    )
    if status is None:
        return (
            render_template(
                "error.html",
                message=f"No agent assignment here has identifier {identifier}.",
            ),
            404,
        )
    return _show_agent_tail(
        owner=status.assignment,
        context=WebAgentTailContext(
            status=str(status.value),
            status_label=_compose_assignment_status_label(status=status),
            detail=status.detail,
            rounds=_compose_agent_rounds(
                round_statuses=status.round_statuses, zone=zone
            ),
        ),
        is_terminal=status.value in STATUSES_THAT_END_A_VIEW,
        status_id="assignment-status",
        zone=zone,
    )


def _show_conversation(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    issue: int,
) -> str | tuple[str, int]:
    """Render one issue-conversation page, or a missing response."""
    status = read_issue_conversation_status(state=state, issue=issue, clock=clock)
    if status is None:
        return _missing_conversation_response(issue=issue)
    return render_template(
        "conversation.html",
        view=_compose_conversation_view(state=state, status=status, zone=zone),
    )


def _show_conversation_tail(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    issue: int,
) -> str | tuple[str, int]:
    """Render conversation feed output written after the requested cursor."""
    status = read_issue_conversation_status(state=state, issue=issue, clock=clock)
    if status is None:
        return _missing_conversation_response(issue=issue)
    return _show_agent_tail(
        owner=status.conversation,
        context=WebAgentTailContext(
            status=str(status.value),
            status_label=str(status.value),
            detail=status.detail,
            rounds=_compose_agent_rounds(
                round_statuses=status.round_statuses, zone=zone
            ),
        ),
        is_terminal=status.is_over,
        status_id="conversation-status",
        zone=zone,
    )


def _show_agent_tail(
    *,
    owner: _WebFeedOwner | None,
    context: WebAgentTailContext,
    is_terminal: bool,
    status_id: str,
    zone: tzinfo | None,
) -> str | tuple[str, int]:
    """Render incremental feed output for an assignment or conversation."""
    try:
        cursor = _decode_feed_cursor(value=request.args.get("cursor", ""))
        tail = _read_agent_tail(
            owner=owner,
            context=context,
            cursor=cursor,
            zone=zone,
        )
    except _InvalidFeedCursorError:
        return _invalid_feed_cursor_response()
    response_status = (
        _HTMX_STOP_POLLING_STATUS if not tail.feed_rounds and is_terminal else 200
    )
    return (
        render_template("tail.html", tail=tail, status_id=status_id),
        response_status,
    )


def _missing_conversation_response(*, issue: int) -> tuple[str, int]:
    """Render the response for an issue with no conversation.

    An issue has a conversation once it has a saved conversation or the latest
    tick observed it as eligible.
    """
    return (
        render_template(
            "error.html",
            message=f"No issue conversation here is for GH{issue}.",
        ),
        404,
    )


def _invalid_feed_cursor_response() -> tuple[str, int]:
    """Render the response for a malformed or stale feed cursor."""
    return render_template("error.html", message="The feed cursor is invalid."), 400


def _show_reportable_error(error: ReportableError, /) -> tuple[str, int]:
    """Render a named read failure for Flask, which passes the error by position."""
    return render_template("error.html", message=str(error)), 500


def _configure_web_theme(*, app: Flask) -> None:
    @app.context_processor
    def add_web_theme() -> dict[str, object]:
        requested_theme = request.args.get("theme")
        remembered_theme = request.cookies.get("theme")
        if requested_theme in _WEB_THEMES:
            theme = requested_theme
        elif remembered_theme in _WEB_THEMES:
            theme = remembered_theme
        else:
            theme = _DEFAULT_WEB_THEME
        return {
            "mark": _WEB_THEME_MARKS[theme],
            "theme": theme,
            "themes": _WEB_THEMES,
        }

    @app.after_request
    def remember_web_theme(response: Response, /) -> Response:
        """Remember a valid theme selected through a browser request."""
        requested_theme = request.args.get("theme")
        if requested_theme in _WEB_THEMES:
            response.set_cookie("theme", requested_theme, samesite="Lax")
        return response


def _run_server(*, server: BaseWSGIServer) -> None:
    server.serve_forever()


def serve_web(
    *,
    state: StateDirectory,
    port: int | None = None,
    browser_opener: Callable[[str], object] = open_browser,
    server_runner: WebServerRunner = _run_server,
    zone: tzinfo | None = None,
) -> None:
    """Serve one local status page, open it, and run until interrupted.

    Page times use the machine's local zone when zone is None.
    """
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    application = create_app(state=state, zone=zone)
    server = _create_web_server(state=state, port=port, application=application)
    address = f"http://{WEB_HOST}:{server.server_port}/"
    try:
        with suppress(KeyboardInterrupt):
            browser_opener(address)
            print(address, flush=True)
            server_runner(server=server)
    finally:
        server.server_close()


def _create_web_server(
    *, state: StateDirectory, port: int | None, application: Flask
) -> BaseWSGIServer:
    starting_port = port if port is not None else _derive_starting_port(state=state)
    ending_port = starting_port if port is not None else WEB_MAX_PORT
    for candidate in range(starting_port, ending_port + 1):
        try:
            return _ExclusiveWebServer(WEB_HOST, candidate, application)
        except _WebServerBindError as failure:
            if failure.error.errno == errno.EADDRINUSE:
                if port is not None:
                    raise ReportableError(f"--port {port} is already in use") from None
                continue
            raise ReportableError(
                f"could not listen on port {candidate}: {failure.error}"
            ) from None
    raise ReportableError(f"no free port is available from {starting_port}")


def _derive_starting_port(*, state: StateDirectory) -> int:
    repository = read_repository(state=state)
    if repository is None:
        return WEB_BASE_PORT
    repository_digest = zlib.crc32(repository.encode("utf-8"))
    return WEB_BASE_PORT + repository_digest % WEB_PORT_RANGE


def _compose_github_repository_url(*, repository: str | None) -> str | None:
    if repository is None:
        return None
    return f"https://github.com/{repository}"


def _compose_home_view(
    *, report: DreamcatcherStatusReport, zone: tzinfo | None
) -> WebHomeView:
    cooldown_end = (
        None
        if report.active_global_cooldown is None
        else describe_time(at=report.active_global_cooldown.ends, zone=zone)
    )
    active_statuses = sorted(
        (
            status
            for status in report.assignment_statuses
            if status.value is not AgentAssignmentStatusValue.COMPLETE
        ),
        key=lambda status: ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER.index(
            status.value
        ),
    )
    complete_statuses = sorted(
        (
            status
            for status in report.assignment_statuses
            if status.value is AgentAssignmentStatusValue.COMPLETE
        ),
        key=_read_assignment_completion_time,
        reverse=True,
    )
    complete_assignments = tuple(
        _compose_assignment_card(status=status) for status in complete_statuses
    )
    active_assignments = tuple(
        _compose_assignment_card(status=status) for status in active_statuses
    )
    return WebHomeView(
        repository=report.repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(
            repository=report.repository
        ),
        daemon_state="stopped" if report.daemon_pid is None else "running",
        daemon_summary=_describe_daemon(
            daemon_pid=report.daemon_pid,
            dreamcatcher_version=report.dreamcatcher_version,
        ),
        instance_facts=_compose_instance_facts(report=report),
        cooldown_message=(
            None if cooldown_end is None else f"Global cooldown ends {cooldown_end}"
        ),
        conversations=tuple(
            _compose_conversation_card(status=status)
            for status in sorted(
                report.conversation_statuses,
                key=lambda status: CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER.index(
                    status.value
                ),
            )
        ),
        active_assignments=active_assignments,
        complete_assignments=complete_assignments,
        failed_setups=tuple(report.failed_assignment_setups),
        available_issues=tuple(
            _compose_issue_row(observation=issue) for issue in report.available_issues
        ),
        blocked_issues=tuple(
            _compose_issue_row(observation=issue) for issue in report.blocked_issues
        ),
    )


def _read_assignment_completion_time(status: AgentAssignmentStatus, /) -> datetime:
    """Return the completion time for sorted, which passes items by position.

    The caller selects complete statuses, whose final round has a successful
    ending.
    """
    ending = cast(
        "SuccessfulAgentRoundEnding",
        status.assignment.rounds[-1].ending,
    )
    return ending.at


def _compose_assignment_card(*, status: AgentAssignmentStatus) -> WebAssignmentCard:
    assignment = status.assignment
    return WebAssignmentCard(
        identifier=assignment.identifier,
        issue=assignment.record.issue,
        title=assignment.record.title,
        status=str(status.value),
        status_label=_compose_assignment_status_label(status=status),
        detail=status.detail,
        dispatch_label=assignment.record.dispatch_label,
        harness=str(assignment.record.harness),
        model=assignment.record.model,
        effort=assignment.record.effort,
        pull_request=assignment.record.pull_request,
        pull_request_state=_describe_pull_request_state(status=status),
        latest_output=status.latest_output,
    )


def _compose_conversation_card(
    *, status: IssueConversationStatus
) -> WebConversationCard:
    """Return the values shown for one issue conversation on the home page.

    A conversation settles its settings when its first round launches.
    """
    conversation = status.conversation
    return WebConversationCard(
        issue=status.issue,
        title=status.title,
        status=str(status.value),
        detail=status.detail,
        settings=(
            None
            if conversation is None
            else " · ".join(
                [
                    str(conversation.record.harness),
                    conversation.record.model,
                    conversation.record.effort,
                ]
            )
        ),
        latest_output=status.latest_output,
    )


def _describe_pull_request_state(*, status: AgentAssignmentStatus) -> str | None:
    pull_request_observation = status.assignment.record.pull_request_observation
    if pull_request_observation is None:
        return None
    if pull_request_observation.is_open:
        return "draft" if pull_request_observation.is_draft else "ready"
    return pull_request_observation.state.value.lower()


def _compose_assignment_view(
    *,
    state: StateDirectory,
    status: AgentAssignmentStatus,
    zone: tzinfo | None,
) -> WebAssignmentView:
    assignment = status.assignment
    record = assignment.record
    repository = read_repository(state=state)
    daemon = read_dreamcatcher_daemon_status(state=state)
    hand_resume_command = status.hand_resume_command
    feed = _read_agent_feed(owner=assignment, zone=zone)
    return WebAssignmentView(
        repository=repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(repository=repository),
        daemon_state="stopped" if daemon.pid is None else "running",
        daemon_summary=_describe_daemon(
            daemon_pid=daemon.pid,
            dreamcatcher_version=daemon.dreamcatcher_version,
        ),
        identifier=assignment.identifier,
        issue=record.issue,
        title=record.title,
        status=str(status.value),
        status_label=_compose_assignment_status_label(status=status),
        detail=status.detail,
        pull_request=record.pull_request,
        pull_request_state=_describe_pull_request_state(status=status),
        dispatch_label=record.dispatch_label,
        harness=str(record.harness),
        model=record.model,
        effort=record.effort,
        rounds=_compose_agent_rounds(round_statuses=status.round_statuses, zone=zone),
        hand_resume_worktree=(
            None
            if hand_resume_command is None
            else state.describe_path(path=record.worktree)
        ),
        hand_resume_command=(
            None if hand_resume_command is None else " ".join(hand_resume_command)
        ),
        feed_rounds=feed.rounds,
        feed_cursor=feed.cursor,
    )


def _compose_conversation_view(
    *,
    state: StateDirectory,
    status: IssueConversationStatus,
    zone: tzinfo | None,
) -> WebConversationView:
    """Return the values shown on one issue-conversation page."""
    conversation = status.conversation
    repository = read_repository(state=state)
    daemon = read_dreamcatcher_daemon_status(state=state)
    rounds = _compose_agent_rounds(round_statuses=status.round_statuses, zone=zone)
    feed = _read_agent_feed(owner=conversation, zone=zone, rounds=rounds)
    return WebConversationView(
        repository=repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(repository=repository),
        daemon_state="stopped" if daemon.pid is None else "running",
        daemon_summary=_describe_daemon(
            daemon_pid=daemon.pid,
            dreamcatcher_version=daemon.dreamcatcher_version,
        ),
        issue=status.issue,
        title=status.title,
        status=str(status.value),
        detail=status.detail,
        facts=(
            ()
            if conversation is None
            else _compose_conversation_facts(conversation=conversation)
        ),
        rounds=rounds,
        feed_rounds=feed.rounds,
        feed_cursor=feed.cursor,
    )


def _compose_conversation_facts(
    *, conversation: IssueConversation
) -> tuple[WebFact, ...]:
    """Return the settings that a conversation settled at its first round."""
    record = conversation.record
    return (
        WebFact(label="label", value=record.label),
        WebFact(label="harness", value=str(record.harness)),
        WebFact(label="model", value=f"{record.model} · {record.effort}"),
    )


def _compose_assignment_status_label(*, status: AgentAssignmentStatus) -> str:
    return (
        "needs feedback"
        if status.value is AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK
        else str(status.value)
    )


def _compose_agent_rounds(
    *, round_statuses: list[AgentRoundStatus], zone: tzinfo | None
) -> tuple[WebAgentRound, ...]:
    return tuple(
        WebAgentRound(
            number=round_status.record.number,
            purpose=str(round_status.record.purpose),
            is_recovery=round_status.record.is_recovery,
            started=describe_time(at=round_status.record.started, zone=zone),
            duration=round_status.duration_description,
            outcome=round_status.outcome_description,
            revision=_shorten_git_revisions(text=round_status.revision),
            revision_description=_shorten_git_revisions(
                text=round_status.revision_description
            ),
        )
        for round_status in round_statuses
    )


def _shorten_git_revisions(*, text: str | None) -> str | None:
    if text is None:
        return None
    return _GIT_REVISION_PATTERN.sub(lambda match: match.group()[:7], text)


def _encode_feed_cursor(*, cursor: WebFeedCursor) -> str:
    return f"{cursor.round_number}:{cursor.position}"


def _decode_feed_cursor(*, value: str) -> WebFeedCursor:
    match = _FEED_CURSOR_PATTERN.fullmatch(value)
    if match is None:
        raise _InvalidFeedCursorError
    try:
        cursor = WebFeedCursor(
            round_number=int(match["round"]),
            position=int(match["position"]),
        )
    except ValueError:
        raise _InvalidFeedCursorError from None
    if cursor.round_number == 0 and cursor.position != 0:
        raise _InvalidFeedCursorError
    return cursor


def _read_agent_tail(
    *,
    owner: _WebFeedOwner | None,
    context: WebAgentTailContext,
    cursor: WebFeedCursor,
    zone: tzinfo | None,
) -> WebAgentTail:
    """Read feed output written after one cursor for any agent work."""
    round_feeds = _list_round_feeds(owner=owner)
    number, position, is_opening_round = _resolve_feed_cursor(
        cursor=cursor,
        round_feeds=round_feeds,
    )
    feed_rounds = []
    next_cursor = cursor
    while (round_feed := round_feeds.get(number)) is not None:
        record = round_feed.record
        feed_path = round_feed.feed
        if not is_complete_line_position(path=feed_path, position=position):
            raise _InvalidFeedCursorError
        written_lines, position = read_lines_from(
            path=feed_path,
            position=position,
        )
        lines = tuple(
            _compose_web_feed_line(written_line=written_line, zone=zone)
            for written_line in written_lines
        )
        if is_opening_round:
            lines = (
                _compose_web_round_boundary(
                    record=record,
                    zone=zone,
                    detail=_find_round_revision_description(
                        rounds=context.rounds, number=record.number
                    ),
                ),
                *lines,
            )
        if lines:
            feed_rounds.append(WebFeedRound(number=number, lines=lines))
        next_cursor = WebFeedCursor(round_number=number, position=position)
        if written_lines or record.ending is None:
            break
        number += 1
        position = 0
        is_opening_round = True
    return WebAgentTail(
        cursor=_encode_feed_cursor(cursor=next_cursor),
        feed_rounds=tuple(feed_rounds),
        status=context.status,
        status_label=context.status_label,
        detail=context.detail,
        rounds=context.rounds,
        has_empty_feed_placeholder=cursor.round_number == 0,
    )


def _resolve_feed_cursor(
    *,
    cursor: WebFeedCursor,
    round_feeds: dict[int, _WebRoundFeed],
) -> tuple[int, int, bool]:
    if cursor.round_number == 0:
        return 1, 0, True
    if cursor.round_number not in round_feeds:
        raise _InvalidFeedCursorError
    return cursor.round_number, cursor.position, False


def _compose_web_round_boundary(
    *, record: AgentRoundRecord, zone: tzinfo | None, detail: str | None = None
) -> WebFeedLine:
    boundary = compose_agent_round_boundary(
        number=record.number,
        purpose=record.purpose,
        is_recovery=record.is_recovery,
        at=record.started,
        detail=detail,
    )
    return WebFeedLine(
        timestamp=describe_time(at=boundary.at, zone=zone),
        label=None,
        detail=boundary.text,
        is_boundary=True,
    )


def _list_round_feeds(*, owner: _WebFeedOwner | None) -> dict[int, _WebRoundFeed]:
    """Return every saved round of the agent work with its feed, by number.

    Agent work with no saved record yet has run no round.
    """
    if owner is None:
        return {}
    return {
        record.number: _WebRoundFeed(
            record=record, feed=owner.compose_round_paths(number=record.number).feed
        )
        for record in owner.rounds
    }


def _read_agent_feed(
    *,
    owner: _WebFeedOwner | None,
    zone: tzinfo | None,
    rounds: tuple[WebAgentRound, ...] = (),
) -> WebAgentFeed:
    """Read the complete saved feed for any agent work."""
    feed_rounds = []
    cursor = WebFeedCursor(round_number=0, position=0)
    for round_feed in _list_round_feeds(owner=owner).values():
        record = round_feed.record
        written_lines, position = read_lines_from(path=round_feed.feed, position=0)
        cursor = WebFeedCursor(round_number=record.number, position=position)
        feed_rounds.append(
            WebFeedRound(
                number=record.number,
                lines=(
                    _compose_web_round_boundary(
                        record=record,
                        zone=zone,
                        detail=_find_round_revision_description(
                            rounds=rounds, number=record.number
                        ),
                    ),
                    *(
                        _compose_web_feed_line(written_line=written_line, zone=zone)
                        for written_line in written_lines
                    ),
                ),
            )
        )
    return WebAgentFeed(
        rounds=tuple(feed_rounds),
        cursor=_encode_feed_cursor(cursor=cursor),
    )


def _find_round_revision_description(
    *, rounds: tuple[WebAgentRound, ...], number: int
) -> str | None:
    """Return one web round's revision description when it has one."""
    return next(
        (round_.revision_description for round_ in rounds if round_.number == number),
        None,
    )


def _compose_web_feed_line(*, written_line: str, zone: tzinfo | None) -> WebFeedLine:
    line = read_feed_line(written_line=written_line)
    if line is None:
        return WebFeedLine(timestamp=None, label=None, detail=written_line)
    return WebFeedLine(
        timestamp=describe_time(at=line.at, zone=zone),
        label=line.label,
        detail=line.detail,
        is_subagent=line.is_subagent,
    )


def _compose_issue_row(*, observation: IssueObservation) -> WebIssueRow:
    is_blocked = observation.blocked.value is IssueFactValue.TRUE
    status = "blocked" if is_blocked else "available"
    return WebIssueRow(
        issue=observation.issue,
        title=observation.title,
        labels=", ".join(observation.dispatch_labels or []),
        status=status,
        evidence=_compose_issue_evidence(
            evidence=observation.blocked.evidence if is_blocked else None
        ),
    )


def _compose_issue_evidence(*, evidence: str | None) -> tuple[str | int, ...]:
    if evidence is None:
        return ()
    return tuple(
        int(part) if index % 2 else part
        for index, part in enumerate(_ISSUE_REFERENCE_PATTERN.split(evidence))
        if part
    )


def _describe_daemon(
    *, daemon_pid: int | None, dreamcatcher_version: str | None
) -> str:
    if daemon_pid is None:
        return "daemon stopped"
    version = (
        ""
        if dreamcatcher_version is None
        else f"dreamcatcher v{dreamcatcher_version} · "
    )
    return f"daemon running · {version}pid {daemon_pid}"


def _compose_instance_facts(*, report: DreamcatcherStatusReport) -> tuple[WebFact, ...]:
    scheduler_hold = report.scheduler_hold
    if scheduler_hold is not None and scheduler_hold.startswith("at cap:"):
        scheduler_hold = None
    values: tuple[tuple[str, str | None, bool], ...] = (
        (
            "harness",
            None if report.agent_harness is None else str(report.agent_harness),
            False,
        ),
        (
            "next update in",
            (
                None
                if report.daemon_pid is None
                else describe_countdown(
                    at=report.at,
                    since=report.latest_scheduler_tick,
                    span_seconds=report.scheduler_interval_seconds,
                )
            ),
            False,
        ),
        (
            "agent capacity",
            (
                None
                if report.max_agents is None
                else f"{report.running_agents} of {report.max_agents} working"
            ),
            False,
        ),
        ("scheduler hold", scheduler_hold, scheduler_hold is not None),
    )
    return tuple(
        WebFact(label=label, value=value, is_warning=is_warning)
        for label, value, is_warning in values
        if value is not None
    )
