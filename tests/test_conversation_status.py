"""Read local status for issue conversations."""

import os
from datetime import timedelta

import pytest
from clocks import PINNED
from observations import observed_conversation
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
from dreamcatcher.scheduler import (
    IssueConversationObservation,
    IssueFactValue,
    SchedulerRecord,
)
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
            conversation_observations=[observed_conversation()],
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


def observe(
    *,
    state: StateDirectory,
    observations: list[IssueConversationObservation],
) -> None:
    """Write a tick that made these conversation observations."""
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, conversation_observations=observations),
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


def test_a_conversation_nobody_has_commented_on_is_idle(conversation_state):
    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.IDLE
    assert found.detail == "no comments yet"
    assert found.is_listed
    assert not found.is_over
    assert found.round_statuses == []


def test_a_conversation_with_comments_to_answer_is_waiting(conversation_state):
    observe(
        state=conversation_state,
        observations=[
            observed_conversation(
                value=IssueFactValue.TRUE,
                evidence="2 comments to answer, waiting for a free agent",
            )
        ],
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "2 comments to answer, waiting for a free agent"


def test_a_conversation_whose_comments_cannot_be_read_is_unknown(
    conversation_state,
):
    observe(
        state=conversation_state,
        observations=[
            observed_conversation(
                value=IssueFactValue.UNKNOWN,
                evidence="could not read comments for GH8: network unavailable",
            )
        ],
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.UNKNOWN
    assert found.detail == "could not read comments for GH8: network unavailable"
    assert found.is_listed


def test_a_conversation_no_tick_has_observed_is_unknown(conversation_state):
    conversation_state.scheduler_record.unlink()

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.UNKNOWN
    assert found.detail == "no current scheduler observation"
    assert found.is_listed


def test_an_ineligible_conversation_is_idle_and_leaves_the_report(
    conversation_state,
):
    conversation_round(state=conversation_state)
    observe(state=conversation_state, observations=[])

    found = status(state=conversation_state)
    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)

    assert found.value is IssueConversationStatusValue.IDLE
    assert found.detail == "issue is not eligible for conversation"
    assert not found.is_listed
    assert found.is_over
    assert report.conversation_statuses == []


def test_an_unrecorded_round_input_is_a_fault(conversation_state):
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

    assert found.value is IssueConversationStatusValue.FAULT
    assert found.detail == "round 1 input exists without a round record"


def test_a_live_round_keeps_an_ineligible_conversation_on_the_report(
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
    observe(state=conversation_state, observations=[])

    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)
    found = report.conversation_statuses[0]

    assert report.running_agents == 1
    assert found.value is IssueConversationStatusValue.WORKING
    assert found.detail == "round 1, running 2h 0m, last output 1h 59m ago"
    assert found.latest_output == "I am reading the scheduler."
    assert found.observed_at == PINNED
    assert not found.is_over
    assert found.round_statuses[0].outcome_description == "running"
    assert found.round_statuses[0].revision == "abc123"


def test_a_live_conversation_that_has_said_nothing_reports_that(
    conversation_state,
):
    conversation_state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    conversation_round(state=conversation_state, status=None)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WORKING
    assert found.detail == "round 1, running 2h 0m, has said nothing yet"
    assert found.latest_output is None


def test_an_unended_round_with_no_daemon_is_a_fault(conversation_state):
    conversation_round(state=conversation_state, status=None)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.FAULT
    assert found.detail == "round 1 interrupted"
    assert found.round_statuses[0].outcome_description == "interrupted"


def test_an_errored_round_is_a_fault(conversation_state):
    conversation_round(state=conversation_state, status=2)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.FAULT
    assert found.detail == "round 1 errored (exit 2)"
    assert found.is_over


def test_a_fault_at_an_ineligible_issue_leaves_the_report(conversation_state):
    conversation_round(state=conversation_state, status=2)
    observe(state=conversation_state, observations=[])

    found = status(state=conversation_state)
    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)

    assert found.value is IssueConversationStatusValue.FAULT
    assert report.conversation_statuses == []


def test_an_errored_conversation_reports_an_unreadable_input(conversation_state):
    conversation_round(state=conversation_state, status=2)
    conversation = read_issue_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.FAULT
    assert "inbox.json is not valid" in found.detail


def test_a_posted_answer_leaves_the_conversation_idle(conversation_state):
    conversation_round(state=conversation_state)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.IDLE
    assert found.detail == "round 1, answered, ran 4m"
    assert not found.is_over
    assert found.round_statuses[0].duration_description == "ran 4m"


def test_an_unreadable_delivered_input_is_a_fault(conversation_state):
    conversation_round(state=conversation_state)
    conversation = read_issue_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.FAULT
    assert "inbox.json is not valid" in found.detail


def test_an_eligible_issue_is_a_conversation_before_its_record_exists(tmp_path):
    state = StateDirectory(root=tmp_path)
    observe(
        state=state,
        observations=[
            observed_conversation(
                issue=9, value=IssueFactValue.TRUE, evidence="1 comment to answer"
            )
        ],
    )

    report = read_status_report(state=state, clock=lambda: LOOKED_AT)
    found = read_issue_conversation_status(state=state, issue=9)

    assert found is not None
    assert report.conversation_statuses == [found]
    assert found.conversation is None
    assert found.issue == 9
    assert found.title == "Issue 9"
    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "1 comment to answer"
    assert found.round_statuses == []


def test_an_eligible_issue_nobody_has_commented_on_is_idle(tmp_path):
    state = StateDirectory(root=tmp_path)
    observe(state=state, observations=[observed_conversation(issue=9)])

    found = read_issue_conversation_status(state=state, issue=9)

    assert found is not None
    assert found.value is IssueConversationStatusValue.IDLE
    assert found.detail == "no comments yet"


def test_an_unobserved_issue_with_no_record_has_no_conversation(conversation_state):
    assert read_issue_conversation_status(state=conversation_state, issue=9) is None
