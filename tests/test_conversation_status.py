"""Read local status for issue conversations."""

import os
from datetime import timedelta

import pytest
from clocks import PINNED
from observations import observed_conversation
from records import (
    hold_daemon_lock_for_test,
    write_conversation,
    write_daemon_run,
    write_feed,
    write_final_output,
    write_round,
    write_tick,
)

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    ConversationRoundPurpose,
    StoppedAgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import request_agent_work_retry
from dreamcatcher.config import AgentHarness
from dreamcatcher.documents import read_json, write_json
from dreamcatcher.feed import FeedLine
from dreamcatcher.issue_conversations import (
    ConversationInput,
    InitialConversationIssue,
    read_conversation,
)
from dreamcatcher.scheduler.models import (
    ConversationObservation,
    IssueFactValue,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import read_conversation_status, read_status_report
from dreamcatcher.status.conversations import ConversationStatusValue

LOOKED_AT = PINNED + timedelta(hours=2)


@pytest.fixture
def conversation_state(tmp_path):
    """Return local state containing one issue conversation."""
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())
    write_conversation(state=state, issue=8)
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
    status: int | None = 0,
    failure: str | None = None,
    final_output: str = "The answer.",
) -> None:
    """Write the conversation's initial round with the requested process status."""
    ending = (
        None
        if status is None
        else _compose_agent_round_ending(
            at=PINNED + timedelta(minutes=4), status=status, failure=failure
        )
    )
    directory = state.conversations / "GH8"
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=ConversationRoundPurpose.DISCUSS,
            started=PINNED,
            pid=1,
            ending=ending,
        ),
    )
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    write_json(
        document=ConversationInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title="Issue 8",
                body="Explain it.",
            ),
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
    write_final_output(directory=directory, number=1, text=final_output)


def write_second_conversation_error(*, state: StateDirectory) -> None:
    """Write a recovery round that errors after the fixture's first round."""
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    first_input = read_json(
        model=ConversationInput,
        path=conversation.compose_round_paths(number=1).round_input,
    )
    write_round(
        directory=conversation.directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            purpose=ConversationRoundPurpose.DISCUSS,
            is_recovery=True,
            started=PINNED + timedelta(minutes=5),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=8),
                status=2,
                failure=None,
            ),
        ),
    )
    write_json(
        document=first_input.model_copy(update={"initial_issue": None}),
        path=conversation.compose_round_paths(number=2).round_input,
    )


def observe(
    *,
    state: StateDirectory,
    observations: list[ConversationObservation],
) -> None:
    """Write a tick that made these conversation observations."""
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, conversation_observations=observations),
    )


def status(*, state: StateDirectory):
    """Return the fixture conversation's status at the pinned time."""
    found = read_conversation_status(state=state, issue=8, clock=lambda: LOOKED_AT)
    assert found is not None
    return found


def test_a_missing_conversation_has_no_status(tmp_path):
    assert (
        read_conversation_status(state=StateDirectory(root=tmp_path), issue=8) is None
    )


def test_a_conversation_nobody_has_commented_on_is_idle(conversation_state):
    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.IDLE
    assert found.detail == "no comments yet"
    assert found.is_listed
    assert not found.is_over
    assert found.round_statuses == []
    assert found.harness_session_identifier == "conversation-session"
    assert found.hand_resume_command == [
        "claude",
        "--resume",
        "conversation-session",
    ]


def test_an_idle_codex_conversation_has_a_codex_hand_resume_command(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_conversation(state=state, issue=8, harness=AgentHarness.CODEX)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_observations=[observed_conversation()],
        ),
    )

    found = status(state=state)

    assert found.hand_resume_command == ["codex", "resume", "conversation-session"]


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

    assert found.value is ConversationStatusValue.WAITING
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

    assert found.value is ConversationStatusValue.UNKNOWN
    assert found.detail == "could not read comments for GH8: network unavailable"
    assert found.is_listed


def test_a_conversation_whose_routes_cannot_be_listed_is_unknown(
    conversation_state,
):
    failure = "could not list issue conversations: network unavailable"
    observe(
        state=conversation_state,
        observations=[
            observed_conversation(
                routing_conflict=IssueFactValue.UNKNOWN,
                routing_conflict_evidence=failure,
            )
        ],
    )

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.UNKNOWN
    assert found.detail == failure


def test_a_conversation_no_tick_has_observed_is_unknown(conversation_state):
    conversation_state.scheduler_record.unlink()

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.UNKNOWN
    assert found.detail == "no current scheduler observation"
    assert found.is_listed


