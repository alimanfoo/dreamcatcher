"""Read local status for issue conversations."""

import os
from datetime import timedelta

import pytest
from clocks import PINNED
from observations import observed_conversation
from records import (
    write_daemon_run,
    write_feed,
    write_final_output,
    write_issue_conversation,
    write_round,
    write_tick,
)

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    ErroredAgentRoundEnding,
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


def conversation_round(
    *,
    state: StateDirectory,
    number: int = 1,
    status: int | None = 0,
    reason: str | None = None,
    failure: str | None = None,
) -> None:
    """Write one conversation round with the requested outcome."""
    started = PINNED + timedelta(minutes=(number - 1) * 6)
    ending = (
        ErroredAgentRoundEnding(at=started + timedelta(minutes=4), reason=reason)
        if reason is not None
        else (
            None
            if status is None
            else compose_agent_round_ending(
                at=started + timedelta(minutes=4),
                status=status,
                failure=failure,
            )
        )
    )
    directory = state.conversations / "GH8"
    write_round(
        directory=directory,
        number=number,
        record=AgentRoundRecord(
            number=number,
            purpose=IssueConversationRoundPurpose.DISCUSS,
            started=started,
            pid=None if reason is not None else 1,
            ending=ending,
            is_recovery=number > 1,
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
                    "id": number,
                    "body": "Please explain.",
                    "author": "alice",
                    "written_at": "2026-09-23T01:00:00Z",
                }
            ],
            revision="abc123" if number == 1 else "def456",
        ),
        path=conversation.compose_round_paths(number=number).round_input,
    )
    write_final_output(directory=directory, number=number, text="The answer.")


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
                evidence="2 comments to answer",
            )
        ],
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "2 comments to answer"


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


def test_an_unrecorded_round_input_waits_for_recovery(conversation_state):
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
    failure = (
        "could not inspect saved conversation GH8: Conversation conversation-GH8 "
        "has input for round 1 without a round record."
    )
    observe(
        state=conversation_state,
        observations=[
            observed_conversation(value=IssueFactValue.UNKNOWN, evidence=failure)
        ],
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "round 1 input is waiting for recovery"


def test_an_unreadable_unrecorded_round_input_is_unknown(conversation_state):
    conversation = read_issue_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    paths = conversation.compose_round_paths(number=1)
    paths.directory.mkdir(parents=True)
    paths.round_input.write_bytes(b"not json")

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.UNKNOWN
    assert "inbox.json is not valid" in found.detail


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


def test_an_unended_conversation_with_no_daemon_waits_for_recovery(
    conversation_state,
):
    conversation_round(state=conversation_state, status=None)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "round 1 interrupted; waiting for recovery"
    assert found.round_statuses[0].outcome_description == "interrupted"


def test_an_errored_conversation_waits_for_recovery(conversation_state):
    conversation_round(state=conversation_state, status=2)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "round 1 errored (exit 2); waiting for recovery"
    assert not found.is_over


def test_a_conversation_launch_failure_reports_its_reason(conversation_state):
    conversation_round(
        state=conversation_state,
        reason="the harness was unavailable",
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == (
        "round 1 errored: the harness was unavailable; waiting for recovery"
    )
    assert found.round_statuses[0].outcome_description == "errored"


def test_two_errored_conversation_rounds_report_a_fault(conversation_state):
    conversation_round(state=conversation_state, status=2)
    conversation_round(
        state=conversation_state,
        number=2,
        status=2,
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.FAULT
    assert found.detail == "two consecutive rounds failed; round 2 errored (exit 2)"
    assert found.round_statuses[1].record.is_recovery is True


def test_a_cooldown_boundary_clears_a_conversation_fault(conversation_state):
    conversation_round(state=conversation_state, status=2)
    conversation_round(
        state=conversation_state,
        number=2,
        status=2,
    )
    write_tick(
        state=conversation_state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(minutes=11),
            most_recent_cooldown_ended=PINNED + timedelta(minutes=11),
        ),
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "round 2 errored (exit 2); waiting for recovery"


@pytest.mark.parametrize(
    "failure",
    [
        "could not post the answer on GH8: network unavailable",
        "the harness returned no final output",
    ],
)
def test_a_round_that_could_not_be_finished_says_why(conversation_state, failure):
    conversation_round(state=conversation_state, failure=failure)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == f"round 1 errored: {failure}; waiting for recovery"
    assert found.round_statuses[0].outcome_description == "errored"


def test_a_round_to_recover_comes_before_comments_to_answer(conversation_state):
    conversation_round(state=conversation_state, status=2)
    observe(
        state=conversation_state,
        observations=[
            observed_conversation(
                value=IssueFactValue.TRUE, evidence="1 comment to answer"
            )
        ],
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "round 1 errored (exit 2); waiting for recovery"


def test_an_errored_round_at_an_ineligible_issue_remains_recoverable(
    conversation_state,
):
    conversation_round(state=conversation_state, status=2)
    observe(state=conversation_state, observations=[])

    found = status(state=conversation_state)
    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)

    assert found.value is IssueConversationStatusValue.WAITING
    assert found.detail == "round 1 errored (exit 2); waiting for recovery"
    assert report.conversation_statuses == [found]


def test_a_round_that_needed_no_reply_says_so(conversation_state):
    conversation_round(state=conversation_state)
    write_final_output(
        directory=conversation_state.conversations / "GH8",
        number=1,
        text="NO_REPLY\n",
    )

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.IDLE
    assert found.detail == "round 1, no reply needed, ran 4m"


def test_an_unreadable_round_input_still_shows_the_round(conversation_state):
    conversation_round(state=conversation_state)
    conversation = read_issue_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.IDLE
    assert found.round_statuses[0].revision is None
    assert found.round_statuses[0].outcome_description == "successful"


def test_a_posted_answer_leaves_the_conversation_idle(conversation_state):
    conversation_round(state=conversation_state)

    found = status(state=conversation_state)

    assert found.value is IssueConversationStatusValue.IDLE
    assert found.detail == "round 1, answered, ran 4m"
    assert not found.is_over
    assert found.round_statuses[0].duration_description == "ran 4m"


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
