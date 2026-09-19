"""Show what the assignments are doing, from what the daemon left on the disk.

This is the terminal interface, and the whole of it. It holds the three views
a reader reaches through a verb of the command line: status, one assignment,
and one assignment's feed. It reads the state directory and never talks to GitHub
or to the daemon, so it answers whether the daemon is alive or dead, and
answers fastest when you most want to look.

Status and one assignment are pictures of a state, so each is drawn over the
one before it. A feed is a log, so it is printed as it is read, and the reader
keeps their scrollback.

What the daemon writes stays plain text, and the colour goes on at the moment of
reading.
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

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    find_harness_session_identifier,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
)
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
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentAssignmentStatus,
    AgentAssignmentStatusValue,
    IssueObservation,
    StatusReport,
    read_agent_assignment_statuses_for_issue,
    read_status_report,
)
from dreamcatcher.words import describe_count, describe_span, describe_time

# What each assignment summary is set in, so a reader can scan the status table.
COLOURS = {
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

# How long a following view waits between looks at what the round has written.
PAUSE = 1.0

# What marks the label of a feed line, which is the harness's own word for what
# it just did.
LABEL = r"^\s*\[[^\]]+\]"

# How far a section's rows are set in from its heading.
INDENT = (0, 0, 0, 2)


def open_console() -> Console:
    """Return the console that the views are written to.

    It names no width and no height, so rich reads the terminal's own on every
    look, and a view redrawn into a window the reader has since resized fills
    the size it is now. Only the tests name a size, so that a picture is cut in
    the same place whatever terminal runs them.
    """
    return Console()


@dataclass(frozen=True, kw_only=True)
class _Picture:
    """A view as one look found it: what to draw, and whether the view is over.

    A view is over when nothing more can reach it. That is not the same as the
    last look, because `_keep_looking` takes one more after it.
    """

    shown: RenderableType
    is_over: bool


def _repaint(
    *, console: Console, look: Callable[[], _Picture], wait: WaitForSeconds
) -> None:
    """Draw what each look finds over the one before, until the view is over.

    A picture of a state has a current value rather than a history, so every
    look is drawn over the one before rather than under it. rich's Live draws
    into the terminal's alternate screen, which it fills, so the view is the
    whole of what the reader sees while it is going and the commands the shell
    printed above it are not read alongside it. The screen is as tall as the
    terminal, so a picture that outgrows it is cut at the bottom. Status puts
    instance facts before agent assignments and available issues.

    Handing the screen back brings the shell's own output back and takes the
    last picture with it, so a view whose last look found it over prints that
    picture where the reader can go on reading it. An assignment that was already
    over when the view opened is drawn once and printed, which is what a
    reader looking one up reads. A view that the reader interrupts while
    something is still coming leaves nothing behind, because interrupting is
    how they say they have seen enough.

    This decides where a look is drawn, and `_keep_looking` decides how long to
    go on looking. A view nobody is watching has no screen to take, and a
    terminal that reports itself as dumb takes no control code, so rich can
    draw nothing into a screen there and writes nothing at all. Either console
    gets one look, printed as anything else is.
    """
    if not console.is_terminal or console.is_dumb_terminal:
        console.print(look().shown)
        return
    last_picture = _Picture(shown="", is_over=False)
    with Live(console=console, auto_refresh=False, screen=True) as live:

        def draw() -> bool:
            """Draw what this look found, and say whether the view is over."""
            nonlocal last_picture
            last_picture = look()
            live.update(last_picture.shown, refresh=True)
            return last_picture.is_over

        _keep_looking(console=console, look=draw, wait=wait)
    if last_picture.is_over:
        console.print(last_picture.shown)


def _keep_looking(
    *, console: Console, look: Callable[[], bool], wait: WaitForSeconds
) -> None:
    """Look again and again, until the view has seen the last of what it shows.

    A look shows where the view stands now and answers whether the view is
    over, which is to say whether anything more can reach it.

    Nobody is watching a console that is no terminal: the view is being piped,
    redirected or captured, and a view that went on looking would write another
    picture into that pipe, that file or that log at every look. So one look is
    the last look there, and the reader is asked for no flag to say so.

    A round records its ending as soon as its own child has gone, and whatever
    it was still writing lands after that, so a view that finds itself over
    looks once more before it ends. Nothing was going before the view opened,
    so a view that opens on something already over ends on its first look and
    never waits.

    The reader ends a view that is still going by interrupting it, which is how
    they say they have seen enough, so it ends without a word.
    """
    was_over = True
    with suppress(KeyboardInterrupt):
        while True:
            is_over = look()
            if (is_over and was_over) or not console.is_terminal:
                return
            was_over = is_over
            wait(PAUSE)


def show_status(
    *,
    state: StateDirectory,
    console: Console,
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
) -> None:
    """Show the instance, issue, and assignment status, and keep it current.

    A status report can always change, so a reader watching one ends it by
    interrupting it. A console that is no terminal has nobody watching, so the
    report is drawn once there and this returns.
    """
    _repaint(
        console=console,
        look=lambda: _look_at_status(state=state, clock=clock),
        wait=wait,
    )


def _look_at_status(
    *, state: StateDirectory, clock: Callable[[], datetime]
) -> _Picture:
    """Return the current status report, which no look ever finds over.

    A daemon can start, a tick can run, or a round can begin after any look.
    """
    return _Picture(
        shown=_render_status(report=read_status_report(state=state, clock=clock)),
        is_over=False,
    )


def _render_status(*, report: StatusReport) -> RenderableType:
    """Render the repository, instance facts, assignments, and available issues."""
    return _render_parts(
        parts=[
            Text(report.repository or "repository unknown", style="bold"),
            _render_instance(report=report),
            _render_assignments(assignments=report.assignments),
            _render_issues(issues=report.issues),
            _describe_nothing_recorded(report=report),
        ]
    )


def _render_parts(*, parts: Sequence[RenderableType | None]) -> RenderableType:
    """Return the parts of a view that have something to say, as one renderable.

    A part with nothing to say answers nothing, so it is left out rather than
    shown empty. The status and assignment views both compose themselves
    through this, so what that means is written down once.
    """
    return Group(*(part for part in parts if part is not None))


def _render_instance(*, report: StatusReport) -> RenderableType:
    """Render the daemon, scheduler, capacity, and cooldown facts."""
    table = _open_table(columns=2)
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
            f"{report.running_agent_rounds} of {report.max_agent_rounds} in use",
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
    table = _open_table(columns=2)
    for issue in issues:
        table.add_row(
            Text(f"GH{issue.issue}"),
            Text(f"dispatch label: {', '.join(issue.dispatch_labels or [])}"),
        )
    return _render_section(heading="available issues", body=table)


def _render_assignments(
    *, assignments: Sequence[AgentAssignmentStatus]
) -> RenderableType | None:
    """Render every agent assignment and its summary status."""
    if not assignments:
        return None
    table = _open_table(columns=3)
    for status in assignments:
        table.add_row(
            Text(status.assignment.identifier),
            Text(str(status.value), style=COLOURS[status.value]),
            _render_assignment_detail(
                status=status,
                prefix=_describe_round(status=status),
            ),
        )
    return _render_section(heading="agent assignments", body=table)


def _describe_round(*, status: AgentAssignmentStatus) -> str:
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


def _describe_nothing_recorded(*, report: StatusReport) -> Text | None:
    """Describe an instance that has no issue or assignment status yet."""
    if report.issues or report.assignments:
        return None
    return Text("no issues or agent assignments recorded yet")


def _open_table(*, columns: int) -> Table:
    """Return an empty table whose columns fit whatever a section puts in them.

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
    """Return one section of a view, set in under its own heading.

    A blank line opens the section, which sets it apart from the section above
    and from the line that opens the view.
    """
    return Group(
        Text(),
        Text(heading, style="bold blue"),
        Padding(body, INDENT, expand=False),
    )


