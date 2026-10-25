"""Scheduling and publication of issue conversations."""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from clocks import PINNED, Ticking
from conftest import (
    ASSIGNMENT_LABEL,
    POSTED_BY,
    REPOSITORY,
    commit,
    compose_comment,
    compose_page,
    compose_stream_line,
    configure,
    offer_listing,
    run_git,
    wait_for_exit,
)
from fakes import Line
from records import (
    MISORDERED_COMMENTS,
    REPEATED_COMMENTS,
    compose_conversation_identifier,
    read_assignments,
    read_conversation,
    replace_relayed_comments,
    write_assignment,
    write_conversation,
    write_ending,
    write_round,
    write_tick,
)
from rows import compose_conversation_row

from dreamcatcher import agent_rounds
from dreamcatcher.agent_rounds import (
    AgentRoundLaunchError,
    AgentRoundOutcome,
    AgentRoundRecord,
    FinishingErroredAgentRoundEnding,
    HarnessErroredAgentRoundEnding,
    LaunchErroredAgentRoundEnding,
    SuccessfulAgentRoundEnding,
    request_agent_round_stop,
)
from dreamcatcher.agent_work import (
    _HARNESS_SESSION_RECORD_NAME,
    AgentWorkEndReason,
    read_agent_work_at_issue,
    record_harness_session_identifier,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.daemon import DreamcatcherDaemon
from dreamcatcher.documents import read_json, write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import _add_detached_worktree, _read_worktree_revision
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import (
    NO_REPLY,
    ConversationRoundInput,
    InitialConversationIssue,
)
from dreamcatcher.prompts import (
    AGENT_POST_MARKER,
)
from dreamcatcher.scheduler import Scheduler, SchedulingContext
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    GlobalCooldown,
    IssueCommentsFinding,
    PauseCause,
    PausedFinding,
    ReadFailureFinding,
    SchedulerRecord,
    StartedRound,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentWorkStatus,
    AgentWorkStatusValue,
    read_agent_work_status,
    read_dreamcatcher_daemon_status,
)

# What a round's prompt opens with when the round before it did not finish.
UNFINISHED_ROUND_OPENING = "Your previous round did not finish."

CONVERSATION_CONFIG = """[[conversation]]
label = "dream:conversation"

[conversation.claude]
prompt = "/dream:conversation GH{issue}"
model = "opus[1m]"
effort = "xhigh"
"""
BOTH_CONVERSATION_CONFIG = (
    CONVERSATION_CONFIG
    + """
[conversation.codex]
prompt = "$dream:conversation GH{issue}"
model = "gpt-5.6-sol"
effort = "xhigh"
config = { model_context_window = 1000000 }
"""
)
SECOND_CONVERSATION_CONFIG = """
[[conversation]]
label = "dream:scout"

[conversation.claude]
prompt = "/dream:scout GH{issue}"
model = "opus[1m]"
effort = "high"
"""
COMMENT_PATH = f"api repos/{REPOSITORY}/issues/8/comments?per_page=100"
POST_PATH = f"api repos/{REPOSITORY}/issues/8/comments --method POST"
ASKED = "2026-09-23T01:00:00Z"

# The title of the conversation issue that the tests offer, unless a test gives
# another.
OFFERED_TITLE = "Why does this happen?"


# What the tick records for a conversation whose label came off its issue.
PAUSED = PausedFinding(cause=PauseCause.LABEL_REMOVED)


def create_scheduler(*, root, harness, clock) -> Scheduler:
    """Create the scheduler for the repository at root."""
    return Scheduler(
        context=SchedulingContext(
            repository=REPOSITORY,
            account=POSTED_BY,
            config=read_dreamcatcher_config(root=root),
            state=StateDirectory(root=root),
            clock=clock,
        ),
        preferred_harness=harness,
        rounds={},
    )


def set_scheduler_config(*, scheduler: Scheduler, config) -> None:
    """Give the scheduler a replacement configuration."""
    scheduler.context = replace(scheduler.context, config=config)


@pytest.fixture
def conversation_scheduler(cloned_repo, gh):
    """Return a configured scheduler and stop any round the test leaves running."""
    configure(root=cloned_repo, head=CONVERSATION_CONFIG)
    clock = Ticking(step=300)
    scheduler = create_scheduler(
        root=cloned_repo,
        harness=AgentHarness.CLAUDE,
        clock=clock,
    )
    yield scheduler, clock, gh
    for running in scheduler.rounds.values():
        running.interrupt()


@pytest.fixture
def codex_conversation_scheduler(cloned_repo, gh):
    """Return a scheduler that chooses Codex from both conversation recipes."""
    configure(root=cloned_repo, head=BOTH_CONVERSATION_CONFIG)
    clock = Ticking(step=300)
    scheduler = create_scheduler(
        root=cloned_repo,
        harness=AgentHarness.CODEX,
        clock=clock,
    )
    yield scheduler, clock, gh
    for running in scheduler.rounds.values():
        running.interrupt()


def compose_conversation_issue(
    *,
    labels: tuple[str, ...],
    number: int = 8,
    title: str = OFFERED_TITLE,
    body: str = "Explain the scheduler.",
    state: str = "OPEN",
    assignees: tuple[str, ...] = (POSTED_BY,),
) -> dict:
    """Return what GitHub holds of the conversation issue the tests offer."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "createdAt": "2026-09-22T01:00:00Z",
        "state": state,
        "assignees": [{"login": login} for login in assignees],
        "labels": [{"name": name} for name in labels],
    }


def show_conversation_issue(*, gh, issue: dict) -> None:
    """Have GitHub answer a read of that issue with this."""
    gh.replies(
        stdout=json.dumps(issue),
        to=(
            f"issue view {issue['number']} --repo {REPOSITORY} "
            "--json number,title,body,createdAt,state,assignees,labels"
        ),
    )


def offer_conversation(
    *,
    gh,
    comments: list[dict],
    label: str = "dream:conversation",
    title: str = OFFERED_TITLE,
    body: str = "Explain the scheduler.",
) -> None:
    """Have GitHub offer one assigned conversation issue and its comments."""
    issue = compose_conversation_issue(labels=(label,), title=title, body=body)
    offer_listing(gh=gh, issues=[issue])
    show_conversation_issue(gh=gh, issue=issue)
    gh.replies(
        stdout=compose_page(items=comments),
        to=f"api repos/{REPOSITORY}/issues/8/comments?per_page=100",
    )


def script_claude_answer(
    *,
    harnesses,
    body: str = "The scheduler waits for work.",
    status: int = 0,
    delay: float = 0,
) -> None:
    """Have Claude identify its session and finish with one final output."""
    harnesses["claude"].streams(
        lines=[
            Line(
                text=compose_stream_line(
                    type="system",
                    subtype="init",
                    model="claude-opus-5",
                    session_id="conversation-session",
                )
                + "\n"
            ),
            Line(
                text=compose_stream_line(
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


def script_codex_answer(
    *,
    harnesses,
    body: str | None = "The scheduler waits for work.",
    status: int = 0,
    session_identifier: str | None = "conversation-codex-session",
) -> None:
    """Have Codex identify its session and write its final-message file."""
    harnesses["codex"].streams(
        lines=(
            []
            if session_identifier is None
            else [
                Line(
                    text=compose_stream_line(
                        type="thread.started",
                        thread_id=session_identifier,
                    )
                    + "\n"
                )
            ]
        ),
        status=status,
        final_output=body,
    )


def compose_question(*, identifier: int = 1, body: str = "Please explain.") -> dict:
    """Return one eligible ordinary issue comment."""
    return compose_comment(id=identifier, created_at=ASKED, body=body)


def count_comment_reads(*, gh) -> int:
    """Return how often GitHub was asked for the conversation's comments."""
    expected = COMMENT_PATH.split()
    return sum(call.arguments[: len(expected)] == expected for call in gh.calls)


def read_status(*, state: StateDirectory) -> AgentWorkStatus:
    """Return the status of the conversation at the issue the tests offer."""
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    return read_agent_work_status(
        state=state,
        work=conversation,
        daemon=read_dreamcatcher_daemon_status(state=state),
    )


def finish(*, scheduler: Scheduler) -> None:
    """Wait for the one conversation round the scheduler started."""
    next(iter(scheduler.rounds.values())).wait()


