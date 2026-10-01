"""Render the Dreamcatcher instance status view in a terminal."""

from collections.abc import Callable, Sequence
from datetime import datetime, tzinfo
from time import sleep
from typing import cast

from rich.console import Console, Group, RenderableType
from rich.text import Text

from dreamcatcher.clock import WaitForSeconds, read_current_time
from dreamcatcher.scheduler import IssueFactValue, IssueObservation
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
    CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER,
    AgentAssignmentStatus,
    AgentAssignmentStatusValue,
    DreamcatcherStatusReport,
    IssueConversationStatus,
    read_status_report,
)
from dreamcatcher.tui_shared import (
    ASSIGNMENT_STATUS_STYLES,
    CONVERSATION_STATUS_STYLES,
    ViewSnapshot,
    combine_renderable_parts,
    create_table,
    refresh_live_view,
    render_assignment_latest_output,
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
        is_over=False,
    )


def _render_status(
    *, report: DreamcatcherStatusReport, zone: tzinfo | None
) -> RenderableType:
    return combine_renderable_parts(
        parts=[
            Text(report.repository or "repository unknown", style="bold"),
            _render_instance_status(report=report, zone=zone),
            _render_assignments(
                assignments=report.assignment_statuses,
                failed_setups=report.failed_assignment_setups,
                available_issues=report.available_issues,
                blocked_issues=report.blocked_issues,
            ),
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
    daemon = (
        "not running"
        if report.daemon_pid is None
        else " ".join(
            filter(
                None,
                (
                    "running",
                    (
                        None
                        if report.dreamcatcher_version is None
                        else f"dreamcatcher v{report.dreamcatcher_version}"
                    ),
                    f"as pid {report.daemon_pid}",
                ),
            )
        )
    )
    tick = (
        None
        if report.daemon_pid is None
        else describe_countdown(
            at=report.at,
            since=report.latest_scheduler_tick,
            span_seconds=report.scheduler_interval_seconds,
        )
    )
    cooldown = (
        "none"
        if report.active_global_cooldown is None
        else f"ends {describe_time(at=report.active_global_cooldown.ends, zone=zone)}"
    )
    return (
        ("daemon", daemon),
        ("harness", report.agent_harness),
        ("next update in", tick),
        (
            "agent capacity",
            (
                None
                if report.max_agents is None
                else f"{report.running_agents} of {report.max_agents} working"
            ),
        ),
        ("global cooldown", cooldown),
        ("scheduler hold", report.scheduler_hold),
    )


def _render_assignments(
    *,
    assignments: Sequence[AgentAssignmentStatus],
    failed_setups: Sequence[IssueObservation],
    available_issues: Sequence[IssueObservation],
    blocked_issues: Sequence[IssueObservation],
) -> RenderableType | None:
    """Render assignment work as one section, mirroring the web home view.

    Orders active assignments, failed assignment setups, available issues, and
    blocked issues in that sequence, with a completed-assignment count last.
    """
    if not (assignments or failed_setups or available_issues or blocked_issues):
        return None
    completed = list(
        filter(
            lambda status: status.value is AgentAssignmentStatusValue.COMPLETE,
            assignments,
        )
    )
    ordered = sorted(
        filter(
            lambda status: status.value is not AgentAssignmentStatusValue.COMPLETE,
            assignments,
        ),
        key=lambda status: ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER.index(
            status.value
        ),
    )
    rows = _render_assignment_rows(assignments=ordered)
    rows += _render_failed_setups(failed_setups=failed_setups)
    rows += _render_open_issues(
        available_issues=available_issues, blocked_issues=blocked_issues
    )
    if completed:
        rows.append(
            Text(describe_count(number=len(completed), noun="completed assignment"))
        )
    return render_section(heading="assignments", body=Group(*rows))


def _render_failed_setups(
    *, failed_setups: Sequence[IssueObservation]
) -> list[RenderableType]:
    """Render incomplete assignment setups with recorded failures."""
    if not failed_setups:
        return []
    table = create_table(columns=2)
    for setup in failed_setups:
        table.add_row(Text(f"GH{setup.issue}"), Text(cast("str", setup.setup_failure)))
    return [table]


def _render_open_issues(
    *,
    available_issues: Sequence[IssueObservation],
    blocked_issues: Sequence[IssueObservation],
) -> list[RenderableType]:
    """Render available and blocked issues as one table, status inline per row."""
    rows = [
        (
            issue,
            ", ".join(issue.assignment_labels or []),
            (
                issue.blocked.evidence
                if issue.blocked.value is IssueFactValue.TRUE
                else "available"
            ),
        )
        for issue in (*available_issues, *blocked_issues)
    ]
    if not rows:
        return []
    table = create_table(columns=3)
    for issue, middle, status in rows:
        table.add_row(Text(f"GH{issue.issue}"), Text(middle), Text(status))
    return [table]


def _render_assignment_rows(
    *, assignments: Sequence[AgentAssignmentStatus]
) -> list[RenderableType]:
    """Render the detailed rows for non-complete assignments."""
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
        latest_output = render_assignment_latest_output(status=status)
        if latest_output is not None:
            rows.append(latest_output)
    return rows


def _render_conversations(
    *, conversations: Sequence[IssueConversationStatus]
) -> RenderableType | None:
    """Render conversations in attention order, preserving order within a status."""
    if not conversations:
        return None
    table = create_table(columns=3)
    for status in sorted(
        conversations,
        key=lambda status: CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER.index(
            status.value
        ),
    ):
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
        or report.available_issues
        or report.blocked_issues
        or report.assignment_statuses
        or report.conversation_statuses
    ):
        return None
    return Group(Text(), Text("no issues or agent assignments recorded yet"))
