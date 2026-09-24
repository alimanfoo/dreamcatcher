"""Render issue conversations in terminal views."""

from datetime import timedelta
from io import StringIO

import pytest
from clocks import PINNED
from records import write_feed, write_issue_conversation, write_round, write_tick
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
from dreamcatcher.scheduler import IssueConversationObservation, SchedulerRecord
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
    is_published: bool = True,
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
            purpose=AgentRoundPurpose.DISCUSS,
            started=PINNED,
            pid=1,
            ending=compose_agent_round_ending(
                at=PINNED + timedelta(minutes=4), status=status
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
    if status == 0:
        save_issue_conversation_reply(
            conversation=conversation, number=1, body="The answer."
        )
        if is_published:
            record_issue_conversation_reply_publication(
                conversation=conversation,
                number=1,
                at=PINNED + timedelta(minutes=5),
            )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_observations=[
                IssueConversationObservation(issue=8, is_eligible=is_eligible)
            ],
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


@pytest.mark.parametrize(
    ("status", "is_published", "expected"),
    [
        (2, False, "needs attention"),
        (0, False, "awaiting publication"),
    ],
)
def test_conversation_detail_shows_failed_and_pending_states(
    tmp_path, status, is_published, expected
):
    state = conversation_state(root=tmp_path, status=status, is_published=is_published)
    console, written = rendered_console()

    show_conversation_view(
        state=state,
        issue=8,
        console=console,
        timing=ViewTiming(clock=lambda: PINNED),
    )

    assert expected in written.getvalue()


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
                purpose=AgentRoundPurpose.DISCUSS,
                started=PINNED + timedelta(minutes=6),
                pid=2,
                ending=compose_agent_round_ending(
                    at=PINNED + timedelta(minutes=10), status=0
                ),
            ),
        )
        write_feed(
            directory=directory,
            number=2,
            lines=[FeedLine(at=PINNED, text="I found the follow-up answer.")],
        )
        conversation = read_issue_conversation(state=state, issue=8)
        assert conversation is not None
        save_issue_conversation_reply(
            conversation=conversation, number=2, body="The follow-up answer."
        )
        record_issue_conversation_reply_publication(
            conversation=conversation,
            number=2,
            at=PINNED + timedelta(minutes=11),
        )
        write_tick(
            state=state,
            tick=SchedulerRecord(
                at=PINNED,
                conversation_observations=[
                    IssueConversationObservation(issue=8, is_eligible=False)
                ],
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
