"""Render status, assignment, and feed views, and read back the goldens.

The goldens are the review surface: read one as the person running the view
would read it, and judge the view by it rather than by the code that wrote it.

Each state directory here is fabricated, so the clock, the console's width and
the daemon's pid are all pinned and every run and every platform renders the
same text.
"""

from collections.abc import Sequence
from datetime import timedelta
from io import StringIO

import psutil
import pytest
from clocks import PINNED
from conftest import DISPATCH_LABEL, FIXTURES, REPOSITORY, configure
from observations import observed_issue
from records import write_agent_assignment, write_feed, write_round, write_tick
from rich.console import Console
from rich.control import Control
from rich.text import Text

from dreamcatcher.agent_rounds import (
    AgentRoundPurpose,
    AgentRoundRecord,
    compose_agent_round_ending,
)
from dreamcatcher.documents import append_text, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.scheduler import (
    NO_ROUND_HAS_RUN,
    AgentAssignmentObservation,
    IssueFactValue,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.tui import (
    VIEW_REFRESH_INTERVAL,
    _render_feed_line,
    _render_written_feed_line,
    show_assignment_view,
    show_feed_view,
    show_status_view,
)

# When a view is rendered: two hours after the last thing on the disk happened.
LOOKED_AT = PINNED + timedelta(hours=2)

# How wide the console is, so a line wraps in the same place every run.
WIDTH = 100

# How tall the console is, so a picture is cut in the same place every run. A
# view on the alternate screen fills the screen and cuts what does not fit, and
# no picture a test here draws is this tall.
HEIGHT = 40

# What a view writes to take the terminal's alternate screen, and what it
# writes to hand it back. Rich owns both codes, so they are read from rich
# rather than spelled out again here.
SCREEN_TAKEN = Control.alt_screen(True).segment.text
SCREEN_HANDED_BACK = Control.alt_screen(False).segment.text

# The pid the fabricated lock names, and the one the stand-in psutil says is
# alive. A real pid would differ from run to run and no golden could hold it.
DAEMON_PID = 4242

ASSIGNMENT_TIMESTAMP = "20260819-184158"
HARNESS_SESSION_IDENTIFIER = "abc-123"

# What one round of an assignment said, as its feed holds it. A subagent's lines
# are set in from the rest, and a line that is not a feed line at all is what a
# harness printed on its stderr.
SAID = (
    FeedLine(
        at=PINNED + timedelta(minutes=1),
        text="[harness session] model opus[1m], id 7f3c9a",
    ),
    FeedLine(at=PINNED + timedelta(minutes=2), text="I will read the issue first."),
    FeedLine(
        at=PINNED + timedelta(minutes=2),
        text="[Read] specs/2026-08-17-skeleton/plan.md",
    ),
    FeedLine(at=PINNED + timedelta(minutes=3), text="  [Bash] ls"),
    FeedLine(
        at=PINNED + timedelta(minutes=3), text="[failed] no such file or directory"
    ),
    FeedLine(
        at=PINNED + timedelta(minutes=5),
        text=(
            "[usage] $0.1772, 455 output, 8 input, 123529 cache read, 8606 cache write"
        ),
    ),
    FeedLine(at=PINNED + timedelta(minutes=5), text="[result] success"),
)

# What a tick writes down against an issue carrying two dispatch labels.
DOUBLE_LABELLED = "carries more than one dispatch label: dream:less, dream:smith"


@pytest.fixture
def daemon(monkeypatch):
    """Answer that the fabricated daemon, and nothing else, is still running."""
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == DAEMON_PID)


def written(*, state, issue: int, records: Sequence[AgentRoundRecord]):
    """Write an assignment for the issue, with these rounds behind it."""
    directory = write_agent_assignment(
        state=state,
        identifier=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}",
        issue=issue,
        harness_session_identifier=(HARNESS_SESSION_IDENTIFIER if records else None),
    )
    for number, record in enumerate(records, start=1):
        write_round(directory=directory, number=number, record=record)
    return directory