def write_faulted_conversation(
    *, state: StateDirectory, issue: int, at: datetime
) -> None:
    """Write an eligible conversation with two current errored rounds."""
    directory = write_conversation(state=state, issue=issue)
    conversation = read_conversation(state=state, issue=issue)
    assert conversation is not None
    conversation.worktree.rmdir()
    _add_detached_worktree(root=state.root, path=conversation.worktree)
    revision = _read_worktree_revision(worktree=conversation.worktree)
    for number in (1, 2):
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=at + timedelta(minutes=number - 1),
                pid=number,
                ending=HarnessErroredAgentRoundEnding(
                    at=at + timedelta(minutes=number), status=2
                ),
            ),
            round_input=ConversationRoundInput(
                issue=issue,
                initial_issue=(
                    InitialConversationIssue(
                        title=f"Issue {issue}",
                        body="Explain it.",
                    )
                    if number == 1
                    else None
                ),
                comments=[compose_question()],
                revision=revision,
            ),
        )


def write_faulted_assignment(
    *, state: StateDirectory, issue: int, identifier: str, at: datetime
) -> None:
    """Write an assignment with two current errored rounds."""
    directory = write_assignment(
        state=state,
        issue=issue,
        identifier=identifier,
    )
    for number in (1, 2):
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=at + timedelta(minutes=number - 1),
                pid=number,
                ending=HarnessErroredAgentRoundEnding(
                    at=at + timedelta(minutes=number), status=2
                ),
            ),
        )


def test_an_initial_conversation_freezes_input_runs_claude_and_publishes_once(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    launched = scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    after = scheduler.tick(at=clock())
    scheduler.tick(at=clock())

    assert launched.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    assert launched.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            finding=IssueCommentsFinding(new_comments=1),
            started_round=StartedRound(number=1),
            title=OFFERED_TITLE,
        )
    ]
    assert after.failures == []
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.harness_session_identifier == "conversation-session"
    assert conversation.rounds[0].outcome is AgentRoundOutcome.SUCCESSFUL
    paths = conversation.compose_round_paths(number=1)
    frozen = read_json(model=ConversationRoundInput, path=paths.round_input)
    assert frozen.initial_issue == InitialConversationIssue(
        title=OFFERED_TITLE,
        body="Explain the scheduler.",
    )
    assert [item.body for item in frozen.comments] == ["Please explain."]
    assert frozen.revision == _read_worktree_revision(worktree=conversation.worktree)
    assert paths.final_output.read_text(encoding="utf-8") == (
        "The scheduler waits for work."
    )
    assert len(harnesses["claude"].calls) == 1
    post_calls = [call for call in gh.calls if call.arguments[:4] == POST_PATH.split()]
    assert len(post_calls) == 1
    assert json.loads(post_calls[0].prompt)["body"].endswith(
        f"The scheduler waits for work.\n\n> written by an agent\n\n{AGENT_POST_MARKER}"
    )
    assert not any(call.arguments[:2] == ["pr", "create"] for call in gh.calls)


