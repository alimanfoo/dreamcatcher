import inspect
import os
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import REPOSITORY, configure
from observations import observed_issue
from records import (
    write_agent_assignment,
    write_daemon_lock,
    write_daemon_run,
    write_feed,
    write_round,
    write_tick,
)

import dreamcatcher.scheduler as scheduler_module
import dreamcatcher.status as status_module
import dreamcatcher.tui as tui_module
from dreamcatcher.agent_rounds import (
    AgentAssignmentRoundPurpose,
    AgentRoundRecord,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    compose_agent_round_ending,
)
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS
from dreamcatcher.documents import write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.scheduler import (
    AgentAssignmentObservation,
    GlobalCooldown,
    IssueFactValue,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentAssignmentStatusValue,
    read_agent_assignment_status,
    read_agent_assignment_statuses_for_issue,
    read_status_report,
)

ASSIGNMENT_ID = "GH13-20260819-184158"
LOOKED_AT = PINNED + timedelta(hours=2)


@pytest.fixture
def state(tmp_path):
    """A configured state directory holding one assignment."""
    configure(root=tmp_path)
    directory = StateDirectory(root=tmp_path)
    write_daemon_run(state=directory, pid=os.getpid(), max_agents=3)
    write_agent_assignment(state=directory, identifier=ASSIGNMENT_ID, issue=13)
    return directory


@pytest.fixture
def running(state):
    """That state directory held by a daemon with this process identifier."""
    write_daemon_lock(state=state)
    return state


