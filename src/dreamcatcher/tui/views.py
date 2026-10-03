"""Render assignment, conversation, and feed views from local state."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path
from time import sleep

from rich.console import Console, RenderableType
from rich.padding import Padding
from rich.text import Text

from dreamcatcher.agent_assignments import Assignment
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
from dreamcatcher.issue_conversations import Conversation
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentRoundStatus,
    AssignmentStatus,
    ConversationStatus,
    read_assignment_statuses_for_issue,
    read_conversation_status,
)
from dreamcatcher.tui.shared import (
    ASSIGNMENT_STATUS_STYLES,
    CONVERSATION_STATUS_STYLES,
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


def show_assignment_view(
    *,
    state: StateDirectory,
    issue: int,
    console: Console,
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
    zone: tzinfo | None = None,
) -> None:
    """Show the issue's newest assignment until it completes or enters fault.

    The view remains open between rounds. A non-terminal or dumb terminal
    renders one snapshot and returns.
    Times use the given zone, or the machine's local zone when it is None.
    """
    refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_assignment_snapshot(
            state=state, issue=issue, clock=clock, zone=zone
        ),
        wait=wait,
    )


def show_conversation_view(
    *,
    state: StateDirectory,
    issue: int,
    console: Console,
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
    zone: tzinfo | None = None,
) -> None:
    """Show one issue conversation until nothing more can happen without the user.

    That is once it enters fault, has a routing conflict, or the status report
    no longer lists it.
    A non-terminal or dumb terminal renders one snapshot and returns.
    """
    refresh_live_view(
        console=console,
        read_snapshot=lambda: _read_conversation_snapshot(
            state=state, issue=issue, clock=clock, zone=zone
        ),
        wait=wait,
    )


def _read_conversation_snapshot(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
) -> ViewSnapshot:
    """Return one conversation snapshot and whether its live view is over."""
    status = _find_conversation_status_for_issue(state=state, issue=issue, clock=clock)
    return ViewSnapshot(
        renderable=_render_conversation(state=state, status=status, zone=zone),
        is_over=status.is_over,
    )


def _render_conversation(
    *,
    state: StateDirectory,
    status: ConversationStatus,
    zone: tzinfo | None,
) -> RenderableType:
    """Render one issue conversation and its saved rounds.

    A conversation settles its settings when its first round launches, so one
    with no saved conversation yet shows only its issue.
    """
    conversation = status.conversation
    status_value = str(status.value)
    rendered_status = Text(f"{status_value}  {status.detail}")
    rendered_status.stylize(
        CONVERSATION_STATUS_STYLES[status.value], 0, len(status_value)
    )
    return combine_renderable_parts(
        parts=[
            Text(f"issue conversation GH{status.issue}"),
            rendered_status,
            render_latest_output(latest_output=status.latest_output),
            _render_conversation_summary(state=state, status=status),
            _render_round_statuses(round_statuses=status.round_statuses, zone=zone),
            (
                None
                if conversation is None
                else _render_harness_resume(
                    state=state,
                    worktree=conversation.worktree,
                    hand_resume_command=status.hand_resume_command,
                )
            ),
        ]
    )


def _render_conversation_summary(
    *, state: StateDirectory, status: ConversationStatus
) -> RenderableType:
    """Return the issue, and what the first round settled for every round."""
    facts: list[tuple[str, object]] = [
        ("issue identifier", f"GH{status.issue}"),
        ("title", status.title),
    ]
    conversation = status.conversation
    if conversation is not None:
        record = conversation.record
        facts.extend(
            [
                ("dispatch label", record.dispatch_label),
                ("worktree", state.describe_path(path=conversation.worktree)),
                ("agent harness", record.harness),
                (
                    "harness session identifier",
                    status.harness_session_identifier or "not recorded",
                ),
                ("model", record.model),
                ("effort", record.effort),
            ]
        )
    table = create_table(columns=2)
    for name, value in facts:
        table.add_row(Text(name), Text(str(value)))
    return render_section(heading="conversation", body=table)


def _read_assignment_snapshot(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
) -> ViewSnapshot:
    """Return the newest assignment and whether its view is over.

    Each refresh reads the issue's statuses once and derives both the rendered
    view and whether the assignment is terminal from that snapshot.
    """
    assignment_statuses = _find_assignment_statuses_for_issue(
        state=state,
        issue=issue,
        clock=clock,
    )
    return ViewSnapshot(
        renderable=_render_assignment(
            state=state, assignment_statuses=assignment_statuses, zone=zone
        ),
        is_over=assignment_statuses[0].is_over,
    )


def _render_assignment(
    *,
    state: StateDirectory,
    assignment_statuses: list[AssignmentStatus],
    zone: tzinfo | None,
) -> RenderableType:
    """Render the newest assignment with older assignments beneath it."""
    current_status = assignment_statuses[0]
    status_value = str(current_status.value)
    rendered_status = Text(f"{status_value}  {current_status.detail}")
    rendered_status.stylize(
        ASSIGNMENT_STATUS_STYLES[current_status.value], 0, len(status_value)
    )
    latest_output = render_latest_output(latest_output=current_status.latest_output)
    if latest_output is not None:
        latest_output = Padding(
            latest_output,
            (0, 0, 0, SECTION_PADDING[3]),
            expand=False,
        )
    return combine_renderable_parts(
        parts=[
            Text(f"newest agent assignment {current_status.assignment.identifier}"),
            rendered_status,
            latest_output,
            _render_assignment_summary(state=state, status=current_status),
            _render_rounds(status=current_status, zone=zone),
            _render_harness_resume(
                state=state,
                worktree=current_status.assignment.record.worktree,
                hand_resume_command=current_status.hand_resume_command,
            ),
            _render_older_assignments(older_statuses=assignment_statuses[1:]),
        ]
    )


def _render_assignment_summary(
    *, state: StateDirectory, status: AssignmentStatus
) -> RenderableType:
    """Return what the assignment dispatch settled for every round."""
    assignment = status.assignment
    record = assignment.record
    table = create_table(columns=2)
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
    return render_section(heading="assignment", body=table)


def _render_rounds(
    *, status: AssignmentStatus, zone: tzinfo | None
) -> RenderableType | None:
    """Return the rounds the assignment has run, newest first."""
    return _render_round_statuses(round_statuses=status.round_statuses, zone=zone)


def _render_round_statuses(
    *, round_statuses: Sequence[AgentRoundStatus], zone: tzinfo | None
) -> RenderableType | None:
    """Return agent round statuses newest first."""
    if not round_statuses:
        return None
    shows_revision = any(status.revision is not None for status in round_statuses)
    table = create_table(columns=6 if shows_revision else 5)
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
            cells.append(
                Text(
                    "" if round_status.revision is None else round_status.revision.value
                )
            )
        cells.extend(
            [
                Text(describe_time(at=record.started, zone=zone)),
                Text(round_status.duration_description),
                Text(round_status.outcome_description),
            ]
        )
        table.add_row(*cells)
    return render_section(heading="rounds", body=table)


def _render_harness_resume(
    *,
    state: StateDirectory,
    worktree: Path,
    hand_resume_command: list[str] | None,
) -> RenderableType | None:
    """Return how to resume the harness session by hand, when one exists."""
    if hand_resume_command is None:
        return None
    described_worktree = state.describe_path(path=worktree)
    command = " ".join(hand_resume_command)
    return render_section(
        heading="resume by hand",
        body=Text(f"cd {described_worktree}\n{command}"),
    )


def _render_older_assignments(
    *, older_statuses: list[AssignmentStatus]
) -> RenderableType | None:
    """Return the assignments at this issue that came before, newest first."""
    if not older_statuses:
        return None
    table = create_table(columns=3)
    for status in older_statuses:
        table.add_row(
            Text(f"agent assignment {status.assignment.identifier}"),
            Text(str(status.value), style=ASSIGNMENT_STATUS_STYLES[status.value]),
            Text(status.detail),
        )
    return render_section(heading="older assignments", body=table)


def show_feed_view(
    *,
    state: StateDirectory,
    issue: int,
    owner_kind: AgentWorkKind,
    console: Console,
    round_number: int | None = None,
    wait: WaitForSeconds = sleep,
    zone: tzinfo | None = None,
) -> None:
    """Show and follow the explicitly selected agent work's feed."""
    if round_number is not None:
        _show_one_round(
            state=state,
            issue=issue,
            owner_kind=owner_kind,
            number=round_number,
            console=console,
            wait=wait,
            zone=zone,
        )
        return
    view = _FeedView(console=console, zone=zone)

    def refresh_feed() -> bool:
        """Show output since the previous refresh and return whether it is over."""
        snapshot = _find_feed_owner(state=state, issue=issue, owner_kind=owner_kind)
        view.show_new_output(
            owner=snapshot.owner,
            records=snapshot.owner.rounds,
            round_details=snapshot.round_details,
        )
        return snapshot.is_over

    refresh_until_view_ends(console=console, refresh_view=refresh_feed, wait=wait)


