import json
from datetime import UTC, datetime

import pytest
from clocks import PINNED
from records import read_conversation

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkRecord,
    _record_agent_work,
    create_agent_work,
    read_agent_work,
)
from dreamcatcher.config import (
    AgentHarness,
    ClaudeRecipe,
    CodexRecipe,
    ConversationRoute,
)
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    GitHubLabel,
    GitHubUserAccount,
    Issue,
    IssueComment,
    IssueState,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import (
    ConversationRoundInput,
    InitialConversationIssue,
    IssueCommentCursor,
    list_issue_comments_past_cursor,
    post_conversation_answer,
    prepare_conversation_round,
    read_conversation_input,
    read_issue_comment_cursor,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.state import StateDirectory

PROMPT_TEMPLATE = "/dream:conversation GH" + "{issue}"
CODEX_PROMPT_TEMPLATE = "$dream:conversation GH" + "{issue}"


def conversation_route() -> ConversationRoute:
    return ConversationRoute(
        label="dream:conversation",
        claude=ClaudeRecipe(
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
        labels=[GitHubLabel(name="dream:conversation")],
    )


def write_conversation(*, state: StateDirectory, number: int = 8) -> AgentWork:
    return _record_agent_work(
        state=state,
        identifier=f"GH{number}-20260923-010000-conversation",
        record=AgentWorkRecord(
            issue=number,
            title="Why does this happen?",
            dispatch_label="dream:conversation",
            kind=AgentWorkKind.CONVERSATION,
            harness=AgentHarness.CLAUDE,
            model="opus[1m]",
            effort="xhigh",
            instructions=f"/dream:conversation GH{number}",
        ),
    )


def comment(
    *,
    identifier: int,
    body: str,
    author: str = "alimanfoo",
    written_at: str = "2026-09-23T01:00:00Z",
) -> IssueComment:
    return IssueComment(
        id=identifier,
        author=author,
        written_at=written_at,
        body=body,
    )


def test_a_conversation_is_recorded_without_a_worktree(tmp_path):
    state = StateDirectory(root=tmp_path)

    created = create_agent_work(
        state=state,
        route=conversation_route(),
        preferred_harness=AgentHarness.CLAUDE,
        issue=8,
        title="Why does this happen?",
        at=PINNED,
    )

    assert created.identifier == "GH8-20260819-184158-conversation"
    assert created.worktree == state.worktrees / created.identifier
    assert not created.worktree.exists()
    assert created.record.kind is AgentWorkKind.CONVERSATION
    assert created.record.title == "Why does this happen?"
    assert created.record.harness == AgentHarness.CLAUDE
    assert created.record.dispatch_label == "dream:conversation"
    assert read_agent_work(state=state) == [created]


def test_a_new_conversation_records_the_preferred_harness_recipe(cloned):
    state = StateDirectory(root=cloned)
    route = ConversationRoute(
        label="dream:conversation",
        claude=conversation_route().claude,
        codex=CodexRecipe(
            prompt=CODEX_PROMPT_TEMPLATE,
            model="gpt-5.6-sol",
            effort="high",
        ),
    )

    created = create_agent_work(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CODEX,
        issue=8,
        title="Why does this happen?",
        at=PINNED,
    )

    assert created.record.harness == AgentHarness.CODEX
    assert created.record.instructions == "$dream:conversation GH8"
    assert created.record.model == "gpt-5.6-sol"
    assert created.record.effort == "high"


def test_only_new_unmarked_comments_from_the_account_are_relayed():
    cursor = IssueCommentCursor(written_at="2026-09-23T01:00:00Z", id=2)
    comments = [
        comment(identifier=4, body="later in the list"),
        comment(identifier=1, body="before the cursor"),
        comment(identifier=3, body="first after the cursor"),
        comment(identifier=5, body="somebody else", author="mallory"),
        comment(identifier=6, body=f"agent answer\n{AGENT_POST_MARKER}"),
        comment(identifier=7, body="  "),
    ]

    relayed = list_issue_comments_past_cursor(
        comments=comments, account="ALIMANFOO", cursor=cursor
    )

    assert [item.id for item in relayed] == [3, 4]
    assert [
        item.id
        for item in list_issue_comments_past_cursor(
            comments=comments, account="alimanfoo", cursor=None
        )
    ] == [1, 3, 4]


@pytest.mark.parametrize(
    ("is_resuming", "initial_issue"),
    [
        (
            False,
            InitialConversationIssue(
                title="Why does this happen?", body="Explain the scheduler."
            ),
        ),
        (True, None),
    ],
)
def test_round_input_freezes_the_issue_comments_and_revision(
    cloned, is_resuming, initial_issue
):
    state = StateDirectory(root=cloned)
    conversation = create_agent_work(
        state=state,
        route=conversation_route(),
        preferred_harness=AgentHarness.CLAUDE,
        issue=8,
        title="Why does this happen?",
        at=PINNED,
    )

    frozen = prepare_conversation_round(
        state=state,
        conversation=conversation,
        issue=issue(),
        comments=[comment(identifier=1, body="Please explain.")],
        is_resuming=is_resuming,
    )

    assert frozen.issue == 8
    assert frozen.initial_issue == initial_issue
    assert frozen.comments[0].body == "Please explain."
    assert frozen.revision
    assert conversation.worktree.joinpath(".git").is_file()


def test_a_follow_up_can_omit_the_issue_text(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    path = conversation.compose_round_paths(number=2).round_input
    write_json(
        document=ConversationRoundInput(
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
        document=ConversationRoundInput(
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


def test_a_conversation_numbers_its_rounds_by_their_records(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)

    assert conversation.next_round_number == 1
    paths = conversation.compose_round_paths(number=1)
    write_json(
        document=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=123,
        ),
        path=paths.record,
    )
    reread = read_conversation(state=StateDirectory(root=tmp_path), issue=8)
    assert reread is not None
    assert reread.next_round_number == 2


def test_a_conversation_recovers_a_session_reported_by_a_later_round(tmp_path):
    conversation = write_conversation(state=StateDirectory(root=tmp_path))
    for number in (1, 2):
        paths = conversation.compose_round_paths(number=number)
        write_json(
            document=AgentRoundRecord(
                number=number,
                started=PINNED,
                pid=1,
            ),
            path=paths.record,
        )
    write_text(
        text=(
            '{"type":"system","subtype":"init","model":"claude-opus-5",'
            '"session_id":"replacement-session"}\n'
        ),
        path=conversation.compose_round_paths(number=2).raw_output,
    )
    reread = read_conversation(state=StateDirectory(root=tmp_path), issue=8)
    assert reread is not None

    recovered = reread.find_harness_session_identifier()

    assert recovered == "replacement-session"


@pytest.mark.parametrize(
    ("third_round_ending", "newest_identifier"),
    [
        (SuccessfulAgentRoundEnding(at=PINNED), 5),
        (StoppedAgentRoundEnding(at=PINNED), 5),
        (ErroredAgentRoundEnding(at=PINNED, status=1), 4),
        (InterruptedAgentRoundEnding(), 4),
        (None, 5),
    ],
)
def test_the_cursor_comes_from_the_latest_relayed_round(
    tmp_path, third_round_ending, newest_identifier
):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    endings = {3: third_round_ending}
    for number, identifier in ((1, 3), (2, 4), (3, 5)):
        paths = conversation.compose_round_paths(number=number)
        write_json(
            document=ConversationRoundInput(
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
                started=PINNED,
                pid=123,
                ending=endings.get(number, SuccessfulAgentRoundEnding(at=PINNED)),
            ),
            path=paths.record,
        )
    reread = read_conversation(state=state, issue=8)
    assert reread is not None

    cursor = read_issue_comment_cursor(conversation=reread)

    assert cursor == IssueCommentCursor(
        written_at="2026-09-23T01:00:00Z", id=newest_identifier
    )


def test_a_stopped_round_that_wrote_no_input_leaves_the_cursor(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    first = conversation.compose_round_paths(number=1)
    write_json(
        document=ConversationRoundInput(
            issue=8,
            comments=[comment(identifier=3, body="Question")],
            revision="abc123",
        ),
        path=first.round_input,
    )
    for number in (1, 2):
        write_json(
            document=AgentRoundRecord(
                number=number,
                started=PINNED,
                ending=StoppedAgentRoundEnding(at=PINNED),
            ),
            path=conversation.compose_round_paths(number=number).record,
        )
    reread = read_conversation(state=state, issue=8)
    assert reread is not None

    assert read_issue_comment_cursor(conversation=reread) == IssueCommentCursor(
        written_at="2026-09-23T01:00:00Z", id=3
    )


def test_the_cursor_refuses_a_round_without_comments(tmp_path):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    paths = conversation.compose_round_paths(number=1)
    write_json(
        document=ConversationRoundInput(
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
            started=PINNED,
            pid=123,
            ending=SuccessfulAgentRoundEnding(at=PINNED),
        ),
        path=paths.record,
    )
    reread = read_conversation(state=state, issue=8)
    assert reread is not None

    with pytest.raises(ReportableError, match="relayed no issue comments"):
        read_issue_comment_cursor(conversation=reread)


@pytest.mark.parametrize(
    ("input_issue", "comment_identifiers", "message"),
    [
        (9, [3], "input names GH9"),
        (8, [4, 3], "comments are not strictly ordered"),
    ],
)
def test_the_cursor_refuses_inconsistent_round_input(
    tmp_path, input_issue, comment_identifiers, message
):
    state = StateDirectory(root=tmp_path)
    conversation = write_conversation(state=state)
    paths = conversation.compose_round_paths(number=1)
    write_json(
        document=ConversationRoundInput(
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
            started=PINNED,
            pid=123,
            ending=SuccessfulAgentRoundEnding(at=PINNED),
        ),
        path=paths.record,
    )
    reread = read_conversation(state=state, issue=8)
    assert reread is not None

    with pytest.raises(ReportableError, match=message):
        read_issue_comment_cursor(conversation=reread)


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
