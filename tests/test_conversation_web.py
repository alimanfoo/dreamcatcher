"""Render issue conversations in the local web interface."""

from datetime import timedelta

import pytest
from clocks import DISPLAY_TIME_ZONE, PINNED
from conftest import REPOSITORY
from records import write_feed, write_issue_conversation, write_round

from dreamcatcher.agent_rounds import (
    AgentRoundPurpose,
    AgentRoundRecord,
    compose_agent_round_ending,
)
from dreamcatcher.documents import append_text, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.issue_conversations import (
    read_issue_conversation,
    record_issue_conversation_reply_publication,
    save_issue_conversation_reply,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.web import create_app

LOOKED_AT = PINNED + timedelta(hours=2)


def fabricate_conversation(
    *,
    state: StateDirectory,
    has_round: bool = True,
    status: int = 0,
    is_published: bool = True,
) -> None:
    """Write one initial conversation exchange."""
    directory = write_issue_conversation(state=state, issue=8)
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    if not has_round:
        return
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


def application(*, state: StateDirectory):
    """Return the local app with pinned time and display zone."""
    return create_app(
        state=state,
        clock=lambda: LOOKED_AT,
        zone=DISPLAY_TIME_ZONE,
    )


def test_home_lists_a_conversation_and_links_to_its_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)

    page = application(state=state).test_client().get("/").text

    assert "Conversations" in page
    assert 'id="conversation-GH8"' in page
    assert 'href="/conversations/8"' in page
    assert "initial answer published" in page


def test_conversation_page_shows_settings_revision_round_and_feed(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)

    response = application(state=state).test_client().get("/conversations/8")

    assert response.status_code == 200
    page = response.text
    assert "Why does this happen?" not in page
    assert "Issue 8" in page
    assert "conversation-session" in page
    assert "abc123" in page
    assert "opus[1m] · xhigh" in page
    assert "discuss" in page
    assert "I found the answer." in page
    assert 'hx-get="/conversations/8/tail"' in page


@pytest.mark.parametrize(
    ("status", "is_published", "expected"),
    [
        (2, False, "status-needs-attention"),
        (0, False, "status-awaiting-publication"),
    ],
)
def test_conversation_page_shows_failed_and_pending_states(
    tmp_path, status, is_published, expected
):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, status=status, is_published=is_published)

    page = application(state=state).test_client().get("/conversations/8").text

    assert expected in page


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


def test_a_finished_conversation_stops_empty_tail_polling(tmp_path):
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


def test_a_waiting_conversation_keeps_empty_tail_polling(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, has_round=False)

    response = (
        application(state=state)
        .test_client()
        .get("/conversations/8/tail", query_string={"cursor": "0:0"})
    )

    assert response.status_code == 200


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
