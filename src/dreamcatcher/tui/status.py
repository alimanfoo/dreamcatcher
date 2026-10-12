"""Render the dreamcatcher instance status view in a terminal."""

from collections.abc import Callable, Sequence
from datetime import datetime, tzinfo
from time import sleep
from typing import cast

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.text import Text

from dreamcatcher.clock import WaitForSeconds, read_current_time
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentWorkStatusSection,
    AssignmentStatus,
    ConversationStatus,
    DreamcatcherStatusReport,
    IssueObservation,
    Truth,
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

_ISSUE_REFERENCE_WIDTH = len("GH99999")
_ISSUE_CONTENT_INDENT = _ISSUE_REFERENCE_WIDTH + 2


def show_status_view(
    *,
    state: StateDirectory,
    console: Console,
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
    zone: tzinfo | None = None,
) -> None:
    """Show instance, assignment, issue and conversation status until interrupted.

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
            _render_conversations(
                conversations=report.conversation_statuses,
                section=report.conversation_section,
            ),
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
    """Render assignment work as one section."""
    if section is None:
        return None
    rows = _render_assignment_rows(assignments=report.active_assignment_statuses)
    rows += _render_failed_setups(failed_setups=report.failed_assignment_setups)
    rows += _render_issue_observations(issues=report.issue_observations)
    if section.empty_message is not None:
        rows.append(Text(section.empty_message))
    ended = report.ended_assignment_statuses
    if ended:
        rows.append(Text(describe_count(number=len(ended), noun="ended assignment")))
    return render_section(heading=section.heading, body=Group(*rows))


def _render_failed_setups(
    *, failed_setups: Sequence[IssueObservation]
) -> list[RenderableType]:
    """Render incomplete assignment setups with recorded failures."""
    return [
        _render_issue_row(
            observation=setup,
            status=cast("str", setup.setup_failure),
            evidence=_describe_issue_evidence(observation=setup),
        )
        for setup in failed_setups
    ]


def _render_issue_observations(
    *, issues: Sequence[IssueObservation]
) -> list[RenderableType]:
    """Render issue observations as titled rows."""
    return [
        _render_issue_row(
            observation=issue,
            status=_describe_issue_observation(observation=issue),
            evidence=(),
        )
        for issue in issues
    ]


def _render_issue_row(
    *, observation: IssueObservation, status: str, evidence: Sequence[str]
) -> RenderableType:
    details = observation.details
    row_details = []
    if details is not None and details.assignment_labels:
        row_details.append(Text(", ".join(details.assignment_labels), style="dim"))
    row_details.extend(Text(item) for item in evidence)
    return _render_titled_row(
        issue=observation.issue,
        title="" if details is None else details.title,
        status=Text(status),
        details=row_details,
    )


def _describe_issue_observation(*, observation: IssueObservation) -> str:
    evidence = _describe_issue_evidence(observation=observation)
    return "; ".join(evidence) if evidence else "available"


def _describe_issue_evidence(*, observation: IssueObservation) -> list[str]:
    return [
        fact.evidence
        for fact in (observation.routing_conflict, observation.blocked)
        if fact.value is Truth.TRUE
    ]


def _render_assignment_rows(
    *, assignments: Sequence[AssignmentStatus]
) -> list[RenderableType]:
    """Render the detailed rows for assignments that have not ended."""
    rows: list[RenderableType] = []
    for status in assignments:
        assignment = status.assignment
        record = assignment.record
        metadata = [
            record.dispatch_label,
            str(record.harness),
            record.model,
            record.effort,
        ]
        if status.pull_request_state is not None:
            metadata.append(f"PR #{record.pull_request} {status.pull_request_state}")
        details = [
            Text(status.detail),
            Text(
                " · ".join(metadata),
                style="dim",
            ),
        ]
        latest_output = render_latest_output(latest_output=status.latest_output)
        if latest_output is not None:
            details.append(latest_output)
        rows.append(
            _render_titled_row(
                issue=record.issue,
                title=record.title,
                status=Text(
                    str(status.value), style=ASSIGNMENT_STATUS_STYLES[status.value]
                ),
                details=details,
            )
        )
    return rows


def _render_conversations(
    *,
    conversations: Sequence[ConversationStatus],
    section: AgentWorkStatusSection | None,
) -> RenderableType | None:
    if section is None:
        return None
    if section.empty_message is not None:
        return render_section(heading=section.heading, body=Text(section.empty_message))
    rows: list[RenderableType] = []
    for status in conversations:
        details = [Text(status.detail)]
        conversation = status.conversation
        if conversation is not None:
            record = conversation.record
            details.append(
                Text(
                    " · ".join(
                        [
                            record.dispatch_label,
                            str(record.harness),
                            record.model,
                            record.effort,
                        ]
                    ),
                    style="dim",
                )
            )
        latest_output = render_latest_output(latest_output=status.latest_output)
        if latest_output is not None:
            details.append(latest_output)
        rows.append(
            _render_titled_row(
                issue=status.issue,
                title=status.title,
                status=Text(
                    str(status.value), style=CONVERSATION_STATUS_STYLES[status.value]
                ),
                details=details,
            )
        )
    return render_section(heading=section.heading, body=Group(*rows))


def _render_titled_row(
    *, issue: int, title: str, status: Text, details: Sequence[Text]
) -> RenderableType:
    issue_reference = f"GH{issue}"
    table = create_table(columns=3)
    table.columns[0].width = _ISSUE_REFERENCE_WIDTH
    table.add_row(Text(issue_reference), Text(title), status)
    return Group(
        table,
        *(
            Padding(
                detail,
                (0, 0, 0, _ISSUE_CONTENT_INDENT),
                expand=False,
            )
            for detail in details
        ),
    )
