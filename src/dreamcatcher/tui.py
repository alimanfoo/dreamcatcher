"""Render status, assignment, and feed views from local state.

The views read the state directory without contacting GitHub or the daemon.
Status and assignment views redraw the current state, while a feed appends new
lines and preserves terminal scrollback. Color is added only during rendering.

"""

from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from time import sleep
from typing import cast

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from dreamcatcher.agent_assignments import AgentAssignment
from dreamcatcher.agent_rounds import AgentRoundRecord
from dreamcatcher.clock import WaitForSeconds, read_current_time
from dreamcatcher.documents import read_lines_from
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import (
    FEED_TIMESTAMP_GAP,
    SUBAGENT_INDENT,
    FeedLine,
    compose_agent_round_boundary,
    describe_agent_round_start,
    read_feed_line,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import IssueConversation
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
    CONVERSATION_STATUSES_THAT_END_A_VIEW,
    STATUSES_THAT_END_A_VIEW,
    AgentAssignmentStatus,
    AgentAssignmentStatusValue,
    AgentRoundStatus,
    DreamcatcherStatusReport,
    IssueConversationStatus,
    IssueConversationStatusValue,
    IssueObservation,
    read_agent_assignment_statuses_for_issue,
    read_issue_conversation_status,
    read_status_report,
)
from dreamcatcher.words import describe_count, describe_span, describe_time

# What each assignment summary is set in, so a reader can scan the status table.
ASSIGNMENT_STATUS_STYLES = dict(
    zip(
        ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
        ("yellow", "red", "green", "cyan", "magenta", "dim"),
        strict=True,
    )
)

CONVERSATION_STATUS_STYLES = {
    IssueConversationStatusValue.NEEDS_ATTENTION: "red",
    IssueConversationStatusValue.RUNNING: "green",
    IssueConversationStatusValue.AWAITING_PUBLICATION: "yellow",
    IssueConversationStatusValue.WAITING: "cyan",
    IssueConversationStatusValue.INACTIVE: "dim",
}

# How long a following view waits between refreshes for new round output.
VIEW_REFRESH_INTERVAL = 1.0

# How far a section's rows are set in from its heading.
SECTION_PADDING = (0, 0, 0, 2)


@dataclass(frozen=True, kw_only=True)
class ViewTiming:
    """Provide the clock, waits, and display zone for one TUI view."""

    clock: Callable[[], datetime] = read_current_time
    wait: WaitForSeconds = sleep
    zone: tzinfo | None = None


DEFAULT_VIEW_TIMING = ViewTiming()


@dataclass(frozen=True, kw_only=True)
class FeedSelection:
    """Select the assignment or conversation feed at one issue."""

    issue: int
    owner_kind: AgentWorkKind


def open_tui_console() -> Console:
    """Return a console that follows the terminal's current dimensions.

    Tests may supply a console with fixed dimensions for stable output.
    """
    return Console()


@dataclass(frozen=True, kw_only=True)
class _ViewSnapshot:
    """Capture one rendered view and whether more output can reach it.

    A view is over when nothing more can reach it. That is not the same as the
    final snapshot, because an active view refreshes once more after first
    reporting that it is over.
    """

    renderable: RenderableType
    is_over: bool


def _refresh_live_view(
    *,
    console: Console,
    read_snapshot: Callable[[], _ViewSnapshot],
    wait: WaitForSeconds,
) -> None:
    """Redraw snapshots in a terminal until the view ends.

    A terminal uses its alternate screen and prints the final snapshot after a
    completed view ends. An interrupted active view leaves no final snapshot.

    A non-terminal or dumb terminal prints one snapshot and returns.
    """
    if not console.is_terminal or console.is_dumb_terminal:
        console.print(read_snapshot().renderable)
        return
    last_snapshot = _ViewSnapshot(renderable="", is_over=False)
    with Live(console=console, auto_refresh=False, screen=True) as live:

        def refresh_live_display() -> bool:
            """Draw the current snapshot and return whether the view is over."""
            nonlocal last_snapshot
            last_snapshot = read_snapshot()
            live.update(last_snapshot.renderable, refresh=True)
            return last_snapshot.is_over

        _refresh_until_view_ends(
            console=console, refresh_view=refresh_live_display, wait=wait
        )
    if last_snapshot.is_over:
        console.print(last_snapshot.renderable)


