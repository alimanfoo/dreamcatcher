"""Render status, assignment, and feed views from local state.

The views read the state directory without contacting GitHub or the daemon.
Status and assignment views redraw the current state, while a feed appends new
lines and preserves terminal scrollback. Color is added only during rendering.

"""

from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from time import sleep

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
    FeedLine,
    compose_agent_round_boundary,
    describe_agent_round_start,
    read_feed_line,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentAssignmentStatus,
    AgentAssignmentStatusValue,
    DreamcatcherStatusReport,
    IssueObservation,
    ObstructedAssignmentSetupStatus,
    read_agent_assignment_statuses_for_issue,
    read_status_report,
)
from dreamcatcher.words import describe_count, describe_span, describe_time

# What each assignment summary is set in, so a reader can scan the status table.
ASSIGNMENT_STATUS_STYLES = {
    AgentAssignmentStatusValue.WORKING: "green",
    AgentAssignmentStatusValue.WAITING: "cyan",
    AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK: "yellow",
    AgentAssignmentStatusValue.FAULT: "red",
    AgentAssignmentStatusValue.COMPLETE: "dim",
    AgentAssignmentStatusValue.UNKNOWN: "magenta",
}

STATUSES_THAT_END_A_VIEW = (
    AgentAssignmentStatusValue.FAULT,
    AgentAssignmentStatusValue.COMPLETE,
)

# How long a following view waits between refreshes for new round output.
VIEW_REFRESH_INTERVAL = 1.0

# What marks the label of a feed line, which is the harness's own word for what
# it just did.
FEED_NOTE_LABEL_PATTERN = r"^\s*\[[^\]]+\]"

# How far a section's rows are set in from its heading.
SECTION_PADDING = (0, 0, 0, 2)


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
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
) -> None:
    """Show instance, issue, and assignment status until interrupted.

    A non-terminal or dumb terminal renders one report and returns.
    """
    _refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_status_snapshot(state=state, clock=clock),
        wait=wait,
    )


def _read_status_snapshot(
    *, state: StateDirectory, clock: Callable[[], datetime]
) -> _ViewSnapshot:
    """Return the current status report as a view that never ends itself.

    A daemon can start, a tick can run, or a round can begin after any refresh.
    """
    return _ViewSnapshot(
        renderable=_render_status(report=read_status_report(state=state, clock=clock)),
        is_over=False,
    )


def _render_status(*, report: DreamcatcherStatusReport) -> RenderableType:
    """Render repository facts, assignments, setup obstacles, and available issues."""
    return _combine_renderable_parts(
        parts=[
            Text(report.repository or "repository unknown", style="bold"),
            _render_instance_status(report=report),
            _render_assignments(assignments=report.assignment_statuses),
            _render_obstructed_assignment_setups(
                setups=report.obstructed_assignment_setups
            ),
            _render_issues(issues=report.issue_observations),
            _describe_empty_status_report(report=report),
        ]
    )


def _combine_renderable_parts(
    *, parts: Sequence[RenderableType | None]
) -> RenderableType:
    return Group(*(part for part in parts if part is not None))


def _render_instance_status(*, report: DreamcatcherStatusReport) -> RenderableType:
    """Render the daemon, scheduler, capacity, and cooldown facts."""
    table = _create_table(columns=2)
    daemon = (
        "not running"
        if report.daemon_pid is None
        else f"running as pid {report.daemon_pid}"
    )
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
    for name, value in (
        ("daemon", daemon),
        ("latest scheduler tick", tick),
        (
            "agent-round capacity",
            (
                None
                if report.max_agent_rounds is None
                else f"{report.running_agent_rounds} of "
                f"{report.max_agent_rounds} in use"
            ),
        ),
        ("global cooldown", cooldown),
        ("scheduler hold", report.scheduler_hold),
    ):
        if value is not None:
            table.add_row(Text(name), Text(value))
    return _render_section(heading="instance", body=table)


def _render_issues(*, issues: Sequence[IssueObservation]) -> RenderableType | None:
    """Render available issues in the order the scheduler will dispatch them."""
    if not issues:
        return None
    table = _create_table(columns=2)
    for issue in issues:
        table.add_row(
            Text(f"GH{issue.issue}"),
            Text(f"dispatch label: {', '.join(issue.dispatch_labels or [])}"),
        )
    return _render_section(heading="available issues", body=table)


