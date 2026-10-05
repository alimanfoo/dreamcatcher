import os
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import REPOSITORY, configure
from observations import observed_issue
from records import (
    hold_daemon_lock_for_test,
    write_assignment,
    write_daemon_run,
    write_feed,
    write_round,
    write_tick,
)

from dreamcatcher.agent_assignments import (
    Assignment,
    cancel_assignment,
    read_assignments,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    AssignmentRoundPurpose,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS
from dreamcatcher.documents import write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.scheduler.models import (
    AgentWorkObservation,
    GlobalCooldown,
    ObservedFact,
    SchedulerRecord,
    Truth,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    DreamcatcherDaemonStatus,
    read_assignment_status,
    read_assignment_statuses_for_issue,
    read_dreamcatcher_daemon_status,
    read_status_report,
)
from dreamcatcher.status.assignments import AssignmentStatusValue

ASSIGNMENT_ID = "GH13-20260819-184158"
LOOKED_AT = PINNED + timedelta(hours=2)


@pytest.fixture
def state(tmp_path):
    """A configured state directory holding one assignment."""
    configure(root=tmp_path)
    directory = StateDirectory(root=tmp_path)
    write_daemon_run(state=directory, pid=os.getpid(), max_agents=3)
    write_assignment(state=directory, identifier=ASSIGNMENT_ID, issue=13)
    return directory


@pytest.fixture
def running(state):
    """That state directory held by a daemon with this process identifier."""
    hold_daemon_lock_for_test(path=state.lock)
    return state


def ran(
    *,
    state: StateDirectory,
    number: int,
    purpose: AssignmentRoundPurpose = AssignmentRoundPurpose.IMPLEMENT,
    status: int | None = 0,
    ended_at=PINNED,
) -> None:
    """Write one round for the fixture's assignment."""
    started = PINNED + timedelta(minutes=number)
    ending = (
        None
        if status is None
        else _compose_agent_round_ending(at=ended_at, status=status)
    )
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=number,
        record=AgentRoundRecord(
            number=number,
            purpose=purpose,
            started=started,
            pid=1,
            ending=ending,
        ),
    )


def said(*, state: StateDirectory, number: int, texts: Sequence[str]) -> None:
    """Write feed lines one minute after the numbered round began."""
    at = PINNED + timedelta(minutes=number + 1)
    write_feed(
        directory=state.assignments / ASSIGNMENT_ID,
        number=number,
        lines=[FeedLine(at=at, text=text) for text in texts],
    )


def report(*, state: StateDirectory):
    """Read the fixture's status report at the pinned time."""
    return read_status_report(state=state, clock=lambda: LOOKED_AT)


def only_assignment(*, state: StateDirectory):
    """Return the only agent-assignment status in the fixture."""
    assignments = report(state=state).assignment_statuses
    assert len(assignments) == 1
    return assignments[0]


def idle_observation() -> AgentWorkObservation:
    """Return the scheduler's explicit observation that no round is required."""
    return AgentWorkObservation(
        identifier=ASSIGNMENT_ID,
        issue=13,
        requires_round=ObservedFact(
            value=Truth.FALSE,
            evidence="no round required",
        ),
    )


def test_an_empty_instance_reports_unknown_capacity_and_no_work(tmp_path):

    found = read_status_report(
        state=StateDirectory(root=tmp_path),
        clock=lambda: LOOKED_AT,
    )

    assert found.at == LOOKED_AT
    assert found.repository is None
    assert found.daemon.pid is None
    assert found.daemon.agent_harness is None
    assert found.daemon.dreamcatcher_version is None
    assert found.latest_scheduler_tick is None
    assert found.daemon.interval_seconds is None
    assert found.scheduler_failure_summary is None
    assert found.daemon.max_agents is None
    assert found.running_agents == 0
    assert found.active_global_cooldown is None
    assert found.issue_observations == []
    assert found.assignment_statuses == []


def test_the_instance_record_names_the_repository(state):
    write_text(text=f"{REPOSITORY}\n", path=state.repository)

    assert report(state=state).repository == REPOSITORY


def test_the_instance_records_name_the_harness_and_version(state):
    write_daemon_run(
        state=state,
        pid=os.getpid(),
        harness=AgentHarness.CODEX,
        version="3.0.0.beta1",
        max_agents=3,
    )

    found = report(state=state)

    assert found.daemon.agent_harness is AgentHarness.CODEX
    assert found.daemon.dreamcatcher_version == "3.0.0.beta1"
    assert not found.daemon.is_running
    assert found.daemon.pid is None