def test_each_conversation_label_selects_its_own_route(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    configure(
        root=scheduler.context.state.root,
        head=CONVERSATION_CONFIG + SECOND_CONVERSATION_CONFIG,
    )
    set_scheduler_config(
        scheduler=scheduler,
        config=read_dreamcatcher_config(root=scheduler.context.state.root),
    )
    offer_conversation(gh=gh, comments=[compose_question()], label="dream:scout")
    script_claude_answer(harnesses=harnesses)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.record.dispatch_label == "dream:scout"
    assert conversation.record.instructions == "/dream:scout GH8"
    assert conversation.record.effort == "high"


def test_an_issue_with_two_conversation_labels_has_a_routing_conflict(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    configure(
        root=scheduler.context.state.root,
        head=CONVERSATION_CONFIG + SECOND_CONVERSATION_CONFIG,
    )
    set_scheduler_config(
        scheduler=scheduler,
        config=read_dreamcatcher_config(root=scheduler.context.state.root),
    )
    offer_listing(
        gh=gh,
        issues=[
            compose_conversation_issue(labels=("dream:conversation", "dream:scout"))
        ],
    )

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    conflict = ConflictingLabelsFinding(labels=["dream:conversation", "dream:scout"])
    assert observed.rows == [
        compose_conversation_row(finding=conflict, title=OFFERED_TITLE),
        compose_conversation_row(
            label="dream:scout", finding=conflict, title=OFFERED_TITLE
        ),
    ]
    assert count_comment_reads(gh=gh) == 0
    assert read_conversation(state=scheduler.context.state, issue=8) is None
    assert harnesses["claude"].calls == []


def test_a_saved_conversation_whose_issue_gains_a_second_label_starts_nothing(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    configure(
        root=scheduler.context.state.root,
        head=CONVERSATION_CONFIG + SECOND_CONVERSATION_CONFIG,
    )
    set_scheduler_config(
        scheduler=scheduler,
        config=read_dreamcatcher_config(root=scheduler.context.state.root),
    )
    write_conversation(state=scheduler.context.state, issue=8)
    labels = ("dream:conversation", "dream:scout")
    offer_listing(gh=gh, issues=[compose_conversation_issue(labels=labels)])
    show_conversation_issue(gh=gh, issue=compose_conversation_issue(labels=labels))

    observed = scheduler.tick(at=clock())

    assert observed.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            finding=ConflictingLabelsFinding(labels=list(labels)),
        ),
        compose_conversation_row(
            label="dream:scout",
            finding=ConflictingLabelsFinding(labels=list(labels)),
            title=OFFERED_TITLE,
        ),
    ]
    assert count_comment_reads(gh=gh) == 0
    assert harnesses["claude"].calls == []


def test_a_new_label_starts_a_fresh_conversation_while_the_old_one_stays_paused(
    conversation_scheduler, harnesses
):
    scheduler, _, gh = conversation_scheduler
    configure(
        root=scheduler.context.state.root,
        head=CONVERSATION_CONFIG + SECOND_CONVERSATION_CONFIG,
    )
    set_scheduler_config(
        scheduler=scheduler,
        config=read_dreamcatcher_config(root=scheduler.context.state.root),
    )
    write_conversation(state=scheduler.context.state, issue=8)
    offer_conversation(gh=gh, comments=[compose_question()], label="dream:scout")
    script_claude_answer(harnesses=harnesses)

    observed = scheduler.tick(at=PINNED + timedelta(hours=1))
    finish(scheduler=scheduler)

    paused = compose_conversation_identifier(issue=8)
    [fresh] = observed.launched_agent_work_identifiers
    assert fresh != paused
    assert observed.rows == [
        compose_conversation_row(agent_work_identifier=paused, finding=PAUSED),
        compose_conversation_row(
            label="dream:scout",
            agent_work_identifier=fresh,
            finding=IssueCommentsFinding(new_comments=1),
            started_round=StartedRound(number=1),
            title=OFFERED_TITLE,
        ),
    ]
    conversations = read_agent_work_at_issue(state=scheduler.context.state, issue=8)
    assert [
        (conversation.record.dispatch_label, conversation.is_open)
        for conversation in conversations
    ] == [("dream:conversation", True), ("dream:scout", True)]


def test_a_listed_issue_with_no_current_route_is_inactive(conversation_scheduler):
    scheduler, clock, gh = conversation_scheduler
    offer_listing(gh=gh, issues=[compose_conversation_issue(labels=("maintenance",))])

    observed = scheduler.tick(at=clock())

    assert observed.rows == []
    assert count_comment_reads(gh=gh) == 0


def test_codex_first_and_resumed_rounds_capture_and_publish_final_messages(
    codex_conversation_scheduler, harnesses
):
    scheduler, clock, gh = codex_conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_codex_answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    offer_conversation(
        gh=gh,
        comments=[
            compose_question(),
            compose_question(identifier=2, body="What evidence supports that?"),
        ],
    )
    script_codex_answer(harnesses=harnesses, body="The follow-up answer.")

    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.record.harness is AgentHarness.CODEX
    assert conversation.harness_session_identifier == ("conversation-codex-session")
    assert len(conversation.rounds) == 2
    calls = harnesses["codex"].calls
    assert len(calls) == 2
    first_output = str(
        conversation.compose_round_paths(number=1).final_output_from_worktree
    )
    second_output = str(
        conversation.compose_round_paths(number=2).final_output_from_worktree
    )
    assert calls[0].arguments[-3:] == [
        "--output-last-message",
        first_output,
        "-",
    ]
    assert calls[1].arguments[-4:] == [
        "--output-last-message",
        second_output,
        "conversation-codex-session",
        "-",
    ]
    post_calls = [call for call in gh.calls if call.arguments[:4] == POST_PATH.split()]
    assert [json.loads(call.prompt)["body"] for call in post_calls] == [
        f"The first answer.\n\n> written by an agent\n\n{AGENT_POST_MARKER}",
        f"The follow-up answer.\n\n> written by an agent\n\n{AGENT_POST_MARKER}",
    ]


def test_a_codex_conversation_round_passes_its_recipes_config(
    codex_conversation_scheduler, harnesses
):
    scheduler, clock, gh = codex_conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_codex_answer(harnesses=harnesses, body="The answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.record.harness_config == {"model_context_window": 1000000}
    [call] = harnesses["codex"].calls
    setting = call.arguments.index("model_context_window=1000000")
    assert call.arguments[setting - 1] == "-c"


@pytest.mark.parametrize(
    ("final_output", "expected_outcome"),
    [
        (NO_REPLY, AgentRoundOutcome.SUCCESSFUL),
        (None, AgentRoundOutcome.ERRORED),
    ],
)
def test_codex_no_reply_and_missing_output_post_nothing(
    codex_conversation_scheduler, harnesses, final_output, expected_outcome
):
    scheduler, clock, gh = codex_conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_codex_answer(harnesses=harnesses, body=final_output)

    scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.rounds[0].outcome is expected_outcome
    assert not any(call.arguments[:4] == POST_PATH.split() for call in gh.calls)


def test_a_codex_round_after_an_error_keeps_its_session_revision_and_permissions(
    codex_conversation_scheduler, harnesses
):
    scheduler, clock, gh = codex_conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_codex_answer(harnesses=harnesses, body="This failed.", status=2)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    first_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=1).round_input,
    )
    offer_conversation(gh=gh, comments=[compose_question()])
    script_codex_answer(harnesses=harnesses, body="The recovered answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    recovered_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert recovered_input == first_input.model_copy(update={"initial_issue": None})
    resumed = harnesses["codex"].calls[1]
    assert 'sandbox_mode="workspace-write"' in resumed.arguments
    assert "sandbox_workspace_write.network_access=true" in resumed.arguments
    assert 'approval_policy="never"' in resumed.arguments
    assert resumed.arguments[-2:] == ["conversation-codex-session", "-"]
    assert resumed.prompt.startswith(UNFINISHED_ROUND_OPENING)
    assert "Issue-conversation input for GH8:" in resumed.prompt


def test_a_codex_round_after_an_error_starts_a_new_session_when_none_was_reported(
    codex_conversation_scheduler, harnesses
):
    scheduler, clock, gh = codex_conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_codex_answer(
        harnesses=harnesses,
        body="This failed.",
        status=2,
        session_identifier=None,
    )
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    first_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=1).round_input,
    )
    offer_conversation(gh=gh, comments=[compose_question()])
    script_codex_answer(harnesses=harnesses, body="The recovered answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    recovered_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert recovered_input == first_input
    restarted = harnesses["codex"].calls[1]
    assert restarted.arguments[:2] == ["exec", "--json"]
    assert "resume" not in restarted.arguments
    assert 'sandbox_mode="workspace-write"' in restarted.arguments
    assert "sandbox_workspace_write.network_access=true" in restarted.arguments
    assert 'approval_policy="never"' in restarted.arguments
    assert restarted.prompt.startswith("$dream:conversation GH8")


def test_a_follow_up_resumes_the_session_with_only_new_comments(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    offer_conversation(
        gh=gh,
        comments=[
            compose_question(),
            compose_question(identifier=2, body="What evidence supports that?"),
        ],
        title="What now happens?",
        body="Explain the current scheduler.",
    )
    script_claude_answer(harnesses=harnesses, body="The follow-up answer.")

    launched = scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert launched.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    assert conversation is not None
    assert len(conversation.rounds) == 2
    follow_up = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert follow_up.initial_issue is None
    assert [item.body for item in follow_up.comments] == [
        "What evidence supports that?"
    ]
    saved_follow_up = json.loads(
        conversation.compose_round_paths(number=2).round_input.read_text(
            encoding="utf-8"
        )
    )
    assert "initial_issue" not in saved_follow_up
    resumed = harnesses["claude"].calls[1]
    assert resumed.arguments[-2:] == ["--resume", "conversation-session"]
    assert resumed.prompt.startswith("Issue-conversation input for GH8:")
    assert "/dream:conversation" not in resumed.prompt
    assert (
        len([call for call in gh.calls if call.arguments[:4] == POST_PATH.split()]) == 2
    )


def test_a_stopped_conversation_waits_for_new_feedback(
    conversation_scheduler, harnesses, monkeypatch
):
    monkeypatch.setattr(
        "dreamcatcher.agent_rounds._STOP_REQUEST_POLL_INTERVAL_SECONDS", 0.01
    )
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(
        harnesses=harnesses, body="This answer must not be posted.", delay=5
    )
    scheduler.tick(at=clock())
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    record_harness_session_identifier(
        work=conversation, identifier="conversation-session"
    )
    request_agent_round_stop(paths=conversation.compose_round_paths(number=1))
    finish(scheduler=scheduler)

    scheduler.tick(at=clock())

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.rounds[0].outcome is AgentRoundOutcome.STOPPED
    assert not any(call.arguments[:4] == POST_PATH.split() for call in gh.calls)

    offer_conversation(
        gh=gh,
        comments=[
            compose_question(),
            compose_question(identifier=2, body="Take a different direction."),
        ],
    )
    script_claude_answer(harnesses=harnesses, body="The revised answer.")

    launched = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert launched.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    # The stopped round's harness may have been ended before it recorded its
    # call, so the revised round's call is the last one rather than the second.
    assert (
        harnesses["claude"]
        .calls[-1]
        .prompt.startswith("The user stopped your previous round")
    )


def test_a_follow_up_refreshes_to_changed_main(conversation_scheduler, harnesses):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    previous_revision = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=1).round_input,
    ).revision
    (scheduler.context.state.root / "README.md").write_bytes(b"what main holds now\n")
    commit(path=scheduler.context.state.root, message="change main")
    run_git(arguments=["push", "origin", "main"], cwd=scheduler.context.state.root)
    offer_conversation(
        gh=gh,
        comments=[
            compose_question(),
            compose_question(identifier=2, body="Does the answer still hold?"),
        ],
    )
    script_claude_answer(harnesses=harnesses, body="The changed answer.")

    launched = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert launched.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    follow_up = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert follow_up.revision != previous_revision
    assert follow_up.revision == _read_worktree_revision(worktree=conversation.worktree)


def test_a_failed_conversation_refresh_is_an_errored_round(
    conversation_scheduler, harnesses, monkeypatch
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    offer_conversation(
        gh=gh,
        comments=[
            compose_question(),
            compose_question(identifier=2, body="Does the answer still hold?"),
        ],
    )
    monkeypatch.setattr(
        "dreamcatcher.issue_conversations.refresh_detached_worktree",
        Mock(side_effect=ReportableError("could not fetch main")),
    )

    observed = scheduler.tick(at=clock())

    assert observed.failures == []
    assert observed.rows == [
        compose_conversation_row(
            title=OFFERED_TITLE,
            agent_work_identifier="GH8-20260819-184158-conversation",
            ended_round=1,
            finding=IssueCommentsFinding(new_comments=1),
            started_round=StartedRound(number=2, launch_failure="could not fetch main"),
        )
    ]
    assert observed.launched_agent_work_identifiers == []
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert len(conversation.rounds) == 2
    ending = conversation.rounds[1].ending
    assert isinstance(ending, LaunchErroredAgentRoundEnding)
    assert ending.reason == "could not fetch main"
    assert conversation.rounds[1].pid is None
    assert not conversation.compose_round_paths(number=2).round_input.exists()
    assert len(harnesses["claude"].calls) == 1


def test_a_round_whose_input_cannot_be_saved_errors_and_the_next_refreshes(
    conversation_scheduler, harnesses, monkeypatch
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    (scheduler.context.state.root / "README.md").write_bytes(b"main moved\n")
    commit(path=scheduler.context.state.root, message="move main")
    run_git(arguments=["push", "origin", "main"], cwd=scheduler.context.state.root)
    comments = [
        compose_question(),
        compose_question(identifier=2, body="Does this still hold?"),
    ]
    offer_conversation(gh=gh, comments=comments)
    write_json = agent_rounds.write_json

    def refuse_conversation_input(*, document, path):
        if isinstance(document, ConversationRoundInput):
            raise ReportableError("could not save conversation input")
        write_json(document=document, path=path)

    with monkeypatch.context() as input_failure:
        input_failure.setattr(
            "dreamcatcher.agent_rounds.write_json", refuse_conversation_input
        )

        failed = scheduler.tick(at=clock())

    refreshed_revision = _read_worktree_revision(worktree=conversation.worktree)
    assert failed.failures == []
    assert failed.rows[0].started_round == StartedRound(
        number=2, launch_failure="could not save conversation input"
    )
    assert not conversation.compose_round_paths(number=2).round_input.exists()
    offer_conversation(gh=gh, comments=comments)
    script_claude_answer(harnesses=harnesses, body="The changed answer.")
    gh.replies(stdout=json.dumps({"id": 100}), to=POST_PATH)

    given_again = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert given_again.failures == []
    assert given_again.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert len(conversation.rounds) == 3
    resumed = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=3).round_input,
    )
    assert resumed.revision == refreshed_revision
    assert [item.body for item in resumed.comments] == ["Does this still hold?"]