def _refresh_until_view_ends(
    *, console: Console, refresh_view: Callable[[], bool], wait: WaitForSeconds
) -> None:
    """Refresh until the view ends.

    The extra refresh lets output that follows a round's terminal record arrive.
    A view that is already over returns after its first refresh, and a
    non-terminal console always takes one refresh. KeyboardInterrupt ends an
    active view quietly.
    """
    was_over_on_previous_refresh = True
    with suppress(KeyboardInterrupt):
        while True:
            is_over = refresh_view()
            if (is_over and was_over_on_previous_refresh) or not console.is_terminal:
                return
            was_over_on_previous_refresh = is_over
            wait(VIEW_REFRESH_INTERVAL)


def show_status_view(
    *,
    state: StateDirectory,
    console: Console,
    timing: ViewTiming = DEFAULT_VIEW_TIMING,
) -> None:
    """Show instance, issue, and assignment status until interrupted.

    A non-terminal or dumb terminal renders one report and returns.
    Times use timing's zone, or the machine's local zone when it is None.
    """
    _refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_status_snapshot(
            state=state, clock=timing.clock, zone=timing.zone
        ),
        wait=timing.wait,
    )


def _read_status_snapshot(
    *, state: StateDirectory, clock: Callable[[], datetime], zone: tzinfo | None
) -> _ViewSnapshot:
    """Return the current status report as a view that never ends itself.

    A daemon can start, a tick can run, or a round can begin after any refresh.
    """
    return _ViewSnapshot(
        renderable=_render_status(
            report=read_status_report(state=state, clock=clock), zone=zone
        ),
        is_over=False,
    )


def _render_status(
    *, report: DreamcatcherStatusReport, zone: tzinfo | None
) -> RenderableType:
    return _combine_renderable_parts(
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


def _combine_renderable_parts(
    *, parts: Sequence[RenderableType | None]
) -> RenderableType:
    return Group(*(part for part in parts if part is not None))


def _render_instance_status(
    *, report: DreamcatcherStatusReport, zone: tzinfo | None
) -> RenderableType:
    """Render the daemon, scheduler, capacity, and cooldown facts."""
    table = _create_table(columns=2)
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
        "none recorded"
        if report.latest_scheduler_tick is None
        else f"{describe_span(span=report.at - report.latest_scheduler_tick)} ago"
    )
    cooldown = (
        "none"
        if report.active_global_cooldown is None
        else f"ends {describe_time(at=report.active_global_cooldown.ends, zone=zone)}"
    )
    for name, value in (
        ("daemon", daemon),
        ("harness", report.agent_harness),
        ("latest scheduler tick", tick),
        (
            "agent capacity",
            (
                None
                if report.max_agents is None
                else f"{report.running_agents} of {report.max_agents} in use"
            ),
        ),
        ("global cooldown", cooldown),
        ("scheduler hold", report.scheduler_hold),
    ):
        if value is not None:
            table.add_row(Text(name), Text(value))
    return _render_section(heading="instance", body=table)


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
    rows += _render_issue_group(
        heading="failed assignment setups",
        issues=failed_setups,
        columns=2,
        build_row=lambda setup: (
            Text(f"GH{setup.issue}"),
            Text(cast("str", setup.setup_failure)),
        ),
    )
    rows += _render_issue_group(
        heading="available issues",
        issues=available_issues,
        columns=2,
        build_row=lambda issue: (
            Text(f"GH{issue.issue}"),
            Text(", ".join(issue.dispatch_labels or [])),
        ),
    )
    rows += _render_issue_group(
        heading="blocked issues",
        issues=blocked_issues,
        columns=3,
        build_row=lambda issue: (
            Text(f"GH{issue.issue}"),
            Text(", ".join(issue.dispatch_labels or [])),
            Text(cast("str", issue.blocked.evidence)),
        ),
    )
    if completed:
        rows.append(
            Text(describe_count(number=len(completed), noun="completed assignment"))
        )
    return _render_section(heading="assignments", body=Group(*rows))


