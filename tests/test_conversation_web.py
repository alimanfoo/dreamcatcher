"""Render issue conversations in the local web interface."""

import html
import re
from datetime import timedelta
from unittest.mock import MagicMock

from clocks import DISPLAY_TIME_ZONE, PINNED
from conftest import REPOSITORY
from records import (
    find_conversation_directory,
    hold_daemon_lock_for_test,
    read_conversation,
    release_daemon_lock,
    write_ending,
    write_feed,
    write_round,
    write_running_conversation,
    write_tick,
)
from rows import compose_request_row
from status_fabrications import (
    compose_conversation_row,
    fabricate_conversation,
    fabricate_everything,
)

import dreamcatcher.status.report as report_module
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import AgentWorkEndReason
from dreamcatcher.documents import append_text, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import (
    ConversationRoundInput,
    InitialConversationIssue,
)
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    PauseCause,
    PausedFinding,
    ReadFailureFinding,
    SchedulerRecord,
)
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
    fabricate_conversation(state=state, is_paused=False)

    page = application(state=state).test_client().get("/").text

    assert page.index('id="assignment-tab"') < page.index('id="conversation-tab"')
    assert 'class="agent-work-card' in page
    assert 'aria-controls="conversation-panel">Conversations</a>' in page
    assert 'id="GH8-20260819-184158-conversation"' in page
    conversation_link = (
        'class="agent-work-open" href="/work/GH8-20260819-184158-conversation" '
        'aria-label="Open conversation GH8-20260819-184158-conversation"'
    )
    assert conversation_link in page
    assert '<span class="chip status-idle">idle</span>' in page
    assert "round 1, answered, ran 4m" in page


def test_conversation_page_asks_once_whether_the_daemon_runs(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    probe = MagicMock(wraps=report_module.is_daemon_lock_held)
    monkeypatch.setattr(report_module, "is_daemon_lock_held", probe)

    response = (
        application(state=state)
        .test_client()
        .get("/work/GH8-20260819-184158-conversation")
    )

    assert response.status_code == 200
    probe.assert_called_once_with(path=state.lock)


def test_conversation_page_shows_settings_revision_round_and_feed(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, harness_session_identifier=None)
    directory = find_conversation_directory(state=state, issue=8)
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
            started=PINNED + timedelta(minutes=6),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=10), status=0
            ),
        ),
        round_input=ConversationRoundInput(
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
    )

    response = (
        application(state=state)
        .test_client()
        .get("/work/GH8-20260819-184158-conversation")
    )

    assert response.status_code == 200
    page = response.text
    assert "Why does this happen?" not in page
    assert "Issue 8" in page
    assert page.count("<dt>") == 3
    assert "<dt>label</dt><dd>dream:conversation</dd>" in page
    assert "<dt>harness</dt><dd>claude</dd>" in page
    assert "<dt>model · effort</dt><dd>opus[1m] · xhigh</dd>" in page
    assert "<dt>worktree</dt>" not in page
    assert "<dt>session</dt>" not in page
    assert "abc123" in page
    assert f"code revision abc123 -&gt; {revision}" in page
    assert revision in page
    assert "opus[1m] · xhigh" in page
    assert "1 comment" in page
    assert "I found the answer." in page
    assert 'hx-get="/work/GH8-20260819-184158-conversation/tail"' in page
    assert "<summary>resume by hand</summary>" in page
    assert "cd .dreamcatcher/v7/worktrees/GH8-20260819-184158-conversation" in page
    assert "claude --resume recovered-session" in page


