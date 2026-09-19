from datetime import UTC, datetime, timedelta, timezone
from pathlib import PurePosixPath, PureWindowsPath

import pytest
from clocks import PINNED, Ticking

from dreamcatcher.feed import (
    FEED_LINE_WIDTH,
    FeedLine,
    FeedNote,
    FeedProse,
    FeedRenderer,
    compose_agent_round_boundary,
    read_feed_line,
    read_last_feed_line,
)

WORKTREE = PurePosixPath("/checkout/worktree")


def feed() -> FeedRenderer:
    return FeedRenderer(worktree=WORKTREE, clock=Ticking())


def test_a_note_becomes_one_timestamped_line():
    assert feed().render(event=FeedNote(label="Bash", detail="pytest")) == (
        "2026-08-19T18:41:58Z  [Bash] pytest\n"
    )


def test_a_note_with_nothing_to_add_is_its_label_alone():
    assert (
        feed().render(event=FeedNote(label="thinking"))
        == "2026-08-19T18:41:58Z  [thinking]\n"
    )


def test_a_detail_loses_the_worktrees_own_path():
    assert feed().render(
        event=FeedNote(label="Edit", detail="/checkout/worktree/src/theme.css")
    ) == ("2026-08-19T18:41:58Z  [Edit] src/theme.css\n")


def test_a_path_outside_the_worktree_keeps_its_own_root():
    assert feed().render(event=FeedNote(label="Read", detail="/etc/hosts")) == (
        "2026-08-19T18:41:58Z  [Read] /etc/hosts\n"
    )


def test_a_sibling_of_the_worktree_that_starts_the_same_way_keeps_its_path():
    assert feed().render(
        event=FeedNote(label="Read", detail="/checkout/worktree-old/src/theme.css")
    ) == ("2026-08-19T18:41:58Z  [Read] /checkout/worktree-old/src/theme.css\n")


def test_a_detail_written_the_windows_way_loses_the_worktree_too():
    windows = FeedRenderer(
        worktree=PureWindowsPath("C:/checkout/worktree"), clock=Ticking()
    )

    assert windows.render(
        event=FeedNote(label="Edit", detail="C:\\checkout\\worktree\\src\\theme.css")
    ) == ("2026-08-19T18:41:58Z  [Edit] src\\theme.css\n")


def test_a_detail_spread_over_lines_becomes_one():
    assert feed().render(
        event=FeedNote(label="Bash", detail="git commit \\\n  --amend")
    ) == ("2026-08-19T18:41:58Z  [Bash] git commit \\ --amend\n")


def test_a_detail_longer_than_the_feed_is_clipped():
    assert feed().render(
        event=FeedNote(label="Write", detail="x" * (FEED_LINE_WIDTH + 10))
    ) == (f"2026-08-19T18:41:58Z  [Write] {'x' * FEED_LINE_WIDTH} ...\n")


def test_prose_becomes_a_line_for_each_line_it_holds():
    assert feed().render(event=FeedProse(text="I read the file.\n\nIt was empty.")) == (
        "2026-08-19T18:41:58Z  I read the file.\n2026-08-19T18:41:58Z  It was empty.\n"
    )


def test_prose_with_nothing_in_it_writes_nothing():
    assert feed().render(event=FeedProse(text="  \n\n")) == ""


def test_a_subagents_lines_are_indented_under_the_timestamp():
    rendered = feed()

    assert rendered.render(
        event=FeedNote(label="Bash", detail="ls", is_subagent=True)
    ) == ("2026-08-19T18:41:58Z    [Bash] ls\n")
    assert rendered.render(event=FeedProse(text="two files", is_subagent=True)) == (
        "2026-08-19T18:41:59Z    two files\n"
    )


@pytest.mark.parametrize(
    ("number", "purpose", "is_recovery", "description"),
    [
        (1, "implement", False, "implement"),
        (2, "implement", True, "implement (recovery)"),
        (2, "wrap up", False, "wrap up"),
        (2, "address feedback", False, "address feedback"),
    ],
)
def test_a_round_boundary_names_its_purpose_and_recovery_independently(
    number, purpose, is_recovery, description
):
    boundary = compose_agent_round_boundary(
        number=number,
        purpose=purpose,
        is_recovery=is_recovery,
        at=PINNED,
    )

    assert boundary.render() == (
        f"2026-08-19T18:41:58Z  round {number}: {description}\n"
    )


def test_a_written_line_reads_back_as_what_it_says_and_when():
    assert read_feed_line(written="2026-08-19T18:41:58Z  [Bash] pytest") == FeedLine(
        at=PINNED, text="[Bash] pytest"
    )


def test_a_subagents_line_reads_back_with_the_indent_that_sets_it_in():
    written = feed().render(
        event=FeedNote(label="Bash", detail="pytest", is_subagent=True)
    )

    assert read_feed_line(written=written.rstrip("\n")) == FeedLine(
        at=PINNED, text="  [Bash] pytest"
    )


def test_a_line_with_no_stamp_on_it_is_not_a_feed_line():
    assert read_feed_line(written="half a line") is None


def test_a_line_whose_stamp_is_not_a_time_is_not_a_feed_line():
    assert read_feed_line(written="the other day  [Bash] pytest") is None


def test_the_last_line_of_a_feed_is_what_the_feed_last_said(tmp_path):
    written = tmp_path / "feed.txt"
    written.write_bytes(
        b"2026-08-19T18:41:58Z  [Bash] pytest\n2026-08-19T18:42:58Z  [Read] pyproject\n"
    )

    assert read_last_feed_line(path=written) == FeedLine(
        at=PINNED + timedelta(minutes=1), text="[Read] pyproject"
    )


def test_a_write_that_never_landed_leaves_the_line_before_it_as_the_last(tmp_path):
    written = tmp_path / "feed.txt"
    # The write was cut off inside the line's own words, so what is there reads
    # as a whole line and is not one.
    written.write_bytes(
        b"2026-08-19T18:41:58Z  [Bash] pytest\n2026-08-19T18:42:58Z  [Read] pypro"
    )

    assert read_last_feed_line(path=written) == FeedLine(
        at=PINNED, text="[Bash] pytest"
    )


def test_a_feed_whose_last_line_is_not_one_has_nothing_to_say(tmp_path):
    written = tmp_path / "feed.txt"
    written.write_bytes(b"the harness said something else\n")

    assert read_last_feed_line(path=written) is None


def test_a_feed_holding_nothing_yet_has_no_last_line(tmp_path):
    written = tmp_path / "feed.txt"
    written.write_bytes(b"")

    assert read_last_feed_line(path=written) is None


def test_a_round_that_has_said_nothing_yet_has_no_last_line(tmp_path):
    assert read_last_feed_line(path=tmp_path / "feed.txt") is None


def test_a_clock_that_is_not_in_utc_still_stamps_utc():
    elsewhere = PINNED.astimezone(timezone(timedelta(hours=5)))

    assert FeedRenderer(worktree=WORKTREE, clock=lambda: elsewhere).render(
        event=FeedNote(label="result", detail="ok")
    ) == ("2026-08-19T18:41:58Z  [result] ok\n")


def test_the_clock_a_renderer_reads_by_default_is_the_time_now_in_utc():
    stamp = (
        FeedRenderer(worktree=WORKTREE)
        .render(event=FeedNote(label="result", detail="success"))
        .split("  ")[0]
    )
    stamped = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    assert abs(stamped - datetime.now(UTC)) < timedelta(seconds=30)
