"""Render issue conversations in terminal views."""

from datetime import timedelta
from io import StringIO

import pytest
from clocks import PINNED
from observations import observed_conversation
from records import write_feed, write_issue_conversation, write_round, write_tick
from rich.console import Console

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    IssueConversationInput,
    IssueConversationRoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.documents import write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import read_issue_conversation
from dreamcatcher.scheduler import SchedulerRecord
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
    state = conversation_state(root=tmp_path)
    console, written = rendered_console()

    show_status_view(
        state=state,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    shown = written.getvalue()
    assert "issue conversations" in shown
    assert "GH8" in shown
    assert "inactive" in shown
    assert "issue is not eligible for conversation" in shown


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


def test_conversation_detail_shows_attention_for_an_unreadable_input(tmp_path):
    state = conversation_state(root=tmp_path)
    conversation = read_issue_conversation(state=state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")
    console, written = rendered_console()

    show_conversation_view(
        state=state,
        issue=8,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    shown = written.getvalue()
    assert "needs attention" in shown
    assert "inbox.json is not valid" in shown


def test_conversation_detail_shows_a_failed_round(tmp_path):
    state = conversation_state(root=tmp_path, status=2)
    console, written = rendered_console()

    show_conversation_view(
        state=state,
        issue=8,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    assert "needs attention" in written.getvalue()


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
