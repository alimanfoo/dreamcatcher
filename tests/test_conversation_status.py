"""Read local status for issue conversations."""

import os
from datetime import timedelta

import pytest
from clocks import PINNED
from records import (
    SCOUT_ROUTES,
    compose_conversation_identifier,
    find_conversation_directory,
    hold_daemon_lock_for_test,
    read_conversation,
    write_conversation,
    write_daemon_run,
    write_ending,
    write_feed,
    write_final_output,
    write_round,
    write_tick,
)
from rows import request_row

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    StoppedAgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import AgentWorkEndReason, request_agent_work_retry
from dreamcatcher.config import AgentHarness
from dreamcatcher.documents import read_json, write_json
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
    RequestFinding,
    RequestRow,
    SchedulerRecord,
    StartedRound,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentWorkStatusSection,
    AgentWorkStatusValue,
    RequestReason,
    read_conversation_status,
    read_dreamcatcher_daemon_status,
    read_status_report,
)
from dreamcatcher.status.requests import RequestStatusValue
from dreamcatcher.status.rounds import _compose_round_revision

LOOKED_AT = PINNED + timedelta(hours=2)

# What the tick records for a conversation whose label came off its issue.
PAUSED = PausedFinding(cause=PauseCause.LABEL_REMOVED)


@pytest.fixture
def conversation_state(tmp_path):
    """Return local state containing one issue conversation."""
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())
    write_conversation(state=state, issue=8)
    observe(state=state, finding=IssueCommentsFinding(new_comments=0))
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
    directory = find_conversation_directory(state=state, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=ending,
        ),
    )
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    write_json(
        document=ConversationRoundInput(
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
    """Write a second round that errors after the fixture's first round."""
    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    first_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=1).round_input,
    )
    write_round(
        directory=conversation.directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
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
    finding: RequestFinding,
    started_round: StartedRound | None = None,
    at=LOOKED_AT,
) -> None:
    """Write a tick that found this for the fixture's conversation."""
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=at,
            rows=[
                request_row(
                    issue=8,
                    kind=AgentWorkKind.CONVERSATION,
                    agent_work_identifier=compose_conversation_identifier(issue=8),
                    finding=finding,
                    started_round=started_round,
                )
            ],
        ),
    )


def status(*, state: StateDirectory):
    """Return the fixture conversation's status at the pinned time."""
    found = read_conversation_status(
        state=state,
        issue=8,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )
    assert found is not None
    return found


def test_a_missing_conversation_has_no_status(tmp_path):
    state = StateDirectory(root=tmp_path)

    assert (
        read_conversation_status(
            state=state, issue=8, daemon=read_dreamcatcher_daemon_status(state=state)
        )
        is None
    )


def test_a_conversation_that_has_run_no_round_waits_for_its_first(
    conversation_state,
):
    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.WAITING
    assert found.detail == "no round has run yet"
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
    observe(state=state, finding=IssueCommentsFinding(new_comments=0))

    found = status(state=state)

    assert found.hand_resume_command == [
        "codex",
        "resume",
        "--model",
        "opus[1m]",
        "-c",
        'model_reasoning_effort="xhigh"',
        "conversation-session",
    ]


def test_a_conversation_with_comments_to_answer_is_waiting(conversation_state):
    conversation_round(state=conversation_state)
    observe(state=conversation_state, finding=IssueCommentsFinding(new_comments=2))

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.WAITING
    assert found.detail == "2 comments to answer"


def test_a_conversation_whose_comments_cannot_be_read_is_unknown(
    conversation_state,
):
    observe(
        state=conversation_state,
        finding=ReadFailureFinding(
            reason="could not read comments for GH8: network unavailable"
        ),
    )

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.UNKNOWN
    assert found.detail == (
        "cannot tell: could not read comments for GH8: network unavailable"
    )


def test_a_conversation_no_tick_has_observed_is_unknown(conversation_state):
    conversation_round(state=conversation_state)
    conversation_state.scheduler_record.unlink()

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.UNKNOWN
    assert found.detail == "not seen by the latest update"


@pytest.mark.parametrize("cause", list(PauseCause))
def test_a_paused_conversation_is_idle_with_its_cause_and_stays_on_the_report(
    conversation_state, cause
):
    conversation_round(state=conversation_state)
    observe(state=conversation_state, finding=PausedFinding(cause=cause))

    found = status(state=conversation_state)
    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == f"paused, {cause}"
    assert report.list_active_work_statuses(kind=AgentWorkKind.CONVERSATION) == [found]


