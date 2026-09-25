"""Scheduling and publication of issue conversations."""

import json
from datetime import timedelta
from unittest.mock import Mock

import pytest
from clocks import PINNED, Ticking
from conftest import (
    FILED,
    POSTED_BY,
    REPOSITORY,
    comment,
    commit,
    configure,
    git,
    listing,
    pages,
    streamed,
)
from fakes import Line
from records import (
    write_agent_assignment,
    write_issue_conversation,
    write_round,
)

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPurpose,
    AgentRoundRecord,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    IssueConversationInput,
    compose_agent_round_ending,
)
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.documents import read_json, write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import add_detached_worktree, read_worktree_revision
from dreamcatcher.issue_conversations import (
    ISSUE_CONVERSATION_RECORD_NAME,
    NO_REPLY,
    read_issue_conversation,
    read_issue_conversation_reply,
    request_issue_conversation_retry,
    save_issue_conversation_reply,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.scheduler import (
    AgentWorkScheduler,
    GlobalCooldown,
    IssueFactValue,
    SchedulerRecord,
    derive_issue_conversation_fault,
)
from dreamcatcher.state import StateDirectory

CONVERSATION_CONFIG = """[conversation]
label = "dream:conversation"
harness = "claude"
prompt = "/dream:conversation GH{issue}"
model = "opus[1m]"
effort = "xhigh"
"""
COMMENT_PATH = f"api repos/{REPOSITORY}/issues/8/comments?per_page=100"
POST_PATH = f"api repos/{REPOSITORY}/issues/8/comments --method POST"
ASKED = "2026-09-23T01:00:00Z"


@pytest.fixture
def conversation_scheduler(cloned, gh):
    """Return a configured scheduler and stop any round the test leaves running."""
    configure(root=cloned, head=CONVERSATION_CONFIG)
    clock = Ticking(step=300)
    scheduler = AgentWorkScheduler(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=read_dreamcatcher_config(root=cloned),
        state=StateDirectory(root=cloned),
        requested_assignment_harness=AgentHarness.CLAUDE,
        clock=clock,
        rounds={},
    )
    yield scheduler, clock, gh
    for running in scheduler.rounds.values():
        running.stop()


def offer_conversation(
    *,
    gh,
    comments: list[dict],
    issue: int = 8,
    title: str = "Why does this happen?",
    body: str = "Explain the scheduler.",
) -> None:
    """Have GitHub offer one assigned conversation issue and its comments."""
    gh.replies(
        stdout=json.dumps(
            [
                {
                    "number": issue,
                    "title": title,
                    "body": body,
                    "createdAt": "2026-09-22T01:00:00Z",
                    "state": "OPEN",
                    "assignees": [{"login": POSTED_BY}],
                    "labels": [{"name": "dream:conversation"}],
                }
            ]
        ),
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} "
            "--label dream:conversation"
        ),
    )
    gh.replies(
        stdout=pages(items=comments),
        to=f"api repos/{REPOSITORY}/issues/{issue}/comments?per_page=100",
    )