def test_a_follow_up_refreshes_again_after_a_launch_failure(
    conversation_scheduler, harnesses, monkeypatch
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    (scheduler.context.state.root / "README.md").write_bytes(b"first move\n")
    commit(path=scheduler.context.state.root, message="move main once")
    run_git(arguments=["push", "origin", "main"], cwd=scheduler.context.state.root)
    comments = [
        compose_question(),
        compose_question(identifier=2, body="Does this still hold?"),
    ]
    offer_conversation(gh=gh, comments=comments)
    with monkeypatch.context() as launch_failure:
        launch_failure.setattr(
            "dreamcatcher.agent_rounds.spawn_command",
            Mock(side_effect=ReportableError("could not launch conversation")),
        )

        failed = scheduler.tick(at=clock())

    failed_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert failed.failures == []
    assert failed.rows[0].started_round == StartedRound(
        number=2, launch_failure="could not launch conversation"
    )
    (scheduler.context.state.root / "README.md").write_bytes(b"second move\n")
    commit(path=scheduler.context.state.root, message="move main twice")
    run_git(arguments=["push", "origin", "main"], cwd=scheduler.context.state.root)
    offer_conversation(gh=gh, comments=comments)
    script_claude_answer(harnesses=harnesses, body="The changed answer.")
    gh.replies(stdout=json.dumps({"id": 100}), to=POST_PATH)

    given_again = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert given_again.failures == []
    resumed = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=3).round_input,
    )
    assert resumed.revision != failed_input.revision
    assert resumed.revision == _read_worktree_revision(worktree=conversation.worktree)
    assert [item.body for item in resumed.comments] == ["Does this still hold?"]


def test_a_running_conversation_is_observed_without_starting_another_round(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    scheduler.max_agents = 2
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, delay=10)
    scheduler.tick(at=clock())
    offer_conversation(
        gh=gh, comments=[compose_question(), compose_question(identifier=2)]
    )

    observed = scheduler.tick(at=clock())

    assert observed.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            finding=IssueCommentsFinding(new_comments=1),
            title=OFFERED_TITLE,
        )
    ]
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert not conversation.compose_round_paths(number=2).record.exists()
    assert count_comment_reads(gh=gh) == 2


def test_a_running_conversation_finishes_before_a_closed_issue_ends_it(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, delay=10)
    scheduler.tick(at=clock())
    show_conversation_issue(
        gh=gh,
        issue=compose_conversation_issue(
            labels=("dream:conversation",), state="CLOSED"
        ),
    )

    observed = scheduler.tick(at=clock())

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.ending is None
    assert observed.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            finding=None,
            title=OFFERED_TITLE,
        )
    ]
    assert count_comment_reads(gh=gh) == 1