def show_assignment(
    *,
    state: StateDirectory,
    issue: int,
    console: Console,
    clock: Callable[[], datetime] = read_current_time,
    wait: WaitForSeconds = sleep,
) -> None:
    """Show the newest assignment at the issue, and keep on showing it.

    An assignment between rounds has another round coming, so the view stays open
    through the gap and shows that round as it starts. An assignment that has run
    a successful wrap-up round, and an assignment currently in fault, have no
    round coming, so either one ends the view. A console that is no terminal has
    nobody watching, so there the assignment is drawn once and this returns.
    """
    _repaint(
        console=console,
        look=lambda: _look_at_assignment(state=state, issue=issue, clock=clock),
        wait=wait,
    )


def _look_at_assignment(
    *, state: StateDirectory, issue: int, clock: Callable[[], datetime]
) -> _Picture:
    """Return the newest assignment at the issue as it stands, and whether it is over.

    One look reads the issue's statuses once, and takes both what it draws and
    whether the assignment is terminal from them.
    """
    statuses = _find_assignment_statuses_for_issue(
        state=state,
        issue=issue,
        clock=clock,
    )
    return _Picture(
        shown=_render_assignment(state=state, statuses=statuses),
        is_over=statuses[0].value in STATUSES_THAT_END_A_VIEW,
    )