def _render_obstructed_assignment_setups(
    *, setups: Sequence[ObstructedAssignmentSetupStatus]
) -> RenderableType | None:
    """Render incomplete assignment setups with recorded obstacles."""
    if not setups:
        return None
    table = _create_table(columns=2)
    for setup in setups:
        table.add_row(Text(f"GH{setup.issue}"), Text(setup.obstacle))
    return _render_section(heading="obstructed assignment setups", body=table)


def _render_assignments(
    *, assignments: Sequence[AgentAssignmentStatus]
) -> RenderableType | None:
    """Render every agent assignment and its summary status."""
    if not assignments:
        return None
    table = _create_table(columns=3)
    for status in assignments:
        table.add_row(
            Text(status.assignment.identifier),
            Text(str(status.value), style=ASSIGNMENT_STATUS_STYLES[status.value]),
            _render_assignment_detail(
                status=status,
                prefix=_describe_running_round(status=status),
            ),
        )
    return _render_section(heading="agent assignments", body=table)


def _describe_running_round(*, status: AgentAssignmentStatus) -> str:
    """Return the running round's number, or nothing between rounds."""
    if status.value is not AgentAssignmentStatusValue.WORKING:
        return ""
    return f"round {len(status.assignment.rounds)}"


def _render_assignment_detail(
    *,
    status: AgentAssignmentStatus,
    prefix: str = "",
    continuation_indent: int = 0,
    style: str = "",
) -> RenderableType:
    """Render assignment detail behind its prefix, latest output beneath it."""
    detail = Text(", ".join(filter(None, (prefix, status.detail))), style=style)
    if status.latest_output is None:
        return detail
    output = Padding(
        Text(status.latest_output),
        (0, 0, 0, continuation_indent),
        expand=False,
    )
    return Group(detail, output)


def _describe_empty_status_report(*, report: DreamcatcherStatusReport) -> Text | None:
    """Describe an instance that has no issue or assignment status yet."""
    if (
        report.obstructed_assignment_setups
        or report.issue_observations
        or report.assignment_statuses
    ):
        return None
    return Text("no issues or agent assignments recorded yet")


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
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
) -> None:
    """Show the issue's newest assignment until it completes or enters fault.

    The view remains open between rounds. A non-terminal or dumb terminal
    renders one snapshot and returns.
    """
    _refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_assignment_snapshot(
            state=state, issue=issue, clock=clock
        ),
        wait=wait,
    )


def _read_assignment_snapshot(
    *, state: StateDirectory, issue: int, clock: Callable[[], datetime]
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
            state=state, assignment_statuses=assignment_statuses
        ),
        is_over=assignment_statuses[0].value in STATUSES_THAT_END_A_VIEW,
    )