def ended(
    *,
    minute: int,
    number: int = 1,
    status: int = 0,
    purpose: AgentRoundPurpose = AgentRoundPurpose.IMPLEMENT,
):
    """A round that started that minute past the pinned hour and ran for four."""
    started = PINNED + timedelta(minutes=minute)
    return AgentRoundRecord(
        number=number,
        started=started,
        pid=1,
        purpose=purpose,
        ending=compose_agent_round_ending(
            at=started + timedelta(minutes=4), status=status
        ),
    )


def running(
    *,
    minute: int,
    number: int = 1,
    purpose: AgentRoundPurpose = AgentRoundPurpose.IMPLEMENT,
    is_recovery: bool = False,
):
    """A round that started that minute past the pinned hour and is still going."""
    return AgentRoundRecord(
        number=number,
        started=PINNED + timedelta(minutes=minute),
        pid=1,
        purpose=purpose,
        is_recovery=is_recovery,
    )


def holding(*, state):
    """Configure the instance and write the lock that its daemon holds."""
    configure(root=state.root)
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_text(text="1\n", path=state.max_agents)
    write_text(text=f"{DAEMON_PID}\n", path=state.lock)


def fabricate_nothing(*, state):
    """A state directory a daemon has bootstrapped and nothing else."""
    configure(root=state.root)
    state.bootstrap()
    write_text(text="1\n", path=state.max_agents)


def fabricate_everything(*, state):
    """A running daemon with varied issue and agent-assignment statuses."""
    holding(state=state)
    directory = written(
        state=state,
        issue=13,
        records=[
            ended(minute=1),
            running(
                minute=30,
                number=2,
                purpose=AgentRoundPurpose.ADDRESS_FEEDBACK,
                is_recovery=True,
            ),
        ],
    )
    write_feed(directory=directory, number=1, lines=SAID)
    write_feed(
        directory=directory,
        number=2,
        lines=[FeedLine(at=PINNED + timedelta(minutes=31), text="[Bash] pytest")],
    )
    write_feed(
        directory=written(state=state, issue=20, records=[ended(minute=1)]),
        number=1,
        lines=[FeedLine(at=PINNED, text="[Bash] git push")],
    )
    written(state=state, issue=31, records=[ended(minute=1)])
    written(state=state, issue=35, records=[ended(minute=1, status=2)])
    written(
        state=state,
        issue=9,
        records=[ended(minute=1, status=1), ended(minute=2, number=2, status=2)],
    )
    written(
        state=state,
        issue=12,
        records=[
            ended(minute=1),
            ended(minute=2, number=2, purpose=AgentRoundPurpose.WRAP_UP),
        ],
    )
    written(state=state, issue=44, records=[])
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            launched_assignment_identifier=f"GH13-{ASSIGNMENT_TIMESTAMP}",
            issue_observations=[
                observed_issue(issue=50),
                observed_issue(issue=51),
                observed_issue(
                    issue=52,
                    values={"blocked": IssueFactValue.TRUE},
                    evidence={"blocked": "blocked by GH50"},
                ),
                observed_issue(
                    issue=53,
                    dispatch_labels=(DISPATCH_LABEL, "dream:less"),
                    values={"routing_conflict": IssueFactValue.TRUE},
                    evidence={"routing_conflict": DOUBLE_LABELLED},
                ),
            ],
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment_identifier=f"GH31-{ASSIGNMENT_TIMESTAMP}",
                    issue=31,
                    reason="1 new post to answer",
                ),
                AgentAssignmentObservation(
                    assignment_identifier=f"GH20-{ASSIGNMENT_TIMESTAMP}",
                    issue=20,
                    reason="no round required",
                    is_round_required=False,
                ),
                AgentAssignmentObservation(
                    assignment_identifier=f"GH35-{ASSIGNMENT_TIMESTAMP}",
                    issue=35,
                    reason="the last round failed (exit 2)",
                ),
                AgentAssignmentObservation(
                    assignment_identifier=f"GH9-{ASSIGNMENT_TIMESTAMP}",
                    issue=9,
                    reason="two consecutive rounds failed",
                ),
                AgentAssignmentObservation(
                    assignment_identifier=f"GH44-{ASSIGNMENT_TIMESTAMP}",
                    issue=44,
                    reason=NO_ROUND_HAS_RUN,
                ),
            ],
        ),
    )