def test_an_unrecorded_round_input_shows_what_the_scheduler_reported(
    conversation_state,
):
    conversation = read_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    write_json(
        document=ConversationRoundInput(
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
        "could not inspect saved conversation GH8: "
        "Conversation GH8-20260819-184158-conversation has input for round 1 "
        "without a round record."
    )
    observe(state=conversation_state, finding=ReadFailureFinding(reason=failure))

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.UNKNOWN
    assert found.detail == f"cannot tell: {failure}"


def test_a_live_round_shows_a_paused_conversation_as_working(
    conversation_state,
):
    hold_daemon_lock_for_test(path=conversation_state.lock)
    conversation_round(state=conversation_state, status=None)
    write_feed(
        directory=find_conversation_directory(state=conversation_state, issue=8),
        number=1,
        lines=[
            FeedLine(
                at=PINNED + timedelta(minutes=1),
                text="I am reading the scheduler.",
            )
        ],
    )
    observe(state=conversation_state, finding=PAUSED)

    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)
    found = report.work_statuses[0]

    assert report.running_agents == 1
    assert report.describe_section(
        kind=AgentWorkKind.CONVERSATION
    ) == AgentWorkStatusSection(heading="conversations", empty_message=None)
    assert found.value is AgentWorkStatusValue.WORKING
    assert found.detail == ("round 1, 1 comment, running 2h 0m, last output 1h 59m ago")
    assert found.latest_output == "I am reading the scheduler."
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

    assert found.value is AgentWorkStatusValue.WORKING
    assert found.detail == "round 1, 1 comment, running 2h 0m, has said nothing yet"
    assert found.latest_output is None


def test_an_unended_round_with_no_daemon_waits_to_be_given_its_input_again(
    conversation_state,
):
    conversation_round(state=conversation_state, status=None)

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.WAITING
    assert found.detail == "round 1 interrupted"
    assert found.round_statuses[0].outcome_description == "interrupted"


def test_an_errored_round_waits_to_be_given_its_input_again(conversation_state):
    conversation_round(state=conversation_state, status=2)

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.WAITING
    assert found.detail == "round 1 errored (exit 2)"


def test_two_current_errors_put_a_conversation_in_fault(conversation_state):
    conversation_round(state=conversation_state, status=2)
    write_second_conversation_error(state=conversation_state)
    write_feed(
        directory=find_conversation_directory(state=conversation_state, issue=8),
        number=2,
        lines=[
            FeedLine(
                at=PINNED + timedelta(minutes=7),
                text="[failed] You hit your spend cap.",
            )
        ],
    )

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.FAULT
    assert found.detail == "round 2 errored (exit 2)"
    assert found.latest_output == "[failed] You hit your spend cap."


@pytest.mark.parametrize(
    "finding",
    [
        ConflictingLabelsFinding(labels=["discuss", "scout"]),
        ReadFailureFinding(
            reason="could not read comments for GH8: network unavailable"
        ),
    ],
    ids=["paused", "unknown"],
)
def test_a_conversation_fault_takes_precedence_over_what_the_tick_found(
    conversation_state, finding
):
    conversation_round(state=conversation_state, status=2)
    write_second_conversation_error(state=conversation_state)
    observe(state=conversation_state, finding=finding)

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.FAULT
    assert found.detail == "round 2 errored (exit 2)"
    assert found.faulted_round_number == 2


def test_a_conversation_fault_shows_before_any_tick_observes_it(conversation_state):
    conversation_round(state=conversation_state, status=2)
    write_second_conversation_error(state=conversation_state)
    conversation_state.scheduler_record.unlink()

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.FAULT
    assert found.faulted_round_number == 2


def test_a_retry_clears_a_conversation_fault(conversation_state):
    conversation_round(state=conversation_state, status=2)
    write_second_conversation_error(state=conversation_state)
    observe(state=conversation_state, finding=PAUSED)
    conversation = read_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    request_agent_work_retry(work=conversation, at=PINNED + timedelta(minutes=9))

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == "paused, label removed"


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

    assert found.value is AgentWorkStatusValue.WAITING
    assert found.detail == f"round 1 errored (exit 0): {failure}"
    assert found.round_statuses[0].outcome_description == "errored"


def test_an_unfinished_round_comes_before_comments_to_answer(conversation_state):
    conversation_round(state=conversation_state, status=2)
    observe(state=conversation_state, finding=IssueCommentsFinding(new_comments=1))

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.WAITING
    assert found.detail == "round 1 errored (exit 2)"


