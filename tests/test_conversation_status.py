"""Read local status for issue conversations."""

import os
from datetime import timedelta

import pytest
from clocks import PINNED
from records import (
    write_daemon_run,
    write_feed,
    write_issue_conversation,
    write_round,
    write_tick,
)

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    IssueConversationInput,
    IssueConversationRoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.documents import write_json
from dreamcatcher.feed import FeedLine
from dreamcatcher.issue_conversations import read_issue_conversation
from dreamcatcher.scheduler import IssueFact, IssueFactValue, SchedulerRecord
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    IssueConversationStatusValue,
    read_issue_conversation_status,
    read_status_report,
)

LOOKED_AT = PINNED + timedelta(hours=2)


@pytest.fixture
def conversation_state(tmp_path):
    """Return local state containing one issue conversation."""
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())
    write_issue_conversation(state=state, issue=8)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_eligibility={
                8: IssueFact(value=IssueFactValue.TRUE),
            },
        ),
    )
    return state


def conversation_round(*, state: StateDirectory, status: int | None = 0) -> None:
    """Write the conversation's initial round with the requested process status."""
    ending = (
        None
        if status is None
        else compose_agent_round_ending(at=PINNED + timedelta(minutes=4), status=status)
    )
    directory = state.conversations / "GH8"
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=IssueConversationRoundPurpose.DISCUSS,
            started=PINNED,
            pid=1,
            ending=ending,
        ),
    )
    conversation = read_issue_conversation(state=state, issue=8)
    assert conversation is not None
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
        path=conversation.compose_round_paths(number=1).round_input,
    )


def status(*, state: StateDirectory):
    """Return the fixture conversation's status at the pinned time."""
    found = read_issue_conversation_status(
        state=state, issue=8, clock=lambda: LOOKED_AT
    )
    assert found is not None
    return found


def test_a_missing_conversation_has_no_status(tmp_path):
    assert (
        read_issue_conversation_status(state=StateDirectory(root=tmp_path), issue=8)
        is None
    )


def test_a_conversation_with_no_round_is_waiting(conversation_state):
    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "initial round has not started"
    assert found.round_statuses == []


def test_an_ineligible_conversation_with_no_round_is_inactive(conversation_state):
    write_tick(
        state=conversation_state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_eligibility={
                8: IssueFact(value=IssueFactValue.FALSE),
            },
        ),
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.INACTIVE
    assert found.detail == "issue is not eligible for conversation"


def test_a_conversation_with_unknown_eligibility_is_waiting(conversation_state):
    write_tick(
        state=conversation_state,
        tick=SchedulerRecord(at=PINNED),
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "issue conversation eligibility is unknown"


def test_an_unrecorded_round_input_needs_attention(conversation_state):
    conversation = read_issue_conversation(state=conversation_state, issue=8)
    assert conversation is not None
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
        path=conversation.compose_round_paths(number=1).round_input,
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.NEEDS_ATTENTION
    assert found.detail == "round 1 input exists without a round record"


def test_a_live_conversation_round_counts_capacity_and_shows_latest_output(
    conversation_state,
):
    conversation_state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    conversation_round(state=conversation_state, status=None)
    write_feed(
        directory=conversation_state.conversations / "GH8",
        number=1,
        lines=[
            FeedLine(
                at=PINNED + timedelta(minutes=1),
                text="I am reading the scheduler.",
            )
        ],
    )
    write_tick(
        state=conversation_state,
        tick=SchedulerRecord(at=PINNED),
    )

    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)
    found = report.conversation_statuses[0]

    assert report.running_agents == 1
    assert found.value is IssueConversationStatusValue.RUNNING
    assert found.detail == "round 1, running 2h 0m, last output 1h 59m ago"
    assert found.latest_output == "I am reading the scheduler."
    assert found.observed_at == PINNED
    assert found.round_statuses[0].outcome_description == "running"
    assert found.round_statuses[0].revision == "abc123"


def test_a_live_conversation_that_has_said_nothing_reports_that(
    conversation_state,
):
    conversation_state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    conversation_round(state=conversation_state, status=None)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.RUNNING
    assert found.detail == "round 1, running 2h 0m, has said nothing yet"
    assert found.latest_output is None


def test_an_unended_conversation_with_no_daemon_needs_attention(
    conversation_state,
):
    conversation_round(state=conversation_state, status=None)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.NEEDS_ATTENTION
    assert found.detail == "round 1 was interrupted"
    assert found.round_statuses[0].outcome_description == "interrupted"


def test_an_errored_conversation_needs_attention(conversation_state):
    conversation_round(state=conversation_state, status=2)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.NEEDS_ATTENTION
    assert found.detail == "errored (exit 2)"


def test_an_errored_conversation_reports_an_unreadable_input(conversation_state):
    conversation_round(state=conversation_state, status=2)
    conversation = read_issue_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.NEEDS_ATTENTION
    assert "inbox.json is not valid" in found.detail


def test_a_posted_answer_waits_for_new_comments(conversation_state):
    conversation_round(state=conversation_state)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "waiting for new comments after round 1"
    assert found.round_statuses[0].duration_description == "ran 4m"


def test_a_finished_ineligible_conversation_is_inactive(conversation_state):
    conversation_round(state=conversation_state)
    write_tick(
        state=conversation_state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_eligibility={
                8: IssueFact(value=IssueFactValue.FALSE),
            },
        ),
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.INACTIVE
    assert found.detail == "issue is not eligible for conversation"


def test_a_finished_conversation_with_unknown_eligibility_waits(
    conversation_state,
):
    conversation_round(state=conversation_state)
    write_tick(
        state=conversation_state,
        tick=SchedulerRecord(at=PINNED),
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "issue conversation eligibility is unknown"


def test_an_unreadable_delivered_input_needs_attention(conversation_state):
    conversation_round(state=conversation_state)
    conversation = read_issue_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.NEEDS_ATTENTION
    assert "inbox.json is not valid" in found.detail