def _render_issue_group(
    *,
    heading: str,
    issues: Sequence[IssueObservation],
    columns: int,
    build_row: Callable[[IssueObservation], tuple[Text, ...]],
) -> list[RenderableType]:
    """Render one optional labelled table of issues, or nothing when empty."""
    if not issues:
        return []
    table = _create_table(columns=columns)
    for issue in issues:
        table.add_row(*build_row(issue))
    return [Text(heading, style="bold"), table]


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
        table = Table(box=None, show_header=False, pad_edge=False)
        table.add_column(style="bold", width=identifier_width)
        table.add_column(width=status_width)
        table.add_column(overflow="fold")
        table.add_row(
            Text(status.assignment.identifier),
            Text(
                str(status.value),
                style=ASSIGNMENT_STATUS_STYLES[status.value],
            ),
            Text(status.detail),
        )
        rows.append(table)
        latest_output = _render_assignment_latest_output(status=status)
        if latest_output is not None:
            rows.append(latest_output)
    return rows


def _render_conversations(
    *, conversations: Sequence[IssueConversationStatus]
) -> RenderableType | None:
    """Render issue conversations in issue order."""
    if not conversations:
        return None
    table = _create_table(columns=3)
    for status in conversations:
        table.add_row(
            Text(f"GH{status.conversation.record.issue}"),
            Text(
                str(status.value),
                style=CONVERSATION_STATUS_STYLES[status.value],
            ),
            Text(status.detail),
        )
    return _render_section(heading="issue conversations", body=table)


def _render_assignment_latest_output(*, status: AgentAssignmentStatus) -> Text | None:
    """Render an assignment's latest output as one dimmed line."""
    return _render_latest_output(latest_output=status.latest_output)


def _render_latest_output(*, latest_output: str | None) -> Text | None:
    """Render agent work's latest output as one dimmed line."""
    if latest_output is None:
        return None
    return Text(
        latest_output,
        style="dim",
        overflow="ellipsis",
        no_wrap=True,
    )


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


def _create_table(*, columns: int) -> Table:
    """Return a table whose cells fold instead of truncating.

    The first column names an assignment or an issue, which is what a reader picks
    a row out by, so it folds onto another line rather than being cut short.
    Two assignments at one issue differ only in the time in their identifiers,
    and a cut that reached that far would leave the rows reading the same.
    """
    table = Table(box=None, show_header=False, pad_edge=False)
    for number in range(columns):
        table.add_column(
            style="bold" if number == 0 else "",
            overflow="fold",
        )
    return table


def _render_section(*, heading: str, body: RenderableType) -> RenderableType:
    return Group(
        Text(),
        Text(heading, style="bold blue"),
        Padding(body, SECTION_PADDING, expand=False),
    )


def show_assignment_view(
    *,
    state: StateDirectory,
    issue: int,
    console: Console,
    timing: ViewTiming = DEFAULT_VIEW_TIMING,
) -> None:
    """Show the issue's newest assignment until it completes or enters fault.

    The view remains open between rounds. A non-terminal or dumb terminal
    renders one snapshot and returns.
    Times use timing's zone, or the machine's local zone when it is None.
    """
    _refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_assignment_snapshot(
            state=state, issue=issue, clock=timing.clock, zone=timing.zone
        ),
        wait=timing.wait,
    )


def show_conversation_view(
    *,
    state: StateDirectory,
    issue: int,
    console: Console,
    timing: ViewTiming = DEFAULT_VIEW_TIMING,
) -> None:
    """Show one issue conversation until it becomes inactive or needs attention."""
    _refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_conversation_snapshot(
            state=state, issue=issue, clock=timing.clock, zone=timing.zone
        ),
        wait=timing.wait,
    )


def _read_conversation_snapshot(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
) -> _ViewSnapshot:
    """Return one conversation snapshot and whether its live view is over."""
    status = _find_conversation_status_for_issue(state=state, issue=issue, clock=clock)
    return _ViewSnapshot(
        renderable=_render_conversation(state=state, status=status, zone=zone),
        is_over=status.value in CONVERSATION_STATUSES_THAT_END_A_VIEW,
    )


def _render_conversation(
    *,
    state: StateDirectory,
    status: IssueConversationStatus,
    zone: tzinfo | None,
) -> RenderableType:
    """Render one issue conversation and its saved rounds."""
    conversation = status.conversation
    record = conversation.record
    status_value = str(status.value)
    rendered_status = Text(f"{status_value}  {status.detail}")
    rendered_status.stylize(
        CONVERSATION_STATUS_STYLES[status.value], 0, len(status_value)
    )
    table = _create_table(columns=2)
    for name, value in (
        ("issue identifier", f"GH{record.issue}"),
        ("title", record.title),
        ("conversation label", record.label),
        ("worktree", state.describe_path(path=conversation.worktree)),
        ("agent harness", record.harness),
        (
            "harness session identifier",
            record.harness_session_identifier or "not recorded",
        ),
        ("model", record.model),
        ("effort", record.effort),
    ):
        table.add_row(Text(name), Text(str(value)))
    return _combine_renderable_parts(
        parts=[
            Text(f"issue conversation GH{record.issue}"),
            rendered_status,
            _render_latest_output(latest_output=status.latest_output),
            _render_section(heading="conversation", body=table),
            _render_round_statuses(round_statuses=status.round_statuses, zone=zone),
        ]
    )


