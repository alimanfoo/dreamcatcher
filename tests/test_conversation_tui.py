"""Render issue conversations in terminal views."""

from datetime import timedelta
from io import StringIO

import pytest
from clocks import PINNED
from records import write_feed, write_issue_conversation, write_round
from rich.console import Console

from dreamcatcher.agent_rounds import (
    AgentRoundPurpose,
    AgentRoundRecord,
    compose_agent_round_ending,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import (
    read_issue_conversation,
    record_issue_conversation_reply_publication,
    save_issue_conversation_reply,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.tui import (
    FeedSelection,
    ViewTiming,
    show_conversation_view,
    show_feed_view,
    show_status_view,
)


def conversation_state(*, root) -> StateDirectory:
    """Return state containing one finished, published conversation."""
    state = StateDirectory(root=root)
    directory = write_issue_conversation(state=state, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AgentRoundPurpose.DISCUSS,
            started=PINNED,
            pid=1,
            ending=compose_agent_round_ending(
                at=PINNED + timedelta(minutes=4), status=0
            ),
        ),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="I found the answer.")],
    )
    conversation = read_issue_conversation(state=state, issue=8)
    assert conversation is not None
    save_issue_conversation_reply(
        conversation=conversation, number=1, body="The answer."
    )
    record_issue_conversation_reply_publication(
        conversation=conversation,
        number=1,
        at=PINNED + timedelta(minutes=5),
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
    assert "initial answer published" in shown


def test_conversation_detail_shows_settings_revision_session_and_round(tmp_path):
    state = conversation_state(root=tmp_path)
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
    assert "opus[1m]" in shown
    assert "discuss" in shown
    assert "successful" in shown


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