def fabricate_a_failed_setup(*, state):
    """A running daemon with an assignment, a failed setup, and available work."""
    holding(state=state)
    written(state=state, issue=13, records=[])
    failure = "assignment setup failed"
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            issue_observations=[
                observed_issue(
                    issue=20,
                    values={"claimed_elsewhere": IssueFactValue.UNKNOWN},
                    evidence={"claimed_elsewhere": failure},
                ).model_copy(update={"setup_failure": failure}),
                observed_issue(issue=21),
            ],
        ),
    )


def fabricate_a_dead_daemon(*, state):
    """The same assignments, with the daemon that was running them gone."""
    fabricate_everything(state=state)
    state.lock.unlink()


def fabricate_the_cap(*, state):
    """A daemon at its cap, which holds every assignment."""
    holding(state=state)
    directory = written(state=state, issue=13, records=[running(minute=30)])
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED + timedelta(minutes=31), text="[Bash] pytest")],
    )
    written(state=state, issue=20, records=[ended(minute=1)])
    hold = "at cap: 1 of 1 rounds running"
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            hold=hold,
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment_identifier=f"GH20-{ASSIGNMENT_TIMESTAMP}",
                    issue=20,
                    reason=hold,
                )
            ],
        ),
    )


def fabricate_repeat_assignments(*, state):
    """Three assignments at one issue, so a repeat dispatch reads as one thing."""
    configure(root=state.root)
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_text(text="1\n", path=state.max_agents)
    for stamp, rounds in (
        (
            "20260817-090000",
            (
                ended(minute=1),
                ended(minute=2, number=2, purpose=AgentRoundPurpose.WRAP_UP),
            ),
        ),
        (
            "20260818-090000",
            (
                ended(minute=1),
                ended(minute=2, number=2, purpose=AgentRoundPurpose.WRAP_UP),
            ),
        ),
        ("20260819-184158", (ended(minute=1),)),
    ):
        directory = write_agent_assignment(
            state=state, identifier=f"GH13-{stamp}", issue=13
        )
        for number, record in enumerate(rounds, start=1):
            write_round(directory=directory, number=number, record=record)
        write_feed(
            directory=directory,
            number=len(rounds),
            lines=[
                FeedLine(
                    at=PINNED + timedelta(minutes=len(rounds) + 1),
                    text="[Bash] git push",
                )
            ],
        )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment_identifier=f"GH13-{ASSIGNMENT_TIMESTAMP}",
                    issue=13,
                    reason="no round required",
                    is_round_required=False,
                )
            ],
        ),
    )


def fabricate_a_silent_round(*, state):
    """A daemon running a round that has yet to write a line of its own.

    The row opens with the round that is running, so what follows says only
    that the round has said nothing.
    """
    holding(state=state)
    directory = written(
        state=state,
        issue=13,
        records=[
            ended(minute=1),
            running(minute=30, number=2, purpose=AgentRoundPurpose.ADDRESS_FEEDBACK),
        ],
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="[Bash] git push")],
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            launched_assignment_identifier=f"GH13-{ASSIGNMENT_TIMESTAMP}",
        ),
    )


STATUS_REPORTS = {
    "nothing": fabricate_nothing,
    "everything": fabricate_everything,
    "failed-setup": fabricate_a_failed_setup,
    "dead-daemon": fabricate_a_dead_daemon,
    "at-cap": fabricate_the_cap,
    "silent-round": fabricate_a_silent_round,
    "repeat-assignments": fabricate_repeat_assignments,
}