def test_a_live_daemon_that_has_not_named_its_run_has_no_pid(tmp_path):
    state = StateDirectory(root=tmp_path)
    hold_daemon_lock_for_test(path=state.lock)

    found = report(state=state)

    assert found.daemon.is_running
    assert found.daemon.pid is None


def test_a_live_round_reports_work_and_its_latest_output(running):
    ran(state=running, number=1, status=None)
    said(state=running, number=1, texts=["first", "[Bash] pytest"])

    found = report(state=running)
    status = found.assignment_statuses[0]

    assert found.daemon.pid == os.getpid()
    assert found.running_agents == 1
    assert status.value is AssignmentStatusValue.WORKING
    assert status.detail == "round 1, implement, running 1h 59m, last output 1h 58m ago"
    assert status.latest_output == "[Bash] pytest"
    assert status.hand_resume_command is None


@pytest.mark.parametrize(
    ("ending", "outcome_description", "duration"),
    [
        (
            _compose_agent_round_ending(at=PINNED + timedelta(minutes=4), status=0),
            "successful",
            "ran 4m",
        ),
        (
            _compose_agent_round_ending(at=PINNED + timedelta(minutes=4), status=2),
            "errored (exit 2)",
            "ran 4m",
        ),
        (InterruptedAgentRoundEnding(), "interrupted", ""),
    ],
)
def test_a_terminal_round_status_describes_its_outcome_and_duration(
    state, ending, outcome_description, duration
):
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
            started=PINNED,
            pid=1,
            ending=ending,
        ),
    )

    round_status = only_assignment(state=state).round_statuses[0]

    assert round_status.outcome_description == outcome_description
    assert round_status.duration_description == duration


@pytest.mark.parametrize(
    ("is_running", "outcome_description"),
    [(True, "running"), (False, "interrupted")],
)
def test_an_unended_round_status_follows_the_daemon(
    state, is_running, outcome_description
):
    if is_running:
        hold_daemon_lock_for_test(path=state.lock)
    ran(state=state, number=1, status=None)

    round_status = only_assignment(state=state).round_statuses[0]

    assert round_status.outcome_description == outcome_description
    assert round_status.duration_description == ""


def test_status_recovers_the_harness_session_and_builds_its_resume_command(tmp_path):
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    directory = write_assignment(
        state=state,
        identifier=ASSIGNMENT_ID,
        issue=13,
        harness_session_identifier=None,
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
            started=PINNED,
            pid=1,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=4), status=0
            ),
        ),
    )
    write_text(
        text=(
            '{"type":"system","subtype":"init","model":"claude-opus-5",'
            '"session_id":"abc-123"}\n'
        ),
        path=directory / "rounds" / "1" / "raw.jsonl",
    )

    status = only_assignment(state=state)

    assert status.harness_session_identifier == "abc-123"
    assert status.hand_resume_command == ["claude", "--resume", "abc-123"]


def test_status_reads_harness_resume_details_only_when_requested(state, monkeypatch):
    calls = []

    def recover_harness_session_identifier(assignment, /):
        calls.append(assignment)
        return "abc-123"

    monkeypatch.setattr(
        Assignment,
        "find_harness_session_identifier",
        recover_harness_session_identifier,
    )

    status = only_assignment(state=state)

    assert calls == []
    assert status.harness_session_identifier == "abc-123"
    assert status.hand_resume_command == ["claude", "--resume", "abc-123"]
    assert len(calls) == 1


def test_status_with_no_harness_session_has_no_resume_command(tmp_path):
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    directory = write_assignment(
        state=state,
        identifier=ASSIGNMENT_ID,
        issue=13,
        harness_session_identifier=None,
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
            started=PINNED,
            pid=1,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=4), status=0
            ),
        ),
    )

    status = only_assignment(state=state)

    assert status.harness_session_identifier is None
    assert status.hand_resume_command is None


def test_a_live_round_that_has_said_nothing_reports_that(running):
    ran(state=running, number=1, status=None)

    status = only_assignment(state=running)

    assert status.value is AssignmentStatusValue.WORKING
    assert status.detail == "round 1, implement, running 1h 59m, has said nothing yet"
    assert status.latest_output is None


@pytest.mark.parametrize(
    ("round_status", "detail"),
    [
        (None, "round 1 interrupted"),
        (2, "round 1 errored (exit 2)"),
    ],
)
def test_an_unfinished_round_waits_for_recovery(state, round_status, detail):
    ran(state=state, number=1, status=round_status)

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.WAITING
    assert status.detail == detail


def test_a_successful_wrap_up_is_complete(state):
    ran(state=state, number=1)
    ran(state=state, number=2, purpose=AssignmentRoundPurpose.WRAP_UP)

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.COMPLETE
    assert status.detail == "2 rounds"
    assert status.is_over


