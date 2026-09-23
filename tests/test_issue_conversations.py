from datetime import UTC, datetime

import pytest
from clocks import PINNED

from dreamcatcher.agent_rounds import (
    AgentRoundPurpose,
    AgentRoundRecord,
    IssueConversationInput,
)
from dreamcatcher.config import AgentHarness, IssueConversationConfig
from dreamcatcher.documents import write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import add_detached_worktree, is_linked_worktree
from dreamcatcher.github import (
    ConversationComment,
    GitHubIssueLabel,
    GitHubUserAccount,
    Issue,
    IssueState,
)
from dreamcatcher.issue_conversations import (
    ISSUE_CONVERSATION_RECORD_NAME,
    IssueCommentCursor,
    IssueConversation,
    IssueConversationRecord,
    advance_issue_comment_delivery_cursor,
    compose_issue_conversation_input,
    create_issue_conversation,
    list_undelivered_issue_comments,
    read_issue_conversation,
    read_issue_conversation_reply,
    read_issue_conversations,
    record_issue_conversation_reply_publication,
    record_issue_conversation_session_identifier,
    restore_issue_comment_delivery_cursor,
    save_issue_conversation_reply,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.state import StateDirectory

PROMPT_TEMPLATE = "/dream:conversation GH" + "{issue}"


def conversation_config() -> IssueConversationConfig:
    return IssueConversationConfig(
        label="dream:conversation",
        harness=AgentHarness.CLAUDE,
        prompt=PROMPT_TEMPLATE,
        model="opus[1m]",
        effort="xhigh",
    )


def issue(*, number: int = 8) -> Issue:
    return Issue(
        number=number,
        title="Why does this happen?",
        body="Explain the scheduler.",
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        state=IssueState.OPEN,
        assignees=[GitHubUserAccount(login="alimanfoo")],
        labels=[GitHubIssueLabel(name="dream:conversation")],
    )


def write_conversation(*, state: StateDirectory, number: int = 8) -> IssueConversation:
    directory = state.conversations / f"GH{number}"
    record = IssueConversationRecord(
        issue=number,
        title="Why does this happen?",
        label="dream:conversation",
        worktree=state.conversation_worktrees / f"GH{number}",
        revision="abc123",
        harness=AgentHarness.CLAUDE,
        model="opus[1m]",
        effort="xhigh",
        prompt=PROMPT_TEMPLATE,
    )
    write_json(document=record, path=directory / ISSUE_CONVERSATION_RECORD_NAME)
    conversation = read_issue_conversation(state=state, issue=number)
    assert conversation is not None
    return conversation


def comment(
    *,
    identifier: int,
    body: str,
    author: str = "alimanfoo",
    written_at: str = "2026-09-23T01:00:00Z",
) -> ConversationComment:
    return ConversationComment(
        id=identifier,
        author=author,
        written_at=written_at,
        body=body,
    )


def test_a_missing_conversation_reads_as_nothing(tmp_path):
    state = StateDirectory(root=tmp_path)

    assert read_issue_conversations(state=state) == []
    assert read_issue_conversation(state=state, issue=8) is None


def test_a_conversation_gets_a_detached_worktree_at_fetched_main(cloned):
    state = StateDirectory(root=cloned)

    created = create_issue_conversation(
        state=state, config=conversation_config(), issue=issue()
    )

    assert created.identifier == "conversation-GH8"
    assert created.record.worktree == state.conversation_worktrees / "GH8"
    assert created.record.worktree.joinpath(".git").is_file()
    assert created.record.revision
    assert created.record.title == "Why does this happen?"
    assert not state.worktrees.exists()
    assert read_issue_conversations(state=state) == [created]
    assert (
        create_issue_conversation(
            state=state, config=conversation_config(), issue=issue()
        )
        == created
    )


def test_an_unrecorded_conversation_worktree_is_not_forced_away(cloned):
    state = StateDirectory(root=cloned)
    path = state.conversation_worktrees / "GH8"
    add_detached_worktree(root=cloned, path=path)

    with pytest.raises(ReportableError) as error:
        create_issue_conversation(
            state=state, config=conversation_config(), issue=issue()
        )

    assert "its unrecorded worktree already exists" in str(error.value)


def test_a_failed_conversation_setup_removes_the_worktree_it_added(cloned, monkeypatch):
    state = StateDirectory(root=cloned)
    path = state.conversation_worktrees / "GH8"

    def fail_revision_read(*, worktree):
        raise ReportableError(f"cannot read the revision at {worktree}")

    monkeypatch.setattr(
        "dreamcatcher.issue_conversations.read_worktree_revision",
        fail_revision_read,
    )

    with pytest.raises(ReportableError, match="cannot read the revision"):
        create_issue_conversation(
            state=state, config=conversation_config(), issue=issue()
        )

    assert not is_linked_worktree(path=path)


def test_a_conversation_record_must_name_its_directory(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    wrong_directory = state.conversations / "GH9"
    write_json(
        document=conversation.record,
        path=wrong_directory / ISSUE_CONVERSATION_RECORD_NAME,
    )

    with pytest.raises(ReportableError) as error:
        read_issue_conversations(state=state)

    assert "records GH8, but its directory is GH9" in str(error.value)


def test_only_new_unmarked_comments_from_the_account_are_delivered():
    cursor = IssueCommentCursor(written_at="2026-09-23T01:00:00Z", id=2)
    comments = [
        comment(identifier=4, body="later in the list"),
        comment(identifier=1, body="before the cursor"),
        comment(identifier=3, body="first after the cursor"),
        comment(identifier=5, body="somebody else", author="mallory"),
        comment(identifier=6, body=f"agent answer\n{AGENT_POST_MARKER}"),
        comment(identifier=7, body="  "),
    ]

    delivered = list_undelivered_issue_comments(
        comments=comments, account="ALIMANFOO", cursor=cursor
    )

    assert [item.id for item in delivered] == [3, 4]
    assert [
        item.id
        for item in list_undelivered_issue_comments(
            comments=comments, account="alimanfoo", cursor=None
        )
    ] == [1, 3, 4]


def test_round_input_freezes_the_issue_comments_and_revision():
    frozen = compose_issue_conversation_input(
        issue=issue(),
        comments=[comment(identifier=1, body="Please explain.")],
        revision="abc123",
    )

    assert frozen.issue == 8
    assert frozen.title == "Why does this happen?"
    assert frozen.body == "Explain the scheduler."
    assert frozen.comments[0].body == "Please explain."
    assert frozen.revision == "abc123"


def test_a_conversation_records_delivery_session_and_round_paths(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)

    advance_issue_comment_delivery_cursor(
        conversation=conversation, newest=comment(identifier=3, body="Question")
    )
    record_issue_conversation_session_identifier(
        conversation=conversation, identifier="abc-123"
    )
    record_issue_conversation_session_identifier(
        conversation=conversation, identifier="abc-123"
    )

    assert conversation.record.delivery_cursor == IssueCommentCursor(
        written_at="2026-09-23T01:00:00Z", id=3
    )
    assert conversation.record.harness_session_identifier == "abc-123"
    assert conversation.next_round_number == 1
    paths = conversation.compose_round_paths(number=1)
    write_json(
        document=AgentRoundRecord(
            number=1,
            purpose=AgentRoundPurpose.DISCUSS,
            started=PINNED,
            pid=123,
        ),
        path=paths.record,
    )
    reread = read_issue_conversation(state=StateDirectory(root=tmp_path), issue=8)
    assert reread is not None
    assert reread.next_round_number == 2
    assert reread.compose_reply_path(number=1) == paths.directory / "reply.json"

    with pytest.raises(ReportableError) as error:
        record_issue_conversation_session_identifier(
            conversation=conversation, identifier="other-456"
        )
    assert "after it already reported abc-123" in str(error.value)


def test_a_missing_delivery_cursor_is_restored_from_the_round_input(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    paths = conversation.compose_round_paths(number=1)
    delivered = comment(identifier=3, body="Question")
    write_json(
        document=IssueConversationInput(
            issue=8,
            title="Why does this happen?",
            body="Explain the scheduler.",
            comments=[delivered],
            revision="abc123",
        ),
        path=paths.round_input,
    )
    write_json(
        document=AgentRoundRecord(
            number=1,
            purpose=AgentRoundPurpose.DISCUSS,
            started=PINNED,
            pid=123,
        ),
        path=paths.record,
    )
    reread = read_issue_conversation(state=state, issue=8)
    assert reread is not None

    restore_issue_comment_delivery_cursor(conversation=reread)

    assert reread.record.delivery_cursor == IssueCommentCursor(
        written_at=delivered.written_at, id=delivered.id
    )
    restore_issue_comment_delivery_cursor(conversation=reread)


def test_a_missing_delivery_cursor_refuses_a_round_without_comments(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    paths = conversation.compose_round_paths(number=1)
    write_json(
        document=IssueConversationInput(
            issue=8,
            title="Why does this happen?",
            body="Explain the scheduler.",
            comments=[],
            revision="abc123",
        ),
        path=paths.round_input,
    )
    write_json(
        document=AgentRoundRecord(
            number=1,
            purpose=AgentRoundPurpose.DISCUSS,
            started=PINNED,
            pid=123,
        ),
        path=paths.record,
    )
    reread = read_issue_conversation(state=state, issue=8)
    assert reread is not None

    with pytest.raises(ReportableError, match="has no delivered issue comments"):
        restore_issue_comment_delivery_cursor(conversation=reread)


def test_a_reply_is_saved_before_its_publication_is_recorded(tmp_path):
    conversation = write_conversation(state=StateDirectory(root=tmp_path))

    assert read_issue_conversation_reply(conversation=conversation, number=1) is None
    reply = save_issue_conversation_reply(
        conversation=conversation, number=1, body="  The answer.\n"
    )

    assert reply.body == "The answer."
    assert not reply.is_no_reply
    assert not reply.is_complete
    published = record_issue_conversation_reply_publication(
        conversation=conversation, number=1, at=PINNED
    )
    assert published.published_at == PINNED
    assert published.is_complete


def test_no_reply_completes_without_publication(tmp_path):
    conversation = write_conversation(state=StateDirectory(root=tmp_path))

    reply = save_issue_conversation_reply(
        conversation=conversation, number=1, body=" NO_REPLY\n"
    )

    assert reply.is_no_reply
    assert reply.is_complete


def test_publication_requires_a_saved_reply(tmp_path):
    conversation = write_conversation(state=StateDirectory(root=tmp_path))

    with pytest.raises(ReportableError) as error:
        record_issue_conversation_reply_publication(
            conversation=conversation, number=1, at=PINNED
        )

    assert "has no saved reply to publish" in str(error.value)