# The feed view each fabricated state directory is worth reading, by the issue
# whose newest assignment it shows.
FEEDS = {
    "working": (fabricate_everything, 13),
    "older-assignments": (fabricate_repeat_assignments, 13),
}


# The assignment view each fabricated state directory is worth reading, by the
# issue whose newest assignment it shows.
ASSIGNMENTS = {
    "working": (fabricate_everything, 13),
    "silent-round": (fabricate_a_silent_round, 13),
    "older-assignments": (fabricate_repeat_assignments, 13),
    "fault": (fabricate_everything, 9),
    "waiting-to-start": (fabricate_everything, 44),
}


def pinned(
    *, written_to, width: int = WIDTH, is_terminal: bool = False, term: str = "xterm"
) -> Console:
    """Return a console that renders the same text wherever it runs.

    Every setting rich would otherwise take from the shell or the platform is
    named here. An environment of its own is what pins the shell's share of
    them, since a shell exporting FORCE_COLOR would make it write escape
    codes, one exporting LINES would say how tall the screen a view fills is,
    and one exporting TERM as dumb would stop it writing a control code at
    all. A legacy Windows console would take a column off its width, and
    saying it has no colour system pins the colour, so a console that says it
    is a terminal, which is what makes a view follow, still writes plain text.

    Naming the terminal is how a test asks for the dumb one, which is a
    terminal a reader watches and rich can draw no picture into.
    """
    return Console(
        file=written_to,
        width=width,
        height=HEIGHT,
        force_terminal=is_terminal,
        color_system=None,
        legacy_windows=False,
        _environ={"TERM": term},
    )


def interrupting(seconds, /):
    """A wait the reader interrupts, which is how a view of a live assignment ends."""
    raise KeyboardInterrupt


def refusing(seconds, /):
    """A wait that a view with nothing more to show must never reach.

    A view that reaches it has gone on looking, and a wait that let it would
    let it look for ever, so the test would hang rather than fail.
    """
    raise AssertionError("the view waited for something that was not coming")


def render_status_view(*, state, width: int = WIDTH) -> str:
    """Return the status report that the state renders on a pinned console.

    Nobody is watching a console that is no terminal, so the report is drawn
    once and the view returns.
    """
    written_to = StringIO()
    show_status_view(
        state=state,
        console=pinned(written_to=written_to, width=width),
        clock=lambda: LOOKED_AT,
        wait=refusing,
    )
    return written_to.getvalue()