def ran(
    *,
    state: StateDirectory,
    number: int,
    purpose: AgentAssignmentRoundPurpose = AgentAssignmentRoundPurpose.IMPLEMENT,
    status: int | None = 0,
    ended_at=PINNED,
) -> None:
    """Write one round for the fixture's assignment."""
    started = PINNED + timedelta(minutes=number)
    ending = (
        None
        if status is None
        else compose_agent_round_ending(at=ended_at, status=status)
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


def idle_observation() -> AgentAssignmentObservation:
    """Return the scheduler's explicit observation that no round is required."""
    return AgentAssignmentObservation(
        assignment_identifier=ASSIGNMENT_ID,
        issue=13,
        reason="no round required",
        is_round_required=False,
    )


def test_an_empty_instance_reports_unknown_capacity_and_no_work(tmp_path):

    found = read_status_report(
        state=StateDirectory(root=tmp_path),
        clock=lambda: LOOKED_AT,
    )

    assert found.at == LOOKED_AT
    assert found.repository is None
    assert found.daemon_pid is None
    assert found.agent_harness is None
    assert found.dreamcatcher_version is None
    assert found.latest_scheduler_tick is None
    assert found.scheduler_interval_seconds is None
    assert found.scheduler_hold is None
    assert found.max_agents is None
    assert found.running_agents == 0
    assert found.active_global_cooldown is None
    assert found.available_issues == []
    assert found.blocked_issues == []
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

    assert found.agent_harness is AgentHarness.CODEX
    assert found.dreamcatcher_version == "3.0.0.beta1"


def test_a_live_daemon_does_not_mix_in_another_runs_facts(state):
    write_daemon_run(
        state=state,
        pid=os.getpid() + 1,
        harness=AgentHarness.CODEX,
        max_agents=4,
    )
    write_daemon_lock(state=state)

    found = report(state=state)

    assert found.agent_harness is None
    assert found.dreamcatcher_version is None
    assert found.max_agents is None


def test_a_live_round_reports_work_and_its_latest_output(running):
    ran(state=running, number=1, status=None)
    said(state=running, number=1, texts=["first", "[Bash] pytest"])

    found = report(state=running)
    status = found.assignment_statuses[0]

    assert found.daemon_pid == os.getpid()
    assert found.running_agents == 1
    assert status.value is AgentAssignmentStatusValue.WORKING
    assert status.detail == "round 1, implement, running 1h 59m, last output 1h 58m ago"
    assert status.latest_output == "[Bash] pytest"
    assert status.hand_resume_command is None


@pytest.mark.parametrize(
    ("ending", "outcome_description", "duration"),
    [
        (
            compose_agent_round_ending(at=PINNED + timedelta(minutes=4), status=0),
            "successful",
            "ran 4m",
        ),
        (
            compose_agent_round_ending(at=PINNED + timedelta(minutes=4), status=2),
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
            purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
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
        write_daemon_lock(state=state)
    ran(state=state, number=1, status=None)

    round_status = only_assignment(state=state).round_statuses[0]

    assert round_status.outcome_description == outcome_description
    assert round_status.duration_description == ""


def test_status_recovers_the_harness_session_and_builds_its_resume_command(tmp_path):
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    directory = write_agent_assignment(
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
            purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
            started=PINNED,
            pid=1,
            ending=compose_agent_round_ending(
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

    def recover_harness_session_identifier(**kwargs):
        calls.append(kwargs)
        return "abc-123"

    monkeypatch.setattr(
        status_module,
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
    directory = write_agent_assignment(
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
            purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
            started=PINNED,
            pid=1,
            ending=compose_agent_round_ending(
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

    assert status.value is AgentAssignmentStatusValue.WORKING
    assert status.detail == "round 1, implement, running 1h 59m, has said nothing yet"
    assert status.latest_output is None


@pytest.mark.parametrize(
    ("round_status", "detail"),
    [
        (None, "next round, implement (recovery)"),
        (2, "next round, implement (recovery)"),
    ],
)
def test_an_unfinished_round_waits_for_recovery(state, round_status, detail):
    ran(state=state, number=1, status=round_status)

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.WAITING
    assert status.detail == detail


def test_a_successful_wrap_up_is_complete(state):
    ran(state=state, number=1)
    ran(state=state, number=2, purpose=AgentAssignmentRoundPurpose.WRAP_UP)

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.COMPLETE
    assert status.detail == "2 rounds"


def test_an_assignment_that_has_run_no_round_waits_for_its_first(state):
    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.WAITING
    assert status.detail == "next round, implement"


def test_a_required_round_reports_the_scheduler_reason(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment_identifier=ASSIGNMENT_ID,
                    issue=13,
                    reason="1 new post to answer",
                )
            ],
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.WAITING
    assert status.detail == "next round, implement"
    assert status.observed_at == LOOKED_AT


def test_an_unknown_assignment_observation_reports_unknown(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment_identifier=ASSIGNMENT_ID,
                    issue=13,
                    reason="cannot read its pull request: unavailable",
                    is_known=False,
                )
            ],
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.UNKNOWN
    assert status.detail == "cannot read its pull request: unavailable"


def test_an_assignment_with_no_scheduler_observation_is_unknown(state):
    ran(state=state, number=1)

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.UNKNOWN
    assert status.detail == "no current scheduler observation"


@pytest.mark.parametrize("launched_agent_work_identifier", [None, ASSIGNMENT_ID])
def test_a_round_ending_after_the_latest_tick_waits_for_the_next_update(
    state, launched_agent_work_identifier
):
    ran(state=state, number=1, ended_at=LOOKED_AT + timedelta(minutes=1))
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            launched_agent_work_identifier=launched_agent_work_identifier,
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.WAITING
    assert status.detail == "round 1 ended, awaiting next update"


@pytest.mark.parametrize("ended_at", [LOOKED_AT - timedelta(minutes=1), LOOKED_AT])
def test_a_tick_at_or_after_the_latest_ending_needs_an_observation(state, ended_at):
    ran(state=state, number=1, ended_at=ended_at)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            launched_agent_work_identifier=ASSIGNMENT_ID,
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.UNKNOWN
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
        only_assignment(state=state).value
        is AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK
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

    assert status.value is AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK
    assert status.detail == "idle 1h 58m"


def test_a_current_idle_assignment_with_no_feed_is_idle(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[idle_observation()],
        ),
    )

    assert only_assignment(state=state).detail == "idle"


def test_a_stopped_assignment_needs_user_feedback(state):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
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

    assert status.value is AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK
    assert status.round_statuses[0].duration_description == "ran 4m"
    assert status.round_statuses[0].outcome_description == "stopped"


def test_two_current_errors_put_an_assignment_in_fault(state):
    ran(state=state, number=1, status=1)
    ran(state=state, number=2, status=2)

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.FAULT
    assert status.detail == (
        "two consecutive rounds failed "
        f"(.dreamcatcher/v3/assignments/{ASSIGNMENT_ID}/rounds/2/feed.txt)"
    )


def test_an_elapsed_cooldown_clears_the_fault_and_active_hold(state):
    ran(state=state, number=1, status=1)
    ran(state=state, number=2, status=2)
    ended = PINNED + timedelta(minutes=15)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            hold="global cooldown",
            cooldown=GlobalCooldown(started=PINNED, ends=ended),
        ),
    )

    found = report(state=state)

    assert found.assignment_statuses[0].value is AgentAssignmentStatusValue.WAITING
    assert found.scheduler_hold is None
    assert found.active_global_cooldown is None


def test_an_active_cooldown_and_hold_are_instance_facts(running):
    cooldown = GlobalCooldown(started=PINNED, ends=LOOKED_AT + timedelta(minutes=1))
    write_tick(
        state=running,
        tick=SchedulerRecord(
            at=PINNED,
            hold="global cooldown",
            cooldown=cooldown,
        ),
    )

    found = report(state=running)

    assert found.latest_scheduler_tick == PINNED
    assert found.scheduler_interval_seconds == DEFAULT_INTERVAL_SECONDS
    assert found.scheduler_hold == "global cooldown"
    assert found.max_agents == 3
    assert found.active_global_cooldown == cooldown


def test_a_stopped_daemon_has_no_current_scheduler_hold(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, hold="at cap: 1 of 1 agents running"),
    )

    assert report(state=state).scheduler_hold is None


def test_a_blocked_issue_is_reported_with_its_evidence(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            issue_observations=[
                observed_issue(
                    issue=20,
                    values={"blocked": IssueFactValue.TRUE},
                    evidence={"blocked": "blocked by GH10"},
                )
            ],
        ),
    )

    status_report = report(state=state)

    assert status_report.available_issues == []
    assert [issue.issue for issue in status_report.blocked_issues] == [20]
    assert status_report.blocked_issues[0].blocked.evidence == "blocked by GH10"


def test_an_open_local_assignment_removes_its_issue_from_available_work(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            issue_observations=[observed_issue(issue=13)],
        ),
    )

    assert report(state=state).available_issues == []


def test_a_complete_local_assignment_no_longer_claims_its_observed_issue(state):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.WRAP_UP)
    observation = observed_issue(
        issue=13,
        values={"claimed_here": IssueFactValue.TRUE},
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, issue_observations=[observation]),
    )

    issue = report(state=state).available_issues[0]

    assert issue.claimed_here.value is IssueFactValue.FALSE
    assert issue.availability.value is IssueFactValue.TRUE


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

    issues = report(state=state).available_issues

    assert [issue.issue for issue in issues] == [20, 21]
    assert issues[0].observed_at == PINNED
    assert issues[1].observed_at == LOOKED_AT


