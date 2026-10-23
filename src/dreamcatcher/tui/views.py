"""Render the agent work and feed views from local state."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from time import sleep

from rich.console import Console, RenderableType
from rich.padding import Padding
from rich.text import Text

from dreamcatcher.agent_assignments import compose_assignment_branch
from dreamcatcher.agent_work import AgentWork, refresh_agent_work
from dreamcatcher.clock import WaitForSeconds, read_current_time
from dreamcatcher.documents import read_lines_from
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import (
    FEED_TIMESTAMP_GAP,
    SUBAGENT_INDENT,
    FeedLine,
    compose_agent_round_boundary,
    read_feed_line,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentRoundStatus,
    AgentWorkStatus,
    read_agent_work_status,
    read_dreamcatcher_daemon_status,
)
from dreamcatcher.tui.shared import (
    AGENT_WORK_STATUS_STYLES,
    SECTION_PADDING,
    ViewSnapshot,
    combine_renderable_parts,
    create_table,
    refresh_live_view,
    refresh_until_view_ends,
    render_latest_output,
    render_section,
)
from dreamcatcher.words import describe_count, describe_time


def show_agent_work_view(
    *,
    state: StateDirectory,
    work: AgentWork,
    console: Console,
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
    zone: tzinfo | None = None,
) -> None:
    """Show the agent work until it ends.

    The view stays on that work, even when newer work arrives at the issue. It
    remains open between rounds. A non-terminal or dumb terminal renders one
    snapshot and returns. Times use the given zone, or the machine's local zone
    when it is None.
    """
    refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_agent_work_snapshot(
            state=state, work=work, clock=clock, zone=zone
        ),
        wait=wait,
    )


def _read_agent_work_snapshot(
    *,
    state: StateDirectory,
    work: AgentWork,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
) -> ViewSnapshot:
    """Return the work's view and whether to stop refreshing it.

    Each refresh reads the work's status once and derives both the rendered view
    and whether the work has ended from that read.
    """
    status = read_agent_work_status(
        state=state,
        work=refresh_agent_work(state=state, work=work),
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=clock,
    )
    return ViewSnapshot(
        renderable=_render_agent_work(state=state, status=status, zone=zone),
        should_stop_refreshing=status.has_ended,
    )


def _render_agent_work(
    *,
    state: StateDirectory,
    status: AgentWorkStatus,
    zone: tzinfo | None,
) -> RenderableType:
    """Render the work's status, settings, rounds and hand-resume command."""
    work = status.work
    status_value = str(status.value)
    rendered_status = Text(f"{status_value}  {status.detail}")
    rendered_status.stylize(
        AGENT_WORK_STATUS_STYLES[status.value], 0, len(status_value)
    )
    latest_output = render_latest_output(latest_output=status.latest_output)
    if latest_output is not None:
        latest_output = Padding(
            latest_output,
            (0, 0, 0, SECTION_PADDING[3]),
            expand=False,
        )
    kind = work.record.kind
    return combine_renderable_parts(
        parts=[
            Text(f"{kind} {work.identifier}"),
            rendered_status,
            latest_output,
            (
                _render_assignment_summary(state=state, status=status)
                if kind is AgentWorkKind.ASSIGNMENT
                else _render_issue_work_summary(state=state, status=status)
            ),
            _render_round_statuses(round_statuses=status.round_statuses, zone=zone),
            _render_harness_resume(state=state, status=status),
        ]
    )


def _render_issue_work_summary(
    *, state: StateDirectory, status: AgentWorkStatus
) -> RenderableType:
    """Return the section that names a conversation or a campaign and its settings."""
    work = status.work
    record = work.record
    table = create_table(columns=2)
    for name, value in (
        ("issue identifier", f"GH{record.issue}"),
        ("agent work identifier", work.identifier),
        ("title", record.title),
        ("label", record.dispatch_label),
        ("worktree", _describe_worktree(state=state, status=status)),
        ("harness", record.harness),
        (
            "harness session identifier",
            status.harness_session_identifier or "not recorded",
        ),
        ("model", record.model),
        ("effort", record.effort),
    ):
        table.add_row(Text(name), Text(str(value)))
    return render_section(heading=str(record.kind), body=table)


def _render_assignment_summary(
    *, state: StateDirectory, status: AgentWorkStatus
) -> RenderableType:
    """Return the section that names an assignment and its settings."""
    assignment = status.work
    record = assignment.record
    table = create_table(columns=2)
    for name, value in (
        ("issue identifier", f"GH{record.issue}"),
        ("agent work identifier", assignment.identifier),
        ("pull request", _describe_pull_request(status=status)),
        ("label", record.dispatch_label),
        ("branch", compose_assignment_branch(identifier=assignment.identifier)),
        ("worktree", _describe_worktree(state=state, status=status)),
        ("harness", record.harness),
        (
            "harness session identifier",
            status.harness_session_identifier or "not recorded",
        ),
        ("model", record.model),
        ("effort", record.effort),
    ):
        table.add_row(Text(name), Text(str(value)))
    return render_section(heading="assignment", body=table)


def _describe_pull_request(*, status: AgentWorkStatus) -> str:
    """Return the pull request's number and where it stands, when that is known."""
    if status.pull_request is None:
        return "none yet"
    if status.pull_request_summary is None:
        return f"#{status.pull_request}"
    return f"#{status.pull_request} {status.pull_request_summary}"