def test_a_conversation_whose_issue_closes_loses_its_worktree_and_keeps_its_records(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    show_conversation_issue(
        gh=gh,
        issue=compose_conversation_issue(
            labels=("dream:conversation",), state="CLOSED"
        ),
    )
    answered = read_conversation(state=scheduler.context.state, issue=8)
    assert answered is not None
    assert answered.worktree.is_dir()

    observed = scheduler.tick(at=clock())

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.ending is not None
    assert conversation.ending.reason is AgentWorkEndReason.ISSUE_CLOSED
    assert not conversation.worktree.exists()
    assert [record.number for record in conversation.rounds] == [1]
    assert observed.failures == []


def test_ready_assignment_rounds_and_conversations_alternate(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    for issue in (13, 14):
        write_assignment(
            state=scheduler.context.state,
            identifier=f"GH{issue}-20260923-010000-assignment",
            issue=issue,
            pull_request=None,
        )
    offer_conversation(gh=gh, comments=[compose_question()])
    harnesses["claude"].replies(stdout="")

    assignment_launch = scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    script_claude_answer(harnesses=harnesses)
    conversation_launch = scheduler.tick(at=clock())

    assert assignment_launch.launched_agent_work_identifiers == [
        "GH13-20260923-010000-assignment"
    ]
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation_launch.launched_agent_work_identifiers == [
        conversation.identifier
    ]


def test_one_tick_alternates_work_kinds_until_capacity_is_full(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    scheduler.max_agents = 3
    for issue in (13, 14):
        write_assignment(
            state=scheduler.context.state,
            identifier=f"GH{issue}-20260923-010000-assignment",
            issue=issue,
            pull_request=None,
        )
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)

    scheduler.tick(at=clock())

    assert list(scheduler.rounds) == [
        "GH13-20260923-010000-assignment",
        "GH8-20260819-184158-conversation",
        "GH14-20260923-010000-assignment",
    ]


def test_after_a_conversation_round_the_next_round_starts_an_assignment(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    offer_conversation(
        gh=gh, comments=[compose_question(), compose_question(identifier=2)]
    )
    offer_listing(
        gh=gh,
        issues=[
            compose_conversation_issue(labels=("dream:conversation", ASSIGNMENT_LABEL))
        ],
    )
    harnesses["claude"].replies(stdout="")

    observed = scheduler.tick(at=clock())

    assignment = read_assignments(state=scheduler.context.state)[0]
    assert observed.launched_agent_work_identifiers == [assignment.identifier]


def test_a_failed_assignment_candidate_does_not_block_a_ready_conversation(
    conversation_scheduler, harnesses, monkeypatch
):
    scheduler, clock, gh = conversation_scheduler
    write_assignment(
        state=scheduler.context.state,
        identifier="GH13-20260923-010000-assignment",
        issue=13,
        pull_request=None,
    )
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)
    launch = Scheduler._launch

    def fail_assignments(self, *, row, candidate, at):
        if row.kind is AgentWorkKind.ASSIGNMENT:
            raise AgentRoundLaunchError(
                agent_work_identifier="GH13-20260923-010000-assignment",
                round_number=1,
                reason="could not start assignment",
            )
        return launch(self, row=row, candidate=candidate, at=at)

    monkeypatch.setattr(Scheduler, "_launch", fail_assignments)

    observed = scheduler.tick(at=clock())

    assert observed.failures == []
    assert observed.rows[0].started_round == StartedRound(
        number=1, launch_failure="could not start assignment"
    )
    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]


def test_an_issue_without_an_eligible_comment_does_not_start(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(
        gh=gh,
        comments=[
            compose_question(
                identifier=1, body=f"an earlier answer\n{AGENT_POST_MARKER}"
            ),
            compose_question(identifier=2, body="somebody else")
            | {"user": {"login": "mallory"}},
        ],
    )

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert observed.rows == [
        compose_conversation_row(
            finding=IssueCommentsFinding(new_comments=0), title=OFFERED_TITLE
        )
    ]
    assert harnesses["claude"].calls == []
    assert read_conversation(state=scheduler.context.state, issue=8) is None


def test_a_conversation_waits_for_shared_capacity(conversation_scheduler, harnesses):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)

    observed = scheduler.tick(at=clock())

    assert scheduler.is_at_capacity
    assert observed.rows == [
        compose_conversation_row(
            finding=IssueCommentsFinding(new_comments=1), title=OFFERED_TITLE
        )
    ]
    assert harnesses["claude"].calls == []


def test_a_conversation_waits_for_the_active_global_cooldown(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    at = clock()
    write_json(
        document=SchedulerRecord(
            at=at,
            finished=at,
            cooldown=GlobalCooldown(started=at, ends=at + timedelta(minutes=15)),
        ),
        path=scheduler.context.state.scheduler_record,
    )

    observed = scheduler.tick(at=at)

    assert observed.cooldown is not None
    assert observed.failures == []
    assert observed.rows == [
        compose_conversation_row(
            finding=IssueCommentsFinding(new_comments=1), title=OFFERED_TITLE
        )
    ]
    assert harnesses["claude"].calls == []


def test_two_faulted_conversations_start_the_global_cooldown(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    fault_started = clock()
    for issue in (8, 9):
        write_faulted_conversation(
            state=scheduler.context.state,
            issue=issue,
            at=fault_started,
        )
    offer_listing(
        gh=gh,
        issues=[
            {
                "number": issue,
                "title": f"Issue {issue}",
                "body": "Explain it.",
                "createdAt": f"2026-09-{issue + 13:02d}T01:00:00Z",
                "state": "OPEN",
                "assignees": [{"login": POSTED_BY}],
                "labels": [{"name": "dream:conversation"}],
            }
            for issue in (8, 9)
        ],
    )
    tick_at = clock()

    observed = scheduler.tick(at=tick_at)

    assert observed.cooldown == GlobalCooldown(
        started=tick_at,
        ends=tick_at + timedelta(minutes=15),
    )
    assert observed.cooldown is not None
    assert observed.failures == []
    assert observed.launched_agent_work_identifiers == []
    assert harnesses["claude"].calls == []


def test_a_faulted_conversation_and_assignment_start_the_global_cooldown(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    fault_started = clock()
    write_faulted_conversation(state=scheduler.context.state, issue=8, at=fault_started)
    write_faulted_assignment(
        state=scheduler.context.state,
        issue=13,
        identifier="GH13-20260923-010000-assignment",
        at=fault_started,
    )
    offer_conversation(gh=gh, comments=[])
    tick_at = clock()

    observed = scheduler.tick(at=tick_at)

    assert observed.cooldown == GlobalCooldown(
        started=tick_at,
        ends=tick_at + timedelta(minutes=15),
    )
    assert observed.cooldown is not None
    assert observed.failures == []
    assert observed.launched_agent_work_identifiers == []
    assert harnesses["claude"].calls == []


def test_the_cooldown_boundary_clears_conversation_faults(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    fault_started = clock()
    for issue in (8, 9):
        write_faulted_conversation(
            state=scheduler.context.state,
            issue=issue,
            at=fault_started,
        )
    cooldown_ends = fault_started + timedelta(minutes=15)
    write_json(
        document=SchedulerRecord(
            at=fault_started,
            finished=fault_started,
            cooldown=GlobalCooldown(
                started=fault_started,
                ends=cooldown_ends,
            ),
        ),
        path=scheduler.context.state.scheduler_record,
    )
    offer_listing(
        gh=gh,
        issues=[
            {
                "number": issue,
                "title": f"Issue {issue}",
                "body": "Explain it.",
                "createdAt": f"2026-09-{issue + 13:02d}T01:00:00Z",
                "state": "OPEN",
                "assignees": [{"login": POSTED_BY}],
                "labels": [{"name": "dream:conversation"}],
            }
            for issue in (8, 9)
        ],
    )
    for issue in (8, 9):
        show_conversation_issue(
            gh=gh,
            issue=compose_conversation_issue(
                labels=("dream:conversation",), number=issue
            ),
        )
        gh.replies(
            stdout=compose_page(items=[compose_question()]),
            to=f"api repos/{REPOSITORY}/issues/{issue}/comments?per_page=100",
        )
    script_claude_answer(harnesses=harnesses, body=NO_REPLY)

    observed = scheduler.tick(at=cooldown_ends)
    finish(scheduler=scheduler)

    assert observed.cooldown is None
    assert observed.most_recent_cooldown_ended == cooldown_ends
    assert scheduler.is_at_capacity
    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]


def test_a_failed_post_gives_its_comments_again_with_new_ones(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)
    gh.fails(stderr="network unavailable", to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    first_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=1).round_input,
    )
    offer_conversation(
        gh=gh, comments=[compose_question(), compose_question(identifier=2)]
    )
    script_claude_answer(harnesses=harnesses, body="The answer, posted this time.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    observed = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    ending = conversation.rounds[0].ending
    assert isinstance(ending, FinishingErroredAgentRoundEnding)
    assert ending.reason.startswith("could not post the answer: ")
    feed = conversation.compose_round_paths(number=1).feed.read_text(encoding="utf-8")
    assert "[failed] could not post the answer: " in feed
    assert observed.failures == []
    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    assert len(conversation.rounds) == 2
    given_again = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert given_again == ConversationRoundInput(
        issue=8,
        comments=[compose_question(), compose_question(identifier=2)],
        revision=first_input.revision,
    )
    resumed = harnesses["claude"].calls[1]
    assert resumed.arguments[-2:] == ["--resume", "conversation-session"]
    assert resumed.prompt.startswith(UNFINISHED_ROUND_OPENING)
    assert "Issue-conversation input for GH8:" in resumed.prompt


def test_deleting_an_errored_rounds_comments_withdraws_them_until_a_new_one(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    state = scheduler.context.state
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, status=2)
    write_tick(state=state, tick=scheduler.tick(at=clock()))
    finish(scheduler=scheduler)

    assert read_status(state=state).value is AgentWorkStatusValue.WAITING

    offer_conversation(gh=gh, comments=[])
    withdrawn = scheduler.tick(at=clock())
    write_tick(state=state, tick=withdrawn)

    found = read_status(state=state)
    assert withdrawn.launched_agent_work_identifiers == []
    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail is not None
    assert found.detail.startswith("round 1, errored (exit 2), ran ")

    offer_conversation(
        gh=gh, comments=[compose_question(identifier=2, body="A new question.")]
    )
    script_claude_answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    asked = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert asked.launched_agent_work_identifiers == [conversation.identifier]
    given = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert [item.body for item in given.comments] == ["A new question."]
    resumed = harnesses["claude"].calls[1]
    assert resumed.arguments[-2:] == ["--resume", "conversation-session"]
    assert resumed.prompt.startswith(UNFINISHED_ROUND_OPENING)


def test_no_reply_completes_without_posting_a_comment(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, body=NO_REPLY)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    observed = scheduler.tick(at=clock())

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert observed.failures == []
    assert conversation.rounds[0].outcome is AgentRoundOutcome.SUCCESSFUL
    assert not any(call.arguments[:4] == POST_PATH.split() for call in gh.calls)


def test_two_errored_rounds_put_a_conversation_in_fault(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, status=2)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, status=2)
    retried = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.rounds[0].outcome is AgentRoundOutcome.ERRORED
    assert conversation.rounds[1].outcome is AgentRoundOutcome.ERRORED
    assert retried.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    assert len(harnesses["claude"].calls) == 2
    assert not any(call.arguments[:4] == POST_PATH.split() for call in gh.calls)
    offer_conversation(gh=gh, comments=[compose_question()])

    faulted = scheduler.tick(at=clock())

    assert faulted.launched_agent_work_identifiers == []
    assert len(harnesses["claude"].calls) == 2


def test_a_daemon_orphan_is_given_its_comments_again_in_its_saved_session(
    conversation_scheduler, harnesses, orphan_round_process
):
    scheduler, clock, gh = conversation_scheduler
    directory = write_conversation(state=scheduler.context.state, issue=8)
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    conversation.worktree.rmdir()
    _add_detached_worktree(
        root=scheduler.context.state.root, path=conversation.worktree
    )
    first_input = ConversationRoundInput(
        issue=8,
        initial_issue=InitialConversationIssue(
            title=OFFERED_TITLE,
            body="Explain the scheduler.",
        ),
        comments=[compose_question()],
        revision=_read_worktree_revision(worktree=conversation.worktree),
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=read_current_time(),
            pid=orphan_round_process.pid,
        ),
        round_input=first_input,
    )
    daemon = DreamcatcherDaemon(
        root=scheduler.context.state.root,
        preferred_harness=AgentHarness.CLAUDE,
    )
    daemon._sweep_orphans()
    assert wait_for_exit(pid=orphan_round_process.pid)
    offer_conversation(
        gh=gh, comments=[compose_question(), compose_question(identifier=2)]
    )
    script_claude_answer(harnesses=harnesses, body="The recovered answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    observed = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    recovered_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert recovered_input == ConversationRoundInput(
        issue=8,
        comments=[compose_question(), compose_question(identifier=2)],
        revision=first_input.revision,
    )
    resumed = harnesses["claude"].calls[0]
    assert resumed.arguments[-2:] == ["--resume", "conversation-session"]
    assert resumed.prompt.startswith(UNFINISHED_ROUND_OPENING)
    assert "Issue-conversation input for GH8:" in resumed.prompt


def test_an_interrupted_round_from_v6_1_is_withdrawn_once_an_update_finds_nothing(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    state = scheduler.context.state
    directory = write_conversation(state=state, issue=8)
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    conversation.worktree.rmdir()
    _add_detached_worktree(root=state.root, path=conversation.worktree)
    write_json(
        document=ConversationRoundInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title=OFFERED_TITLE,
                body="Explain the scheduler.",
            ),
            comments=[compose_question()],
            revision=_read_worktree_revision(worktree=conversation.worktree),
        ),
        path=conversation.compose_round_paths(number=1).round_input,
    )
    # An update made while the round ran counted its comment as relayed.
    updated = clock()
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=updated,
            finished=updated,
            rows=[
                compose_conversation_row(
                    agent_work_identifier=conversation.identifier,
                    finding=IssueCommentsFinding(new_comments=0),
                    title=OFFERED_TITLE,
                )
            ],
        ),
    )
    (directory / "rounds" / "1" / "round.json").write_bytes(
        b'{"number": 1, "started": "2026-08-19T18:41:58Z", "pid": 1,'
        b' "ending": {"outcome": "interrupted"}}'
    )

    assert read_status(state=state).value is AgentWorkStatusValue.WAITING

    offer_conversation(gh=gh, comments=[])
    withdrawn = scheduler.tick(at=clock())
    write_tick(state=state, tick=withdrawn)

    found = read_status(state=state)
    assert withdrawn.launched_agent_work_identifiers == []
    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == "round 1, interrupted"

    offer_conversation(
        gh=gh, comments=[compose_question(identifier=2, body="A new question.")]
    )
    script_claude_answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    asked = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert asked.launched_agent_work_identifiers == [conversation.identifier]
    given = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert [item.body for item in given.comments] == ["A new question."]
    resumed = harnesses["claude"].calls[0]
    assert resumed.arguments[-2:] == ["--resume", "conversation-session"]
    assert resumed.prompt.startswith(UNFINISHED_ROUND_OPENING)