def _render_assignment(
    *, state: StateDirectory, assignment_statuses: list[AgentAssignmentStatus]
) -> RenderableType:
    """Render the newest assignment with older assignments beneath it.

    Each dispatch creates another assignment for the issue, and the caller
    orders them newest first.
    """
    current_status = assignment_statuses[0]
    return _combine_renderable_parts(
        parts=[
            Text(f"newest agent assignment {current_status.assignment.identifier}"),
            _render_assignment_detail(
                status=current_status,
                prefix=str(current_status.value),
                continuation_indent=SECTION_PADDING[3],
                style=ASSIGNMENT_STATUS_STYLES[current_status.value],
            ),
            _render_assignment_summary(state=state, status=current_status),
            _render_rounds(status=current_status),
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


def _render_rounds(*, status: AgentAssignmentStatus) -> RenderableType | None:
    """Return the rounds the assignment has run, newest first.

    Each row keeps the round number accepted by `feed --round`. An assignment
    with no rounds returns no section.
    """
    if not status.round_statuses:
        return None
    table = _create_table(columns=5)
    for round_status in reversed(status.round_statuses):
        record = round_status.record
        table.add_row(
            Text(str(record.number)),
            Text(
                describe_agent_round_start(
                    purpose=record.purpose,
                    is_recovery=record.is_recovery,
                )
            ),
            Text(describe_time(at=record.started)),
            Text(round_status.duration_description),
            Text(round_status.outcome_description),
        )
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
            Text(str(status.value), style=ASSIGNMENT_STATUS_STYLES[status.value]),
            _render_assignment_detail(status=status),
        )
    return _render_section(heading="older assignments", body=table)


def show_feed_view(
    *,
    state: StateDirectory,
    issue: int,
    console: Console,
    round_number: int | None = None,
    wait: WaitForSeconds = sleep,
) -> None:
    """Show and follow the newest assignment's feed.

    Naming a round limits the view to that round and ends when the round ends.
    Without a round number, the view follows new rounds across the gaps between
    them until the assignment completes or enters fault.

    Every feed line carries its own timestamp, so the view needs no clock. A
    non-terminal or dumb terminal shows the current contents once and returns.
    """
    if round_number is not None:
        _show_one_round(
            state=state, issue=issue, number=round_number, console=console, wait=wait
        )
        return
    view = _FeedView(console=console)

    def refresh_feed() -> bool:
        """Show output since the previous refresh and return whether it is over."""
        status = _find_assignment_statuses_for_issue(state=state, issue=issue)[0]
        assignment = status.assignment
        view.show_new_output(assignment=assignment, records=assignment.rounds)
        return status.value in STATUSES_THAT_END_A_VIEW

    _refresh_until_view_ends(console=console, refresh_view=refresh_feed, wait=wait)


def _show_one_round(
    *,
    state: StateDirectory,
    issue: int,
    number: int,
    console: Console,
    wait: WaitForSeconds,
) -> None:
    """Show one round of the newest assignment until the round ends.

    Raise ReportableError when the assignment has no round with the requested
    number.
    """
    view = _FeedView(console=console)

    def refresh_round_feed() -> bool:
        """Show output since the previous refresh and return whether it has ended."""
        assignment = _find_assignment_statuses_for_issue(
            state=state,
            issue=issue,
        )[0].assignment
        record = next(
            (record for record in assignment.rounds if record.number == number), None
        )
        if record is None:
            raise ReportableError(
                f"{assignment.identifier} has run "
                f"{describe_count(number=len(assignment.rounds), noun='round')}, "
                f"so it has no round {number}."
            )
        view.show_new_output(assignment=assignment, records=[record])
        return record.ending is not None

    _refresh_until_view_ends(
        console=console, refresh_view=refresh_round_feed, wait=wait
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


@dataclass(frozen=True, kw_only=True)
class _FeedView:
    """Track how far a console has read each round of an assignment feed.

    Each refresh resumes from the stored byte position. A round without a stored
    position first receives its heading.
    """

    console: Console
    positions: dict[int, int] = field(default_factory=dict)

    def show_new_output(
        self, *, assignment: AgentAssignment, records: Iterable[AgentRoundRecord]
    ) -> None:
        """Show assignment output written since the previous refresh."""
        for record in records:
            if record.number not in self.positions:
                self._show_round_heading(record=record)
            self._show_new_lines(assignment=assignment, round_number=record.number)

    def _show_round_heading(self, *, record: AgentRoundRecord) -> None:
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
        )
        self.console.print(
            _render_feed_line(
                line=round_heading,
                content=Text(round_heading.text, style="bold"),
            )
        )
        self.positions[record.number] = 0

    def _show_new_lines(
        self, *, assignment: AgentAssignment, round_number: int
    ) -> None:
        """Show lines the round wrote since the previous refresh."""
        feed_path = assignment.compose_round_paths(number=round_number).feed
        new_lines, new_position = read_lines_from(
            path=feed_path, position=self.positions[round_number]
        )
        for line in new_lines:
            self.console.print(_render_written_feed_line(written_line=line))
        self.positions[round_number] = new_position


def _render_written_feed_line(*, written_line: str) -> Text:
    """Return one line of a feed as it reads on a console.

    An unparseable line is returned unchanged.
    """
    line = read_feed_line(written_line=written_line)
    if line is None:
        return Text(written_line)
    content = Text(line.text)
    content.highlight_regex(FEED_NOTE_LABEL_PATTERN, "cyan")
    return _render_feed_line(line=line, content=content)


def _render_feed_line(*, line: FeedLine, content: Text) -> Text:
    return Text.assemble(
        (describe_time(at=line.at), "dim"), FEED_TIMESTAMP_GAP, content
    )
