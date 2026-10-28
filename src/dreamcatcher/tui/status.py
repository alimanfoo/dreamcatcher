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
    AgentWorkStatus,
    DreamcatcherStatusReport,
    IssueFact,
    RequestStatus,
    read_status_report,
)
from dreamcatcher.tui.shared import (
    AGENT_WORK_STATUS_STYLES,
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
    """Show the instance, its agent work and its requests until interrupted.

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
            *(_render_agent_work(report=report, kind=kind) for kind in AgentWorkKind),
        ]
    )


def _render_instance_status(*, report: DreamcatcherStatusReport) -> RenderableType:
    """Render the daemon, the instance facts and the scheduler failures.

    Each scheduler failure starts at a dash, and a failure that wraps hangs
    under its own text, so where one ends and the next begins stays clear.
    """
    table = create_table(columns=2)
    for fact in (report.daemon.status_fact, *report.instance_facts):
        table.add_row(Text(fact.label), Text(fact.value))
    if report.scheduler_failures:
        failures = create_table(columns=2)
        for failure in report.scheduler_failures:
            failures.add_row(Text("-"), Text(failure))
        table.add_row(Text("scheduler failures"), failures)
    return render_section(heading="instance", body=table)


def _render_agent_work(
    *, report: DreamcatcherStatusReport, kind: AgentWorkKind
) -> RenderableType:
    """Render one kind of agent work as one section, mirroring the web home view.

    Orders the active work, the requests with no open work, the guidance and
    the count of ended work in that sequence.
    """
    section = report.describe_section(kind=kind)
    rows = _render_work_rows(statuses=report.list_active_work_statuses(kind=kind))
    rows += _render_request_rows(requests=report.list_request_statuses(kind=kind))
    if section.guidance is not None:
        rows.append(Text(section.guidance.message))
        if section.guidance.documentation is not None:
            documentation = section.guidance.documentation
            rows.append(Text(f"{documentation.title}: {documentation.url}"))
    ended = report.list_ended_work_statuses(kind=kind)
    if ended:
        rows.append(Text(describe_count(number=len(ended), noun=f"ended {kind}")))
    return render_section(heading=section.heading, body=Group(*rows))


def _render_request_rows(*, requests: Sequence[RequestStatus]) -> list[RenderableType]:
    """Render the requests with no open work as one table.

    Each row gives its status, then where its issue stands on GitHub and any
    detail, as a piece of work's row gives its status and then its detail.
    """
    if not requests:
        return []
    table = create_table(columns=4)
    for request in requests:
        issue = ", ".join(
            [
                *([] if request.issue_state is None else [request.issue_state]),
                *(_render_issue_fact(fact=fact) for fact in request.issue_facts),
            ]
        )
        table.add_row(
            Text(f"GH{request.row.issue}"),
            Text(request.row.dispatch_label),
            Text(str(request.value)),
            Text(issue if request.detail is None else f"{issue}; {request.detail}"),
        )
    return [table]


def _render_issue_fact(*, fact: IssueFact) -> str:
    """Return one fact's words followed by the issues and pull requests it names."""
    references = [
        *(
            f"{issue.repository}#{issue.number}"
            if issue.repository
            else f"GH{issue.number}"
            for issue in fact.issues
        ),
        *(f"PR #{number}" for number in fact.pull_requests),
    ]
    if not references:
        return fact.words
    return f"{fact.words} {', '.join(references)}"


def _render_work_rows(*, statuses: Sequence[AgentWorkStatus]) -> list[RenderableType]:
    """Render the detailed rows for work that has not ended."""
    if not statuses:
        return []
    identifier_width = max(len(status.work.identifier) for status in statuses)
    status_width = max(len(status.words) for status in statuses)
    rows: list[RenderableType] = []
    for status in statuses:
        table = create_table(columns=3)
        table.columns[0].width = identifier_width
        table.columns[1].width = status_width
        table.add_row(
            Text(status.work.identifier),
            Text(status.words, style=AGENT_WORK_STATUS_STYLES[status.value]),
            Text(status.detail or ""),
        )
        rows.append(table)
        latest_output = render_latest_output(latest_output=status.latest_output)
        if latest_output is not None:
            rows.append(latest_output)
    return rows