def test_conversation_page_requests_a_stop_for_its_running_round(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    write_running_conversation(state=state, issue=8, started=PINNED)
    client = application(state=state).test_client()

    page = client.get("/work/GH8-20260819-184158-conversation")

    assert page.status_code == 200
    assert re.search(
        r'<div id="agent-work-foot"[^>]*>\s*<form id="stop-form" [^>]*'
        r'action="/work/GH8-20260819-184158-conversation/stop/1" '
        r'data-confirmation="Stop this round\?',
        page.text,
    )
    assert "<summary>resume by hand</summary>" not in page.text

    response = client.post(
        "/work/GH8-20260819-184158-conversation/stop/1",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assert response.location == "/work/GH8-20260819-184158-conversation"
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

    working = client.get(
        "/work/GH8-20260819-184158-conversation/tail", query_string=query
    )
    release_daemon_lock(path=state.lock)
    without_daemon = client.get(
        "/work/GH8-20260819-184158-conversation/tail", query_string=query
    )

    assert "<summary>resume by hand</summary>" not in working.text
    assert "<summary>resume by hand</summary>" in without_daemon.text
    assert "claude --resume conversation-session" in without_daemon.text


def test_an_old_conversation_stop_submission_cannot_stop_the_next_round(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    write_round(
        directory=find_conversation_directory(state=state, issue=8),
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED + timedelta(minutes=5),
            pid=1,
        ),
    )
    client = application(state=state).test_client()

    response = client.post(
        "/work/GH8-20260819-184158-conversation/stop/1",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert not conversation.compose_round_paths(number=2).stop_request.exists()


def test_a_stale_conversation_stop_request_is_already_done(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    client = application(state=state).test_client()

    response = client.post(
        "/work/GH8-20260819-184158-conversation/stop/1",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert not conversation.compose_round_paths(number=1).stop_request.exists()


def test_an_unknown_conversation_cannot_receive_a_stop_request(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = application(state=state).test_client()

    response = client.post(
        "/work/GH8-20260819-184158-conversation/stop/1",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 404


def test_conversation_stop_requests_must_come_from_the_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = application(state=state).test_client()

    response = client.post(
        "/work/GH8-20260819-184158-conversation/stop/1",
        headers={"Origin": "https://example.com"},
    )

    assert response.status_code == 403


def test_conversation_page_requests_a_retry_for_its_fault(tmp_path):
    state = StateDirectory(root=tmp_path)
    _fabricate_faulted_conversation(state=state)
    client = application(state=state).test_client()

    page = client.get("/work/GH8-20260819-184158-conversation")

    assert 'action="/work/GH8-20260819-184158-conversation/retry/2"' in page.text

    response = client.post(
        "/work/GH8-20260819-184158-conversation/retry/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assert response.location == "/work/GH8-20260819-184158-conversation"
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert conversation.retry_requested_at == LOOKED_AT
    assert (
        'action="/work/GH8-20260819-184158-conversation/retry/2"'
        not in client.get("/work/GH8-20260819-184158-conversation").text
    )


def test_an_old_conversation_retry_submission_cannot_clear_a_newer_fault(tmp_path):
    state = StateDirectory(root=tmp_path)
    _fabricate_faulted_conversation(state=state)
    client = application(state=state).test_client()

    response = client.post(
        "/work/GH8-20260819-184158-conversation/retry/1",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert conversation.retry_requested_at is None


def test_an_unknown_conversation_cannot_receive_a_retry_request(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = application(state=state).test_client()

    response = client.post(
        "/work/GH8-20260819-184158-conversation/retry/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 404


def test_conversation_retry_requests_must_come_from_the_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    _fabricate_faulted_conversation(state=state)
    client = application(state=state).test_client()

    response = client.post(
        "/work/GH8-20260819-184158-conversation/retry/2",
        headers={"Origin": "https://example.com"},
    )

    assert response.status_code == 403
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert conversation.retry_requested_at is None


def test_conversation_page_with_an_unreadable_input_names_the_file(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    round_input = conversation.compose_round_paths(number=1).round_input
    round_input.write_bytes(b"not json")

    response = (
        application(state=state)
        .test_client()
        .get("/work/GH8-20260819-184158-conversation")
    )

    assert response.status_code == 500
    assert html.escape(str(round_input)) in response.text
    assert "I found the answer." not in response.text


def test_conversation_page_shows_a_failed_round_waiting_to_run_again(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, status=2, is_paused=False)

    page = (
        application(state=state)
        .test_client()
        .get("/work/GH8-20260819-184158-conversation")
        .text
    )

    assert "status-waiting" in page
    assert "round 1 errored (exit 2)" in page


def _fabricate_faulted_conversation(*, state: StateDirectory) -> None:
    """Save conversation GH8 with two consecutive errored rounds."""
    fabricate_conversation(state=state, status=2, is_paused=False)
    directory = find_conversation_directory(state=state, issue=8)
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED + timedelta(minutes=5),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=8), status=2
            ),
        ),
        round_input=ConversationRoundInput(
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
    )


def test_conversation_page_shows_two_errors_as_a_fault(tmp_path):
    state = StateDirectory(root=tmp_path)
    _fabricate_faulted_conversation(state=state)

    page = (
        application(state=state)
        .test_client()
        .get("/work/GH8-20260819-184158-conversation")
        .text
    )

    assert "status-fault" in page
    assert "round 2 errored (exit 2)" in page


def test_conversation_before_its_first_round_has_no_feed_yet(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, has_round=False)
    client = application(state=state).test_client()

    page = client.get("/work/GH8-20260819-184158-conversation").text
    tail = client.get(
        "/work/GH8-20260819-184158-conversation/tail", query_string={"cursor": "0:0"}
    ).text

    assert 'id="cursor" name="cursor" value="0:0"' in page
    assert "-- no rounds have run --" not in page
    assert "-- no rounds have run --" not in tail
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
        .get(
            "/work/GH8-20260819-184158-conversation/tail",
            query_string={"cursor": f"1:{cursor}"},
        )
    )

    assert response.status_code == 200
    assert "One more detail." in response.text
    assert f'value="1:{feed.stat().st_size}"' in response.text
    assert 'id="agent-work-status"' in response.text


def test_an_ended_conversation_stops_empty_tail_polling(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    write_ending(
        directory=find_conversation_directory(state=state, issue=8),
        reason=AgentWorkEndReason.COMPLETED,
        at=PINNED + timedelta(minutes=5),
    )
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    feed = conversation.compose_round_paths(number=1).feed

    response = (
        application(state=state)
        .test_client()
        .get(
            "/work/GH8-20260819-184158-conversation/tail",
            query_string={"cursor": f"1:{feed.stat().st_size}"},
        )
    )

    assert response.status_code == 286


def test_a_waiting_conversation_keeps_empty_tail_polling(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, has_round=False, is_paused=False)

    response = (
        application(state=state)
        .test_client()
        .get(
            "/work/GH8-20260819-184158-conversation/tail",
            query_string={"cursor": "0:0"},
        )
    )

    assert response.status_code == 200


def test_a_faulted_conversation_keeps_empty_tail_polling(tmp_path):
    state = StateDirectory(root=tmp_path)
    _fabricate_faulted_conversation(state=state)
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None

    response = (
        application(state=state)
        .test_client()
        .get(
            "/work/GH8-20260819-184158-conversation/tail",
            query_string={"cursor": "2:0"},
        )
    )

    assert response.status_code == 200


def test_a_routing_conflict_keeps_empty_conversation_tail_polling(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, is_paused=False)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                compose_conversation_row(
                    finding=ConflictingLabelsFinding(labels=["discuss", "scout"])
                )
            ],
        ),
    )
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    feed = conversation.compose_round_paths(number=1).feed

    response = (
        application(state=state)
        .test_client()
        .get(
            "/work/GH8-20260819-184158-conversation/tail",
            query_string={"cursor": f"1:{feed.stat().st_size}"},
        )
    )

    assert response.status_code == 200


def test_conversation_tail_adds_a_later_round_without_repeating_the_first(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state, is_paused=False)
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    first_feed = conversation.compose_round_paths(number=1).feed
    directory = find_conversation_directory(state=state, issue=8)
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED + timedelta(minutes=6),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=10), status=0
            ),
        ),
        round_input=ConversationRoundInput(
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
            rows=[
                compose_conversation_row(
                    finding=PausedFinding(cause=PauseCause.LABEL_REMOVED)
                )
            ],
        ),
    )

    response = (
        application(state=state)
        .test_client()
        .get(
            "/work/GH8-20260819-184158-conversation/tail",
            query_string={"cursor": f"1:{first_feed.stat().st_size}"},
        )
    )

    assert response.status_code == 200
    assert "I found the answer." not in response.text
    assert 'id="agent-work-detail"' in response.text
    assert "paused, label removed" in response.text
    assert response.text.count("round 2: 1 comment") == 1
    assert response.text.count("code revision abc123 -&gt; def456") == 1
    assert response.text.count("I found the follow-up answer.") == 1


def test_conversation_tail_refuses_an_invalid_cursor(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)

    response = (
        application(state=state)
        .test_client()
        .get(
            "/work/GH8-20260819-184158-conversation/tail",
            query_string={"cursor": "not-a-cursor"},
        )
    )

    assert response.status_code == 400
    assert "feed cursor is invalid" in response.text


def test_missing_conversation_pages_answer_not_found(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = application(state=state).test_client()

    page = client.get("/work/GH8-20260819-184158-conversation")
    tail = client.get(
        "/work/GH8-20260819-184158-conversation/tail", query_string={"cursor": "0:0"}
    )

    assert page.status_code == 404
    assert tail.status_code == 404
    assert (
        "No agent work here has identifier GH8-20260819-184158-conversation."
        in page.text
    )


def fabricate_unsaved_conversation(*, state: StateDirectory) -> None:
    """Write a tick that found a comment to answer at GH9, which has no record."""
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                compose_request_row(
                    issue=9,
                    kind=AgentWorkKind.CONVERSATION,
                    finding=IssueCommentsFinding(new_comments=1),
                )
            ],
        ),
    )


