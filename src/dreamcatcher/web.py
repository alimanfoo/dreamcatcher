"""Render Dreamcatcher status reports as local web pages."""

import errno
import logging
import zlib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from webbrowser import open as open_browser

from flask import Flask, render_template
from werkzeug.serving import BaseWSGIServer

from dreamcatcher.clock import read_current_time
from dreamcatcher.documents import read_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
    AgentAssignmentStatus,
    AgentAssignmentStatusValue,
    DreamcatcherStatusReport,
    FailedAssignmentSetupStatus,
    IssueFactValue,
    IssueObservation,
    read_status_report,
)
from dreamcatcher.words import describe_span, describe_time

WEB_HOST = "127.0.0.1"
WEB_BASE_PORT = 8100
WEB_PORT_RANGE = 400
WEB_MAX_PORT = 65535


class _WebServerBindError(Exception):
    def __init__(self, *, error: OSError) -> None:
        super().__init__(str(error))
        self.error = error


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
    """Represent one assignment card without presentation decisions."""

    identifier: str
    issue: int
    status: str
    detail: str
    harness: str
    model: str
    effort: str
    pull_request: int
    latest_output: str | None


@dataclass(frozen=True, kw_only=True)
class WebIssueRow:
    """Represent one available or blocked issue row."""

    issue: int
    labels: str
    status: str
    evidence: str | None


@dataclass(frozen=True, kw_only=True)
class WebHomeView:
    """Represent every value that the home template lays out."""

    repository: str
    daemon_state: str
    daemon_summary: str
    instance_facts: tuple[WebFact, ...]
    cooldown_message: str | None
    active_assignments: tuple[WebAssignmentCard, ...]
    complete_assignments: tuple[WebAssignmentCard, ...]
    failed_setups: tuple[FailedAssignmentSetupStatus, ...]
    available_issues: tuple[WebIssueRow, ...]
    blocked_issues: tuple[WebIssueRow, ...]


def create_app(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime] = read_current_time,
) -> Flask:
    """Create the read-only web application for one local state directory."""
    app = Flask(__name__)
    app.config["TRUSTED_HOSTS"] = [WEB_HOST, "localhost"]

    @app.get("/")
    def show_home() -> str:
        report = read_status_report(state=state, clock=clock)
        return render_template("home.html", view=_compose_home_view(report=report))

    @app.errorhandler(ReportableError)
    def show_reportable_error(error: ReportableError, /) -> tuple[str, int]:
        """Render a named read failure for Flask, which passes the error by position."""
        return render_template("error.html", message=str(error)), 500

    return app


def _run_server(*, server: BaseWSGIServer) -> None:
    server.serve_forever()


def serve_web(
    *,
    state: StateDirectory,
    port: int | None = None,
    browser_opener: Callable[[str], object] = open_browser,
    server_runner: WebServerRunner = _run_server,
) -> None:
    """Serve one local status page, open it, and run until interrupted."""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    application = create_app(state=state)
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
    if not state.repository.is_file():
        return WEB_BASE_PORT
    repository = read_text(path=state.repository).strip()
    repository_digest = zlib.crc32(repository.encode("utf-8"))
    return WEB_BASE_PORT + repository_digest % WEB_PORT_RANGE


def _compose_home_view(*, report: DreamcatcherStatusReport) -> WebHomeView:
    ordered_statuses = sorted(
        report.assignment_statuses,
        key=lambda status: ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER.index(
            status.value
        ),
    )
    assignments = tuple(
        _compose_assignment_card(status=status) for status in ordered_statuses
    )
    complete_assignments = tuple(
        assignment
        for assignment, status in zip(assignments, ordered_statuses, strict=True)
        if status.value is AgentAssignmentStatusValue.COMPLETE
    )
    active_assignments = tuple(
        assignment
        for assignment in assignments
        if assignment not in complete_assignments
    )
    return WebHomeView(
        repository=report.repository or "repository unknown",
        daemon_state="stopped" if report.daemon_pid is None else "running",
        daemon_summary=_describe_daemon(report=report),
        instance_facts=_compose_instance_facts(report=report),
        cooldown_message=(
            None
            if report.active_global_cooldown is None
            else (
                "Global cooldown ends "
                f"{describe_time(at=report.active_global_cooldown.ends)}"
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


def _compose_assignment_card(*, status: AgentAssignmentStatus) -> WebAssignmentCard:
    assignment = status.assignment
    round_prefix = (
        f"round {len(assignment.rounds)}, "
        if status.value is AgentAssignmentStatusValue.WORKING
        else ""
    )
    return WebAssignmentCard(
        identifier=assignment.identifier,
        issue=assignment.record.issue,
        status=str(status.value),
        detail=f"{round_prefix}{status.detail}",
        harness=str(assignment.record.harness),
        model=assignment.record.model,
        effort=assignment.record.effort,
        pull_request=assignment.record.pull_request,
        latest_output=status.latest_output,
    )


def _compose_issue_row(*, observation: IssueObservation) -> WebIssueRow:
    is_blocked = observation.blocked.value is IssueFactValue.TRUE
    status = "blocked" if is_blocked else "available"
    return WebIssueRow(
        issue=observation.issue,
        labels=", ".join(observation.dispatch_labels or []),
        status=status,
        evidence=observation.blocked.evidence if is_blocked else None,
    )


def _describe_daemon(*, report: DreamcatcherStatusReport) -> str:
    if report.daemon_pid is None:
        return "daemon STOPPED"
    version = (
        ""
        if report.dreamcatcher_version is None
        else f"dreamcatcher v{report.dreamcatcher_version} · "
    )
    return f"daemon RUNNING · {version}pid {report.daemon_pid}"


def _compose_instance_facts(*, report: DreamcatcherStatusReport) -> tuple[WebFact, ...]:
    tick = (
        "none recorded"
        if report.latest_scheduler_tick is None
        else f"{describe_span(span=report.at - report.latest_scheduler_tick)} ago"
    )
    cooldown = (
        "none"
        if report.active_global_cooldown is None
        else f"ends {describe_time(at=report.active_global_cooldown.ends)}"
    )
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
        ("scheduler hold", report.scheduler_hold, report.scheduler_hold is not None),
    )
    return tuple(
        WebFact(label=label, value=value, is_warning=is_warning)
        for label, value, is_warning in values
        if value is not None
    )