@pytest.mark.parametrize("did_tick_start_round", [False, True])
def test_a_round_ending_after_the_latest_tick_is_idle_until_the_next_update(
    conversation_state, did_tick_start_round
):
    conversation_round(state=conversation_state)
    observe(
        state=conversation_state,
        finding=IssueCommentsFinding(new_comments=int(did_tick_start_round)),
        started_round=(StartedRound(number=1) if did_tick_start_round else None),
        at=PINNED,
    )

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == "round 1 ended, awaiting next update"

    observe(
        state=conversation_state,
        finding=IssueCommentsFinding(new_comments=0),
    )

    refreshed = status(state=conversation_state)

    assert refreshed.value is AgentWorkStatusValue.IDLE
    assert refreshed.detail == "round 1, answered, ran 4m"


def test_a_stopped_round_ending_after_the_latest_tick_is_idle_until_the_next_update(
    conversation_state,
):
    directory = find_conversation_directory(state=conversation_state, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=4)),
        ),
    )
    observe(
        state=conversation_state,
        finding=IssueCommentsFinding(new_comments=0),
        at=PINNED,
    )

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == "round 1 ended, awaiting next update"


def test_new_comments_found_while_a_round_ran_wait_after_it_ends(
    conversation_state,
):
    conversation_round(state=conversation_state)
    observe(
        state=conversation_state,
        finding=IssueCommentsFinding(new_comments=1),
        at=PINNED,
    )

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.WAITING
    assert found.detail == "1 comment to answer"


def test_a_conversation_with_two_conversation_labels_is_paused_saying_so(
    conversation_state,
):
    conversation_round(state=conversation_state)
    observe(
        state=conversation_state,
        finding=ConflictingLabelsFinding(labels=["discuss", "scout"]),
    )

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == "paused, multiple conversation labels: discuss, scout"


def test_an_errored_round_of_a_paused_conversation_does_not_wait(
    conversation_state,
):
    conversation_round(state=conversation_state, status=2)
    observe(state=conversation_state, finding=PAUSED)

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == "paused, label removed"


def test_a_round_that_needed_no_reply_says_so(conversation_state):
    conversation_round(state=conversation_state, final_output="NO_REPLY\n")

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == "round 1, no reply needed, ran 4m"


def test_an_unreadable_round_input_still_shows_the_round(conversation_state):
    conversation_round(state=conversation_state)
    conversation = read_conversation(state=conversation_state, issue=8)
    assert conversation is not None
    conversation.compose_round_paths(number=1).round_input.write_bytes(b"not json")

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.round_statuses[0].revision is None
    assert found.round_statuses[0].outcome_description == "successful"


def test_a_posted_answer_leaves_the_conversation_idle(conversation_state):
    conversation_round(state=conversation_state)

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == "round 1, answered, ran 4m"
    assert found.round_statuses[0].duration_description == "ran 4m"


def test_a_stopped_conversation_waits_for_new_comments(conversation_state):
    directory = find_conversation_directory(state=conversation_state, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=4)),
        ),
    )

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.IDLE
    assert found.detail == "round 1, stopped, ran 4m"
    assert found.round_statuses[0].outcome_description == "stopped"


def conversation_requests(*, state: StateDirectory, rows: list[RequestRow]):
    """Return the conversation requests that a tick writing these rows reports."""
    write_tick(state=state, tick=SchedulerRecord(at=PINNED, rows=rows))
    report = read_status_report(state=state, clock=lambda: LOOKED_AT)
    return report.list_request_statuses(kind=AgentWorkKind.CONVERSATION)


def test_an_issue_with_a_comment_waiting_is_a_request_until_its_conversation_starts(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)

    [request] = conversation_requests(
        state=state,
        rows=[
            request_row(
                issue=9,
                kind=AgentWorkKind.CONVERSATION,
                finding=IssueCommentsFinding(new_comments=1),
            )
        ],
    )

    assert request.value is RequestStatusValue.AVAILABLE
    assert request.reasons == (RequestReason(words="1 comment to answer"),)
    assert (
        read_conversation_status(
            state=state, issue=9, daemon=read_dreamcatcher_daemon_status(state=state)
        )
        is None
    )


def test_an_issue_nobody_has_commented_on_waits_for_a_comment(tmp_path):
    [request] = conversation_requests(
        state=StateDirectory(root=tmp_path),
        rows=[
            request_row(
                issue=9,
                kind=AgentWorkKind.CONVERSATION,
                finding=IssueCommentsFinding(new_comments=0),
            )
        ],
    )

    assert request.value is RequestStatusValue.IDLE
    assert request.reasons == (RequestReason(words="waiting for a comment"),)