def _render_assignment(
    *, state: StateDirectory, statuses: list[AgentAssignmentStatus]
) -> RenderableType:
    """Return the newest of these assignments, with the older ones beneath it.

    An issue that has been dispatched more than once has an assignment for each
    dispatch. The newest is the one still going, or the one that got furthest,
    so it is the one the view is about.
    """
    newest = statuses[0]
    assignment = newest.assignment
    harness_adapter = HARNESS_ADAPTERS[assignment.record.harness]
    harness_session_identifier = find_harness_session_identifier(
        assignment=assignment,
        harness_adapter=harness_adapter,
    )
    return _render_parts(
        parts=[
            Text(f"newest agent assignment {newest.assignment.identifier}"),
            _render_assignment_detail(
                status=newest,
                prefix=str(newest.value),
                continuation_indent=INDENT[3],
                style=COLOURS[newest.value],
            ),
            _render_vitals(
                state=state,
                status=newest,
                harness_session_identifier=harness_session_identifier,
            ),
            _render_rounds(status=newest),
            _render_harness_resume(
                state=state,
                status=newest,
                harness_session_identifier=harness_session_identifier,
            ),
            _render_older_assignments(older=statuses[1:]),
        ]
    )


def _render_vitals(
    *,
    state: StateDirectory,
    status: AgentAssignmentStatus,
    harness_session_identifier: HarnessSessionIdentifier | None,
) -> RenderableType:
    """Return what the dispatch settled for every round of the assignment."""
    assignment = status.assignment
    record = assignment.record
    table = _open_table(columns=2)
    for name, value in (
        ("issue identifier", f"GH{record.issue}"),
        ("agent assignment identifier", assignment.identifier),
        ("pull request", f"#{record.pull_request}"),
        ("dispatch label", record.label),
        ("branch", record.branch),
        ("worktree", state.describe_path(path=record.worktree)),
        ("agent harness", record.harness),
        (
            "harness session identifier",
            harness_session_identifier or "not recorded",
        ),
        ("model", record.model),
        ("effort", record.effort),
    ):
        table.add_row(Text(name), Text(str(value)))
    return _render_section(heading="assignment", body=table)