def test_an_ineligible_conversation_is_idle_and_leaves_the_report(
    conversation_state,
):
    conversation_round(state=conversation_state)
    observe(state=conversation_state, observations=[])

    found = status(state=conversation_state)
    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)

    assert found.value is ConversationStatusValue.IDLE
    assert found.detail == "issue is not eligible for conversation"
    assert not found.is_listed
    assert found.is_over
    assert report.conversation_statuses == []


def test_an_unrecorded_round_input_shows_what_the_scheduler_reported(
    conversation_state,
):
    conversation = read_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    write_json(
        document=ConversationInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title="Issue 8",
                body="Explain it.",
            ),
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

    assert found.value is ConversationStatusValue.UNKNOWN
    assert found.detail == failure


def test_a_live_round_keeps_an_ineligible_conversation_on_the_report(
    conversation_state,
):
    hold_daemon_lock_for_test(path=conversation_state.lock)
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
    assert found.value is ConversationStatusValue.WORKING
    assert found.detail == ("round 1, discuss, running 2h 0m, last output 1h 59m ago")
    assert found.latest_output == "I am reading the scheduler."
    assert found.observed_at == PINNED
    assert not found.is_over
    assert found.round_statuses[0].outcome_description == "running"
    assert found.round_statuses[0].revision is not None
    assert found.round_statuses[0].revision.value == "abc123"
    assert found.harness_session_identifier == "conversation-session"
    assert found.hand_resume_command is None


def test_a_live_conversation_that_has_said_nothing_reports_that(
    conversation_state,
):
    hold_daemon_lock_for_test(path=conversation_state.lock)
    conversation_round(state=conversation_state, status=None)

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.WORKING
    assert found.detail == "round 1, discuss, running 2h 0m, has said nothing yet"
    assert found.latest_output is None


def test_an_unended_round_with_no_daemon_waits_to_be_recovered(conversation_state):
    conversation_round(state=conversation_state, status=None)

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.WAITING
    assert found.detail == "round 1 interrupted"
    assert found.round_statuses[0].outcome_description == "interrupted"


def test_an_errored_round_waits_to_be_recovered(conversation_state):
    conversation_round(state=conversation_state, status=2)

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.WAITING
    assert found.detail == "round 1 errored (exit 2)"
    assert not found.is_over


def test_two_current_errors_put_a_conversation_in_fault(conversation_state):
    conversation_round(state=conversation_state, status=2)
    write_second_conversation_error(state=conversation_state)
    write_feed(
        directory=conversation_state.conversations / "GH8",
        number=2,
        lines=[
            FeedLine(
                at=PINNED + timedelta(minutes=7),
                text="[failed] You hit your spend cap.",
            )
        ],
    )

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.FAULT
    assert found.detail == "round 2 errored (exit 2)"
    assert found.latest_output == "[failed] You hit your spend cap."
    assert found.is_over


@pytest.mark.parametrize(
    "observations",
    [
        [
            observed_conversation(
                routing_conflict=IssueFactValue.TRUE,
                routing_conflict_evidence=(
                    "carries more than one conversation label: discuss, scout"
                ),
            )
        ],
        [
            observed_conversation(
                value=IssueFactValue.UNKNOWN,
                evidence="could not read comments for GH8: network unavailable",
            )
        ],
    ],
    ids=["routing conflict", "unknown"],
)
def test_a_conversation_fault_takes_precedence_over_its_issue_eligibility(
    conversation_state, observations
):
    conversation_round(state=conversation_state, status=2)
    write_second_conversation_error(state=conversation_state)
    observe(state=conversation_state, observations=observations)

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.FAULT
    assert found.detail == "round 2 errored (exit 2)"
    assert found.faulted_round_number == 2


def test_a_conversation_fault_shows_before_any_tick_observes_it(conversation_state):
    conversation_round(state=conversation_state, status=2)
    write_second_conversation_error(state=conversation_state)
    conversation_state.scheduler_record.unlink()

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.FAULT
    assert found.faulted_round_number == 2


def test_a_faulted_conversation_at_an_ineligible_issue_leaves_the_report(
    conversation_state,
):
    conversation_round(state=conversation_state, status=2)
    write_second_conversation_error(state=conversation_state)
    observe(state=conversation_state, observations=[])

    found = status(state=conversation_state)
    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)

    assert found.value is ConversationStatusValue.FAULT
    assert found.faulted_round_number == 2
    assert report.conversation_statuses == []


