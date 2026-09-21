"""Render Dreamcatcher status reports as local web pages."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from flask import Flask, render_template

from dreamcatcher.clock import read_current_time
from dreamcatcher.errors import ReportableError
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
    AgentAssignmentStatus,
    AgentAssignmentStatusValue,
    DreamcatcherStatusReport,
    FailedAssignmentSetupStatus,
    IssueObservation,
    read_status_report,
)
from dreamcatcher.words import describe_span, describe_time


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
    status_class: str
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
    status_class: str
    evidence: str | None


@dataclass(frozen=True, kw_only=True)
class WebFailedSetupRow:
    """Represent one failed assignment setup row."""

    issue: int
    failure: str


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
    assignment_count: str
    failed_setups: tuple[WebFailedSetupRow, ...]
    available_issues: tuple[WebIssueRow, ...]
    blocked_issues: tuple[WebIssueRow, ...]
    issue_count: str


def create_app(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime] = read_current_time,
) -> Flask:
    """Create the read-only web application for one local state directory."""
    app = Flask(__name__)

    @app.get("/")
    def show_home() -> str:
        report = read_status_report(state=state, clock=clock)
        return render_template("home.html", view=_compose_home_view(report=report))

    @app.errorhandler(ReportableError)
    def show_reportable_error(error: ReportableError, /) -> tuple[str, int]:
        """Render a named read failure for Flask, which passes the error by position."""
        return render_template("error.html", message=str(error)), 500

    return app


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
    issue_count = len(report.available_issues) + len(report.blocked_issues)
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
        assignment_count=f"{len(assignments):02d}",
        failed_setups=tuple(
            _compose_failed_setup_row(setup=setup)
            for setup in report.failed_assignment_setups
        ),
        available_issues=tuple(
            _compose_issue_row(observation=issue, status="available")
            for issue in report.available_issues
        ),
        blocked_issues=tuple(
            _compose_issue_row(observation=issue, status="blocked")
            for issue in report.blocked_issues
        ),
        issue_count=f"{issue_count:02d}",
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
        status=str(status.value).upper(),
        status_class=str(status.value).replace(" ", "-"),
        detail=f"{round_prefix}{status.detail}",
        harness=str(assignment.record.harness),
        model=assignment.record.model,
        effort=assignment.record.effort,
        pull_request=assignment.record.pull_request,
        latest_output=status.latest_output,
    )


def _compose_issue_row(*, observation: IssueObservation, status: str) -> WebIssueRow:
    evidence = observation.blocked.evidence if status == "blocked" else None
    return WebIssueRow(
        issue=observation.issue,
        labels=", ".join(observation.dispatch_labels or []),
        status=status.upper(),
        status_class=status,
        evidence=evidence,
    )


def _compose_failed_setup_row(
    *, setup: FailedAssignmentSetupStatus
) -> WebFailedSetupRow:
    return WebFailedSetupRow(issue=setup.issue, failure=setup.failure)


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
