"""Render the dreamcatcher instance status view in a terminal."""

from collections.abc import Callable, Sequence
from datetime import datetime, tzinfo
from time import sleep
from typing import cast

from rich.console import Console, Group, RenderableType
from rich.text import Text

from dreamcatcher.clock import WaitForSeconds, read_current_time
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AssignmentStatus,
    ConversationStatus,
    DreamcatcherStatusReport,
    IssueStatus,
    read_status_report,
)
from dreamcatcher.tui.shared import (
    ASSIGNMENT_STATUS_STYLES,
    CONVERSATION_STATUS_STYLES,
    ViewSnapshot,
    combine_renderable_parts,
    create_table,
    refresh_live_view,
    render_latest_output,
    render_section,
)
from dreamcatcher.words import describe_count, describe_countdown, describe_time


def show_status_view(
    *,
    state: StateDirectory,
    console: Console,
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
    zone: tzinfo | None = None,
) -> None:
    """Show instance, issue, and assignment status until interrupted.

    A non-terminal or dumb terminal renders one report and returns.
    Times use the given zone, or the machine's local zone when it is None.
    """
    refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_status_snapshot(
            state=state, clock=clock, zone=zone
        ),
        wait=wait,
    )


def _read_status_snapshot(
    *, state: StateDirectory, clock: Callable[[], datetime], zone: tzinfo | None
) -> ViewSnapshot:
    """Return the current status report as a view that never ends itself.

    A daemon can start, a tick can run, or a round can begin after any refresh.
    """
    return ViewSnapshot(
        renderable=_render_status(
            report=read_status_report(state=state, clock=clock), zone=zone
        ),
        should_stop_refreshing=False,
    )


def _render_status(
    *, report: DreamcatcherStatusReport, zone: tzinfo | None
) -> RenderableType:
    return combine_renderable_parts(
        parts=[
            Text(report.repository or "repository unknown", style="bold"),
            _render_instance_status(report=report, zone=zone),
            _render_assignments(report=report),
            _render_conversations(conversations=report.conversation_statuses),
            _describe_empty_status_report(report=report),
        ]
    )


def _render_instance_status(
    *, report: DreamcatcherStatusReport, zone: tzinfo | None
) -> RenderableType:
    """Render the daemon, scheduler, capacity, and cooldown facts."""
    table = create_table(columns=2)
    for name, value in _compose_instance_rows(report=report, zone=zone):
        if value is not None:
            table.add_row(Text(name), Text(cast("str", value)))
    return render_section(heading="instance", body=table)


def _compose_instance_rows(
    *, report: DreamcatcherStatusReport, zone: tzinfo | None
) -> tuple[tuple[str, object | None], ...]:
    daemon_status = report.daemon
    tick = (
        None
        if not daemon_status.is_running
        else describe_countdown(
            at=report.at,
            since=report.latest_scheduler_tick,
            span_seconds=daemon_status.interval_seconds,
        )
    )
    cooldown = (
        "none"
        if report.active_global_cooldown is None
        else f"ends {describe_time(at=report.active_global_cooldown.ends, zone=zone)}"
    )
    return (
        ("daemon", daemon_status.summary),
        ("preferred harness", daemon_status.agent_harness),
        ("next update in", tick),
        (
            "agent capacity",
            (
                None
                if daemon_status.max_agents is None
                else f"{report.running_agents} of {daemon_status.max_agents} working"
            ),
        ),
        ("global cooldown", cooldown),
        ("scheduler failures", report.scheduler_failure_summary),
    )


def _render_assignments(*, report: DreamcatcherStatusReport) -> RenderableType | None:
    """Render assignment work as one section, mirroring the web home view.

    Orders active assignments, failed assignment setups, issue observations,
    and the ended-assignment count in that sequence.
    """
    if not (
        report.assignment_statuses
        or report.failed_assignment_setups
        or report.issue_statuses
    ):
        return None
    rows = _render_assignment_rows(assignments=report.active_assignment_statuses)
    rows += _render_failed_setups(failed_setups=report.failed_assignment_setups)
    rows += _render_issue_statuses(issues=report.issue_statuses)
    ended = report.ended_assignment_statuses
    if ended:
        rows.append(Text(describe_count(number=len(ended), noun="ended assignment")))
    return render_section(heading="assignments", body=Group(*rows))


def _render_failed_setups(
    *, failed_setups: Sequence[IssueStatus]
) -> list[RenderableType]:
    """Render incomplete assignment setups with recorded failures."""
    if not failed_setups:
        return []
    table = create_table(columns=2)
    for setup in failed_setups:
        table.add_row(Text(f"GH{setup.observation.issue}"), Text(setup.detail))
    return [table]


def _render_issue_statuses(*, issues: Sequence[IssueStatus]) -> list[RenderableType]:
    """Render the observed issues as one table, status inline per row."""
    if not issues:
        return []
    table = create_table(columns=3)
    for issue in issues:
        details = issue.observation.details
        table.add_row(
            Text(f"GH{issue.observation.issue}"),
            Text(", ".join([] if details is None else details.assignment_labels)),
            Text(issue.detail),
        )
    return [table]


def _render_assignment_rows(
    *, assignments: Sequence[AssignmentStatus]
) -> list[RenderableType]:
    """Render the detailed rows for assignments that have not ended."""
    if not assignments:
        return []
    identifier_width = max(len(status.assignment.identifier) for status in assignments)
    status_width = max(len(status.value) for status in assignments)
    rows: list[RenderableType] = []
    for status in assignments:
        table = create_table(columns=3)
        table.columns[0].width = identifier_width
        table.columns[1].width = status_width
        table.add_row(
            Text(status.assignment.identifier),
            Text(str(status.value), style=ASSIGNMENT_STATUS_STYLES[status.value]),
            Text(status.detail),
        )
        rows.append(table)
        latest_output = render_latest_output(latest_output=status.latest_output)
        if latest_output is not None:
            rows.append(latest_output)
    return rows


def _render_conversations(
    *, conversations: Sequence[ConversationStatus]
) -> RenderableType | None:
    if not conversations:
        return None
    table = create_table(columns=3)
    for status in conversations:
        table.add_row(
            Text(f"GH{status.issue}"),
            Text(str(status.value), style=CONVERSATION_STATUS_STYLES[status.value]),
            Text(status.detail),
        )
    return render_section(heading="issue conversations", body=table)


def _describe_empty_status_report(
    *, report: DreamcatcherStatusReport
) -> RenderableType | None:
    """Describe an instance that has no issue or assignment status yet."""
    if (
        report.failed_assignment_setups
        or report.issue_statuses
        or report.assignment_statuses
        or report.conversation_statuses
    ):
        return None
    return Group(Text(), Text("no issues or agent assignments recorded yet"))
