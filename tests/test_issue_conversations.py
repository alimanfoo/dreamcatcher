import json
from datetime import UTC, datetime

import pytest
from clocks import PINNED

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    ConversationRoundPurpose,
)
from dreamcatcher.config import AgentHarness, ConversationRoute, DispatchRecipe
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
    CONVERSATION_RECORD_NAME,
    Conversation,
    ConversationInput,
    ConversationRecord,
    InitialConversationIssue,
    IssueCommentCursor,
    create_conversation,
    describe_conversation_revision,
    list_undelivered_issue_comments,
    post_conversation_answer,
    prepare_conversation_input,
    read_conversation,
    read_conversation_input,
    read_conversations,
    read_issue_comment_delivery_cursor,
    record_conversation_session_identifier,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.state import StateDirectory

PROMPT_TEMPLATE = "/dream:conversation GH" + "{issue}"
CODEX_PROMPT_TEMPLATE = "$dream:conversation GH" + "{issue}"


def conversation_route() -> ConversationRoute:
    return ConversationRoute(
        label="dream:conversation",
        claude=DispatchRecipe(
            prompt=PROMPT_TEMPLATE,
            model="opus[1m]",
            effort="xhigh",
        ),
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


def write_conversation(*, state: StateDirectory, number: int = 8) -> Conversation:
    directory = state.conversations / f"GH{number}"
    record = ConversationRecord(
        issue=number,
        title="Why does this happen?",
        dispatch_label="dream:conversation",
        harness=AgentHarness.CLAUDE,
        model="opus[1m]",
        effort="xhigh",
        prompt=PROMPT_TEMPLATE,
    )
    write_json(document=record, path=directory / CONVERSATION_RECORD_NAME)
    conversation = read_conversation(state=state, issue=number)
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

    assert read_conversations(state=state) == []
    assert read_conversation(state=state, issue=8) is None


def test_a_conversation_gets_a_detached_worktree_at_fetched_main(cloned):
    state = StateDirectory(root=cloned)

    created = create_conversation(
        state=state,
        route=conversation_route(),
        requested_harness=AgentHarness.CLAUDE,
        issue=issue(),
    )

    assert created.identifier == "conversation-GH8"
    assert created.worktree == state.conversation_worktrees / "GH8"
    assert created.worktree.joinpath(".git").is_file()
    assert created.record.title == "Why does this happen?"
    assert created.record.harness == AgentHarness.CLAUDE
    assert not state.worktrees.exists()
    assert read_conversations(state=state) == [created]
    assert (
        create_conversation(
            state=state,
            route=ConversationRoute(
                label="dream:scout",
                codex=DispatchRecipe(
                    prompt="$dream:conversation GH{issue}",
                    model="gpt-5.6-sol",
                    effort="high",
                ),
            ),
            requested_harness=AgentHarness.CODEX,
            issue=issue(),
        )
        == created
    )
    assert created.record.dispatch_label == "dream:conversation"


def test_a_new_conversation_records_the_requested_harness_recipe(cloned):
    state = StateDirectory(root=cloned)
    route = ConversationRoute(
        label="dream:conversation",
        claude=conversation_route().recipes[AgentHarness.CLAUDE],
        codex=DispatchRecipe(
            prompt=CODEX_PROMPT_TEMPLATE,
            model="gpt-5.6-sol",
            effort="high",
        ),
    )

    created = create_conversation(
        state=state,
        route=route,
        requested_harness=AgentHarness.CODEX,
        issue=issue(),
    )

    assert created.record.harness == AgentHarness.CODEX
    assert created.record.prompt == CODEX_PROMPT_TEMPLATE
    assert created.record.model == "gpt-5.6-sol"
    assert created.record.effort == "high"


def test_an_unrecorded_conversation_worktree_is_not_forced_away(cloned):
    state = StateDirectory(root=cloned)
    path = state.conversation_worktrees / "GH8"
    add_detached_worktree(root=cloned, path=path)

    with pytest.raises(ReportableError) as error:
        create_conversation(
            state=state,
            route=conversation_route(),
            requested_harness=AgentHarness.CLAUDE,
            issue=issue(),
        )

    assert "its unrecorded worktree already exists" in str(error.value)


def test_a_failed_conversation_setup_removes_the_worktree_it_added(cloned, monkeypatch):
    state = StateDirectory(root=cloned)
    path = state.conversation_worktrees / "GH8"

    def fail_record_write(*, document, path):
        raise ReportableError(f"cannot write the record at {path}")

    monkeypatch.setattr(
        "dreamcatcher.issue_conversations.write_json",
        fail_record_write,
    )

    with pytest.raises(ReportableError, match="cannot write the record"):
        create_conversation(
            state=state,
            route=conversation_route(),
            requested_harness=AgentHarness.CLAUDE,
            issue=issue(),
        )

    assert not is_linked_worktree(path=path)


def test_a_conversation_record_must_name_its_directory(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    wrong_directory = state.conversations / "GH9"
    write_json(
        document=conversation.record,
        path=wrong_directory / CONVERSATION_RECORD_NAME,
    )

    with pytest.raises(ReportableError) as error:
        read_conversations(state=state)

    assert "records GH8, but its directory is GH9" in str(error.value)


def test_a_non_object_conversation_record_is_reportable(tmp_path):
    state = StateDirectory(root=tmp_path)
    record = state.conversations / "GH8" / CONVERSATION_RECORD_NAME
    record.parent.mkdir(parents=True)
    record.write_bytes(b"null")

    with pytest.raises(ReportableError):
        read_conversation(state=state, issue=8)


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


def test_round_input_freezes_the_issue_comments_and_revision(cloned):
    state = StateDirectory(root=cloned)
    conversation = create_conversation(
        state=state,
        route=conversation_route(),
        requested_harness=AgentHarness.CLAUDE,
        issue=issue(),
    )

    frozen = prepare_conversation_input(
        state=state,
        conversation=conversation,
        issue=issue(),
        comments=[comment(identifier=1, body="Please explain.")],
    )

    assert frozen.issue == 8
    assert frozen.initial_issue == InitialConversationIssue(
        title="Why does this happen?",
        body="Explain the scheduler.",
    )
    assert frozen.comments[0].body == "Please explain."
    assert frozen.revision


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (None, "abc123", "code revision abc123"),
        ("abc123", "abc123", "code revision abc123 (unchanged)"),
        ("abc123", "def456", "code revision abc123 -> def456"),
    ],
)
def test_a_conversation_revision_description_names_its_transition(
    previous, current, expected
):
    assert (
        describe_conversation_revision(
            previous_revision=previous,
            revision=current,
        )
        == expected
    )


