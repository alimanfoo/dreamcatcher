"""Render issue conversations in the local web interface."""

import os
from datetime import timedelta

from clocks import DISPLAY_TIME_ZONE, PINNED
from conftest import REPOSITORY
from observations import observed_conversation
from records import (
    write_feed,
    write_issue_conversation,
    write_round,
    write_running_conversation,
    write_tick,
)
from status_fabrications import fabricate_everything

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    IssueConversationInput,
    IssueConversationRoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.documents import append_text, write_json, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.issue_conversations import (
    read_issue_conversation,
)
from dreamcatcher.scheduler import IssueFactValue, SchedulerRecord
from dreamcatcher.state import StateDirectory
from dreamcatcher.web import create_app

LOOKED_AT = PINNED + timedelta(hours=2)


def fabricate_conversation(
    *,
    state: StateDirectory,
    has_round: bool = True,
    status: int = 0,
    is_eligible: bool = False,
) -> None:
    """Write one initial conversation exchange."""
    directory = write_issue_conversation(state=state, issue=8)
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_observations=[observed_conversation()] if is_eligible else [],
        ),
    )
    if not has_round:
        return
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


def application(*, state: StateDirectory):
    """Return the local app with pinned time and display zone."""
    return create_app(
        state=state,
        clock=lambda: LOOKED_AT,
        zone=DISPLAY_TIME_ZONE,
    )


def test_home_lists_a_conversation_and_links_to_its_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    fabricate_conversation(state=state, is_eligible=True)

    page = application(state=state).test_client().get("/").text

    assert page.index('id="assignments-heading"') < page.index(
        'id="conversations-heading"'
    )
    assert 'class="assignment-card' in page
    assert "Conversations" in page
    assert 'id="conversation-GH8"' in page
    assert 'href="/conversations/8"' in page
    assert "round 1, answered, ran 4m" in page