def _read_assignment_snapshot(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
) -> _ViewSnapshot:
    """Return the newest assignment and whether its view is over.

    Each refresh reads the issue's statuses once and derives both the rendered
    view and whether the assignment is terminal from that snapshot.
    """
    assignment_statuses = _find_assignment_statuses_for_issue(
        state=state,
        issue=issue,
        clock=clock,
    )
    return _ViewSnapshot(
        renderable=_render_assignment(
            state=state, assignment_statuses=assignment_statuses, zone=zone
        ),
        is_over=assignment_statuses[0].value in STATUSES_THAT_END_A_VIEW,
    )


def _render_assignment(
    *,
    state: StateDirectory,
    assignment_statuses: list[AgentAssignmentStatus],
    zone: tzinfo | None,
) -> RenderableType:
    """Render the newest assignment with older assignments beneath it.

    Each dispatch creates another assignment for the issue, and the caller
    orders them newest first.
    """
    current_status = assignment_statuses[0]
    status_value = str(current_status.value)
    rendered_status = Text(f"{status_value}  {current_status.detail}")
    rendered_status.stylize(
        ASSIGNMENT_STATUS_STYLES[current_status.value],
        0,
        len(status_value),
    )
    latest_output = _render_assignment_latest_output(status=current_status)
    if latest_output is not None:
        latest_output = Padding(
            latest_output,
            (0, 0, 0, SECTION_PADDING[3]),
            expand=False,
        )
    return _combine_renderable_parts(
        parts=[
            Text(f"newest agent assignment {current_status.assignment.identifier}"),
            rendered_status,
            latest_output,
            _render_assignment_summary(state=state, status=current_status),
            _render_rounds(status=current_status, zone=zone),
            _render_harness_resume(state=state, status=current_status),
            _render_older_assignments(older_statuses=assignment_statuses[1:]),
        ]
    )


def _render_assignment_summary(
    *,
    state: StateDirectory,
    status: AgentAssignmentStatus,
) -> RenderableType:
    """Return what the dispatch settled for every round of the assignment."""
    assignment = status.assignment
    record = assignment.record
    table = _create_table(columns=2)
    for name, value in (
        ("issue identifier", f"GH{record.issue}"),
        ("agent assignment identifier", assignment.identifier),
        ("pull request", f"#{record.pull_request}"),
        ("dispatch label", record.dispatch_label),
        ("branch", record.branch),
        ("worktree", state.describe_path(path=record.worktree)),
        ("agent harness", record.harness),
        (
            "harness session identifier",
            status.harness_session_identifier or "not recorded",
        ),
        ("model", record.model),
        ("effort", record.effort),
    ):
        table.add_row(Text(name), Text(str(value)))
    return _render_section(heading="assignment", body=table)


def _render_rounds(
    *, status: AgentAssignmentStatus, zone: tzinfo | None
) -> RenderableType | None:
    """Return the rounds the assignment has run, newest first.

    Each row keeps the round number accepted by `feed --round`. An assignment
    with no rounds returns no section.
    """
    return _render_round_statuses(round_statuses=status.round_statuses, zone=zone)


def _render_round_statuses(
    *, round_statuses: Sequence[AgentRoundStatus], zone: tzinfo | None
) -> RenderableType | None:
    """Return agent round statuses newest first."""
    if not round_statuses:
        return None
    shows_revision = any(status.revision is not None for status in round_statuses)
    table = _create_table(columns=6 if shows_revision else 5)
    for round_status in reversed(round_statuses):
        record = round_status.record
        cells = [
            Text(str(record.number)),
            Text(
                describe_agent_round_start(
                    purpose=record.purpose,
                    is_recovery=record.is_recovery,
                )
            ),
        ]
        if shows_revision:
            cells.append(Text(round_status.revision or ""))
        cells.extend(
            [
                Text(describe_time(at=record.started, zone=zone)),
                Text(round_status.duration_description),
                Text(round_status.outcome_description),
            ]
        )
        table.add_row(*cells)
    return _render_section(heading="rounds", body=table)