def test_a_session_identifier_left_in_raw_output_is_found(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, status=2)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    (conversation.directory / _HARNESS_SESSION_RECORD_NAME).unlink()
    offer_conversation(
        gh=gh, comments=[compose_question(), compose_question(identifier=2)]
    )
    script_claude_answer(harnesses=harnesses, body="The recovered answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    observed = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    resumed = harnesses["claude"].calls[1]
    assert resumed.arguments[-2:] == ["--resume", "conversation-session"]
    assert resumed.prompt.startswith(UNFINISHED_ROUND_OPENING)
    assert "Issue-conversation input for GH8:" in resumed.prompt


def test_a_first_round_without_a_session_is_given_again_in_a_new_session(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    harnesses["claude"].streams(lines=[], status=2)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    offer_conversation(
        gh=gh, comments=[compose_question(), compose_question(identifier=2)]
    )
    script_claude_answer(harnesses=harnesses, body="The recovered answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    observed = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    assert conversation.harness_session_identifier == "conversation-session"
    restarted = harnesses["claude"].calls[1]
    assert "--resume" not in restarted.arguments
    assert restarted.prompt.startswith("/dream:conversation GH8")
    assert "Issue-conversation input for GH8:" in restarted.prompt


def test_a_follow_up_without_a_saved_session_starts_a_new_one(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    (conversation.directory / _HARNESS_SESSION_RECORD_NAME).unlink()
    conversation.compose_round_paths(number=1).raw_output.unlink()
    offer_conversation(
        gh=gh, comments=[compose_question(), compose_question(identifier=2)]
    )
    script_claude_answer(harnesses=harnesses)

    observed = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    restarted = harnesses["claude"].calls[1]
    assert "--resume" not in restarted.arguments
    assert restarted.prompt.startswith("/dream:conversation GH8")
    follow_up = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert follow_up.initial_issue is not None
    assert [comment.id for comment in follow_up.comments] == [2]


def test_a_failed_listing_leaves_open_conversations_inspected(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    write_conversation(state=scheduler.context.state, issue=8)
    gh.fails(
        stderr="network unavailable",
        to="issue list",
    )
    show_conversation_issue(
        gh=gh, issue=compose_conversation_issue(labels=("dream:conversation",))
    )
    gh.replies(stdout=compose_page(items=[]), to=COMMENT_PATH)

    observed = scheduler.tick(at=clock())

    [failure] = observed.failures
    assert failure.startswith("could not list issues")
    assert observed.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            finding=IssueCommentsFinding(new_comments=0),
        )
    ]


def test_open_conversation_faults_start_the_cooldown_whatever_the_listing(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    fault_started = clock()
    for issue in (8, 9):
        write_faulted_conversation(
            state=scheduler.context.state,
            issue=issue,
            at=fault_started,
        )
        show_conversation_issue(
            gh=gh,
            issue=compose_conversation_issue(
                labels=("dream:conversation",), number=issue
            ),
        )
    gh.fails(
        stderr="network unavailable",
        to="issue list",
    )
    tick_at = clock()

    observed = scheduler.tick(at=tick_at)

    assert observed.cooldown == GlobalCooldown(
        started=tick_at,
        ends=tick_at + timedelta(minutes=15),
    )
    [failure] = observed.failures
    assert observed.cooldown is not None
    assert failure.startswith("could not list issues")
    assert observed.rows == [
        compose_conversation_row(
            issue=issue,
            agent_work_identifier=compose_conversation_identifier(issue=issue),
            ended_round=2,
            finding=None,
        )
        for issue in (8, 9)
    ]


@pytest.mark.parametrize(
    ("issue", "cause"),
    [
        (compose_conversation_issue(labels=()), PauseCause.LABEL_REMOVED),
        (
            compose_conversation_issue(labels=("dream:conversation",), assignees=()),
            PauseCause.ISSUE_UNASSIGNED,
        ),
    ],
    ids=["label removed", "issue unassigned"],
)
def test_a_paused_conversation_says_why_and_its_comments_are_not_read(
    conversation_scheduler, issue, cause
):
    scheduler, clock, gh = conversation_scheduler
    write_conversation(state=scheduler.context.state, issue=8)
    show_conversation_issue(gh=gh, issue=issue)

    observed = scheduler.tick(at=clock())

    assert observed.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            finding=PausedFinding(cause=cause),
        )
    ]
    assert count_comment_reads(gh=gh) == 0


def test_a_conversation_whose_issue_closes_ends_without_its_comments_read(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    write_conversation(state=scheduler.context.state, issue=8)
    show_conversation_issue(
        gh=gh,
        issue=compose_conversation_issue(
            labels=("dream:conversation",), state="CLOSED"
        ),
    )

    observed = scheduler.tick(at=clock())

    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.ending is not None
    assert conversation.ending.reason is AgentWorkEndReason.ISSUE_CLOSED
    assert observed.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            finding=None,
        )
    ]
    assert count_comment_reads(gh=gh) == 0
    assert scheduler.tick(at=clock()).rows == []


def test_a_conversation_whose_issue_cannot_be_read_is_unknown(conversation_scheduler):
    scheduler, clock, gh = conversation_scheduler
    write_conversation(state=scheduler.context.state, issue=8)
    gh.fails(stderr="network unavailable", to=f"issue view 8 --repo {REPOSITORY}")

    observed = scheduler.tick(at=clock())

    [row] = observed.rows
    assert isinstance(row.finding, ReadFailureFinding)
    assert "network unavailable" in row.finding.reason
    assert count_comment_reads(gh=gh) == 0


def test_a_paused_conversation_does_not_retry_its_errored_round(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    directory = write_conversation(state=scheduler.context.state, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=clock(),
            pid=1,
            ending=HarnessErroredAgentRoundEnding(at=clock(), status=2),
        ),
    )
    show_conversation_issue(gh=gh, issue=compose_conversation_issue(labels=()))

    observed = scheduler.tick(at=clock())

    assert observed.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            ended_round=1,
            finding=PAUSED,
        )
    ]
    assert observed.launched_agent_work_identifiers == []
    assert count_comment_reads(gh=gh) == 0
    assert harnesses["claude"].calls == []


