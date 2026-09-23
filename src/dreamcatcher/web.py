"""Render Dreamcatcher status reports as local web pages."""

import errno
import logging
import re
import zlib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Protocol, cast
from webbrowser import open as open_browser

from flask import Flask, Response, render_template, request
from werkzeug.serving import BaseWSGIServer

from dreamcatcher.agent_rounds import AgentRoundRecord, SuccessfulAgentRoundEnding
from dreamcatcher.clock import read_current_time
from dreamcatcher.documents import is_complete_line_position, read_lines_from
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import (
    compose_agent_round_boundary,
    read_feed_line,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
    STATUSES_THAT_END_A_VIEW,
    AgentAssignmentStatus,
    AgentAssignmentStatusValue,
    DreamcatcherStatusReport,
    IssueFactValue,
    IssueObservation,
    read_agent_assignment_status,
    read_dreamcatcher_daemon_status,
    read_repository,
    read_status_report,
)
from dreamcatcher.words import describe_span, describe_time

WEB_HOST = "127.0.0.1"
WEB_BASE_PORT = 8100
WEB_PORT_RANGE = 400
WEB_MAX_PORT = 65535
_ISSUE_REFERENCE_PATTERN = re.compile(r"(?<!\w)(?:GH|#)(\d+)\b(?!-)")
_FEED_CURSOR_PATTERN = re.compile(r"(?P<round>0|[1-9]\d*):(?P<position>\d+)")
_HTMX_STOP_POLLING_STATUS = 286
_DEFAULT_WEB_THEME = "matrix"
_WEB_THEMES = frozenset({_DEFAULT_WEB_THEME, "nature"})


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
    harness: str
    model: str
    effort: str
    pull_request: int
    pull_request_state: str | None
    latest_output: str | None


@dataclass(frozen=True, kw_only=True)
class WebAssignmentRound:
    """Represent one round row on an assignment page."""

    number: int
    purpose: str
    is_recovery: bool
    started: str
    duration: str
    outcome: str


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
class WebAssignmentFeed:
    """Represent the complete feed and the cursor after its last line."""

    rounds: tuple[WebFeedRound, ...]
    cursor: str


@dataclass(frozen=True, kw_only=True)
class WebFeedCursor:
    """Identify the next feed byte to read within an assignment round."""

    round_number: int
    position: int


@dataclass(frozen=True, kw_only=True)
class WebAssignmentTail:
    """Represent one incremental assignment-feed response."""

    cursor: str
    feed_rounds: tuple[WebFeedRound, ...]
    status: str
    status_label: str
    rounds: tuple[WebAssignmentRound, ...]
    has_empty_feed_placeholder: bool


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
    branch: str
    harness: str
    harness_session_identifier: str
    model: str
    effort: str
    rounds: tuple[WebAssignmentRound, ...]
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
class WebHomeView:
    """Represent every value that the home template lays out."""

    repository: str
    github_repository_url: str | None
    daemon_state: str
    daemon_summary: str
    instance_facts: tuple[WebFact, ...]
    cooldown_message: str | None
    active_assignments: tuple[WebAssignmentCard, ...]
    complete_assignments: tuple[WebAssignmentCard, ...]
    failed_setups: tuple[IssueObservation, ...]
    available_issues: tuple[WebIssueRow, ...]
    blocked_issues: tuple[WebIssueRow, ...]


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

    @app.get("/")
    def show_home() -> str:
        report = read_status_report(state=state, clock=clock)
        return render_template(
            "home.html", view=_compose_home_view(report=report, zone=zone)
        )

    @app.get("/assignments/<identifier>")
    def show_assignment(*, identifier: str) -> str | tuple[str, int]:
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

    @app.get("/assignments/<identifier>/tail")
    def show_assignment_tail(*, identifier: str) -> str | tuple[str, int]:
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
        try:
            cursor = _decode_feed_cursor(value=request.args.get("cursor", ""))
            tail = _read_assignment_tail(status=status, cursor=cursor, zone=zone)
        except _InvalidFeedCursorError:
            return (
                render_template("error.html", message="The feed cursor is invalid."),
                400,
            )
        response_status = (
            _HTMX_STOP_POLLING_STATUS
            if not tail.feed_rounds and status.value in STATUSES_THAT_END_A_VIEW
            else 200
        )
        return render_template("tail.html", tail=tail), response_status

    @app.errorhandler(ReportableError)
    def show_reportable_error(error: ReportableError, /) -> tuple[str, int]:
        """Render a named read failure for Flask, which passes the error by position."""
        return render_template("error.html", message=str(error)), 500

    return app