def _render_harness_resume(
    *,
    state: StateDirectory,
    status: AgentAssignmentStatus,
) -> RenderableType | None:
    """Return how to resume the harness session by hand, when one exists.

    A round of the daemon's own is talking to the harness already, so there is
    nothing to resume until it has finished. An assignment that has run no round
    at all has no harness session behind it either, so there is nothing to resume
    there and never will be.
    """
    if status.hand_resume_command is None:
        return None
    worktree = state.describe_path(path=status.assignment.record.worktree)
    command = " ".join(status.hand_resume_command)
    return _render_section(
        heading="resume harness session yourself",
        body=Text(f"cd {worktree}\n{command}"),
    )


def _render_older_assignments(
    *, older_statuses: list[AgentAssignmentStatus]
) -> RenderableType | None:
    """Return the assignments at this issue that came before, newest first.

    An assignment that is the only one at its issue has none, and answers nothing.
    """
    if not older_statuses:
        return None
    table = _create_table(columns=3)
    for status in older_statuses:
        table.add_row(
            Text(f"agent assignment {status.assignment.identifier}"),
            Text(
                str(status.value),
                style=ASSIGNMENT_STATUS_STYLES[status.value],
            ),
            Text(status.detail),
        )
    return _render_section(heading="older assignments", body=table)


def show_feed_view(
    *,
    state: StateDirectory,
    selection: FeedSelection,
    console: Console,
    round_number: int | None = None,
    timing: ViewTiming = DEFAULT_VIEW_TIMING,
) -> None:
    """Show and follow the explicitly selected agent work's feed.

    Naming a round limits the view to that round and ends when the round ends.
    Without a round number, the view follows new rounds across the gaps between
    them until the assignment completes or enters fault.

    Every feed line carries its own timestamp, so the view needs no clock. A
    non-terminal or dumb terminal shows the current contents once and returns.
    Times use timing's zone, or the machine's local zone when it is None.
    """
    if round_number is not None:
        _show_one_round(
            state=state,
            selection=selection,
            number=round_number,
            console=console,
            timing=timing,
        )
        return
    view = _FeedView(console=console, zone=timing.zone)

    def refresh_feed() -> bool:
        """Show output since the previous refresh and return whether it is over."""
        snapshot = _find_feed_owner(
            state=state,
            issue=selection.issue,
            owner_kind=selection.owner_kind,
        )
        view.show_new_output(
            owner=snapshot.owner,
            records=snapshot.owner.rounds,
            round_details=snapshot.round_details,
        )
        return snapshot.is_over

    _refresh_until_view_ends(
        console=console, refresh_view=refresh_feed, wait=timing.wait
    )


def _show_one_round(
    *,
    state: StateDirectory,
    selection: FeedSelection,
    number: int,
    console: Console,
    timing: ViewTiming,
) -> None:
    """Show one round of the selected agent work until the round ends.

    Raise ReportableError when the assignment has no round with the requested
    number.
    """
    view = _FeedView(console=console, zone=timing.zone)

    def refresh_round_feed() -> bool:
        """Show output since the previous refresh and return whether it has ended."""
        snapshot = _find_feed_owner(
            state=state,
            issue=selection.issue,
            owner_kind=selection.owner_kind,
        )
        owner = snapshot.owner
        record = next(
            (record for record in owner.rounds if record.number == number), None
        )
        if record is None:
            raise ReportableError(
                f"{owner.identifier} has run "
                f"{describe_count(number=len(owner.rounds), noun='round')}, "
                f"so it has no round {number}."
            )
        view.show_new_output(
            owner=owner,
            records=[record],
            round_details=snapshot.round_details,
        )
        return record.ending is not None

    _refresh_until_view_ends(
        console=console, refresh_view=refresh_round_feed, wait=timing.wait
    )


def _find_assignment_statuses_for_issue(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime] = read_current_time,
) -> list[AgentAssignmentStatus]:
    """Return the issue's agent-assignment statuses, or refuse if none.

    A view of one issue reads that issue's assignments rather than the full
    status report. This is the one place that turns an issue with no assignment
    behind it into words for the reader.
    """
    assignment_statuses = read_agent_assignment_statuses_for_issue(
        state=state,
        issue=issue,
        clock=clock,
    )
    if not assignment_statuses:
        raise ReportableError(f"No assignment here for GH{issue}.")
    return assignment_statuses