def test_paused_conversation_faults_do_not_start_the_global_cooldown(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    fault_started = clock()
    for issue in (8, 9):
        write_faulted_conversation(
            state=scheduler.context.state,
            issue=issue,
            at=fault_started,
        )
        show_conversation_issue(
            gh=gh, issue=compose_conversation_issue(labels=(), number=issue)
        )
    tick_at = clock()

    observed = scheduler.tick(at=tick_at)

    assert observed.cooldown is None
    assert observed.failures == []
    assert observed.rows == [
        compose_conversation_row(
            issue=issue,
            agent_work_identifier=compose_conversation_identifier(issue=issue),
            ended_round=2,
            finding=PAUSED,
        )
        for issue in (8, 9)
    ]
    assert count_comment_reads(gh=gh) == 0


def test_a_relayed_round_whose_input_cannot_be_read_fails_the_update(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    directory = write_conversation(state=scheduler.context.state, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=clock(),
            pid=1,
            ending=SuccessfulAgentRoundEnding(at=clock()),
        ),
    )
    round_input = directory / "rounds" / "1" / "round-input.json"
    round_input.write_bytes(b"not json\n")
    offer_conversation(gh=gh, comments=[compose_question()])

    with pytest.raises(ReportableError, match=r"round-input\.json is not valid"):
        scheduler.tick(at=clock())

    assert harnesses["claude"].calls == []


@pytest.mark.parametrize(
    "comments",
    [[], MISORDERED_COMMENTS, REPEATED_COMMENTS],
    ids=["none", "misordered", "repeated"],
)
def test_a_relayed_round_with_comments_the_relay_never_gives_fails_the_update(
    conversation_scheduler, harnesses, comments
):
    scheduler, clock, gh = conversation_scheduler
    directory = write_conversation(state=scheduler.context.state, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=clock(),
            pid=1,
            ending=SuccessfulAgentRoundEnding(at=clock()),
        ),
        round_input=ConversationRoundInput(
            issue=8, comments=[compose_question()], revision="abc123"
        ),
    )
    round_input = directory / "rounds" / "1" / "round-input.json"
    replace_relayed_comments(path=round_input, comments=comments)
    offer_conversation(gh=gh, comments=[compose_question(identifier=2)])

    with pytest.raises(ReportableError, match=r"round-input\.json is not valid"):
        scheduler.tick(at=clock())

    assert harnesses["claude"].calls == []


@pytest.mark.parametrize(
    ("issue", "cause"),
    [
        (compose_conversation_issue(labels=()), PauseCause.LABEL_REMOVED),
        (
            compose_conversation_issue(labels=("dream:conversation",), assignees=()),
            PauseCause.ISSUE_UNASSIGNED,
        ),
    ],
    ids=["label removed", "issue unassigned"],
)
def test_a_resumed_conversation_is_given_comments_posted_while_it_was_paused(
    conversation_scheduler, harnesses, issue, cause
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, body="The first answer.")
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    scheduler.tick(at=clock())
    comment_reads_before = count_comment_reads(gh=gh)
    show_conversation_issue(gh=gh, issue=issue)

    paused = scheduler.tick(at=clock())

    assert paused.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            ended_round=1,
            finding=PausedFinding(cause=cause),
            title=OFFERED_TITLE,
        )
    ]
    assert count_comment_reads(gh=gh) == comment_reads_before
    offer_conversation(
        gh=gh,
        comments=[
            compose_question(),
            compose_question(identifier=2, body="A question posted while paused"),
        ],
    )
    script_claude_answer(harnesses=harnesses, body="The later answer.")

    resumed = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert resumed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    later_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=2).round_input,
    )
    assert [item.body for item in later_input.comments] == [
        "A question posted while paused"
    ]
    resumed_call = harnesses["claude"].calls[1]
    assert resumed_call.arguments[-2:] == ["--resume", "conversation-session"]


def test_an_open_conversation_carries_on_when_its_route_is_removed(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    write_conversation(state=scheduler.context.state, issue=8)
    set_scheduler_config(
        scheduler=scheduler,
        config=scheduler.context.config.model_copy(update={"conversation": []}),
    )
    show_conversation_issue(
        gh=gh, issue=compose_conversation_issue(labels=("dream:conversation",))
    )
    gh.replies(stdout=compose_page(items=[]), to=COMMENT_PATH)

    observed = scheduler.tick(at=clock())

    assert observed.rows == [
        compose_conversation_row(
            agent_work_identifier=compose_conversation_identifier(issue=8),
            finding=IssueCommentsFinding(new_comments=0),
        )
    ]


def test_an_open_conversation_matches_its_label_and_assignee_in_any_case(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    root = scheduler.context.state.root
    configure(
        root=root,
        head=CONVERSATION_CONFIG.replace(
            'label = "dream:conversation"', 'label = "Dream:Conversation"'
        ),
    )
    set_scheduler_config(
        scheduler=scheduler, config=read_dreamcatcher_config(root=root)
    )
    write_conversation(
        state=scheduler.context.state, issue=8, dispatch_label="dream:CONVERSATION"
    )
    issue = compose_conversation_issue(
        labels=("DREAM:CONVERSATION",), assignees=(POSTED_BY.upper(),)
    )
    offer_listing(gh=gh, issues=[issue])
    show_conversation_issue(gh=gh, issue=issue)
    gh.replies(stdout=compose_page(items=[]), to=COMMENT_PATH)

    observed = scheduler.tick(at=clock())

    assert observed.rows == [
        compose_conversation_row(
            label="dream:CONVERSATION",
            agent_work_identifier=compose_conversation_identifier(issue=8),
            finding=IssueCommentsFinding(new_comments=0),
        )
    ]


def test_a_conversation_whose_route_is_removed_still_pauses_for_a_second_label(
    conversation_scheduler, harnesses
):
    scheduler, _, gh = conversation_scheduler
    configure(root=scheduler.context.state.root, head=SECOND_CONVERSATION_CONFIG)
    set_scheduler_config(
        scheduler=scheduler,
        config=read_dreamcatcher_config(root=scheduler.context.state.root),
    )
    write_conversation(state=scheduler.context.state, issue=8)
    labels = ("dream:conversation", "dream:scout")
    offer_conversation(gh=gh, comments=[compose_question()], label="dream:scout")
    show_conversation_issue(gh=gh, issue=compose_conversation_issue(labels=labels))
    script_claude_answer(harnesses=harnesses)

    observed = scheduler.tick(at=PINNED + timedelta(hours=1))
    finish(scheduler=scheduler)

    assert observed.rows[0] == compose_conversation_row(
        agent_work_identifier=compose_conversation_identifier(issue=8),
        finding=ConflictingLabelsFinding(labels=list(labels)),
    )
    assert observed.launched_agent_work_identifiers == [
        observed.rows[1].agent_work_identifier
    ]


def test_no_conversation_routes_still_read_saved_conversations(conversation_scheduler):
    scheduler, clock, _ = conversation_scheduler
    directory = write_conversation(state=scheduler.context.state, issue=8)
    (directory / "work.json").write_bytes(b"{}\n")
    set_scheduler_config(
        scheduler=scheduler,
        config=scheduler.context.config.model_copy(update={"conversation": []}),
    )

    with pytest.raises(ReportableError, match=r"work\.json"):
        scheduler.tick(at=clock())


def test_a_failed_comment_read_records_its_reason_and_starts_nothing(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[])
    gh.fails(stderr="network unavailable", to=COMMENT_PATH)

    observed = scheduler.tick(at=clock())

    assert observed.failures == []
    assert observed.launched_agent_work_identifiers == []
    [row] = observed.rows
    assert isinstance(row.finding, ReadFailureFinding)
    assert "issues/8/comments" in row.finding.reason
    assert row.finding.reason.endswith("network unavailable")
    assert row == compose_conversation_row(finding=row.finding, title=OFFERED_TITLE)


@pytest.mark.parametrize("is_valid", [True, False], ids=["stale", "malformed"])
def test_an_unrecorded_round_input_is_replaced_by_the_next_batch(
    conversation_scheduler, harnesses, is_valid
):
    scheduler, clock, gh = conversation_scheduler
    write_conversation(state=scheduler.context.state, issue=8)
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    conversation.worktree.rmdir()
    _add_detached_worktree(
        root=scheduler.context.state.root,
        path=conversation.worktree,
    )
    round_input = conversation.compose_round_paths(number=1).round_input
    if is_valid:
        write_json(
            document=ConversationRoundInput(
                issue=8,
                initial_issue=InitialConversationIssue(
                    title=OFFERED_TITLE,
                    body="Explain the scheduler.",
                ),
                comments=[compose_question(body="stale saved input")],
                revision="abc123",
            ),
            path=round_input,
        )
    else:
        round_input.parent.mkdir(parents=True)
        round_input.write_bytes(b"not json")
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    observed = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert observed.failures == []
    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    replaced = read_json(
        model=ConversationRoundInput,
        path=round_input,
    )
    assert [comment.body for comment in replaced.comments] == ["Please explain."]
    assert replaced.revision != "abc123"
    assert len(harnesses["claude"].calls) == 1


def test_a_failed_comment_read_leaves_the_other_requests_to_start(
    conversation_scheduler, harnesses
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
    offer_listing(gh=gh, issues=issues)
    gh.replies(stdout=compose_page(items=[compose_question()]), to=COMMENT_PATH)
    gh.fails(
        stderr="issue-specific failure",
        to=f"api repos/{REPOSITORY}/issues/9/comments?per_page=100",
    )
    gh.replies(
        stdout=compose_page(items=[compose_question(identifier=2)]),
        to=f"api repos/{REPOSITORY}/issues/10/comments?per_page=100",
    )

    script_claude_answer(harnesses=harnesses)

    observed = scheduler.tick(at=clock())

    assert observed.failures == []
    assert [row.issue for row in observed.rows] == [8, 9, 10]
    failed_read = observed.rows[1].finding
    assert isinstance(failed_read, ReadFailureFinding)
    assert "issues/9/comments" in failed_read.reason
    assert any("issues/10/comments" in " ".join(call.arguments) for call in gh.calls)
    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]


def test_an_existing_empty_conversation_can_start(conversation_scheduler, harnesses):
    scheduler, clock, gh = conversation_scheduler
    write_conversation(state=scheduler.context.state, issue=8)
    worktree = scheduler.context.state.worktrees / compose_conversation_identifier(
        issue=8
    )
    worktree.rmdir()
    _add_detached_worktree(root=scheduler.context.state.root, path=worktree)
    (scheduler.context.state.root / "README.md").write_bytes(b"new main before retry\n")
    commit(path=scheduler.context.state.root, message="advance main before retry")
    run_git(arguments=["push", "origin", "main"], cwd=scheduler.context.state.root)
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    round_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=1).round_input,
    )
    assert round_input.revision == _read_worktree_revision(worktree=worktree)
    assert (worktree / "README.md").read_text(encoding="utf-8") == (
        "new main before retry\n"
    )
    assert (
        run_git(
            arguments=["branch", "--show-current"], cwd=scheduler.context.state.root
        ).strip()
        == "main"
    )