def test_assignments_are_ordered_by_issue_with_the_newest_at_an_issue_first(state):
    write_agent_assignment(
        state=state,
        identifier="GH13-20260820-090000",
        issue=13,
    )
    write_agent_assignment(
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
    write_agent_assignment(
        state=state,
        identifier="GH13-20260820-090000",
        issue=13,
    )
    write_agent_assignment(
        state=state,
        identifier="GH9-20260819-184158",
        issue=9,
    )

    statuses = read_agent_assignment_statuses_for_issue(
        state=state,
        issue=13,
        clock=lambda: LOOKED_AT,
    )

    assert [status.assignment.identifier for status in statuses] == [
        "GH13-20260820-090000",
        ASSIGNMENT_ID,
    ]


def test_reading_one_assignment_uses_its_exact_identifier(state):
    other_identifier = "GH13-20260820-090000"
    write_agent_assignment(
        state=state,
        identifier=other_identifier,
        issue=13,
    )

    status = read_agent_assignment_status(
        state=state,
        identifier=other_identifier,
        clock=lambda: LOOKED_AT,
    )

    assert status is not None
    assert status.assignment.identifier == other_identifier


def test_reading_an_unknown_assignment_finds_nothing(state):
    assert (
        read_agent_assignment_status(
            state=state,
            identifier="GH99-20260820-090000",
            clock=lambda: LOOKED_AT,
        )
        is None
    )


def test_reading_an_incomplete_assignment_finds_nothing(state):
    identifier = "GH99-20260820-090000"
    (state.worktrees / identifier).mkdir()

    assert (
        read_agent_assignment_status(
            state=state,
            identifier=identifier,
            clock=lambda: LOOKED_AT,
        )
        is None
    )


def test_reading_one_assignment_does_not_read_an_unrelated_assignment(state):
    corrupt_identifier = "GH99-20260820-090000"
    write_agent_assignment(
        state=state,
        identifier=corrupt_identifier,
        issue=99,
    )
    record = state.assignments / corrupt_identifier / "assignment.json"
    record.write_bytes(b"{")

    status = read_agent_assignment_status(
        state=state,
        identifier=ASSIGNMENT_ID,
        clock=lambda: LOOKED_AT,
    )
    unknown = read_agent_assignment_status(
        state=state,
        identifier="GH100-20260820-090000",
        clock=lambda: LOOKED_AT,
    )

    assert status is not None
    assert status.assignment.identifier == ASSIGNMENT_ID
    assert unknown is None


def test_a_failed_setup_reports_independently_of_an_external_claim(state):
    observation = observed_issue(
        issue=20,
        values={"claimed_elsewhere": IssueFactValue.TRUE},
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
    assert status_report.available_issues == []


def test_scheduling_does_not_consume_status_reports():
    assert "dreamcatcher.status" not in inspect.getsource(scheduler_module)


@pytest.mark.parametrize(
    "dependency",
    [
        "dreamcatcher.scheduler",
        "find_harness_session_identifier",
        "HARNESS_ADAPTERS",
        "ErroredAgentRoundEnding",
        "InterruptedAgentRoundEnding",
    ],
)
def test_the_tui_does_not_import_domain_policy_or_operations(dependency):
    assert dependency not in inspect.getsource(tui_module)