def cancel(*, state: StateDirectory) -> None:
    """Cancel the fixture's assignment."""
    cancel_assignment(assignment=read_assignments(state=state)[0], at=PINNED)


def test_a_cancelled_assignment_has_ended(state):
    ran(state=state, number=1)
    cancel(state=state)

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.CANCELLED
    assert status.detail == "1 round"
    assert status.has_ended
    assert status.is_over


def test_a_round_still_running_after_a_cancel_is_working(running):
    ran(state=running, number=1, status=None)
    cancel(state=running)

    status = only_assignment(state=running)

    assert status.value is AssignmentStatusValue.WORKING
    assert not status.has_ended


def test_a_cancelled_assignment_is_cancelled_rather_than_in_fault(state):
    ran(state=state, number=1, status=1)
    ran(state=state, number=2, status=2)
    cancel(state=state)

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.CANCELLED


def test_a_cancelled_assignment_stops_reporting_its_pull_request_state(tmp_path):
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    write_assignment(
        state=state,
        identifier=ASSIGNMENT_ID,
        issue=13,
        title="The issue title",
    )
    assert only_assignment(state=state).pull_request_state == "draft"

    cancel(state=state)

    assert only_assignment(state=state).pull_request_state is None


def test_an_assignment_that_has_run_no_round_waits_for_its_first(state):
    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.WAITING
    assert status.detail == "next round, implement"
    assert not status.is_over


def test_a_required_round_reports_the_scheduler_reason(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[
                AgentWorkObservation(
                    identifier=ASSIGNMENT_ID,
                    issue=13,
                    requires_round=ObservedFact(
                        value=Truth.TRUE,
                        evidence="1 new post to answer",
                    ),
                )
            ],
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.WAITING
    assert status.detail == "next round, implement"


def test_an_unknown_assignment_observation_reports_unknown(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[
                AgentWorkObservation(
                    identifier=ASSIGNMENT_ID,
                    issue=13,
                    requires_round=ObservedFact(
                        value=Truth.UNKNOWN,
                        evidence="cannot read its pull request: unavailable",
                    ),
                )
            ],
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.UNKNOWN
    assert status.detail == "cannot read its pull request: unavailable"


def test_an_assignment_with_no_scheduler_observation_is_unknown(state):
    ran(state=state, number=1)

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.UNKNOWN
    assert status.detail == "no current scheduler observation"


@pytest.mark.parametrize("is_launched_observed", [False, True])
def test_a_round_ending_after_the_latest_tick_waits_for_the_next_update(
    state, is_launched_observed
):
    ran(state=state, number=1, ended_at=LOOKED_AT + timedelta(minutes=1))
    launched_observation = AgentWorkObservation(
        identifier=ASSIGNMENT_ID,
        issue=13,
        requires_round=ObservedFact(
            value=Truth.FALSE,
            evidence="round 1 started",
        ),
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=(
                [launched_observation] if is_launched_observed else []
            ),
            launched_agent_work_identifiers=(
                [ASSIGNMENT_ID] if is_launched_observed else []
            ),
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.WAITING
    assert status.detail == "round 1 ended, awaiting next update"


@pytest.mark.parametrize("ended_at", [LOOKED_AT - timedelta(minutes=1), LOOKED_AT])
def test_a_tick_at_or_after_the_latest_ending_needs_an_observation(state, ended_at):
    ran(state=state, number=1, ended_at=ended_at)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            launched_agent_work_identifiers=[ASSIGNMENT_ID],
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.UNKNOWN
    assert status.detail == "no current scheduler observation"


def test_an_observation_is_current_when_a_round_ends_after_the_tick_begins(state):
    ran(state=state, number=1, ended_at=LOOKED_AT + timedelta(minutes=1))
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[idle_observation()],
        ),
    )

    assert (
        only_assignment(state=state).value is AssignmentStatusValue.NEEDS_USER_FEEDBACK
    )


def test_a_current_tick_with_no_required_round_needs_user_feedback(state):
    ran(state=state, number=1)
    said(state=state, number=1, texts=["Ready for review"])
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[idle_observation()],
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.NEEDS_USER_FEEDBACK
    assert status.detail == "last output 1h 58m ago"


def test_an_assignment_needing_feedback_with_no_feed_has_no_output(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[idle_observation()],
        ),
    )

    assert only_assignment(state=state).detail == "no output"


