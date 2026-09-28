"""Render issue conversations in terminal views."""

import os
from datetime import timedelta
from io import StringIO

import pytest
from clocks import PINNED
from observations import observed_conversation
from records import (
    write_feed,
    write_final_output,
    write_issue_conversation,
    write_round,
    write_running_conversation,
    write_tick,
)
from rich.console import Console

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    IssueConversationRoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.documents import write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import IssueConversationInput
from dreamcatcher.scheduler import IssueFactValue, SchedulerRecord
from dreamcatcher.state import StateDirectory
from dreamcatcher.tui import (
    FeedSelection,
    ViewTiming,
    show_conversation_view,
    show_feed_view,
    show_status_view,
)


def conversation_state(
    *,
    root,
    status: int = 0,
    is_eligible: bool = False,
) -> StateDirectory:
    """Return state containing one finished conversation."""
    state = StateDirectory(root=root)
    directory = write_issue_conversation(state=state, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=IssueConversationRoundPurpose.DISCUSS,
            started=PINNED,
            pid=1,
            ending=compose_agent_round_ending(
                at=PINNED + timedelta(minutes=4), status=status
            ),
        ),
    )
    write_json(
        document=IssueConversationInput(
            issue=8,
            title="Issue 8",
            body="Explain it.",
            comments=[
                {
                    "id": 1,
                    "body": "Please explain.",
                    "author": "alice",
                    "written_at": "2026-09-23T01:00:00Z",
                }
            ],
            revision="abc123",
        ),
        path=(directory / "rounds" / "1" / "inbox.json"),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="I found the answer.")],
    )
    write_final_output(directory=directory, number=1, text="The answer.")
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_observations=[observed_conversation()] if is_eligible else [],
        ),
    )
    return state


def rendered_console() -> tuple[Console, StringIO]:
    """Return a plain fixed-width console and the text it writes."""
    written = StringIO()
    return Console(file=written, width=100, color_system=None), written