def test_conversation_page_shows_settings_revision_round_and_feed(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
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

    response = application(state=state).test_client().get("/conversations/8")

    assert response.status_code == 200
    page = response.text
    assert "Why does this happen?" not in page
    assert "Issue 8" in page
    assert "conversation-session" in page
    assert "abc123" in page
    assert "def456" in page
    assert "code revision abc123 -&gt; def456" in page
    assert "opus[1m] · xhigh" in page
    assert "discuss" in page
    assert "I found the answer." in page
    assert 'hx-get="/conversations/8/tail"' in page


def test_conversation_page_shows_a_fault_for_an_unreadable_input(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    conversation = read_issue_conversation(state=state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")

    response = application(state=state).test_client().get("/conversations/8")

    assert response.status_code == 200
    assert "status-fault" in response.text
    assert "inbox.json is not valid" in response.text


def test_conversation_page_shows_a_failed_round(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, status=2)

    page = application(state=state).test_client().get("/conversations/8").text

    assert "status-fault" in page


def test_conversation_before_its_first_round_has_an_empty_feed(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, has_round=False)

    page = application(state=state).test_client().get("/conversations/8").text

    assert 'id="cursor" name="cursor" value="0:0"' in page
    assert "-- no rounds have run --" in page
    assert "-- no feed yet --" in page


def test_conversation_tail_returns_new_output_and_advances_its_cursor(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    conversation = read_issue_conversation(state=state, issue=8)
    assert conversation is not None
    feed = conversation.compose_round_paths(number=1).feed
    cursor = feed.stat().st_size
    append_text(
        text=FeedLine(at=LOOKED_AT, text="One more detail.").render(),
        path=feed,
    )

    response = (
        application(state=state)
        .test_client()
        .get("/conversations/8/tail", query_string={"cursor": f"1:{cursor}"})
    )

    assert response.status_code == 200
    assert "One more detail." in response.text
    assert f'value="1:{feed.stat().st_size}"' in response.text
    assert 'id="conversation-status"' in response.text


def test_an_ineligible_conversation_stops_empty_tail_polling(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    conversation = read_issue_conversation(state=state, issue=8)
    assert conversation is not None
    feed = conversation.compose_round_paths(number=1).feed

    response = (
        application(state=state)
        .test_client()
        .get(
            "/conversations/8/tail",
            query_string={"cursor": f"1:{feed.stat().st_size}"},
        )
    )

    assert response.status_code == 286


def test_a_faulted_conversation_stops_empty_tail_polling(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, status=2, is_eligible=True)
    conversation = read_issue_conversation(state=state, issue=8)
    assert conversation is not None
    feed = conversation.compose_round_paths(number=1).feed

    response = (
        application(state=state)
        .test_client()
        .get(
            "/conversations/8/tail",
            query_string={"cursor": f"1:{feed.stat().st_size}"},
        )
    )

    assert response.status_code == 286


def test_a_waiting_conversation_keeps_empty_tail_polling(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, has_round=False, is_eligible=True)

    response = (
        application(state=state)
        .test_client()
        .get("/conversations/8/tail", query_string={"cursor": "0:0"})
    )

    assert response.status_code == 200


def test_conversation_tail_adds_a_later_round_without_repeating_the_first(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, is_eligible=True)
    conversation = read_issue_conversation(state=state, issue=8)
    assert conversation is not None
    first_feed = conversation.compose_round_paths(number=1).feed
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
        lines=[FeedLine(at=LOOKED_AT, text="I found the follow-up answer.")],
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_observations=[],
        ),
    )

    response = (
        application(state=state)
        .test_client()
        .get(
            "/conversations/8/tail",
            query_string={"cursor": f"1:{first_feed.stat().st_size}"},
        )
    )

    assert response.status_code == 200
    assert "I found the answer." not in response.text
    assert 'id="conversation-detail"' in response.text
    assert "issue is not eligible for conversation" in response.text
    assert response.text.count("round 2: discuss") == 1
    assert response.text.count("code revision abc123 -&gt; def456") == 1
    assert response.text.count("I found the follow-up answer.") == 1


def test_conversation_tail_refuses_an_invalid_cursor(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)

    response = (
        application(state=state)
        .test_client()
        .get("/conversations/8/tail", query_string={"cursor": "not-a-cursor"})
    )

    assert response.status_code == 400
    assert "feed cursor is invalid" in response.text


def test_missing_conversation_pages_answer_not_found(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = application(state=state).test_client()

    page = client.get("/conversations/8")
    tail = client.get("/conversations/8/tail", query_string={"cursor": "0:0"})

    assert page.status_code == 404
    assert tail.status_code == 404
    assert "No issue conversation here is for GH8" in page.text


def fabricate_unsaved_conversation(*, state: StateDirectory) -> None:
    """Write a tick that observed GH9 with a comment to answer and no record."""
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
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


def test_home_lists_an_eligible_issue_before_its_conversation_is_saved(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_unsaved_conversation(state=state)

    page = application(state=state).test_client().get("/").text

    assert 'id="conversation-GH9"' in page
    assert 'href="/conversations/9"' in page
    assert "1 comment to answer" in page
    assert "assignment-meta" not in page


def test_conversation_page_before_its_record_shows_its_issue_and_polls(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_unsaved_conversation(state=state)
    client = application(state=state).test_client()

    page = client.get("/conversations/9")
    tail = client.get("/conversations/9/tail", query_string={"cursor": "0:0"})

    assert page.status_code == 200
    assert "Issue 9" in page.text
    assert "assignment-facts" not in page.text
    assert "-- no feed yet --" in page.text
    assert tail.status_code == 200
    assert 'value="0:0"' in tail.text


def test_home_lists_conversations_in_attention_order(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, status=2)
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

    page = application(state=state).test_client().get("/").text

    assert (
        page.index('id="conversation-GH8"')
        < page.index('id="conversation-GH11"')
        < page.index('id="conversation-GH10"')
        < page.index('id="conversation-GH12"')
        < page.index('id="conversation-GH9"')
    )
    assert "status-working" in page
    assert "status-unknown" in page