def test_a_stopped_assignment_needs_user_feedback(state):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
            started=started,
            pid=1,
            ending=StoppedAgentRoundEnding(at=started + timedelta(minutes=4)),
        ),
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[idle_observation()],
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.NEEDS_USER_FEEDBACK
    assert status.round_statuses[0].duration_description == "ran 4m"
    assert status.round_statuses[0].outcome_description == "stopped"


def test_two_current_errors_put_an_assignment_in_fault(state):
    ran(state=state, number=1, status=1)
    ran(state=state, number=2, status=2)
    said(state=state, number=2, texts=["[failed] You hit your spend cap."])

    status = only_assignment(state=state)

    assert status.value is AssignmentStatusValue.FAULT
    assert status.detail == "round 2 errored (exit 2)"
    assert status.latest_output == "[failed] You hit your spend cap."
    assert status.is_over


def test_a_fault_with_no_output_names_the_latest_round_ending(state):
    ran(state=state, number=1, status=1)
    ran(state=state, number=2, status=2)

    status = only_assignment(state=state)

    assert status.detail == "round 2 errored (exit 2)"
    assert status.latest_output is None


def test_an_elapsed_cooldown_clears_the_fault_and_the_cooldown(state):
    ran(state=state, number=1, status=1)
    ran(state=state, number=2, status=2)
    ended = PINNED + timedelta(minutes=15)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            cooldown=GlobalCooldown(started=PINNED, ends=ended),
        ),
    )

    found = report(state=state)

    assert found.assignment_statuses[0].value is AssignmentStatusValue.WAITING
    assert found.active_global_cooldown is None


def test_an_active_cooldown_and_scheduler_failures_are_instance_facts(running):
    cooldown = GlobalCooldown(started=PINNED, ends=LOOKED_AT + timedelta(minutes=1))
    write_tick(
        state=running,
        tick=SchedulerRecord(
            at=PINNED,
            failures=["could not start assignment", "could not read comments for GH8"],
            cooldown=cooldown,
        ),
    )

    found = report(state=running)

    assert found.latest_scheduler_tick == PINNED
    assert found.daemon.interval_seconds == DEFAULT_INTERVAL_SECONDS
    assert found.scheduler_failure_summary == (
        "could not start assignment; could not read comments for GH8"
    )
    assert found.daemon.max_agents == 3
    assert found.active_global_cooldown == cooldown


def test_a_stopped_daemon_has_no_current_scheduler_failures(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, failures=["could not start assignment"]),
    )

    assert report(state=state).scheduler_failure_summary is None


def test_a_blocked_issue_is_reported_with_its_evidence(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            issue_observations=[
                observed_issue(
                    issue=20,
                    values={"blocked": Truth.TRUE},
                    evidence={"blocked": "blocked by GH10"},
                )
            ],
        ),
    )

    status_report = report(state=state)

    assert [issue.issue for issue in status_report.issue_observations] == [20]
    assert status_report.issue_observations[0].blocked.evidence == "blocked by GH10"


def test_a_routing_conflict_and_blocker_are_reported_once_with_their_evidence(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            issue_observations=[
                observed_issue(
                    issue=20,
                    values={
                        "routing_conflict": Truth.TRUE,
                        "blocked": Truth.TRUE,
                    },
                    evidence={
                        "routing_conflict": "multiple assignment labels",
                        "blocked": "blocked by GH10",
                    },
                )
            ],
        ),
    )

    status_report = report(state=state)

    assert [issue.issue for issue in status_report.issue_observations] == [20]
    assert (
        status_report.issue_observations[0].routing_conflict.evidence
        == "multiple assignment labels"
    )
    assert status_report.issue_observations[0].blocked.evidence == "blocked by GH10"


def test_a_routing_conflict_without_a_blocker_is_reported(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            issue_observations=[
                observed_issue(
                    issue=20,
                    values={"routing_conflict": Truth.TRUE},
                    evidence={"routing_conflict": "multiple assignment labels"},
                )
            ],
        ),
    )

    status_report = report(state=state)

    assert [issue.issue for issue in status_report.issue_observations] == [20]


def test_an_open_local_assignment_removes_its_issue_from_available_work(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            issue_observations=[observed_issue(issue=13)],
        ),
    )

    assert report(state=state).issue_observations == []


def test_a_complete_local_assignment_no_longer_claims_its_observed_issue(state):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.WRAP_UP)
    observation = observed_issue(
        issue=13,
        values={"claimed_here": Truth.TRUE},
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, issue_observations=[observation]),
    )

    issue = report(state=state).issue_observations[0]

    assert issue.claimed_here.value is Truth.FALSE
    assert issue.availability.value is Truth.TRUE


