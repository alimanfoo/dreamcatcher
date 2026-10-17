"""Render the dreamcatcher instance status view in a terminal."""

from collections.abc import Callable, Sequence
from datetime import datetime, tzinfo
from time import sleep

from rich.console import Console, Group, RenderableType
from rich.text import Text

from dreamcatcher.clock import WaitForSeconds, read_current_time
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentWorkStatusSection,
    AssignmentStatus,
    DreamcatcherStatusReport,
    RequestReason,
    RequestStatus,
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
from dreamcatcher.words import describe_count


def show_status_view(
    *,
    state: StateDirectory,
    console: Console,
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
    zone: tzinfo | None = None,
) -> None:
    """Show instance, assignment, request and conversation status until interrupted.

    A non-terminal or dumb terminal renders one report and returns.
    """
    refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_status_snapshot(state=state, clock=clock),
        wait=wait,
    )


def _read_status_snapshot(
    *, state: StateDirectory, clock: Callable[[], datetime]
) -> ViewSnapshot:
    """Return the current status report as a view that never ends itself.

    A daemon can start, a tick can run, or a round can begin after any refresh.
    """
    return ViewSnapshot(
        renderable=_render_status(report=read_status_report(state=state, clock=clock)),
        should_stop_refreshing=False,
    )


def _render_status(*, report: DreamcatcherStatusReport) -> RenderableType:
    return combine_renderable_parts(
        parts=[
            Text(report.repository or "repository unknown", style="bold"),
            _render_instance_status(report=report),
            _render_assignments(report=report, section=report.assignment_section),
            _render_conversations(report=report, section=report.conversation_section),
        ]
    )


def _render_instance_status(*, report: DreamcatcherStatusReport) -> RenderableType:
    """Render the daemon and the instance facts."""
    table = create_table(columns=2)
    for fact in (report.daemon.status_fact, *report.instance_facts):
        table.add_row(Text(fact.label), Text(fact.value))
    return render_section(heading="instance", body=table)


def _render_assignments(
    *, report: DreamcatcherStatusReport, section: AgentWorkStatusSection | None
) -> RenderableType | None:
    """Render assignment work as one section, mirroring the web home view.

    Orders active assignments, requests with no open assignment, and the
    ended-assignment count in that sequence.
    """
    if section is None:
        return None
    rows = _render_assignment_rows(assignments=report.active_assignment_statuses)
    rows += _render_request_rows(
        requests=report.list_request_statuses(kind=AgentWorkKind.ASSIGNMENT)
    )
    if section.empty_message is not None:
        rows.append(Text(section.empty_message))
    ended = report.ended_assignment_statuses
    if ended:
        rows.append(Text(describe_count(number=len(ended), noun="ended assignment")))
    return render_section(heading=section.heading, body=Group(*rows))


def _render_request_rows(*, requests: Sequence[RequestStatus]) -> list[RenderableType]:
    """Render the requests with no open work as one table, reasons inline per row."""
    if not requests:
        return []
    table = create_table(columns=3)
    for request in requests:
        table.add_row(
            Text(f"GH{request.issue}"),
            Text(request.dispatch_label),
            Text(
                "; ".join(
                    _render_request_reason(reason=reason) for reason in request.reasons
                )
                or str(request.value)
            ),
        )
    return [table]


def _render_request_reason(*, reason: RequestReason) -> str:
    """Return one reason's words followed by the issues and pull requests it names."""
    references = [
        *(f"GH{number}" for number in reason.issues),
        *(f"#{number}" for number in reason.pull_requests),
    ]
    if not references:
        return reason.words
    return f"{reason.words} {', '.join(references)}"


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
    *, report: DreamcatcherStatusReport, section: AgentWorkStatusSection | None
) -> RenderableType | None:
    """Render conversation work as one section, as the web home view does."""
    if section is None:
        return None
    rows: list[RenderableType] = []
    active = report.active_conversation_statuses
    if active:
        table = create_table(columns=3)
        for status in active:
            table.add_row(
                Text(f"GH{status.issue}"),
                Text(str(status.value), style=CONVERSATION_STATUS_STYLES[status.value]),
                Text(status.detail),
            )
        rows.append(table)
    rows += _render_request_rows(
        requests=report.list_request_statuses(kind=AgentWorkKind.CONVERSATION)
    )
    if section.empty_message is not None:
        rows.append(Text(section.empty_message))
    ended = report.ended_conversation_statuses
    if ended:
        rows.append(Text(describe_count(number=len(ended), noun="ended conversation")))
    return render_section(heading=section.heading, body=Group(*rows))