@pytest.mark.parametrize("name", sorted(STATUS_REPORTS))
def test_a_state_directory_renders_as_its_golden_status(name, tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    STATUS_REPORTS[name](state=state)

    status = render_status_view(state=state)

    assert status == (FIXTURES / "status" / f"{name}.txt").read_text(encoding="utf-8")


def test_identifiers_remain_whole_when_the_assignment_table_folds(tmp_path):
    """Two assignments at one issue differ only in their identifier times."""
    state = StateDirectory(root=tmp_path)
    fabricate_repeat_assignments(state=state)

    status = render_status_view(state=state, width=55)

    compact = "".join(status.split())
    assert "GH13-20260818-090000" in compact
    assert "GH13-20260817-090000" in compact


def test_status_nobody_is_watching_is_drawn_once_and_returns(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()

    show_status_view(
        state=state,
        console=pinned(written_to=written_to),
        clock=lambda: LOOKED_AT,
        wait=refusing,
    )

    assert "running as pid 4242" in written_to.getvalue()


def test_status_a_reader_watches_keeps_up_with_what_the_daemon_writes(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_nothing(state=state)
    written_to = StringIO()
    looks = []

    def wait(seconds, /):
        looks.append(seconds)
        if len(looks) > 1:
            raise KeyboardInterrupt
        holding(state=state)
        directory = written(state=state, issue=13, records=[running(minute=30)])
        write_feed(
            directory=directory,
            number=1,
            lines=[FeedLine(at=PINNED + timedelta(minutes=31), text="[Bash] pytest")],
        )

    show_status_view(
        state=state,
        console=pinned(written_to=written_to, is_terminal=True),
        clock=lambda: LOOKED_AT,
        wait=wait,
    )
    status = written_to.getvalue()

    # Status is never over, so it drew again on the assignment that was dispatched
    # while the reader was watching, and ended only when they interrupted it.
    assert looks == [VIEW_REFRESH_INTERVAL, VIEW_REFRESH_INTERVAL]
    assert "no issues or agent assignments recorded yet" in status
    assert f"GH13-{ASSIGNMENT_TIMESTAMP}" in status


def test_status_a_reader_watches_takes_the_screen_and_hands_it_back(tmp_path, daemon):
    """The reader gets the terminal back as it was, and their scrollback with it."""
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()

    show_status_view(
        state=state,
        console=pinned(written_to=written_to, is_terminal=True),
        clock=lambda: LOOKED_AT,
        wait=interrupting,
    )
    status = written_to.getvalue()

    # The screen was taken before anything was drawn into it, so nothing the
    # shell had printed was ever drawn over, and handing it back was the last
    # thing the view did, so status that the reader has seen enough of leaves
    # nothing behind.
    assert status.index(SCREEN_TAKEN) < status.index("daemon")
    assert status.endswith(SCREEN_HANDED_BACK)


def test_status_on_a_dumb_terminal_is_drawn_once_and_returns(tmp_path, daemon):
    """A dumb terminal takes no control code, so rich draws no picture into one."""
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()

    show_status_view(
        state=state,
        console=pinned(written_to=written_to, is_terminal=True, term="dumb"),
        clock=lambda: LOOKED_AT,
        wait=refusing,
    )
    status = written_to.getvalue()

    # Nothing was drawn over anything, so the reader reads the report itself
    # rather than the nothing that rich writes into a screen it cannot take.
    assert "daemon" in status
    assert SCREEN_TAKEN not in status


def viewed(*, state, issue: int, width: int = WIDTH) -> str:
    """Return the assignment view that issue renders as, on a pinned console."""
    written_to = StringIO()
    show_assignment_view(
        state=state,
        issue=issue,
        console=pinned(written_to=written_to, width=width),
        clock=lambda: LOOKED_AT,
        wait=refusing,
    )
    return written_to.getvalue()


def test_wrapped_latest_output_keeps_its_indent(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    holding(state=state)
    directory = written(
        state=state,
        issue=13,
        records=[running(minute=1, purpose=AgentRoundPurpose.IMPLEMENT)],
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[
            FeedLine(
                at=PINNED,
                text="The agent is explaining a long change that needs to wrap onto "
                "another line.",
            )
        ],
    )

    view = viewed(state=state, issue=13, width=40)
    output = [
        line
        for line in view.splitlines()
        if "agent is explaining" in line or "that needs to wrap" in line
    ]

    assert [line.strip() for line in output] == [
        "The agent is explaining a long change",
        "that needs to wrap onto another line.",
    ]
    assert all(line.startswith("  ") and not line.startswith("   ") for line in output)


@pytest.mark.parametrize("name", sorted(ASSIGNMENTS))
def test_an_assignment_renders_as_its_golden_view(name, tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate, issue = ASSIGNMENTS[name]
    fabricate(state=state)

    view = viewed(state=state, issue=issue)

    assert view == (FIXTURES / "assignment" / f"{name}.txt").read_text(encoding="utf-8")


def test_an_assignment_view_shows_the_round_that_starts_while_it_is_open(
    tmp_path, daemon
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()
    looks = []

    def wait(seconds, /):
        looks.append(seconds)
        if len(looks) > 1:
            raise KeyboardInterrupt
        write_round(
            directory=state.assignments / f"GH20-{ASSIGNMENT_TIMESTAMP}",
            number=2,
            record=running(
                minute=60, number=2, purpose=AgentRoundPurpose.ADDRESS_FEEDBACK
            ),
        )

    show_assignment_view(
        state=state,
        issue=20,
        console=pinned(written_to=written_to, is_terminal=True),
        clock=lambda: LOOKED_AT,
        wait=wait,
    )

    # The round GH20 had run was over and its pull request was waiting for the
    # reader, so the view stayed open through the gap and drew the round that
    # answered what they posted.
    assert looks == [VIEW_REFRESH_INTERVAL, VIEW_REFRESH_INTERVAL]
    assert "address feedback" in written_to.getvalue()


@pytest.mark.parametrize("issue", [12, 9])
def test_an_assignment_view_of_an_assignment_that_is_over_never_waits(
    issue, tmp_path, daemon
):
    """GH12 completed its wrap-up, and GH9 is in fault, so neither has one coming."""
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()

    show_assignment_view(
        state=state,
        issue=issue,
        console=pinned(written_to=written_to, is_terminal=True),
        clock=lambda: LOOKED_AT,
        wait=refusing,
    )

    assert f"GH{issue}-{ASSIGNMENT_TIMESTAMP}" in written_to.getvalue()


def test_an_assignment_view_of_an_assignment_that_is_over_keeps_its_last_picture(
    tmp_path, daemon
):
    """GH12 completed its wrap-up, so the view ends and its picture stays."""
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()

    show_assignment_view(
        state=state,
        issue=12,
        console=pinned(written_to=written_to, is_terminal=True),
        clock=lambda: LOOKED_AT,
        wait=refusing,
    )
    kept = written_to.getvalue().split(SCREEN_HANDED_BACK)[-1]

    # Handing the screen back took the picture the view ended on with it, so
    # the view printed that picture where a reader looking the assignment up
    # reads it.
    assert f"GH12-{ASSIGNMENT_TIMESTAMP}" in kept


def followed(*, state, issue: int, wait=refusing) -> str:
    """Return the feed view that issue renders as, on a console being watched."""
    written_to = StringIO()
    show_feed_view(
        state=state,
        issue=issue,
        console=pinned(written_to=written_to, is_terminal=True),
        wait=wait,
    )
    return written_to.getvalue()


def test_a_feed_nobody_is_watching_shows_what_is_there_and_returns(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()

    # A console that is no terminal is a pipe, a redirect or a log, and a view
    # that followed for as long as this assignment runs could be none of those.
    show_feed_view(
        state=state, issue=13, console=pinned(written_to=written_to), wait=refusing
    )

    assert "[Bash] pytest" in written_to.getvalue()


@pytest.mark.parametrize("name", sorted(FEEDS))
def test_a_feed_renders_as_its_golden_view(name, tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate, issue = FEEDS[name]
    fabricate(state=state)

    feed = followed(state=state, issue=issue, wait=interrupting)

    assert feed == (FIXTURES / "feed" / f"{name}.txt").read_text(encoding="utf-8")


def test_only_a_feed_lines_stamp_is_dim():
    console = Console(color_system="standard")
    action = _render_written_feed_line(written_line=SAID[2].render())
    label = action.plain.index("[")
    detail = action.plain.index("specs")
    boundary = _render_feed_line(line=SAID[1], content=Text(SAID[1].text, style="bold"))
    boundary_text = boundary.plain.index(SAID[1].text)
    label_colour = action.get_style_at_offset(console, label).color

    assert action.get_style_at_offset(console, 0).dim
    assert not action.get_style_at_offset(console, label - 1).dim
    assert label_colour is not None
    assert label_colour.name == "cyan"
    assert not action.get_style_at_offset(console, detail).dim
    assert boundary.get_style_at_offset(console, boundary_text).bold
    assert not boundary.get_style_at_offset(console, boundary_text).dim


def test_a_following_view_waits_for_the_round_an_assignment_has_yet_to_run(
    tmp_path, daemon
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    waits = []

    def wait(seconds, /):
        waits.append(seconds)
        raise KeyboardInterrupt

    followed(state=state, issue=20, wait=wait)

    # The assignment's pull request is waiting for the reader, so the round that
    # answers them is still to come and the view waits for it rather than
    # ending between the rounds.
    assert waits == [VIEW_REFRESH_INTERVAL]


def test_a_following_view_looks_once_more_when_the_last_round_stops(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    directory = state.assignments / f"GH13-{ASSIGNMENT_TIMESTAMP}"
    waits = []

    def wait(seconds, /):
        waits.append(seconds)
        write_round(
            directory=directory,
            number=2,
            record=ended(minute=30, number=2, purpose=AgentRoundPurpose.WRAP_UP),
        )

    followed(state=state, issue=13, wait=wait)

    # The wrap-up round ended while the view was waiting, so the view looked once
    # more for whatever that round was still writing as it stopped.
    assert waits == [VIEW_REFRESH_INTERVAL, VIEW_REFRESH_INTERVAL]


def test_a_round_that_starts_while_the_view_is_going_arrives_in_it(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    directory = state.assignments / f"GH20-{ASSIGNMENT_TIMESTAMP}"
    looks = []

    def wait(seconds, /):
        looks.append(seconds)
        if len(looks) > 1:
            raise KeyboardInterrupt
        write_round(
            directory=directory,
            number=2,
            record=running(
                minute=60, number=2, purpose=AgentRoundPurpose.ADDRESS_FEEDBACK
            ),
        )
        write_feed(
            directory=directory,
            number=2,
            lines=[
                FeedLine(at=PINNED + timedelta(minutes=61), text="[Bash] git commit")
            ],
        )

    feed = followed(state=state, issue=20, wait=wait)

    # The pull request was waiting for the reader when the view opened, and the
    # round that answers what they posted started while the view was going, so
    # the reader reads its feed while it is still running.
    assert "round 2: address feedback" in feed
    assert "[Bash] git commit" in feed
    assert feed.count("round 1: implement") == 1


def test_a_view_of_an_assignment_that_is_over_never_waits(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    assert "round 2: wrap up" in followed(state=state, issue=12)


def test_a_following_view_waits_for_the_next_daemon(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_a_dead_daemon(state=state)
    waits = []

    def wait(seconds, /):
        waits.append(seconds)
        raise KeyboardInterrupt

    followed(state=state, issue=13, wait=wait)

    # The daemon that was running the assignment has gone, and the next one
    # carries its round on from where it stopped, so the view waits for that
    # round rather than end with the daemon.
    assert waits == [VIEW_REFRESH_INTERVAL]


def test_a_view_of_a_faulted_assignment_never_waits(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    assert "round 2: implement" in followed(state=state, issue=9)


def test_a_following_view_reads_a_round_on_from_where_it_stopped(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    directory = state.assignments / f"GH13-{ASSIGNMENT_TIMESTAMP}"
    looks = []

    def wait(seconds, /):
        looks.append(seconds)
        if len(looks) > 1:
            raise KeyboardInterrupt
        # A feed only grows, so rewriting a line that the view has shown already
        # puts something there that only a second read of that line could
        # find. The rewritten line is as long as the one it replaces, so the
        # line after it starts where the view stopped reading.
        write_feed(
            directory=directory,
            number=1,
            lines=[
                FeedLine(
                    at=SAID[0].at,
                    text="[harness session] model opus[1m], id 000000",
                ),
                *SAID[1:],
                FeedLine(at=PINNED + timedelta(minutes=7), text="[Bash] git push"),
            ],
        )

    feed = followed(state=state, issue=13, wait=wait)

    assert "[Bash] git push" in feed
    assert "id 000000" not in feed


def test_a_write_that_never_landed_waits_for_the_look_that_shows_it_whole(
    tmp_path, daemon
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    feed = (
        state.assignments / f"GH13-{ASSIGNMENT_TIMESTAMP}" / "rounds" / "2" / "feed.txt"
    )
    looks = []

    def wait(seconds, /):
        looks.append(seconds)
        if len(looks) == 1:
            append_text(text="2026-08-19T19:13:58Z  [Grep] pypro", path=feed)
        elif len(looks) == 2:
            append_text(text="ject.toml\n", path=feed)
        else:
            raise KeyboardInterrupt

    shown = followed(state=state, issue=13, wait=wait)

    # The line was not shown while it was half written, and the look after the
    # rest of it landed showed the whole of it once.
    assert "[Grep] pypro\n" not in shown
    assert shown.count("[Grep] pyproject.toml") == 1


def test_a_line_the_view_cannot_read_reaches_the_reader_as_it_was_written(
    tmp_path, daemon
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    write_text(
        text="the harness said something else\n",
        path=state.assignments
        / f"GH13-{ASSIGNMENT_TIMESTAMP}"
        / "rounds"
        / "2"
        / "feed.txt",
    )

    feed = followed(state=state, issue=13, wait=interrupting)

    assert "the harness said something else" in feed


def test_a_reader_who_has_seen_enough_interrupts_the_view(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    assert "[Bash] pytest" in followed(state=state, issue=13, wait=interrupting)


def viewed_round(
    *,
    state,
    issue: int,
    number: int,
    wait=refusing,
    is_terminal: bool = False,
) -> str:
    """Return the view of one round of that issue, on a pinned console."""
    written_to = StringIO()
    show_feed_view(
        state=state,
        issue=issue,
        console=pinned(written_to=written_to, is_terminal=is_terminal),
        round_number=number,
        wait=wait,
    )
    return written_to.getvalue()


def test_a_round_view_uses_the_number_persisted_by_the_round(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    directory = state.assignments / f"GH12-{ASSIGNMENT_TIMESTAMP}"
    write_round(directory=directory, number=4, record=ended(minute=40, number=4))
    write_feed(
        directory=directory,
        number=4,
        lines=[FeedLine(at=PINNED + timedelta(minutes=41), text="[Bash] git status")],
    )

    shown = viewed_round(state=state, issue=12, number=4)

    assert "round 4: implement" in shown
    assert "[Bash] git status" in shown
    with pytest.raises(ReportableError, match="has no round 3"):
        viewed_round(state=state, issue=12, number=3)


def test_one_round_of_an_assignment_reads_on_its_own(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    assert viewed_round(state=state, issue=13, number=2) == (
        "2026-08-19T19:11:58Z  round 2: address feedback (recovery)\n"
        "2026-08-19T19:12:58Z  [Bash] pytest\n"
    )


def test_a_round_that_wrote_no_feed_shows_the_line_that_opens_it(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    assert (
        viewed_round(state=state, issue=12, number=1)
        == "2026-08-19T18:42:58Z  round 1: implement\n"
    )


def test_a_view_of_a_round_that_has_ended_never_waits(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    # Round 1 of this assignment ended, and one named round is all the view shows,
    # so it ends there rather than wait for what round 2 says next.
    shown = viewed_round(state=state, issue=13, number=1, is_terminal=True)

    assert "round 1: implement" in shown


def test_a_view_of_a_running_round_ends_when_that_round_does(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    directory = state.assignments / f"GH13-{ASSIGNMENT_TIMESTAMP}"
    looks = []

    def wait(seconds, /):
        looks.append(seconds)
        if len(looks) > 2:
            raise AssertionError("the view outlived the round it was showing")
        write_round(directory=directory, number=2, record=ended(minute=30, number=2))

    shown = viewed_round(state=state, issue=13, number=2, wait=wait, is_terminal=True)

    # The round ended while the view was waiting, so the view looked once more
    # for whatever that round was still writing as it stopped, and ended.
    assert looks == [VIEW_REFRESH_INTERVAL, VIEW_REFRESH_INTERVAL]
    assert "[Bash] pytest" in shown


def test_a_round_the_assignment_never_ran_says_how_many_it_did(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    with pytest.raises(ReportableError, match="has run 2 rounds"):
        viewed_round(state=state, issue=13, number=7)


def test_an_issue_no_assignment_here_has_says_so(tmp_path):
    with pytest.raises(ReportableError, match="GH99"):
        viewed(state=StateDirectory(root=tmp_path), issue=99)