def test_status_lists_the_issue_conversation(tmp_path):
    state = conversation_state(root=tmp_path, is_eligible=True)
    console, written = rendered_console()

    show_status_view(
        state=state,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    shown = written.getvalue()
    assert "issue conversations" in shown
    assert "GH8" in shown
    assert "idle" in shown
    assert "round 1, answered, ran 4m" in shown


def test_conversation_detail_shows_settings_revision_session_and_round(tmp_path):
    state = conversation_state(root=tmp_path)
    directory = state.conversations / "GH8"
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            purpose=IssueConversationRoundPurpose.DISCUSS,
            started=PINNED + timedelta(minutes=6),
            pid=2,
            ending=compose_agent_round_ending(
                at=PINNED + timedelta(minutes=10), status=0
            ),
        ),
    )
    write_json(
        document=IssueConversationInput(
            issue=8,
            title="Issue 8",
            body="Explain it.",
            comments=[
                {
                    "id": 2,
                    "body": "Does that still hold?",
                    "author": "alice",
                    "written_at": "2026-09-23T02:00:00Z",
                }
            ],
            revision="def456",
        ),
        path=(directory / "rounds" / "2" / "inbox.json"),
    )
    console, written = rendered_console()

    show_conversation_view(
        state=state,
        issue=8,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    shown = written.getvalue()
    assert "issue conversation GH8" in shown
    assert "conversation-session" in shown
    assert "abc123" in shown
    assert "def456" in shown
    assert "opus[1m]" in shown
    assert "discuss" in shown
    assert "successful" in shown


def test_conversation_detail_shows_a_failed_round(tmp_path):
    state = conversation_state(root=tmp_path, status=2, is_eligible=True)
    console, written = rendered_console()

    show_conversation_view(
        state=state,
        issue=8,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    assert "waiting  round 1 errored (exit 2)" in written.getvalue()


def test_conversation_detail_shows_two_errors_as_a_fault(tmp_path):
    state = conversation_state(root=tmp_path, status=2, is_eligible=True)
    directory = state.conversations / "GH8"
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            purpose=IssueConversationRoundPurpose.DISCUSS,
            is_recovery=True,
            started=PINNED + timedelta(minutes=5),
            pid=2,
            ending=compose_agent_round_ending(
                at=PINNED + timedelta(minutes=8), status=2
            ),
        ),
    )
    write_json(
        document=IssueConversationInput(
            issue=8,
            comments=[
                {
                    "id": 1,
                    "body": "Please explain.",
                    "author": "alice",
                    "written_at": "2026-09-23T01:00:00Z",
                }
            ],
            revision="abc123",
        ),
        path=directory / "rounds" / "2" / "inbox.json",
    )
    console, written = rendered_console()
    console.width = 140

    show_conversation_view(
        state=state,
        issue=8,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    shown = written.getvalue()
    assert "fault  round 2 errored (exit 2)" in shown
    assert "discuss (recovery)" in shown


def test_conversation_feed_shows_its_saved_activity(tmp_path):
    state = conversation_state(root=tmp_path)
    console, written = rendered_console()

    show_feed_view(
        state=state,
        selection=FeedSelection(issue=8, owner_kind=AgentWorkKind.CONVERSATION),
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    shown = written.getvalue()
    assert "round 1: discuss" in shown
    assert "I found the answer." in shown


def test_conversation_feed_follows_a_later_round_without_repeating_the_first(
    tmp_path,
):
    state = conversation_state(root=tmp_path, is_eligible=True)
    written = StringIO()
    console = Console(
        file=written,
        width=100,
        color_system=None,
        force_terminal=True,
    )

    def wait(seconds, /):
        assert seconds > 0
        directory = state.conversations / "GH8"
        write_round(
            directory=directory,
            number=2,
            record=AgentRoundRecord(
                number=2,
                purpose=IssueConversationRoundPurpose.DISCUSS,
                started=PINNED + timedelta(minutes=6),
                pid=2,
                ending=compose_agent_round_ending(
                    at=PINNED + timedelta(minutes=10), status=0
                ),
            ),
        )
        write_json(
            document=IssueConversationInput(
                issue=8,
                title="Issue 8",
                body="Explain it.",
                comments=[
                    {
                        "id": 2,
                        "body": "What evidence supports that?",
                        "author": "alice",
                        "written_at": "2026-09-23T02:00:00Z",
                    }
                ],
                revision="def456",
            ),
            path=(directory / "rounds" / "2" / "inbox.json"),
        )
        write_feed(
            directory=directory,
            number=2,
            lines=[FeedLine(at=PINNED, text="I found the follow-up answer.")],
        )
        write_tick(
            state=state,
            tick=SchedulerRecord(
                at=PINNED,
                conversation_observations=[],
            ),
        )

    show_feed_view(
        state=state,
        selection=FeedSelection(issue=8, owner_kind=AgentWorkKind.CONVERSATION),
        console=console,
        timing=ViewTiming(clock=lambda: PINNED, wait=wait),
    )

    shown = written.getvalue()
    assert shown.count("round 1: discuss") == 1
    assert shown.count("I found the answer.") == 1
    assert shown.count("round 2: discuss") == 1
    assert shown.count("code revision abc123 -> def456") == 1
    assert shown.count("I found the follow-up answer.") == 1


def test_conversation_feed_can_select_one_round(tmp_path):
    state = conversation_state(root=tmp_path)
    console, written = rendered_console()

    show_feed_view(
        state=state,
        selection=FeedSelection(issue=8, owner_kind=AgentWorkKind.CONVERSATION),
        console=console,
        round_number=1,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    assert "I found the answer." in written.getvalue()


def test_a_missing_conversation_detail_is_reportable(tmp_path):
    console, _ = rendered_console()

    with pytest.raises(ReportableError, match="No conversation here for GH8"):
        show_conversation_view(
            state=StateDirectory(root=tmp_path),
            issue=8,
            console=console,
        )


def test_a_missing_conversation_round_says_how_many_exist(tmp_path):
    state = conversation_state(root=tmp_path)
    console, _ = rendered_console()

    with pytest.raises(ReportableError, match="has run 1 round, so it has no round 2"):
        show_feed_view(
            state=state,
            selection=FeedSelection(issue=8, owner_kind=AgentWorkKind.CONVERSATION),
            console=console,
            round_number=2,
        )


def unsaved_conversation_state(*, root) -> StateDirectory:
    """Return state whose latest tick observed GH9 with a comment to answer."""
    state = StateDirectory(root=root)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_observations=[
                observed_conversation(
                    issue=9, value=IssueFactValue.TRUE, evidence="1 comment to answer"
                )
            ],
        ),
    )
    return state


def test_status_lists_an_eligible_issue_before_its_conversation_is_saved(tmp_path):
    state = unsaved_conversation_state(root=tmp_path)
    console, written = rendered_console()

    show_status_view(
        state=state,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    shown = written.getvalue()
    assert "GH9" in shown
    assert "waiting" in shown
    assert "1 comment to answer" in shown


def test_conversation_detail_before_its_first_round_shows_its_issue(tmp_path):
    state = unsaved_conversation_state(root=tmp_path)
    console, written = rendered_console()

    show_conversation_view(
        state=state,
        issue=9,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    shown = written.getvalue()
    assert "issue conversation GH9" in shown
    assert "Issue 9" in shown
    assert "agent harness" not in shown


def test_a_conversation_feed_before_its_first_round_says_so(tmp_path):
    state = unsaved_conversation_state(root=tmp_path)
    console, _ = rendered_console()

    with pytest.raises(ReportableError, match="GH9 has not run a round yet"):
        show_feed_view(
            state=state,
            selection=FeedSelection(issue=9, owner_kind=AgentWorkKind.CONVERSATION),
            console=console,
        )


def test_conversations_are_listed_in_attention_order(tmp_path):
    state = conversation_state(root=tmp_path)
    write_running_conversation(state=state, issue=11, started=PINNED)
    state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_observations=[
                observed_conversation(issue=8),
                observed_conversation(issue=9),
                observed_conversation(
                    issue=10, value=IssueFactValue.TRUE, evidence="1 comment to answer"
                ),
                observed_conversation(issue=11),
                observed_conversation(
                    issue=12, value=IssueFactValue.UNKNOWN, evidence="cannot tell"
                ),
            ],
        ),
    )
    console, written = rendered_console()

    show_status_view(
        state=state,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    shown = written.getvalue()
    assert (
        shown.index("GH11")
        < shown.index("GH10")
        < shown.index("GH12")
        < shown.index("GH8")
        < shown.index("GH9")
    )
    assert "working" in shown
    assert "unknown" in shown


def watched_console() -> tuple[Console, StringIO]:
    """Return a plain console that says it is a terminal, so a view follows."""
    written = StringIO()
    return (
        Console(
            file=written,
            width=100,
            height=40,
            force_terminal=True,
            color_system=None,
            legacy_windows=False,
            _environ={"TERM": "xterm"},
        ),
        written,
    )


def refusing(seconds, /):
    """A wait that a view with nothing more to show must never reach."""
    raise AssertionError("the view waited for something that was not coming")


@pytest.mark.parametrize("status", [0, 2], ids=["answered", "errored"])
def test_a_conversation_view_off_the_report_never_waits(tmp_path, status):
    state = conversation_state(root=tmp_path, status=status)
    console, written = watched_console()

    show_conversation_view(
        state=state,
        issue=8,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED, wait=refusing),
    )

    assert "issue conversation GH8" in written.getvalue()


def test_a_conversation_view_of_an_idle_conversation_keeps_watching(tmp_path):
    state = conversation_state(root=tmp_path, is_eligible=True)
    console, _ = watched_console()
    waits = []

    def interrupting(seconds, /):
        waits.append(seconds)
        raise KeyboardInterrupt

    show_conversation_view(
        state=state,
        issue=8,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED, wait=interrupting),
    )

    assert waits
