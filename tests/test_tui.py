"""Render status, assignment, and feed views, and read back the goldens.

The goldens are the review surface: read one as the person running the view
would read it, and judge the view by it rather than by the code that wrote it.

Each state directory here is fabricated, so the clock, the console's width and
the daemon's pid are all pinned and every run and every platform renders the
same text.
"""

from datetime import timedelta
from io import StringIO

import pytest
from clocks import DISPLAY_TIME_ZONE, PINNED
from conftest import FIXTURES, assert_matches_view_golden
from records import write_feed, write_round
from rich.console import Console
from rich.control import Control
from rich.text import Text
from status_fabrications import (
    ASSIGNMENT_TIMESTAMP,
    LOOKED_AT,
    SAID,
    STATUS_REPORTS,
    ended,
    fabricate_a_dead_daemon,
    fabricate_a_silent_round,
    fabricate_everything,
    fabricate_nothing,
    fabricate_repeat_assignments,
    fabricate_status_everything,
    holding,
    running,
    written,
)

from dreamcatcher.agent_rounds import (
    AgentAssignmentRoundPurpose,
)
from dreamcatcher.documents import append_text, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory
from dreamcatcher.tui import (
    VIEW_REFRESH_INTERVAL,
    FeedSelection,
    ViewTiming,
    _render_feed_line,
    _render_written_feed_line,
    show_assignment_view,
    show_feed_view,
    show_status_view,
)

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


def create_view_timing(*, wait=refusing) -> ViewTiming:
    """Return timing that pins displayed time and refuses an unexpected wait."""
    return ViewTiming(
        clock=lambda: LOOKED_AT,
        wait=wait,
        zone=DISPLAY_TIME_ZONE,
    )


def render_status_view(*, state, width: int = WIDTH) -> str:
    """Return the status report that the state renders on a pinned console.

    Nobody is watching a console that is no terminal, so the report is drawn
    once and the view returns.
    """
    written_to = StringIO()
    show_status_view(
        state=state,
        console=pinned(written_to=written_to, width=width),
        timing=create_view_timing(),
    )
    return written_to.getvalue()


@pytest.mark.parametrize("name", sorted(STATUS_REPORTS))
def test_a_state_directory_renders_as_its_golden_status(
    name, tmp_path, daemon, pytestconfig
):
    state = StateDirectory(root=tmp_path)
    STATUS_REPORTS[name](state=state)

    status = render_status_view(state=state)

    assert_matches_view_golden(
        rendered=status,
        path=FIXTURES / "status" / f"{name}.txt",
        config=pytestconfig,
    )


def test_next_update_is_left_out_when_no_daemon_is_running(tmp_path):
    state = StateDirectory(root=tmp_path)
    STATUS_REPORTS["nothing"](state=state)

    status = render_status_view(state=state)

    assert "next update in" not in status


def test_identifiers_remain_whole_when_the_assignment_table_folds(tmp_path):
    """Keep the active assignment identifier whole when the table folds."""
    state = StateDirectory(root=tmp_path)
    fabricate_repeat_assignments(state=state)

    status = render_status_view(state=state, width=55)

    compact = "".join(status.split())
    assert "GH13-20260819-184158" in compact
    assert "2completedassignments" in compact


