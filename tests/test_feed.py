from datetime import timedelta, timezone
from pathlib import PurePosixPath

from clocks import PINNED, Ticking

from dreamcatcher.feed import WIDTH, Note, Prose, Renderer

ROUND = PurePosixPath("/checkout/worktree")


def feed() -> Renderer:
    return Renderer(ROUND, clock=Ticking())


def test_a_note_becomes_one_timestamped_line():
    assert feed().render(Note("Bash", "pytest")) == (
        "2026-08-19T18:41:58Z  [Bash] pytest\n"
    )


def test_a_note_with_nothing_to_add_is_its_label_alone():
    assert feed().render(Note("thinking")) == "2026-08-19T18:41:58Z  [thinking]\n"


def test_a_detail_loses_the_rounds_own_directory():
    assert feed().render(Note("Edit", "/checkout/worktree/src/theme.css")) == (
        "2026-08-19T18:41:58Z  [Edit] src/theme.css\n"
    )


def test_a_path_outside_the_round_keeps_its_own_root():
    assert feed().render(Note("Read", "/etc/hosts")) == (
        "2026-08-19T18:41:58Z  [Read] /etc/hosts\n"
    )


def test_a_detail_spread_over_lines_becomes_one():
    assert feed().render(Note("Bash", "git commit \\\n  --amend")) == (
        "2026-08-19T18:41:58Z  [Bash] git commit \\ --amend\n"
    )


def test_a_detail_longer_than_the_feed_is_clipped():
    assert feed().render(Note("Write", "x" * (WIDTH + 10))) == (
        f"2026-08-19T18:41:58Z  [Write] {'x' * WIDTH} ...\n"
    )


def test_prose_becomes_a_line_for_each_line_it_holds():
    assert feed().render(Prose("I read the file.\n\nIt was empty.")) == (
        "2026-08-19T18:41:58Z  I read the file.\n2026-08-19T18:41:58Z  It was empty.\n"
    )


def test_prose_with_nothing_in_it_writes_nothing():
    assert feed().render(Prose("  \n\n")) == ""


def test_a_subagents_lines_are_indented_under_the_timestamp():
    rendered = feed()

    assert rendered.render(Note("Bash", "ls", subagent=True)) == (
        "2026-08-19T18:41:58Z    [Bash] ls\n"
    )
    assert rendered.render(Prose("two files", subagent=True)) == (
        "2026-08-19T18:41:59Z    two files\n"
    )


def test_a_round_opens_with_its_number_and_its_cause():
    assert feed().boundary(3, "resumed on 2 posts") == (
        "2026-08-19T18:41:58Z  round 3: resumed on 2 posts\n"
    )


def test_a_clock_that_is_not_in_utc_still_stamps_utc():
    elsewhere = PINNED.astimezone(timezone(timedelta(hours=5)))

    assert Renderer(ROUND, clock=lambda: elsewhere).render(Note("result", "ok")) == (
        "2026-08-19T18:41:58Z  [result] ok\n"
    )