def _render_rounds(*, status: AgentAssignmentStatus) -> RenderableType | None:
    """Return the rounds the assignment has run, newest first.

    The newest round is the one a reader came for, so it opens the section,
    as the newest assignment opens the view. Each round keeps the number it ran
    under, because that is the number `feed --round` takes.

    An assignment that has run none answers nothing.
    """
    rounds = status.assignment.rounds
    if not rounds:
        return None
    table = _open_table(columns=5)
    for record in reversed(rounds):
        is_running = (
            status.value is AgentAssignmentStatusValue.WORKING
            and record.number == rounds[-1].number
        )
        table.add_row(
            Text(str(record.number)),
            Text(
                describe_agent_round_start(
                    purpose=record.purpose,
                    is_recovery=record.is_recovery,
                )
            ),
            Text(describe_time(at=record.started)),
            Text(_describe_run(record=record)),
            Text(_describe_ending(record=record, is_running=is_running)),
        )
    return _render_section(heading="rounds", body=table)


def _describe_run(*, record: AgentRoundRecord) -> str:
    """Return how long the round ran, or nothing while it is still running."""
    if record.ending is None or isinstance(record.ending, InterruptedAgentRoundEnding):
        return ""
    return f"ran {describe_span(span=record.ending.at - record.started)}"


def _describe_ending(*, record: AgentRoundRecord, is_running: bool) -> str:
    """Return how the round ended, or what it is doing instead.

    A round that recorded no ending never finished. It is running when a daemon
    is still there to run it, and interrupted once that daemon has gone, since
    a round cannot outlive its daemon.
    """
    if isinstance(record.ending, ErroredAgentRoundEnding):
        return f"errored (exit {record.ending.status})"
    if isinstance(record.ending, InterruptedAgentRoundEnding):
        return "interrupted"
    if record.ending is not None:
        return "successful"
    return "running" if is_running else "interrupted"


def _render_harness_resume(
    *,
    state: StateDirectory,
    status: AgentAssignmentStatus,
    harness_session_identifier: HarnessSessionIdentifier | None,
) -> RenderableType | None:
    """Return how to resume the harness session by hand, when one exists.

    A round of the daemon's own is talking to the harness already, so there is
    nothing to resume until it has finished. An assignment that has run no round
    at all has no harness session behind it either, so there is nothing to resume
    there and never will be.
    """
    if (
        status.value is AgentAssignmentStatusValue.WORKING
        or harness_session_identifier is None
    ):
        return None
    harness_adapter = HARNESS_ADAPTERS[status.assignment.record.harness]
    worktree = state.describe_path(path=status.assignment.record.worktree)
    command = " ".join(
        harness_adapter.build_hand_resume(
            harness_session_identifier=harness_session_identifier
        )
    )
    return _render_section(
        heading="resume harness session yourself",
        body=Text(f"cd {worktree}\n{command}"),
    )


def _render_older_assignments(
    *, older: list[AgentAssignmentStatus]
) -> RenderableType | None:
    """Return the assignments at this issue that came before, newest first.

    An assignment that is the only one at its issue has none, and answers nothing.
    """
    if not older:
        return None
    table = _open_table(columns=3)
    for status in older:
        table.add_row(
            Text(f"agent assignment {status.assignment.identifier}"),
            Text(str(status.value), style=COLOURS[status.value]),
            _render_assignment_detail(status=status),
        )
    return _render_section(heading="older assignments", body=table)