def answer(
    *,
    harnesses,
    body: str = "The scheduler waits for work.",
    status: int = 0,
    delay: float = 0,
) -> None:
    """Have Claude identify its session and finish with one final result."""
    harnesses["claude"].streams(
        lines=[
            Line(
                text=streamed(
                    type="system",
                    subtype="init",
                    model="claude-opus-5",
                    session_id="conversation-session",
                )
                + "\n"
            ),
            Line(
                text=streamed(
                    type="result",
                    subtype="success",
                    is_error=False,
                    result=body,
                    total_cost_usd=0.0,
                    usage={
                        "output_tokens": 1,
                        "input_tokens": 1,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                )
                + "\n"
            ),
        ],
        status=status,
        delay=delay,
    )


def ask(*, identifier: int = 1, body: str = "Please explain.") -> dict:
    """Return one trusted ordinary issue comment."""
    return comment(id=identifier, created_at=ASKED, body=body)


def count_comment_reads(*, gh) -> int:
    """Return how often GitHub was asked for the conversation's comments."""
    expected = COMMENT_PATH.split()
    return sum(call.arguments[: len(expected)] == expected for call in gh.calls)


def finish(*, scheduler: AgentWorkScheduler) -> None:
    """Wait for the one conversation round the scheduler started."""
    next(iter(scheduler.rounds.values())).wait()


def save_pending_reply(*, state: StateDirectory, issue: int) -> None:
    """Write one successful conversation round whose answer still needs posting."""
    directory = write_issue_conversation(state=state, issue=issue)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AgentRoundPurpose.DISCUSS,
            started=PINNED,
            pid=123,
            ending=compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    conversation = read_issue_conversation(state=state, issue=issue)
    assert conversation is not None
    save_issue_conversation_reply(
        conversation=conversation, number=1, body=f"Answer for GH{issue}."
    )


def test_an_initial_conversation_freezes_input_runs_claude_and_publishes_once(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    launched = scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    published = scheduler.tick(at=clock())
    scheduler.tick(at=clock())

    assert launched.launched_conversation_identifier == "conversation-GH8"
    assert published.hold is None
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    assert conversation.record.harness_session_identifier == "conversation-session"
    assert conversation.rounds[0].purpose is AgentRoundPurpose.DISCUSS
    assert conversation.rounds[0].outcome is AgentRoundOutcome.SUCCESSFUL
    paths = conversation.compose_round_paths(number=1)
    frozen = read_json(model=IssueConversationInput, path=paths.round_input)
    assert frozen.title == "Why does this happen?"
    assert frozen.body == "Explain the scheduler."
    assert [item.body for item in frozen.comments] == ["Please explain."]
    assert frozen.revision == read_worktree_revision(worktree=conversation.worktree)
    assert paths.final_output.read_text(encoding="utf-8") == (
        "The scheduler waits for work."
    )
    reply = read_issue_conversation_reply(conversation=conversation, number=1)
    assert reply is not None
    assert reply.published_at is not None
    assert len(harnesses["claude"].calls) == 1
    post_calls = [call for call in gh.calls if call.arguments[:4] == POST_PATH.split()]
    assert len(post_calls) == 1
    assert json.loads(post_calls[0].prompt)["body"].endswith(
        f"The scheduler waits for work.\n\n{AGENT_POST_MARKER}"
    )
    assert not any(call.arguments[:2] == ["pr", "create"] for call in gh.calls)


def test_a_follow_up_resumes_the_session_with_only_new_comments(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    offer_conversation(
        gh=gh,
        comments=[ask(), ask(identifier=2, body="What evidence supports that?")],
        title="What now happens?",
        body="Explain the current scheduler.",
    )
    answer(harnesses=harnesses, body="The follow-up answer.")

    launched = scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())

    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert launched.launched_conversation_identifier == "conversation-GH8"
    assert conversation is not None
    assert len(conversation.rounds) == 2
    follow_up = read_json(
        model=IssueConversationInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert follow_up.title is None
    assert follow_up.body is None
    assert [item.body for item in follow_up.comments] == [
        "What evidence supports that?"
    ]
    saved_follow_up = json.loads(
        conversation.compose_round_paths(number=2).round_input.read_text(
            encoding="utf-8"
        )
    )
    assert "title" not in saved_follow_up
    assert "body" not in saved_follow_up
    resumed = harnesses["claude"].calls[1]
    assert resumed.arguments[-2:] == ["--resume", "conversation-session"]
    assert resumed.prompt.startswith("Issue-conversation input for GH8:")
    assert "/dream:conversation" not in resumed.prompt
    assert (
        len([call for call in gh.calls if call.arguments[:4] == POST_PATH.split()]) == 2
    )


def test_a_follow_up_refreshes_to_changed_main(conversation_scheduler, harnesses):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    previous_revision = read_json(
        model=IssueConversationInput,
        path=conversation.compose_round_paths(number=1).round_input,
    ).revision
    (scheduler.state.root / "README.md").write_bytes(b"what main holds now\n")
    commit(path=scheduler.state.root, message="change main")
    git(arguments=["push", "origin", "main"], cwd=scheduler.state.root)
    offer_conversation(
        gh=gh,
        comments=[ask(), ask(identifier=2, body="Does the answer still hold?")],
    )
    answer(harnesses=harnesses, body="The changed answer.")

    launched = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert launched.launched_conversation_identifier == "conversation-GH8"
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    follow_up = read_json(
        model=IssueConversationInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert follow_up.revision != previous_revision
    assert follow_up.revision == read_worktree_revision(worktree=conversation.worktree)


def test_a_failed_conversation_refresh_leaves_the_batch_waiting(
    conversation_scheduler, harnesses, monkeypatch
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    offer_conversation(
        gh=gh,
        comments=[ask(), ask(identifier=2, body="Does the answer still hold?")],
    )
    monkeypatch.setattr(
        "dreamcatcher.issue_conversations.refresh_detached_worktree",
        Mock(side_effect=ReportableError("could not fetch main")),
    )

    observed = scheduler.tick(at=clock())

    assert observed.hold == "could not fetch main"
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    assert len(conversation.rounds) == 1
    assert not conversation.compose_round_paths(number=2).round_input.exists()
    assert len(harnesses["claude"].calls) == 1


def test_comments_queued_during_a_round_wait_without_another_comment_read(
    conversation_scheduler, harnesses, monkeypatch
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses, delay=10)
    scheduler.tick(at=clock())
    comment_reads_before = count_comment_reads(gh=gh)
    refresh = Mock()
    monkeypatch.setattr(
        "dreamcatcher.issue_conversations.refresh_detached_worktree",
        refresh,
    )

    observed = scheduler.tick(at=clock())

    assert observed.hold == "at cap: 1 of 1 agents running"
    assert count_comment_reads(gh=gh) == comment_reads_before
    refresh.assert_not_called()


def test_ready_assignment_rounds_and_conversations_alternate(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    for issue in (13, 14):
        write_agent_assignment(
            state=scheduler.state,
            identifier=f"GH{issue}-20260923-010000",
            issue=issue,
        )
    offer_conversation(gh=gh, comments=[ask()])
    harnesses["claude"].replies(stdout="")

    assignment_launch = scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    answer(harnesses=harnesses)
    conversation_launch = scheduler.tick(at=clock())

    assert assignment_launch.launched_assignment_identifier == "GH13-20260923-010000"
    assert conversation_launch.launched_conversation_identifier == "conversation-GH8"


def test_after_a_conversation_round_the_next_round_dispatches_an_assignment(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    offer_conversation(gh=gh, comments=[ask(), ask(identifier=2)])
    gh.replies(stdout=listing(issues=[(8, FILED)]), to="issue list")
    harnesses["claude"].replies(stdout="")

    observed = scheduler.tick(at=clock())

    assert observed.launched_assignment_identifier is not None


def test_after_a_failed_assignment_start_the_next_round_is_a_conversation(
    conversation_scheduler, harnesses, monkeypatch
):
    scheduler, clock, gh = conversation_scheduler
    write_agent_assignment(
        state=scheduler.state,
        identifier="GH13-20260923-010000",
        issue=13,
    )
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses)
    monkeypatch.setattr(
        scheduler,
        "_launch_required_round",
        Mock(side_effect=ReportableError("could not start assignment")),
    )

    failed = scheduler.tick(at=clock())
    launched = scheduler.tick(at=clock())

    assert failed.hold == "could not start assignment"
    assert launched.launched_conversation_identifier == "conversation-GH8"


def test_an_issue_without_a_trusted_unmarked_comment_does_not_start(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(
        gh=gh,
        comments=[
            ask(identifier=1, body=f"an earlier answer\n{AGENT_POST_MARKER}"),
            ask(identifier=2, body="somebody else") | {"user": {"login": "mallory"}},
        ],
    )

    observed = scheduler.tick(at=clock())

    assert observed.launched_conversation_identifier is None
    assert harnesses["claude"].calls == []
    assert read_issue_conversation(state=scheduler.state, issue=8) is None


def test_a_conversation_waits_for_shared_capacity(conversation_scheduler, harnesses):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)

    observed = scheduler.tick(at=clock())

    assert observed.hold == "at cap: 1 of 1 agents running"
    assert harnesses["claude"].calls == []
    assert count_comment_reads(gh=gh) == 0


def test_a_conversation_waits_for_the_active_global_cooldown(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    at = clock()
    write_json(
        document=SchedulerRecord(
            at=at,
            cooldown=GlobalCooldown(started=at, ends=at + timedelta(minutes=15)),
        ),
        path=scheduler.state.scheduler_record,
    )

    observed = scheduler.tick(at=at)

    assert observed.hold == "global cooldown"
    assert harnesses["claude"].calls == []


def test_a_failed_publication_retries_the_saved_answer_without_another_round(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses)
    gh.fails(stderr="network unavailable", to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    failed = scheduler.tick(at=clock())

    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    saved = read_issue_conversation_reply(conversation=conversation, number=1)
    assert saved is not None
    assert saved.published_at is None
    assert failed.hold is not None
    assert failed.hold.startswith("could not publish the answer for GH8")
    assert count_comment_reads(gh=gh) == 1

    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    retried = scheduler.tick(at=clock())

    saved = read_issue_conversation_reply(conversation=conversation, number=1)
    assert retried.hold is None
    assert saved is not None
    assert saved.published_at is not None
    assert len(harnesses["claude"].calls) == 1


def test_one_failed_publication_does_not_starve_another_saved_answer(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    save_pending_reply(state=scheduler.state, issue=8)
    save_pending_reply(state=scheduler.state, issue=9)
    gh.replies(
        stdout="[]",
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} "
            "--label dream:conversation"
        ),
    )
    gh.fails(stderr="issue is locked", to=POST_PATH)
    gh.replies(
        stdout=json.dumps({"id": 100}),
        to=f"api repos/{REPOSITORY}/issues/9/comments --method POST",
    )

    observed = scheduler.tick(at=clock())

    conversation = read_issue_conversation(state=scheduler.state, issue=9)
    assert conversation is not None
    reply = read_issue_conversation_reply(conversation=conversation, number=1)
    assert observed.hold is not None
    assert "could not publish the answer for GH8" in observed.hold
    assert reply is not None
    assert reply.published_at is not None


def test_one_failed_reply_read_does_not_starve_another_conversation(
    conversation_scheduler, monkeypatch
):
    scheduler, clock, gh = conversation_scheduler
    save_pending_reply(state=scheduler.state, issue=8)
    save_pending_reply(state=scheduler.state, issue=9)
    gh.replies(
        stdout="[]",
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} "
            "--label dream:conversation"
        ),
    )
    publish = Mock(side_effect=[ReportableError("could not read reply"), None])
    monkeypatch.setattr(
        "dreamcatcher.scheduler._publish_issue_conversation_reply", publish
    )

    observed = scheduler.tick(at=clock())

    assert observed.hold is not None
    assert "could not publish the answer for GH8" in observed.hold
    assert publish.call_count == 2


def test_an_unreadable_reply_does_not_block_assignment_work(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    save_pending_reply(state=scheduler.state, issue=8)
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    conversation.compose_reply_path(number=1).write_bytes(b"not json")
    offer_conversation(gh=gh, comments=[ask()])
    assignment_identifier = "GH13-20260923-010000"
    write_agent_assignment(
        state=scheduler.state,
        identifier=assignment_identifier,
        issue=13,
    )
    harnesses["claude"].replies(stdout="")

    observed = scheduler.tick(at=clock())

    assert observed.launched_assignment_identifier == assignment_identifier
    assert observed.hold is not None
    assert "could not inspect saved conversation GH8" in observed.hold


def test_no_reply_completes_without_posting_a_comment(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses, body=NO_REPLY)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    observed = scheduler.tick(at=clock())

    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    reply = read_issue_conversation_reply(conversation=conversation, number=1)
    assert observed.hold is None
    assert reply is not None
    assert reply.is_complete
    assert not any(call.arguments[:4] == POST_PATH.split() for call in gh.calls)


def test_an_errored_round_recovers_the_saved_batch_and_revision(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses, status=2)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    first = read_issue_conversation(state=scheduler.state, issue=8)
    assert first is not None
    first_input = read_json(
        model=IssueConversationInput,
        path=first.compose_round_paths(number=1).round_input,
    )
    offer_conversation(
        gh=gh,
        comments=[ask(), ask(identifier=2, body="A later question.")],
    )
    answer(harnesses=harnesses, body="The recovered answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    launched = scheduler.tick(at=clock())
    comment_reads_when_recovery_launched = count_comment_reads(gh=gh)
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())

    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    assert conversation.rounds[0].outcome is AgentRoundOutcome.ERRORED
    assert conversation.rounds[1].is_recovery
    assert conversation.rounds[1].outcome is AgentRoundOutcome.SUCCESSFUL
    assert read_issue_conversation_reply(conversation=conversation, number=1) is None
    recovered_input = read_json(
        model=IssueConversationInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert recovered_input == first_input
    assert launched.launched_conversation_identifier == "conversation-GH8"
    resumed = harnesses["claude"].calls[1]
    assert resumed.arguments[-2:] == ["--resume", "conversation-session"]
    assert resumed.prompt.startswith(
        "Your previous issue-conversation round did not finish."
    )
    assert comment_reads_when_recovery_launched == 1
    assert (
        len([call for call in gh.calls if call.arguments[:4] == POST_PATH.split()]) == 1
    )


def test_an_interrupted_conversation_recovers_after_eligibility_loss(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    directory = write_issue_conversation(state=scheduler.state, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AgentRoundPurpose.DISCUSS,
            started=PINNED,
            pid=123,
            ending=InterruptedAgentRoundEnding(),
        ),
    )
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    frozen = IssueConversationInput(
        issue=8,
        title="Why does this happen?",
        body="Explain the scheduler.",
        comments=[ask()],
        revision="frozen-revision",
    )
    write_json(
        document=frozen,
        path=conversation.compose_round_paths(number=1).round_input,
    )
    answer(harnesses=harnesses)

    launched = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    recovered = conversation.rounds[-1]
    assert launched.launched_conversation_identifier == "conversation-GH8"
    assert launched.conversation_eligibility[8].value is IssueFactValue.FALSE
    assert recovered.is_recovery
    assert (
        read_json(
            model=IssueConversationInput,
            path=conversation.compose_round_paths(number=2).round_input,
        )
        == frozen
    )
    assert harnesses["claude"].calls[0].arguments[-2:] == [
        "--resume",
        "conversation-session",
    ]
    assert count_comment_reads(gh=gh) == 0


def test_two_failed_conversation_attempts_wait_for_a_user_retry(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses, status=1)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    answer(harnesses=harnesses, status=2)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    faulted = scheduler.tick(at=clock())

    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    assert derive_issue_conversation_fault(
        conversation=conversation,
        most_recent_cooldown_ended=None,
    )
    assert faulted.launched_agent_work_identifier is None
    assert faulted.cooldown is None
    assert len(harnesses["claude"].calls) == 2

    request_issue_conversation_retry(conversation=conversation, at=clock())
    answer(harnesses=harnesses)
    retried = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    assert retried.launched_conversation_identifier == "conversation-GH8"
    assert conversation.rounds[-1].is_recovery
    assert len(harnesses["claude"].calls) == 3


def test_a_follow_up_refuses_to_replace_a_missing_saved_session(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    write_json(
        document=conversation.record.model_copy(
            update={"harness_session_identifier": None}
        ),
        path=conversation.directory / ISSUE_CONVERSATION_RECORD_NAME,
    )
    offer_conversation(gh=gh, comments=[ask(), ask(identifier=2)])

    observed = scheduler.tick(at=clock())

    assert observed.hold is not None
    assert observed.hold.startswith(
        "Could not resume conversation-GH8: its first round did not report"
    )
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    assert len(conversation.rounds) == 2
    failed = conversation.rounds[-1]
    assert failed.outcome is AgentRoundOutcome.ERRORED
    assert failed.pid is None
    assert isinstance(failed.ending, ErroredAgentRoundEnding)
    assert failed.ending.reason == observed.hold
    frozen = read_json(
        model=IssueConversationInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert [comment.id for comment in frozen.comments] == [2]
    assert len(harnesses["claude"].calls) == 1


def test_a_failed_conversation_listing_holds_launches(conversation_scheduler):
    scheduler, clock, gh = conversation_scheduler
    write_issue_conversation(state=scheduler.state, issue=8)
    gh.fails(
        stderr="network unavailable",
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} "
            "--label dream:conversation"
        ),
    )

    observed = scheduler.tick(at=clock())

    assert observed.hold is not None
    assert observed.hold.startswith("could not list issue conversations")
    assert observed.conversation_eligibility[8].value is IssueFactValue.UNKNOWN


def test_an_ineligible_saved_conversation_is_not_polled(conversation_scheduler):
    scheduler, clock, gh = conversation_scheduler
    write_issue_conversation(state=scheduler.state, issue=8)

    observed = scheduler.tick(at=clock())

    assert observed.conversation_eligibility[8].value is IssueFactValue.FALSE
    assert count_comment_reads(gh=gh) == 0


def test_rediscovery_delivers_comments_posted_while_a_conversation_was_inactive(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    comment_reads_before = count_comment_reads(gh=gh)
    gh.replies(
        stdout="[]",
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} "
            "--label dream:conversation"
        ),
    )

    inactive = scheduler.tick(at=clock())

    assert inactive.conversation_eligibility[8].value is IssueFactValue.FALSE
    assert count_comment_reads(gh=gh) == comment_reads_before
    offer_conversation(
        gh=gh,
        comments=[ask(), ask(identifier=2, body="A question posted while inactive")],
    )
    answer(harnesses=harnesses, body="The later answer.")

    rediscovered = scheduler.tick(at=clock())

    assert rediscovered.launched_conversation_identifier == "conversation-GH8"
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    later_input = read_json(
        model=IssueConversationInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert [item.body for item in later_input.comments] == [
        "A question posted while inactive"
    ]


def test_removing_conversation_configuration_makes_saved_work_inactive(
    conversation_scheduler,
):
    scheduler, clock, _ = conversation_scheduler
    write_issue_conversation(state=scheduler.state, issue=8)
    scheduler.config = scheduler.config.model_copy(update={"conversation": None})

    observed = scheduler.tick(at=clock())

    assert observed.conversation_eligibility[8].value is IssueFactValue.FALSE


def test_a_conversation_failure_remains_visible_when_an_assignment_launches(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    assignment_identifier = "GH13-20260923-010000"
    write_agent_assignment(
        state=scheduler.state, identifier=assignment_identifier, issue=13
    )
    gh.fails(
        stderr="network unavailable",
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} "
            "--label dream:conversation"
        ),
    )
    harnesses["claude"].replies(stdout="")

    observed = scheduler.tick(at=clock())

    assert observed.launched_assignment_identifier == assignment_identifier
    assert observed.hold is not None
    assert observed.hold.startswith("could not list issue conversations")


def test_a_failed_comment_listing_holds_launches(conversation_scheduler):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[])
    gh.fails(stderr="network unavailable", to=COMMENT_PATH)

    observed = scheduler.tick(at=clock())

    assert observed.hold is not None
    assert observed.hold.startswith("could not read comments for GH8")


def test_a_failed_delivery_cursor_read_is_a_scheduler_hold(
    conversation_scheduler, monkeypatch
):
    scheduler, clock, gh = conversation_scheduler
    write_issue_conversation(state=scheduler.state, issue=8)
    offer_conversation(gh=gh, comments=[])
    monkeypatch.setattr(
        "dreamcatcher.scheduler.read_issue_comment_delivery_cursor",
        Mock(side_effect=ReportableError("could not read the round input")),
    )

    observed = scheduler.tick(at=clock())

    assert observed.hold is not None
    assert observed.hold.startswith("could not read delivered comments for GH8")


def test_an_unrecorded_round_input_is_not_delivered_again(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    write_issue_conversation(state=scheduler.state, issue=8)
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    write_json(
        document=IssueConversationInput(
            issue=8,
            title="Why does this happen?",
            body="Explain the scheduler.",
            comments=[ask()],
            revision="abc123",
        ),
        path=conversation.compose_round_paths(number=1).round_input,
    )
    offer_conversation(gh=gh, comments=[ask()])

    observed = scheduler.tick(at=clock())

    assert observed.hold is not None
    assert "has input for round 1 without a round record" in observed.hold
    assert harnesses["claude"].calls == []


def test_a_partial_comment_scan_does_not_launch_or_starve_later_reads(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    issues = [
        {
            "number": number,
            "title": f"Issue {number}",
            "body": "Explain it.",
            "createdAt": f"2026-09-{number + 13:02d}T01:00:00Z",
            "state": "OPEN",
            "assignees": [{"login": POSTED_BY}],
            "labels": [{"name": "dream:conversation"}],
        }
        for number in (8, 9, 10)
    ]
    gh.replies(
        stdout=json.dumps(issues),
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} "
            "--label dream:conversation"
        ),
    )
    gh.replies(stdout=pages(items=[ask()]), to=COMMENT_PATH)
    gh.fails(
        stderr="issue-specific failure",
        to=f"api repos/{REPOSITORY}/issues/9/comments?per_page=100",
    )
    gh.replies(
        stdout=pages(items=[ask(identifier=2)]),
        to=f"api repos/{REPOSITORY}/issues/10/comments?per_page=100",
    )

    observed = scheduler.tick(at=clock())

    assert observed.launched_conversation_identifier is None
    assert observed.hold is not None
    assert "could not read comments for GH9" in observed.hold
    assert any("issues/10/comments" in " ".join(call.arguments) for call in gh.calls)


def test_an_existing_empty_conversation_can_start(conversation_scheduler, harnesses):
    scheduler, clock, gh = conversation_scheduler
    write_issue_conversation(state=scheduler.state, issue=8)
    worktree = scheduler.state.conversation_worktrees / "GH8"
    worktree.rmdir()
    add_detached_worktree(root=scheduler.state.root, path=worktree)
    (scheduler.state.root / "README.md").write_bytes(b"new main before retry\n")
    commit(path=scheduler.state.root, message="advance main before retry")
    git(arguments=["push", "origin", "main"], cwd=scheduler.state.root)
    offer_conversation(gh=gh, comments=[ask()])
    answer(harnesses=harnesses)

    observed = scheduler.tick(at=clock())

    assert observed.launched_conversation_identifier == "conversation-GH8"
    assert observed.conversation_eligibility[8].value is IssueFactValue.TRUE
    conversation = read_issue_conversation(state=scheduler.state, issue=8)
    assert conversation is not None
    round_input = read_json(
        model=IssueConversationInput,
        path=conversation.compose_round_paths(number=1).round_input,
    )
    assert round_input.revision == read_worktree_revision(worktree=worktree)
    assert (worktree / "README.md").read_text(encoding="utf-8") == (
        "new main before retry\n"
    )
    assert (
        git(arguments=["branch", "--show-current"], cwd=scheduler.state.root).strip()
        == "main"
    )


def test_a_missing_empty_conversation_worktree_holds_without_detaching_main(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    write_issue_conversation(state=scheduler.state, issue=8)
    offer_conversation(gh=gh, comments=[ask()])

    observed = scheduler.tick(at=clock())

    assert observed.hold is not None
    assert "it is not a linked worktree" in observed.hold
    assert (
        git(arguments=["branch", "--show-current"], cwd=scheduler.state.root).strip()
        == "main"
    )


def test_a_conversation_setup_failure_is_a_scheduler_hold(conversation_scheduler):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[ask()])
    add_detached_worktree(
        root=scheduler.state.root,
        path=scheduler.state.conversation_worktrees / "GH8",
    )

    observed = scheduler.tick(at=clock())

    assert observed.hold is not None
    assert "unrecorded worktree already exists" in observed.hold


def test_the_oldest_waiting_comment_selects_the_conversation(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    issue_list = [
        {
            "number": number,
            "title": f"Issue {number}",
            "body": "Explain it.",
            "createdAt": created_at,
            "state": "OPEN",
            "assignees": [{"login": POSTED_BY}],
            "labels": [{"name": "dream:conversation"}],
        }
        for number, created_at in [
            (8, "2026-09-21T01:00:00Z"),
            (9, "2026-09-22T01:00:00Z"),
        ]
    ]
    gh.replies(
        stdout=json.dumps(issue_list),
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} "
            "--label dream:conversation"
        ),
    )
    gh.replies(
        stdout=pages(
            items=[ask(identifier=2) | {"created_at": "2026-09-23T02:00:00Z"}]
        ),
        to=f"api repos/{REPOSITORY}/issues/8/comments?per_page=100",
    )
    gh.replies(
        stdout=pages(
            items=[ask(identifier=1) | {"created_at": "2026-09-23T01:00:00Z"}]
        ),
        to=f"api repos/{REPOSITORY}/issues/9/comments?per_page=100",
    )
    answer(harnesses=harnesses)

    observed = scheduler.tick(at=clock())

    assert observed.launched_conversation_identifier == "conversation-GH9"