def test_home_lists_a_conversation_request_before_its_conversation_is_saved(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)
    fabricate_unsaved_conversation(state=state)

    page = application(state=state).test_client().get("/").text

    assert 'id="request-9-dream%3Aconversation"' in page
    assert "Open conversation #9" not in page
    assert (
        '<span class="chip status-available"><span>1 comment to answer</span></span>'
        in page
    )


def test_home_lists_conversations_in_attention_order_before_requests(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    write_running_conversation(state=state, issue=11, started=PINNED)
    write_feed(
        directory=find_conversation_directory(state=state, issue=11),
        number=1,
        lines=[FeedLine(at=PINNED, text="Still working.")],
    )
    hold_daemon_lock_for_test(path=state.lock)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                compose_conversation_row(finding=IssueCommentsFinding(new_comments=0)),
                compose_conversation_row(
                    issue=11, finding=IssueCommentsFinding(new_comments=0)
                ),
                compose_request_row(
                    issue=9,
                    kind=AgentWorkKind.CONVERSATION,
                    finding=IssueCommentsFinding(new_comments=0),
                ),
                compose_request_row(
                    issue=10,
                    kind=AgentWorkKind.CONVERSATION,
                    finding=IssueCommentsFinding(new_comments=1),
                ),
                compose_request_row(
                    issue=12,
                    kind=AgentWorkKind.CONVERSATION,
                    finding=ReadFailureFinding(reason="gh: offline"),
                ),
            ],
        ),
    )

    page = application(state=state).test_client().get("/").text

    assert (
        page.index('id="GH11-20260819-184158-conversation"')
        < page.index('id="GH8-20260819-184158-conversation"')
        < page.index('id="request-9-dream%3Aconversation"')
        < page.index('id="request-10-dream%3Aconversation"')
        < page.index('id="request-12-dream%3Aconversation"')
    )
    assert "status-working" in page
    assert (
        '<span class="chip status-unknown"><span>cannot tell: gh: offline</span></span>'
        in page
    )
    assert '<p class="latest-output"><span>agent</span> Still working.</p>' in page


def test_home_collapses_an_ended_conversation(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    fabricate_conversation(state=state)
    write_ending(
        directory=find_conversation_directory(state=state, issue=8),
        reason=AgentWorkEndReason.COMPLETED,
        at=PINNED + timedelta(minutes=10),
    )

    page = application(state=state).test_client().get("/").text

    conversations = page[page.index('id="conversation-panel"') :]
    ended = conversations[conversations.index('<details class="ended-work">') :]
    assert "<summary>+ 1 ended</summary>" in ended
    assert 'id="GH8-20260819-184158-conversation"' in ended
    assert '<span class="chip status-ended">ended</span>' in ended