def test_a_missing_conversation_worktree_is_added_without_detaching_main(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    write_conversation(state=scheduler.context.state, issue=8)
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)
    gh.replies(stdout=json.dumps({"id": 99}), to=POST_PATH)

    observed = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert observed.failures == []
    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    conversation = read_conversation(state=scheduler.context.state, issue=8)
    assert conversation is not None
    assert conversation.worktree.joinpath(".git").is_file()
    assert (
        run_git(
            arguments=["branch", "--show-current"], cwd=scheduler.context.state.root
        ).strip()
        == "main"
    )


def test_a_conversation_worktree_that_cannot_be_added_errors_its_round(
    conversation_scheduler,
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    worktree = scheduler.context.state.worktrees / compose_conversation_identifier(
        issue=8
    )
    worktree.mkdir(parents=True)
    (worktree / "occupied").write_bytes(b"not a worktree\n")

    observed = scheduler.tick(at=clock())

    assert observed.failures == []
    [row] = observed.rows
    assert row.started_round is not None
    assert row.started_round.number == 1
    assert row.started_round.launch_failure is not None
    assert "git worktree add --detach" in row.started_round.launch_failure
    assert observed.launched_agent_work_identifiers == []


def test_new_conversations_start_in_listing_order(conversation_scheduler, harnesses):
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
    offer_listing(gh=gh, issues=issue_list)
    gh.replies(
        stdout=compose_page(
            items=[
                compose_question(identifier=2) | {"created_at": "2026-09-23T02:00:00Z"}
            ]
        ),
        to=f"api repos/{REPOSITORY}/issues/8/comments?per_page=100",
    )
    gh.replies(
        stdout=compose_page(
            items=[
                compose_question(identifier=1) | {"created_at": "2026-09-23T01:00:00Z"}
            ]
        ),
        to=f"api repos/{REPOSITORY}/issues/9/comments?per_page=100",
    )
    script_claude_answer(harnesses=harnesses)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]


def test_an_open_conversation_starts_before_a_new_one(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, status=2)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    offer_listing(
        gh=gh,
        issues=[
            {
                "number": number,
                "title": f"Issue {number}",
                "body": "Explain it.",
                "createdAt": f"2026-09-{number + 13:02d}T01:00:00Z",
                "state": "OPEN",
                "assignees": [{"login": POSTED_BY}],
                "labels": [{"name": "dream:conversation"}],
            }
            for number in (8, 9)
        ],
    )
    gh.replies(
        stdout=compose_page(items=[compose_question(identifier=2)]),
        to=f"api repos/{REPOSITORY}/issues/9/comments?per_page=100",
    )
    script_claude_answer(harnesses=harnesses)

    observed = scheduler.tick(at=clock())

    assert scheduler.is_at_capacity
    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    assert observed.rows == [
        compose_conversation_row(
            agent_work_identifier="GH8-20260819-184158-conversation",
            ended_round=1,
            finding=IssueCommentsFinding(new_comments=1),
            started_round=StartedRound(number=2),
            title=OFFERED_TITLE,
        ),
        compose_conversation_row(issue=9, finding=IssueCommentsFinding(new_comments=1)),
    ]


def test_an_unrelated_comment_failure_does_not_block_an_unfinished_round(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses, status=2)
    scheduler.tick(at=clock())
    finish(scheduler=scheduler)
    offer_listing(
        gh=gh,
        issues=[
            {
                "number": number,
                "title": f"Issue {number}",
                "body": "Explain it.",
                "createdAt": f"2026-09-{number + 13:02d}T01:00:00Z",
                "state": "OPEN",
                "assignees": [{"login": POSTED_BY}],
                "labels": [{"name": "dream:conversation"}],
            }
            for number in (8, 9)
        ],
    )
    gh.fails(
        stderr="network unavailable",
        to=f"api repos/{REPOSITORY}/issues/9/comments?per_page=100",
    )
    script_claude_answer(harnesses=harnesses, body=NO_REPLY)

    observed = scheduler.tick(at=clock())
    finish(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [
        "GH8-20260819-184158-conversation"
    ]
    assert observed.failures == []
    failed_read = observed.rows[1].finding
    assert isinstance(failed_read, ReadFailureFinding)
    assert "issues/9/comments" in failed_read.reason
    assert "network unavailable" in failed_read.reason


def test_an_ended_conversation_is_left_alone_and_a_comment_starts_another(
    conversation_scheduler, harnesses
):
    scheduler, clock, gh = conversation_scheduler
    ended = write_conversation(state=scheduler.context.state, issue=8)
    write_ending(
        directory=ended,
        reason=AgentWorkEndReason.COMPLETED,
        at=clock(),
    )
    offer_conversation(gh=gh, comments=[compose_question()])
    script_claude_answer(harnesses=harnesses)

    launched = scheduler.tick(at=clock())

    [identifier] = launched.launched_agent_work_identifiers
    assert identifier != ended.name
    assert not (ended / "rounds").exists()
