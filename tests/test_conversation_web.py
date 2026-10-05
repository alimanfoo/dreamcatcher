"""Render issue conversations in the local web interface."""

from datetime import timedelta

from clocks import DISPLAY_TIME_ZONE, PINNED
from conftest import REPOSITORY
from observations import observed_conversation
from records import (
    hold_daemon_lock_for_test,
    write_feed,
    write_round,
    write_running_conversation,
    write_tick,
)
from status_fabrications import fabricate_conversation, fabricate_everything

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    ConversationRoundPurpose,
    _compose_agent_round_ending,
)
from dreamcatcher.documents import append_text, remove_file, write_json, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.issue_conversations import (
    ConversationInput,
    InitialConversationIssue,
    read_conversation,
)
from dreamcatcher.scheduler.models import IssueFactValue, SchedulerRecord
from dreamcatcher.state import StateDirectory
from dreamcatcher.web.app import _create_app

LOOKED_AT = PINNED + timedelta(hours=2)


def application(*, state: StateDirectory):
    """Return the local app with pinned time and display zone."""
    return _create_app(
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
    conversation_link = (
        'class="assignment-open" href="/conversations/8" target="_blank" '
        'rel="noopener noreferrer" '
        'aria-label="Open conversation GH8 (opens in new tab)"'
    )
    assert conversation_link in page
    assert '<span class="chip status-idle">idle</span>' in page
    assert "round 1, answered, ran 4m" in page


def test_conversation_page_shows_settings_revision_round_and_feed(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, harness_session_identifier=None)
    directory = state.conversations / "GH8"
    write_text(
        text=(
            '{"type":"system","subtype":"init","model":"claude-opus-5",'
            '"session_id":"recovered-session"}\n'
        ),
        path=directory / "rounds" / "1" / "raw.jsonl",
    )
    revision = "0123456789abcdef0123456789abcdef01234567"
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            purpose=ConversationRoundPurpose.DISCUSS,
            started=PINNED + timedelta(minutes=6),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=10), status=0
            ),
        ),
    )
    write_json(
        document=ConversationInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title="Issue 8",
                body="Explain it.",
            ),
            comments=[
                {
                    "id": 2,
                    "body": "Does that still hold?",
                    "author": "alice",
                    "written_at": "2026-09-23T02:00:00Z",
                }
            ],
            revision=revision,
        ),
        path=(directory / "rounds" / "2" / "inbox.json"),
    )

    response = application(state=state).test_client().get("/conversations/8")

    assert response.status_code == 200
    page = response.text
    assert "Why does this happen?" not in page
    assert "Issue 8" in page
    assert page.count("<dt>") == 3
    assert "<dt>label</dt><dd>dream:conversation</dd>" in page
    assert "<dt>harness</dt><dd>claude</dd>" in page
    assert "<dt>model</dt><dd>opus[1m] · xhigh</dd>" in page
    assert "<dt>worktree</dt>" not in page
    assert "<dt>session</dt>" not in page
    assert "abc123" in page
    assert page.count("0123456") == 2
    assert "code revision abc123 -&gt; 0123456" in page
    assert revision not in page
    assert "opus[1m] · xhigh" in page
    assert "discuss" in page
    assert "I found the answer." in page
    assert 'hx-get="/conversations/8/tail"' in page
    assert "<summary>resume by hand</summary>" in page
    assert "cd .dreamcatcher/v5/conversation-worktrees/GH8" in page
    assert "claude --resume recovered-session" in page