def _find_conversation_status_for_issue(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime] = read_current_time,
) -> IssueConversationStatus:
    """Return the issue's conversation status, or refuse if none."""
    status = read_issue_conversation_status(state=state, issue=issue, clock=clock)
    if status is None:
        raise ReportableError(f"No conversation here for GH{issue}.")
    return status


@dataclass(frozen=True, kw_only=True)
class _FeedOwnerSnapshot:
    """Hold one feed owner and the status-derived context for its headings."""

    owner: AgentAssignment | IssueConversation
    is_over: bool
    round_details: dict[int, str]


def _find_feed_owner(
    *, state: StateDirectory, issue: int, owner_kind: AgentWorkKind
) -> _FeedOwnerSnapshot:
    """Return the selected feed owner and whether more output can reach it."""
    if owner_kind is AgentWorkKind.CONVERSATION:
        status = _find_conversation_status_for_issue(state=state, issue=issue)
        return _FeedOwnerSnapshot(
            owner=status.conversation,
            is_over=status.value in CONVERSATION_STATUSES_THAT_END_A_VIEW,
            round_details={
                round_status.record.number: round_status.revision_description
                for round_status in status.round_statuses
                if round_status.revision_description is not None
            },
        )
    status = _find_assignment_statuses_for_issue(state=state, issue=issue)[0]
    return _FeedOwnerSnapshot(
        owner=status.assignment,
        is_over=status.value in STATUSES_THAT_END_A_VIEW,
        round_details={},
    )


@dataclass(frozen=True, kw_only=True)
class _FeedView:
    """Track how far a console has read each round of an agent-work feed.

    Each refresh resumes from the stored byte position. A round without a stored
    position first receives its heading.
    """

    console: Console
    zone: tzinfo | None
    positions: dict[int, int] = field(default_factory=dict)

    def show_new_output(
        self,
        *,
        owner: AgentAssignment | IssueConversation,
        records: Iterable[AgentRoundRecord],
        round_details: dict[int, str],
    ) -> None:
        """Show agent output written since the previous refresh."""
        for record in records:
            if record.number not in self.positions:
                self._show_round_heading(
                    record=record, detail=round_details.get(record.number)
                )
            self._show_new_lines(owner=owner, round_number=record.number)

    def _show_round_heading(
        self,
        *,
        record: AgentRoundRecord,
        detail: str | None,
    ) -> None:
        """Show the line that opens a round, saying what caused it.

        A feed holds one round, so the stitch between two of them lands in no
        file and is the reader's. A blank line sets each round apart from the
        one before, which is why the first round of a view opens without one.
        """
        if self.positions:
            self.console.print()
        round_heading = compose_agent_round_boundary(
            number=record.number,
            purpose=record.purpose,
            is_recovery=record.is_recovery,
            at=record.started,
            detail=detail,
        )
        self.console.print(
            _render_feed_line(
                line=round_heading,
                content=Text(round_heading.text, style="bold"),
                zone=self.zone,
            )
        )
        self.positions[record.number] = 0

    def _show_new_lines(
        self,
        *,
        owner: AgentAssignment | IssueConversation,
        round_number: int,
    ) -> None:
        """Show lines the round wrote since the previous refresh."""
        feed_path = owner.compose_round_paths(number=round_number).feed
        new_lines, new_position = read_lines_from(
            path=feed_path, position=self.positions[round_number]
        )
        for line in new_lines:
            self.console.print(
                _render_written_feed_line(written_line=line, zone=self.zone)
            )
        self.positions[round_number] = new_position


def _render_written_feed_line(*, written_line: str, zone: tzinfo | None) -> Text:
    """Return one line of a feed as it reads on a console.

    An unparseable line is returned unchanged.
    """
    line = read_feed_line(written_line=written_line)
    if line is None:
        return Text(written_line)
    content = Text(line.text)
    if line.label is not None:
        label_start = len(SUBAGENT_INDENT) if line.is_subagent else 0
        content.stylize("cyan", label_start, label_start + len(line.label) + 2)
    return _render_feed_line(line=line, content=content, zone=zone)


def _render_feed_line(*, line: FeedLine, content: Text, zone: tzinfo | None) -> Text:
    return Text.assemble(
        (describe_time(at=line.at, zone=zone), "dim"), FEED_TIMESTAMP_GAP, content
    )