def _show_one_round(
    *,
    state: StateDirectory,
    issue: int,
    owner_kind: AgentWorkKind,
    number: int,
    console: Console,
    wait: WaitForSeconds,
    zone: tzinfo | None,
) -> None:
    """Show one round of the selected agent work until the round ends."""
    view = _FeedView(console=console, zone=zone)

    def refresh_round_feed() -> bool:
        """Show output since the previous refresh and return whether it has ended."""
        snapshot = _find_feed_owner(state=state, issue=issue, owner_kind=owner_kind)
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

    refresh_until_view_ends(console=console, refresh_view=refresh_round_feed, wait=wait)


def _find_assignment_statuses_for_issue(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime] = read_current_time,
) -> list[AssignmentStatus]:
    """Return the issue's agent-assignment statuses, or refuse if none."""
    assignment_statuses = read_assignment_statuses_for_issue(
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
) -> ConversationStatus:
    """Return the issue's conversation status, or refuse if none."""
    status = read_conversation_status(state=state, issue=issue, clock=clock)
    if status is None:
        raise ReportableError(f"No conversation here for GH{issue}.")
    return status


@dataclass(frozen=True, kw_only=True)
class _FeedOwnerSnapshot:
    """Hold one feed owner and the status-derived context for its headings."""

    owner: Assignment | Conversation
    is_over: bool
    round_details: dict[int, str]


def _find_feed_owner(
    *, state: StateDirectory, issue: int, owner_kind: AgentWorkKind
) -> _FeedOwnerSnapshot:
    """Return the selected feed owner and whether more output can reach it."""
    if owner_kind is AgentWorkKind.CONVERSATION:
        status = _find_conversation_status_for_issue(state=state, issue=issue)
        if status.conversation is None:
            raise ReportableError(
                f"The conversation at GH{issue} has not run a round yet."
            )
        return _FeedOwnerSnapshot(
            owner=status.conversation,
            is_over=status.is_over,
            round_details={
                round_status.record.number: round_status.revision.description
                for round_status in status.round_statuses
                if round_status.revision is not None
            },
        )
    status = _find_assignment_statuses_for_issue(state=state, issue=issue)[0]
    return _FeedOwnerSnapshot(
        owner=status.assignment,
        is_over=status.is_over,
        round_details={},
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
        owner: Assignment | Conversation,
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
        self, *, record: AgentRoundRecord, detail: str | None
    ) -> None:
        """Show the line that opens a round, saying what caused it."""
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
        self, *, owner: Assignment | Conversation, round_number: int
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