def _configure_web_theme(*, app: Flask) -> None:
    @app.context_processor
    def add_web_theme() -> dict[str, str]:
        return {"theme": _read_web_theme()}

    @app.after_request
    def remember_web_theme(response: Response, /) -> Response:
        """Remember a valid theme selected through a browser request."""
        requested_theme = request.args.get("theme")
        if requested_theme in _WEB_THEMES:
            response.set_cookie("theme", requested_theme, samesite="Lax")
        return response


def _read_web_theme() -> str:
    requested_theme = request.args.get("theme")
    if requested_theme in _WEB_THEMES:
        return requested_theme
    remembered_theme = request.cookies.get("theme")
    if remembered_theme in _WEB_THEMES:
        return remembered_theme
    return _DEFAULT_WEB_THEME


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
        instance_facts=_compose_instance_facts(
            report=report, cooldown_end=cooldown_end
        ),
        cooldown_message=(
            None if cooldown_end is None else f"Global cooldown ends {cooldown_end}"
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
        status_label=_compose_web_status_label(status=status),
        detail=status.detail,
        harness=str(assignment.record.harness),
        model=assignment.record.model,
        effort=assignment.record.effort,
        pull_request=assignment.record.pull_request,
        pull_request_state=_describe_pull_request_state(status=status),
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
    feed = _read_assignment_feed(status=status, zone=zone)
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
        status_label=_compose_web_status_label(status=status),
        detail=status.detail,
        pull_request=record.pull_request,
        pull_request_state=_describe_pull_request_state(status=status),
        branch=record.branch,
        harness=str(record.harness),
        harness_session_identifier=(
            "not recorded"
            if status.harness_session_identifier is None
            else status.harness_session_identifier
        ),
        model=record.model,
        effort=record.effort,
        rounds=_compose_assignment_rounds(status=status, zone=zone),
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


def _compose_web_status_label(*, status: AgentAssignmentStatus) -> str:
    return (
        "needs feedback"
        if status.value is AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK
        else str(status.value)
    )


def _compose_assignment_rounds(
    *, status: AgentAssignmentStatus, zone: tzinfo | None
) -> tuple[WebAssignmentRound, ...]:
    return tuple(
        WebAssignmentRound(
            number=round_status.record.number,
            purpose=str(round_status.record.purpose),
            is_recovery=round_status.record.is_recovery,
            started=describe_time(at=round_status.record.started, zone=zone),
            duration=round_status.duration_description,
            outcome=round_status.outcome_description,
        )
        for round_status in status.round_statuses
    )


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


def _read_assignment_tail(
    *,
    status: AgentAssignmentStatus,
    cursor: WebFeedCursor,
    zone: tzinfo | None,
) -> WebAssignmentTail:
    assignment = status.assignment
    records_by_number = {record.number: record for record in assignment.rounds}
    number, position, is_opening_round = _resolve_feed_cursor(
        cursor=cursor,
        records_by_number=records_by_number,
    )
    feed_rounds = []
    next_cursor = cursor
    while (record := records_by_number.get(number)) is not None:
        feed_path = assignment.compose_round_paths(number=number).feed
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
            lines = (_compose_web_round_boundary(record=record, zone=zone), *lines)
        if lines:
            feed_rounds.append(WebFeedRound(number=number, lines=lines))
        next_cursor = WebFeedCursor(round_number=number, position=position)
        if written_lines or record.ending is None:
            break
        number += 1
        position = 0
        is_opening_round = True
    return WebAssignmentTail(
        cursor=_encode_feed_cursor(cursor=next_cursor),
        feed_rounds=tuple(feed_rounds),
        status=str(status.value),
        status_label=_compose_web_status_label(status=status),
        rounds=_compose_assignment_rounds(status=status, zone=zone),
        has_empty_feed_placeholder=cursor.round_number == 0,
    )


def _resolve_feed_cursor(
    *,
    cursor: WebFeedCursor,
    records_by_number: dict[int, AgentRoundRecord],
) -> tuple[int, int, bool]:
    if cursor.round_number == 0:
        return 1, 0, True
    if cursor.round_number not in records_by_number:
        raise _InvalidFeedCursorError
    return cursor.round_number, cursor.position, False


def _compose_web_round_boundary(
    *, record: AgentRoundRecord, zone: tzinfo | None
) -> WebFeedLine:
    boundary = compose_agent_round_boundary(
        number=record.number,
        purpose=record.purpose,
        is_recovery=record.is_recovery,
        at=record.started,
    )
    return WebFeedLine(
        timestamp=describe_time(at=boundary.at, zone=zone),
        label=None,
        detail=boundary.text,
        is_boundary=True,
    )


def _read_assignment_feed(
    *, status: AgentAssignmentStatus, zone: tzinfo | None
) -> WebAssignmentFeed:
    assignment = status.assignment
    feed_rounds = []
    cursor = WebFeedCursor(round_number=0, position=0)
    for record in assignment.rounds:
        written_lines, position = read_lines_from(
            path=assignment.compose_round_paths(number=record.number).feed,
            position=0,
        )
        cursor = WebFeedCursor(round_number=record.number, position=position)
        feed_rounds.append(
            WebFeedRound(
                number=record.number,
                lines=(
                    _compose_web_round_boundary(record=record, zone=zone),
                    *(
                        _compose_web_feed_line(written_line=written_line, zone=zone)
                        for written_line in written_lines
                    ),
                ),
            )
        )
    return WebAssignmentFeed(
        rounds=tuple(feed_rounds),
        cursor=_encode_feed_cursor(cursor=cursor),
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
        return "daemon STOPPED"
    version = (
        ""
        if dreamcatcher_version is None
        else f"dreamcatcher v{dreamcatcher_version} · "
    )
    return f"daemon RUNNING · {version}pid {daemon_pid}"


def _compose_instance_facts(
    *, report: DreamcatcherStatusReport, cooldown_end: str | None
) -> tuple[WebFact, ...]:
    tick = (
        "none recorded"
        if report.latest_scheduler_tick is None
        else f"{describe_span(span=report.at - report.latest_scheduler_tick)} ago"
    )
    cooldown = "none" if cooldown_end is None else f"ends {cooldown_end}"
    scheduler_hold = report.scheduler_hold
    if scheduler_hold is not None and scheduler_hold.startswith("at cap:"):
        scheduler_hold = None
    values: tuple[tuple[str, str | None, bool], ...] = (
        (
            "harness",
            None if report.agent_harness is None else str(report.agent_harness),
            False,
        ),
        ("latest scheduler tick", tick, False),
        (
            "agent capacity",
            (
                None
                if report.max_agents is None
                else f"{report.running_agents} of {report.max_agents} in use"
            ),
            False,
        ),
        ("global cooldown", cooldown, report.active_global_cooldown is not None),
        ("scheduler hold", scheduler_hold, scheduler_hold is not None),
    )
    return tuple(
        WebFact(label=label, value=value, is_warning=is_warning)
        for label, value, is_warning in values
        if value is not None
    )