def test_conversation_page_requests_a_stop_for_its_running_round(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    write_running_conversation(state=state, issue=8, started=PINNED)
    client = application(state=state).test_client()

    page = client.get("/conversations/8")

    assert page.status_code == 200
    assert 'action="/conversations/8/stop/1"' in page.text
    assert "<summary>resume by hand</summary>" not in page.text

    response = client.post(
        "/conversations/8/stop/1", headers={"Origin": "http://localhost"}
    )

    assert response.status_code == 303
    assert response.location == "/conversations/8"
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    paths = conversation.compose_round_paths(number=1)
    assert paths.stop_request.read_text(encoding="utf-8") == ""


def test_conversation_tail_offers_a_hand_resume_only_while_no_round_runs(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    write_running_conversation(state=state, issue=8, started=PINNED)
    client = application(state=state).test_client()
    query = {"cursor": "0:0"}

    working = client.get("/conversations/8/tail", query_string=query)
    remove_file(path=state.lock)
    without_daemon = client.get("/conversations/8/tail", query_string=query)

    assert (
        '<div id="hand-resume" class="hand-resume" hx-swap-oob="morph"></div>'
        in working.text
    )
    assert "<summary>resume by hand</summary>" in without_daemon.text
    assert "claude --resume conversation-session" in without_daemon.text


def test_an_old_conversation_stop_submission_cannot_stop_the_next_round(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    write_round(
        directory=state.conversations / "GH8",
        number=2,
        record=AgentRoundRecord(
            number=2,
            purpose=ConversationRoundPurpose.DISCUSS,
            started=PINNED + timedelta(minutes=5),
            pid=1,
        ),
    )
    client = application(state=state).test_client()

    response = client.post(
        "/conversations/8/stop/1", headers={"Origin": "http://localhost"}
    )

    assert response.status_code == 303
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert not conversation.compose_round_paths(number=2).stop_request.exists()


def test_unsaved_conversation_has_no_stop_control(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    fabricate_unsaved_conversation(state=state)

    response = application(state=state).test_client().get("/conversations/9")

    assert response.status_code == 200
    assert 'action="/conversations/9/stop/1"' not in response.text
    assert "<summary>resume by hand</summary>" not in response.text


def test_a_stale_conversation_stop_request_is_already_done(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    client = application(state=state).test_client()

    response = client.post(
        "/conversations/8/stop/1", headers={"Origin": "http://localhost"}
    )

    assert response.status_code == 303
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert not conversation.compose_round_paths(number=1).stop_request.exists()


def test_an_unknown_conversation_cannot_receive_a_stop_request(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = application(state=state).test_client()

    response = client.post(
        "/conversations/8/stop/1", headers={"Origin": "http://localhost"}
    )

    assert response.status_code == 404


def test_conversation_stop_requests_must_come_from_the_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = application(state=state).test_client()

    response = client.post(
        "/conversations/8/stop/1", headers={"Origin": "https://example.com"}
    )

    assert response.status_code == 403


def test_conversation_page_requests_a_retry_for_its_fault(tmp_path):
    state = StateDirectory(root=tmp_path)
    _fabricate_faulted_conversation(state=state)
    client = application(state=state).test_client()

    page = client.get("/conversations/8")

    assert 'action="/conversations/8/retry/2"' in page.text

    response = client.post(
        "/conversations/8/retry/2", headers={"Origin": "http://localhost"}
    )

    assert response.status_code == 303
    assert response.location == "/conversations/8"
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert conversation.retry_requested_at == LOOKED_AT
    assert (
        'action="/conversations/8/retry/2"' not in client.get("/conversations/8").text
    )


def test_an_old_conversation_retry_submission_cannot_clear_a_newer_fault(tmp_path):
    state = StateDirectory(root=tmp_path)
    _fabricate_faulted_conversation(state=state)
    client = application(state=state).test_client()

    response = client.post(
        "/conversations/8/retry/1", headers={"Origin": "http://localhost"}
    )

    assert response.status_code == 303
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert conversation.retry_requested_at is None


def test_an_unknown_conversation_cannot_receive_a_retry_request(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = application(state=state).test_client()

    response = client.post(
        "/conversations/8/retry/2", headers={"Origin": "http://localhost"}
    )

    assert response.status_code == 404


def test_conversation_retry_requests_must_come_from_the_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    _fabricate_faulted_conversation(state=state)
    client = application(state=state).test_client()

    response = client.post(
        "/conversations/8/retry/2", headers={"Origin": "https://example.com"}
    )

    assert response.status_code == 403
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert conversation.retry_requested_at is None


def test_conversation_page_with_an_unreadable_input_still_renders(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")

    response = application(state=state).test_client().get("/conversations/8")

    assert response.status_code == 200
    assert "I found the answer." in response.text


def test_conversation_page_shows_a_failed_round_waiting_to_be_recovered(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, status=2, is_eligible=True)

    page = application(state=state).test_client().get("/conversations/8").text

    assert "status-waiting" in page
    assert "round 1 errored (exit 2)" in page


def _fabricate_faulted_conversation(*, state: StateDirectory) -> None:
    """Save conversation GH8 with two consecutive errored rounds."""
    fabricate_conversation(state=state, status=2, is_eligible=True)
    directory = state.conversations / "GH8"
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            purpose=ConversationRoundPurpose.DISCUSS,
            is_recovery=True,
            started=PINNED + timedelta(minutes=5),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=8), status=2
            ),
        ),
    )
    write_json(
        document=ConversationInput(
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


def test_conversation_page_shows_two_errors_as_a_fault(tmp_path):
    state = StateDirectory(root=tmp_path)
    _fabricate_faulted_conversation(state=state)

    page = application(state=state).test_client().get("/conversations/8").text

    assert "status-fault" in page
    assert "round 2 errored (exit 2)" in page
    assert "(recovery)" in page


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
    conversation = read_conversation(state=state, issue=8)
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
    assert 'id="agent-work-status"' in response.text


def test_an_ineligible_conversation_stops_empty_tail_polling(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    conversation = read_conversation(state=state, issue=8)
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
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    first_feed = conversation.compose_round_paths(number=1).feed
    directory = state.conversations / "GH8"
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            purpose=ConversationRoundPurpose.DISCUSS,
            started=PINNED + timedelta(minutes=6),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=10), status=0
            ),
        ),
    )
    write_json(
        document=ConversationInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title="Issue 8",
                body="Explain it.",
            ),
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
    assert 'id="agent-work-detail"' in response.text
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
    fabricate_conversation(state=state)
    write_running_conversation(state=state, issue=11, started=PINNED)
    write_feed(
        directory=state.conversations / "GH11",
        number=1,
        lines=[FeedLine(at=PINNED, text="Still working.")],
    )
    hold_daemon_lock_for_test(path=state.lock)
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
        page.index('id="conversation-GH11"')
        < page.index('id="conversation-GH10"')
        < page.index('id="conversation-GH12"')
        < page.index('id="conversation-GH8"')
        < page.index('id="conversation-GH9"')
    )
    assert "status-working" in page
    assert "status-unknown" in page
    assert '<p class="latest-output"><span>agent</span> Still working.</p>' in page