def test_available_issues_keep_scheduler_order_and_observation_times(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            issue_observations=[
                observed_issue(issue=20),
                observed_issue(issue=21).model_copy(update={"observed_at": LOOKED_AT}),
            ],
        ),
    )

    issues = report(state=state).issue_observations

    assert [issue.issue for issue in issues] == [20, 21]
    assert issues[0].observed_at == PINNED
    assert issues[1].observed_at == LOOKED_AT


def test_assignments_are_ordered_by_issue_with_the_newest_at_an_issue_first(state):
    write_assignment(
        state=state,
        identifier="GH13-20260820-090000",
        issue=13,
    )
    write_assignment(
        state=state,
        identifier="GH9-20260819-184158",
        issue=9,
    )

    identifiers = [
        status.assignment.identifier
        for status in report(state=state).assignment_statuses
    ]

    assert identifiers == [
        "GH9-20260819-184158",
        "GH13-20260820-090000",
        ASSIGNMENT_ID,
    ]


def test_reading_one_issue_returns_only_its_assignments_newest_first(state):
    write_assignment(
        state=state,
        identifier="GH13-20260820-090000",
        issue=13,
    )
    write_assignment(
        state=state,
        identifier="GH9-20260819-184158",
        issue=9,
    )

    statuses = read_assignment_statuses_for_issue(
        state=state,
        issue=13,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )

    assert [status.assignment.identifier for status in statuses] == [
        "GH13-20260820-090000",
        ASSIGNMENT_ID,
    ]


def test_reading_one_assignment_uses_its_exact_identifier(state):
    other_identifier = "GH13-20260820-090000"
    write_assignment(
        state=state,
        identifier=other_identifier,
        issue=13,
    )

    status = read_assignment_status(
        state=state,
        identifier=other_identifier,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )

    assert status is not None
    assert status.assignment.identifier == other_identifier


def test_reading_one_assignment_uses_the_daemon_status_it_is_given(state):
    ran(state=state, number=1, status=None)

    status = read_assignment_status(
        state=state,
        identifier=ASSIGNMENT_ID,
        daemon=DreamcatcherDaemonStatus(is_running=True, run=None),
        clock=lambda: LOOKED_AT,
    )

    assert status is not None
    assert status.round_statuses[0].outcome_description == "running"


def test_reading_an_unknown_assignment_finds_nothing(state):
    assert (
        read_assignment_status(
            state=state,
            identifier="GH99-20260820-090000",
            daemon=read_dreamcatcher_daemon_status(state=state),
            clock=lambda: LOOKED_AT,
        )
        is None
    )


def test_reading_an_incomplete_assignment_finds_nothing(state):
    identifier = "GH99-20260820-090000"
    (state.worktrees / identifier).mkdir()

    assert (
        read_assignment_status(
            state=state,
            identifier=identifier,
            daemon=read_dreamcatcher_daemon_status(state=state),
            clock=lambda: LOOKED_AT,
        )
        is None
    )


def test_reading_one_assignment_does_not_read_an_unrelated_assignment(state):
    corrupt_identifier = "GH99-20260820-090000"
    write_assignment(
        state=state,
        identifier=corrupt_identifier,
        issue=99,
    )
    record = state.assignments / corrupt_identifier / "assignment.json"
    record.write_bytes(b"{")

    status = read_assignment_status(
        state=state,
        identifier=ASSIGNMENT_ID,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )
    unknown = read_assignment_status(
        state=state,
        identifier="GH100-20260820-090000",
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )

    assert status is not None
    assert status.assignment.identifier == ASSIGNMENT_ID
    assert unknown is None


def test_a_failed_setup_reports_independently_of_an_external_claim(state):
    observation = observed_issue(
        issue=20,
        values={"claimed_elsewhere": Truth.TRUE},
        evidence={"claimed_elsewhere": "a pull request is open on it: #52"},
    ).model_copy(
        update={"title": "Failed issue", "setup_failure": "assignment setup failed"}
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, issue_observations=[observation]),
    )

    status_report = report(state=state)

    assert status_report.failed_assignment_setups == [
        observation.model_copy(update={"observed_at": PINNED})
    ]
    assert status_report.issue_observations == []


def test_a_failed_setup_with_a_routing_conflict_is_reported_once(state):
    observation = observed_issue(
        issue=20,
        values={"routing_conflict": Truth.TRUE},
        evidence={"routing_conflict": "multiple assignment labels"},
    ).model_copy(update={"setup_failure": "assignment setup failed"})
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, issue_observations=[observation]),
    )

    status_report = report(state=state)

    assert [issue.issue for issue in status_report.failed_assignment_setups] == [20]
    assert status_report.issue_observations == []