def show_feed(
    *,
    state: StateDirectory,
    issue: int,
    console: Console,
    round_number: int | None = None,
    wait: WaitForSeconds = sleep,
) -> None:
    """Show what the issue's newest assignment said, and follow what arrives.

    Naming a round narrows the view to that one round, and everything below is
    about the view of the whole assignment, which is what a reader gets when they
    name no round.

    Neither view reads a clock, unlike the status and assignment views, which
    say how long ago something happened. Every line a feed shows carries the
    time it was written, so what a feed shows is the same whenever it is read.

    Reading an assignment that is over and watching one that is going are the same
    view in two tenses, so this shows what is there and then keeps showing what
    lands for as long as the assignment has another round coming.

    An assignment between rounds is still going, so the view stays open through the
    gaps: while the assignment waits for a round that no daemon has launched yet,
    while its pull request waits for the reader to post on it, and while the
    daemon that was running it is stopped and started again.

    An assignment with a successful wrap-up round has nothing more to say. An
    assignment currently in fault has no ordinary recovery round coming, so
    either state ends the view rather than have it wait indefinitely. A later
    global cooldown can clear the fault, after which a new view follows recovery.

    Every look reads the assignment again, so a round that starts while the view
    is going is shown as it arrives, and not only the rounds it opened with.

    A console that is no terminal has nobody watching, so there either view
    shows what is there once and returns.
    """
    if round_number is not None:
        _show_one_round(
            state=state, issue=issue, number=round_number, console=console, wait=wait
        )
        return
    view = _FeedView(console=console)

    def look() -> bool:
        """Show what the assignment said since the last look, and say if it is over."""
        status = _find_assignment_statuses_for_issue(state=state, issue=issue)[0]
        assignment = status.assignment
        view.show_what_arrived(assignment=assignment, records=assignment.rounds)
        return status.value in STATUSES_THAT_END_A_VIEW

    _keep_looking(console=console, look=look, wait=wait)


def _show_one_round(
    *,
    state: StateDirectory,
    issue: int,
    number: int,
    console: Console,
    wait: WaitForSeconds,
) -> None:
    """Show one round of the issue's newest assignment, until that round ends.

    One named round is all this shows, so it ends when that round has, rather
    than stay open for the round after it.

    The round list of the assignment view is where a reader finds the number, so
    a number no round of the assignment carries is the reader's mistake, and is
    the one thing this turns into words for them.
    """
    view = _FeedView(console=console)

    def look() -> bool:
        """Show what the round said since the last look, and say if it has ended."""
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
        view.show_what_arrived(assignment=assignment, records=[record])
        return record.ending is not None

    _keep_looking(console=console, look=look, wait=wait)


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
    statuses = read_agent_assignment_statuses_for_issue(
        state=state,
        issue=issue,
        clock=clock,
    )
    if not statuses:
        raise ReportableError(f"No assignment here for GH{issue}.")
    return statuses


@dataclass(frozen=True, kw_only=True)
class _FeedView:
    """An assignment's feed on a console, and how far each round of it has been read.

    A feed only grows, so a later look at one reads each round on from where
    the last look stopped and shows what arrived. The rounds a position is held
    for are the rounds already shown, so a round that has started since the
    last look is the one that opens with its own heading.
    """

    console: Console
    positions: dict[int, int] = field(default_factory=dict)

    def show_what_arrived(
        self, *, assignment: AgentAssignment, records: Iterable[AgentRoundRecord]
    ) -> None:
        """Show what these rounds of the assignment have said since the last look."""
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
        heading = compose_agent_round_boundary(
            number=record.number,
            purpose=record.purpose,
            is_recovery=record.is_recovery,
            at=record.started,
        )
        self.console.print(_paint(line=heading, said=Text(heading.text, style="bold")))
        self.positions[record.number] = 0

    def _show_new_lines(
        self, *, assignment: AgentAssignment, round_number: int
    ) -> None:
        """Show the lines this round has written since the last look at it."""
        feed = assignment.round_paths(number=round_number).feed
        lines, position = read_lines_from(
            path=feed, position=self.positions[round_number]
        )
        for line in lines:
            self.console.print(_paint_written(written=line))
        self.positions[round_number] = position


def _paint_written(*, written: str) -> Text:
    """Return one line of a feed as it reads on a console.

    A line the reader cannot parse reaches the reader as it was written, since
    showing what the feed holds is the whole point of showing it.
    """
    line = read_feed_line(written=written)
    if line is None:
        return Text(written)
    said = Text(line.text)
    said.highlight_regex(LABEL, "cyan")
    return _paint(line=line, said=said)


def _paint(*, line: FeedLine, said: Text) -> Text:
    """Return the line with its stamp set back, so the words stand out."""
    return Text.assemble((describe_time(at=line.at), "dim"), FEED_TIMESTAMP_GAP, said)