def test_an_unobserved_issue_with_no_record_has_no_conversation(conversation_state):
    assert (
        read_conversation_status(
            state=conversation_state,
            issue=9,
            daemon=read_dreamcatcher_daemon_status(state=conversation_state),
        )
        is None
    )


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (None, "abc123", "code revision abc123"),
        ("abc123", "abc123", "code revision abc123 (unchanged)"),
        ("abc123", "def456", "code revision abc123 -> def456"),
        (
            "0123456" + "0" * 33,
            "0123456" + "f" * 33,
            f"code revision {'0123456' + '0' * 33} -> {'0123456' + 'f' * 33}",
        ),
    ],
)
def test_a_round_revision_description_names_its_transition(previous, current, expected):
    found = _compose_round_revision(previous_revision=previous, revision=current)

    assert found.description == expected


def test_a_round_revision_keeps_its_whole_value():
    found = _compose_round_revision(previous_revision=None, revision="0123456789abcdef")

    assert found.value == "0123456789abcdef"
    assert found.description == "code revision 0123456789abcdef"


def end_conversation(*, state: StateDirectory, minutes: int = 10) -> None:
    """Record that the fixture conversation ended that many minutes in."""
    write_ending(
        directory=find_conversation_directory(state=state, issue=8),
        reason=AgentWorkEndReason.ISSUE_CLOSED,
        at=PINNED + timedelta(minutes=minutes),
    )


def test_an_ended_conversation_reads_as_ended_with_its_reason(conversation_state):
    conversation_round(state=conversation_state)
    end_conversation(state=conversation_state)
    observe(state=conversation_state, finding=PAUSED)

    found = status(state=conversation_state)

    assert found.value is AgentWorkStatusValue.ENDED
    assert found.detail == "issue closed"
    assert found.has_ended
    assert not found.is_active


def test_a_running_round_keeps_an_ended_conversation_working(conversation_state):
    hold_daemon_lock_for_test(path=conversation_state.lock)
    conversation_round(state=conversation_state, status=None)
    end_conversation(state=conversation_state)

    assert status(state=conversation_state).value is AgentWorkStatusValue.WORKING


def test_the_report_lists_ended_conversations_apart_newest_first(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid(), routes=SCOUT_ROUTES)
    for issue, minutes in ((8, 10), (9, 20)):
        write_ending(
            directory=write_conversation(state=state, issue=issue),
            reason=AgentWorkEndReason.ISSUE_CLOSED,
            at=PINNED + timedelta(minutes=minutes),
        )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(
                    issue=10,
                    kind=AgentWorkKind.CONVERSATION,
                    finding=IssueCommentsFinding(new_comments=0),
                )
            ],
        ),
    )

    report = read_status_report(state=state, clock=lambda: LOOKED_AT)

    assert report.list_active_work_statuses(kind=AgentWorkKind.CONVERSATION) == []
    assert [
        request.row.issue
        for request in report.list_request_statuses(kind=AgentWorkKind.CONVERSATION)
    ] == [10]
    assert [
        status.work.record.issue
        for status in report.list_ended_work_statuses(kind=AgentWorkKind.CONVERSATION)
    ] == [9, 8]
    assert report.describe_section(
        kind=AgentWorkKind.CONVERSATION
    ) == AgentWorkStatusSection(heading="conversations", empty_message=None)


def test_a_section_of_ended_conversations_alone_gives_its_guidance(
    conversation_state,
):
    write_daemon_run(state=conversation_state, pid=os.getpid(), routes=SCOUT_ROUTES)
    end_conversation(state=conversation_state)
    observe(state=conversation_state, finding=PAUSED)

    report = read_status_report(state=conversation_state, clock=lambda: LOOKED_AT)

    assert report.list_active_work_statuses(kind=AgentWorkKind.CONVERSATION) == []
    assert report.describe_section(
        kind=AgentWorkKind.CONVERSATION
    ) == AgentWorkStatusSection(
        heading="conversations",
        empty_message=(
            "Assign an issue to yourself, label it with dream:scout and post a "
            "comment to start a conversation."
        ),
    )


def test_the_status_at_an_issue_whose_conversation_ended_is_ended(
    conversation_state,
):
    end_conversation(state=conversation_state)

    found = status(state=conversation_state)

    assert found.has_ended
    assert found.value is AgentWorkStatusValue.ENDED