def test_assignments_are_rendered_in_attention_order(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    rendered = render_status_view(state=state)

    identifiers = [
        "GH20-20260819-184158",
        "GH9-20260819-184158",
        "GH13-20260819-184158",
        "GH31-20260819-184158",
        "GH35-20260819-184158",
        "GH44-20260819-184158",
        "GH40-20260819-184158",
    ]
    assert [rendered.index(identifier) for identifier in identifiers] == sorted(
        rendered.index(identifier) for identifier in identifiers
    )
    assert "1 completed assignment" in rendered


@pytest.mark.parametrize("width", [60, 80])
def test_status_output_fits_one_line_without_hiding_later_assignments(
    width, tmp_path, daemon
):
    state = StateDirectory(root=tmp_path)
    fabricate_status_everything(state=state)

    rendered = render_status_view(state=state, width=width)
    output = [line for line in rendered.splitlines() if "agent is explaining" in line]

    assert len(output) == 1
    assert len(output[0]) <= width
    assert f"GH31-{ASSIGNMENT_TIMESTAMP}" in rendered


def test_completed_assignments_are_summarized(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_repeat_assignments(state=state)

    rendered = render_status_view(state=state)

    assert "2 completed assignments" in rendered
    assert "GH13-20260818-090000" not in rendered
    assert "GH13-20260817-090000" not in rendered


def test_only_completed_assignments_are_summarized(tmp_path):
    state = StateDirectory(root=tmp_path)
    completed_round = ended(minute=1, purpose=AgentAssignmentRoundPurpose.WRAP_UP)
    written(state=state, issue=12, records=[completed_round])
    written(state=state, issue=13, records=[completed_round])

    rendered = render_status_view(state=state)

    assert "2 completed assignments" in rendered
    assert "GH12-20260819-184158" not in rendered
    assert "GH13-20260819-184158" not in rendered


def test_status_nobody_is_watching_is_drawn_once_and_returns(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()

    show_status_view(
        state=state,
        console=pinned(written_to=written_to),
        timing=create_view_timing(),
    )

    assert "running dreamcatcher v3.0.0.beta1 as pid 4242" in written_to.getvalue()


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
        timing=create_view_timing(wait=wait),
    )
    status = written_to.getvalue()

    # Status is never over, so it drew again when the assignment started
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
        timing=create_view_timing(wait=interrupting),
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
        timing=create_view_timing(),
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
        timing=create_view_timing(),
    )
    return written_to.getvalue()


def test_assignment_latest_output_is_indented_on_one_line(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    holding(state=state)
    directory = written(
        state=state,
        issue=13,
        records=[running(minute=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)],
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
    output = [line for line in view.splitlines() if "agent is explaining" in line]

    assert len(output) == 1
    assert output[0].startswith("  ")
    assert not output[0].startswith("   ")
    assert len(output[0]) <= 40
    assert output[0].endswith("…")


def test_assignment_status_alone_is_coloured_and_latest_output_is_dim(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()
    console = Console(
        file=written_to,
        width=WIDTH,
        height=HEIGHT,
        force_terminal=False,
        color_system="standard",
        legacy_windows=False,
        _environ={"TERM": "xterm"},
        record=True,
    )

    show_assignment_view(
        state=state,
        issue=13,
        console=console,
        timing=create_view_timing(),
    )
    rendered = console.export_text(styles=True)

    assert (
        "\x1b[32mworking\x1b[0m  round 2, address feedback (recovery), running"
        in rendered
    )
    assert "\x1b[2m[Bash] pytest\x1b[0m" in rendered


@pytest.mark.parametrize("name", sorted(ASSIGNMENTS))
def test_an_assignment_renders_as_its_golden_view(name, tmp_path, daemon, pytestconfig):
    state = StateDirectory(root=tmp_path)
    fabricate, issue = ASSIGNMENTS[name]
    fabricate(state=state)

    view = viewed(state=state, issue=issue)

    assert_matches_view_golden(
        rendered=view,
        path=FIXTURES / "assignment" / f"{name}.txt",
        config=pytestconfig,
    )


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
                minute=60,
                number=2,
                purpose=AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK,
            ),
        )

    show_assignment_view(
        state=state,
        issue=20,
        console=pinned(written_to=written_to, is_terminal=True),
        timing=create_view_timing(wait=wait),
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
        timing=create_view_timing(),
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
        timing=create_view_timing(),
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
        selection=FeedSelection(issue=issue, owner_kind=AgentWorkKind.ASSIGNMENT),
        console=pinned(written_to=written_to, is_terminal=True),
        timing=create_view_timing(wait=wait),
    )
    return written_to.getvalue()


def test_a_feed_nobody_is_watching_shows_what_is_there_and_returns(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written_to = StringIO()

    # A console that is no terminal is a pipe, a redirect or a log, and a view
    # that followed for as long as this assignment runs could be none of those.
    show_feed_view(
        state=state,
        selection=FeedSelection(issue=13, owner_kind=AgentWorkKind.ASSIGNMENT),
        console=pinned(written_to=written_to),
        timing=create_view_timing(),
    )

    assert "[Bash] pytest" in written_to.getvalue()


@pytest.mark.parametrize("name", sorted(FEEDS))
def test_a_feed_renders_as_its_golden_view(name, tmp_path, daemon, pytestconfig):
    state = StateDirectory(root=tmp_path)
    fabricate, issue = FEEDS[name]
    fabricate(state=state)

    feed = followed(state=state, issue=issue, wait=interrupting)

    assert_matches_view_golden(
        rendered=feed,
        path=FIXTURES / "feed" / f"{name}.txt",
        config=pytestconfig,
    )


def test_only_a_feed_lines_stamp_is_dim():
    console = Console(color_system="standard")
    action = _render_written_feed_line(
        written_line=SAID[2].render(), zone=DISPLAY_TIME_ZONE
    )
    label = action.plain.index("[")
    detail = action.plain.index("specs")
    boundary = _render_feed_line(
        line=SAID[1],
        content=Text(SAID[1].text, style="bold"),
        zone=DISPLAY_TIME_ZONE,
    )
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
            record=ended(
                minute=30, number=2, purpose=AgentAssignmentRoundPurpose.WRAP_UP
            ),
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
                minute=60,
                number=2,
                purpose=AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK,
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
        selection=FeedSelection(issue=issue, owner_kind=AgentWorkKind.ASSIGNMENT),
        console=pinned(written_to=written_to, is_terminal=is_terminal),
        round_number=number,
        timing=create_view_timing(wait=wait),
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
        "2026-08-20 03:11:58  round 2: address feedback (recovery)\n"
        "2026-08-20 03:12:58  [Bash] pytest\n"
    )


def test_a_round_that_wrote_no_feed_shows_the_line_that_opens_it(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    assert (
        viewed_round(state=state, issue=12, number=1)
        == "2026-08-20 02:42:58  round 1: implement\n"
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