def test_an_initial_round_requires_the_issue_text(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    path = conversation.compose_round_paths(number=1).round_input
    write_json(
        document=ConversationInput(
            issue=8,
            comments=[comment(identifier=1, body="Question")],
            revision="abc123",
        ),
        path=path,
    )

    with pytest.raises(ReportableError, match="initial issue title and body"):
        read_conversation_input(conversation=conversation, number=1)


def test_a_follow_up_can_omit_the_issue_text(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    path = conversation.compose_round_paths(number=2).round_input
    write_json(
        document=ConversationInput(
            issue=8,
            comments=[comment(identifier=2, body="Question")],
            revision="def456",
        ),
        path=path,
    )

    found = read_conversation_input(conversation=conversation, number=2)

    assert found.initial_issue is None
    assert "initial_issue" not in json.loads(path.read_text(encoding="utf-8"))


def test_a_follow_up_from_an_earlier_version_can_keep_issue_text(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    path = conversation.compose_round_paths(number=2).round_input
    write_json(
        document=ConversationInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title="Why does this happen?",
                body="Explain the scheduler.",
            ),
            comments=[comment(identifier=2, body="Question")],
            revision="def456",
        ),
        path=path,
    )

    found = read_conversation_input(conversation=conversation, number=2)

    assert found.initial_issue == InitialConversationIssue(
        title="Why does this happen?",
        body="Explain the scheduler.",
    )


def test_a_conversation_records_its_session_and_round_paths(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)

    record_conversation_session_identifier(
        conversation=conversation, identifier="abc-123"
    )
    record_conversation_session_identifier(
        conversation=conversation, identifier="abc-123"
    )

    assert conversation.record.harness_session_identifier == "abc-123"
    assert conversation.next_round_number == 1
    paths = conversation.compose_round_paths(number=1)
    write_json(
        document=AgentRoundRecord(
            number=1,
            purpose=ConversationRoundPurpose.DISCUSS,
            started=PINNED,
            pid=123,
        ),
        path=paths.record,
    )
    reread = read_conversation(state=StateDirectory(root=tmp_path), issue=8)
    assert reread is not None
    assert reread.next_round_number == 2

    with pytest.raises(ReportableError) as error:
        record_conversation_session_identifier(
            conversation=conversation, identifier="other-456"
        )
    assert "after it already reported abc-123" in str(error.value)


def test_the_delivery_cursor_comes_from_the_latest_round_input(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    for number, identifier in ((1, 3), (2, 4)):
        paths = conversation.compose_round_paths(number=number)
        write_json(
            document=ConversationInput(
                issue=8,
                initial_issue=InitialConversationIssue(
                    title="Why does this happen?",
                    body="Explain the scheduler.",
                ),
                comments=[comment(identifier=identifier, body="Question")],
                revision="abc123",
            ),
            path=paths.round_input,
        )
        write_json(
            document=AgentRoundRecord(
                number=number,
                purpose=ConversationRoundPurpose.DISCUSS,
                started=PINNED,
                pid=123,
            ),
            path=paths.record,
        )
    reread = read_conversation(state=state, issue=8)
    assert reread is not None

    cursor = read_issue_comment_delivery_cursor(conversation=reread)

    assert cursor == IssueCommentCursor(written_at="2026-09-23T01:00:00Z", id=4)


def test_the_delivery_cursor_refuses_a_round_without_comments(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    paths = conversation.compose_round_paths(number=1)
    write_json(
        document=ConversationInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title="Why does this happen?",
                body="Explain the scheduler.",
            ),
            comments=[],
            revision="abc123",
        ),
        path=paths.round_input,
    )
    write_json(
        document=AgentRoundRecord(
            number=1,
            purpose=ConversationRoundPurpose.DISCUSS,
            started=PINNED,
            pid=123,
        ),
        path=paths.record,
    )
    reread = read_conversation(state=state, issue=8)
    assert reread is not None

    with pytest.raises(ReportableError, match="has no delivered issue comments"):
        read_issue_comment_delivery_cursor(conversation=reread)


@pytest.mark.parametrize(
    ("input_issue", "comment_identifiers", "message"),
    [
        (9, [3], "input names GH9"),
        (8, [4, 3], "comments are not strictly ordered"),
    ],
)
def test_the_delivery_cursor_refuses_inconsistent_round_input(
    tmp_path, input_issue, comment_identifiers, message
):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    paths = conversation.compose_round_paths(number=1)
    write_json(
        document=ConversationInput(
            issue=input_issue,
            initial_issue=InitialConversationIssue(
                title="Why does this happen?",
                body="Explain the scheduler.",
            ),
            comments=[
                comment(identifier=identifier, body="Question")
                for identifier in comment_identifiers
            ],
            revision="abc123",
        ),
        path=paths.round_input,
    )
    write_json(
        document=AgentRoundRecord(
            number=1,
            purpose=ConversationRoundPurpose.DISCUSS,
            started=PINNED,
            pid=123,
        ),
        path=paths.record,
    )
    reread = read_conversation(state=state, issue=8)
    assert reread is not None

    with pytest.raises(ReportableError, match=message):
        read_issue_comment_delivery_cursor(conversation=reread)


def test_an_answer_is_posted_trimmed_and_marked(fake):
    gh = fake(program="gh")
    gh.replies(stdout=json.dumps({"id": 91}))

    post_conversation_answer(
        repository="alimanfoo/dreamcatcher", issue=8, final_output="  The answer.\n"
    )

    assert json.loads(gh.calls[0].prompt) == {
        "body": f"The answer.\n\n> written by an agent\n\n{AGENT_POST_MARKER}"
    }


def test_no_reply_posts_nothing(fake):
    gh = fake(program="gh")

    post_conversation_answer(
        repository="alimanfoo/dreamcatcher", issue=8, final_output=" NO_REPLY\n"
    )

    assert gh.calls == []


@pytest.mark.parametrize("final_output", [None, "   \n"])
def test_a_missing_or_empty_answer_is_reportable(fake, final_output):
    gh = fake(program="gh")

    with pytest.raises(ReportableError, match="the harness returned no final output"):
        post_conversation_answer(
            repository="alimanfoo/dreamcatcher", issue=8, final_output=final_output
        )

    assert gh.calls == []


def test_an_answer_github_refuses_is_reportable(fake):
    fake(program="gh").fails(stderr="issue is locked")

    with pytest.raises(ReportableError) as error:
        post_conversation_answer(
            repository="alimanfoo/dreamcatcher", issue=8, final_output="The answer."
        )

    assert str(error.value).startswith("could not post the answer on GH8: ")
    assert "issue is locked" in str(error.value)