def _render_round_statuses(
    *, round_statuses: Sequence[AgentRoundStatus], zone: tzinfo | None
) -> RenderableType | None:
    """Return agent round statuses newest first."""
    if not round_statuses:
        return None
    table = create_table(columns=5)
    for round_status in reversed(round_statuses):
        record = round_status.record
        table.add_row(
            Text(str(record.number)),
            Text(round_status.trigger.describe()),
            Text(describe_time(at=record.started, zone=zone)),
            Text(round_status.duration_description),
            Text(round_status.outcome_description),
        )
    return render_section(heading="rounds", body=table)


def _describe_worktree(*, state: StateDirectory, status: AgentWorkStatus) -> str:
    """Return where the work's worktree is, or that it has been removed."""
    worktree = status.worktree
    return "removed" if worktree is None else state.describe_path(path=worktree)


def _render_harness_resume(
    *, state: StateDirectory, status: AgentWorkStatus
) -> RenderableType | None:
    """Return how to resume the harness session by hand, when one exists."""
    worktree = status.worktree
    hand_resume_command = status.hand_resume_command
    if worktree is None or hand_resume_command is None:
        return None
    described_worktree = state.describe_path(path=worktree)
    command = " ".join(hand_resume_command)
    return render_section(
        heading="resume by hand",
        body=Text(f"cd {described_worktree}\n{command}"),
    )


def show_feed_view(
    *,
    state: StateDirectory,
    work: AgentWork,
    console: Console,
    round_number: int | None = None,
    wait: WaitForSeconds = sleep,
    zone: tzinfo | None = None,
) -> None:
    """Show and follow the feed of the agent work.

    The view stays on that work, even when newer work arrives at the issue.
    """
    if round_number is not None:
        _show_one_round(
            state=state,
            work=work,
            number=round_number,
            console=console,
            wait=wait,
            zone=zone,
        )
        return
    view = _FeedView(console=console, zone=zone)

    def refresh_feed() -> bool:
        """Show new output and return whether refreshing should stop."""
        status = _read_feed_status(state=state, work=work)
        view.show_new_output(work=status.work, round_statuses=status.round_statuses)
        return status.has_ended

    refresh_until_view_ends(console=console, refresh_view=refresh_feed, wait=wait)


def _show_one_round(
    *,
    state: StateDirectory,
    work: AgentWork,
    number: int,
    console: Console,
    wait: WaitForSeconds,
    zone: tzinfo | None,
) -> None:
    """Show one round of the agent work until the round ends."""
    view = _FeedView(console=console, zone=zone)

    def refresh_round_feed() -> bool:
        """Show output since the previous refresh and return whether it has ended."""
        status = _read_feed_status(state=state, work=work)
        round_status = next(
            (
                round_status
                for round_status in status.round_statuses
                if round_status.record.number == number
            ),
            None,
        )
        if round_status is None:
            raise ReportableError(
                f"{work.identifier} has run "
                f"{describe_count(number=len(status.work.rounds), noun='round')}, "
                f"so it has no round {number}."
            )
        view.show_new_output(work=status.work, round_statuses=[round_status])
        return round_status.record.ending is not None

    refresh_until_view_ends(console=console, refresh_view=refresh_round_feed, wait=wait)


def _read_feed_status(*, state: StateDirectory, work: AgentWork) -> AgentWorkStatus:
    """Return the status of the work as it reads now."""
    return read_agent_work_status(
        state=state,
        work=refresh_agent_work(state=state, work=work),
        daemon=read_dreamcatcher_daemon_status(state=state),
    )


@dataclass(frozen=True, kw_only=True)
class _FeedView:
    """Track how far a console has read each round of an agent-work feed."""

    console: Console
    zone: tzinfo | None
    positions: dict[int, int] = field(default_factory=dict)

    def show_new_output(
        self,
        *,
        work: AgentWork,
        round_statuses: Iterable[AgentRoundStatus],
    ) -> None:
        """Show agent output written since the previous refresh."""
        for round_status in round_statuses:
            number = round_status.record.number
            if number not in self.positions:
                self._show_round_boundary(round_status=round_status)
            self._show_new_lines(work=work, round_number=number)

    def _show_round_boundary(self, *, round_status: AgentRoundStatus) -> None:
        """Show the line that opens a round, saying what woke it."""
        if self.positions:
            self.console.print()
        record = round_status.record
        round_boundary = compose_agent_round_boundary(
            number=record.number,
            trigger=round_status.trigger.describe(),
            at=record.started,
        )
        self.console.print(
            _render_feed_line(
                line=round_boundary,
                content=Text(round_boundary.text, style="bold"),
                zone=self.zone,
            )
        )
        self.positions[record.number] = 0

    def _show_new_lines(self, *, work: AgentWork, round_number: int) -> None:
        """Show lines the round wrote since the previous refresh."""
        feed_path = work.compose_round_paths(number=round_number).feed
        new_lines, new_position = read_lines_from(
            path=feed_path, position=self.positions[round_number]
        )
        for line in new_lines:
            self.console.print(
                _render_written_feed_line(written_line=line, zone=self.zone)
            )
        self.positions[round_number] = new_position


def _render_written_feed_line(*, written_line: str, zone: tzinfo | None) -> Text:
    """Return one line of a feed as it reads on a console."""
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