def test_a_retry_clears_a_conversation_fault(conversation_state):
    conversation_round(state=conversation_state, status=2)
    write_second_conversation_error(state=conversation_state)
    observe(state=conversation_state, observations=[])
    conversation = read_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    request_agent_work_retry(work=conversation, at=PINNED + timedelta(minutes=9))

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.IDLE
    assert found.detail == "issue is not eligible for conversation"


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

    assert found.value is ConversationStatusValue.WAITING
    assert found.detail == f"round 1 errored (exit 0): {failure}"
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

    assert found.value is ConversationStatusValue.WAITING
    assert found.detail == "round 1 errored (exit 2)"


def test_a_round_ending_after_the_latest_tick_waits_for_the_next_update(
    conversation_state,
):
    conversation_round(state=conversation_state)
    write_tick(
        state=conversation_state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_observations=[observed_conversation()],
            launched_agent_work_identifiers=["conversation-GH8"],
        ),
    )

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.WAITING
    assert found.detail == "round 1 ended, awaiting next update"


def test_an_errored_round_at_an_ineligible_issue_leaves_the_report(
    conversation_state,
):
    conversation_round(state=conversation_state, status=2)
    observe(state=conversation_state, observations=[])

    found = status(state=conversation_state)
    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)

    assert found.value is ConversationStatusValue.IDLE
    assert found.detail == "issue is not eligible for conversation"
    assert report.conversation_statuses == []


def test_a_round_that_needed_no_reply_says_so(conversation_state):
    conversation_round(state=conversation_state, final_output="NO_REPLY\n")

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.IDLE
    assert found.detail == "round 1, no reply needed, ran 4m"


def test_an_unreadable_round_input_still_shows_the_round(conversation_state):
    conversation_round(state=conversation_state)
    conversation = read_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.IDLE
    assert found.round_statuses[0].revision is None
    assert found.round_statuses[0].outcome_description == "successful"


def test_a_posted_answer_leaves_the_conversation_idle(conversation_state):
    conversation_round(state=conversation_state)

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.IDLE
    assert found.detail == "round 1, answered, ran 4m"
    assert not found.is_over
    assert found.round_statuses[0].duration_description == "ran 4m"


def test_a_stopped_conversation_waits_for_new_comments(conversation_state):
    directory = conversation_state.conversations / "GH8"
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=ConversationRoundPurpose.DISCUSS,
            started=PINNED,
            pid=1,
            ending=StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=4)),
        ),
    )

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.IDLE
    assert found.detail == "round 1, stopped, ran 4m"
    assert found.round_statuses[0].outcome_description == "stopped"


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
    found = read_conversation_status(state=state, issue=9)

    assert found is not None
    assert report.conversation_statuses == [found]
    assert found.conversation is None
    assert found.issue == 9
    assert found.title == "Issue 9"
    assert found.value is ConversationStatusValue.WAITING
    assert found.detail == "1 comment to answer"
    assert found.round_statuses == []
    assert found.harness_session_identifier is None
    assert found.hand_resume_command is None


def test_an_eligible_issue_nobody_has_commented_on_is_idle(tmp_path):
    state = StateDirectory(root=tmp_path)
    observe(state=state, observations=[observed_conversation(issue=9)])

    found = read_conversation_status(state=state, issue=9)

    assert found is not None
    assert found.value is ConversationStatusValue.IDLE
    assert found.detail == "no comments yet"


def test_an_unsaved_conversation_with_two_routes_reports_its_conflict(tmp_path):
    state = StateDirectory(root=tmp_path)
    conflict = "carries more than one conversation label: discuss, scout"
    observe(
        state=state,
        observations=[
            observed_conversation(
                issue=9,
                routing_conflict=IssueFactValue.TRUE,
                routing_conflict_evidence=conflict,
            )
        ],
    )

    found = read_conversation_status(state=state, issue=9)

    assert found is not None
    assert found.value is ConversationStatusValue.ROUTING_CONFLICT
    assert found.detail == conflict
    assert found.is_over


def test_a_saved_conversation_with_two_routes_reports_its_conflict(
    conversation_state,
):
    conflict = "carries more than one conversation label: discuss, scout"
    observe(
        state=conversation_state,
        observations=[
            observed_conversation(
                routing_conflict=IssueFactValue.TRUE,
                routing_conflict_evidence=conflict,
            )
        ],
    )

    found = status(state=conversation_state)

    assert found.value is ConversationStatusValue.ROUTING_CONFLICT
    assert found.detail == conflict


def test_an_unobserved_issue_with_no_record_has_no_conversation(conversation_state):
    assert read_conversation_status(state=conversation_state, issue=9) is None
