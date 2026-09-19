import inspect
import os
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import configure
from observations import observed_issue
from records import write_agent_assignment, write_feed, write_round, write_tick

import dreamcatcher.scheduler as scheduler_module
import dreamcatcher.tui as tui_module
from dreamcatcher.agent_rounds import (
    AgentRoundPurpose,
    AgentRoundRecord,
    compose_agent_round_ending,
)
from dreamcatcher.feed import Line
from dreamcatcher.scheduler import (
    NO_ROUND_HAS_RUN,
    AgentAssignmentObservation,
    GlobalCooldown,
    IssueFactValue,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentAssignmentStatusValue,
    read_agent_assignment_statuses_for_issue,
    read_status_report,
)

ASSIGNMENT_ID = "GH13-20260819-184158"
LOOKED_AT = PINNED + timedelta(hours=2)


@pytest.fixture
def state(tmp_path):
    """A configured state directory holding one assignment."""
    configure(root=tmp_path, head="interval = 300\nmax_agents = 3\n\n")
    directory = StateDirectory(root=tmp_path)
    write_agent_assignment(state=directory, identifier=ASSIGNMENT_ID, issue=13)
    return directory


@pytest.fixture
def running(state):
    """That state directory held by a daemon with this process identifier."""
    state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return state


def ran(
    *,
    state: StateDirectory,
    number: int,
    purpose: AgentRoundPurpose = AgentRoundPurpose.IMPLEMENT,
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
        lines=[Line(at=at, text=text) for text in texts],
    )


def report(*, state: StateDirectory):
    """Read the fixture's status report at the pinned time."""
    return read_status_report(state=state, clock=lambda: LOOKED_AT)


def only_assignment(*, state: StateDirectory):
    """Return the only agent-assignment status in the fixture."""
    assignments = report(state=state).assignments
    assert len(assignments) == 1
    return assignments[0]


def idle_observation() -> AgentAssignmentObservation:
    """Return the scheduler's explicit observation that no round is required."""
    return AgentAssignmentObservation(
        assignment=ASSIGNMENT_ID,
        issue=13,
        reason="no round required",
        is_round_required=False,
    )


def test_an_empty_instance_reports_its_configuration_and_no_work(tmp_path):
    configure(root=tmp_path, head="interval = 300\nmax_agents = 3\n\n")

    found = read_status_report(
        state=StateDirectory(root=tmp_path),
        clock=lambda: LOOKED_AT,
    )

    assert found.at == LOOKED_AT
    assert found.daemon_pid is None
    assert found.latest_scheduler_tick is None
    assert found.scheduler_hold is None
    assert found.max_agent_rounds == 3
    assert found.running_agent_rounds == 0
    assert found.active_global_cooldown is None
    assert found.issues == []
    assert found.assignments == []


def test_a_live_round_reports_work_and_its_latest_output(running):
    ran(state=running, number=1, status=None)
    said(state=running, number=1, texts=["first", "[Bash] pytest"])

    found = report(state=running)
    status = found.assignments[0]

    assert found.daemon_pid == os.getpid()
    assert found.running_agent_rounds == 1
    assert status.value is AgentAssignmentStatusValue.WORKING
    assert status.detail == "running 1h 59m, last output 1h 58m ago"
    assert status.latest_output == "[Bash] pytest"


def test_a_live_round_that_has_said_nothing_reports_that(running):
    ran(state=running, number=1, status=None)

    status = only_assignment(state=running)

    assert status.value is AgentAssignmentStatusValue.WORKING
    assert status.detail == "running 1h 59m, has said nothing yet"
    assert status.latest_output is None


@pytest.mark.parametrize(
    ("round_status", "detail"),
    [
        (None, "the last round was interrupted"),
        (2, "the last round failed (exit 2)"),
    ],
)
def test_an_unfinished_round_waits_for_recovery(state, round_status, detail):
    ran(state=state, number=1, status=round_status)

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.WAITING
    assert status.detail == detail


def test_a_successful_wrap_up_is_complete(state):
    ran(state=state, number=1)
    ran(state=state, number=2, purpose=AgentRoundPurpose.WRAP_UP)

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.COMPLETE
    assert status.detail == "2 rounds"


def test_an_assignment_that_has_run_no_round_waits_for_its_first(state):
    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.WAITING
    assert status.detail == NO_ROUND_HAS_RUN


def test_a_required_round_reports_the_scheduler_reason(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment=ASSIGNMENT_ID,
                    issue=13,
                    reason="1 new post to answer",
                )
            ],
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.WAITING
    assert status.detail == "1 new post to answer"
    assert status.observed_at == LOOKED_AT


def test_an_unknown_assignment_observation_reports_unknown(state):
    ran(state=state, number=1)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment=ASSIGNMENT_ID,
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


def test_a_tick_without_an_observation_of_the_latest_ending_is_not_current(state):
    ran(state=state, number=1, ended_at=LOOKED_AT + timedelta(minutes=1))
    write_tick(state=state, tick=SchedulerRecord(at=LOOKED_AT))

    assert only_assignment(state=state).value is AgentAssignmentStatusValue.UNKNOWN


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


def test_two_current_errors_put_an_assignment_in_fault(state):
    ran(state=state, number=1, status=1)
    ran(state=state, number=2, status=2)

    status = only_assignment(state=state)

    assert status.value is AgentAssignmentStatusValue.FAULT
    assert status.detail == (
        "two consecutive rounds failed "
        f"(.dreamcatcher/assignments/{ASSIGNMENT_ID}/rounds/2/feed.txt)"
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

    assert found.assignments[0].value is AgentAssignmentStatusValue.WAITING
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
    assert found.scheduler_hold == "global cooldown"
    assert found.active_global_cooldown == cooldown


def test_a_stopped_daemon_has_no_current_scheduler_hold(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, hold="at cap: 1 of 1 rounds running"),
    )

    assert report(state=state).scheduler_hold is None


def test_issue_status_reuses_the_scheduler_availability_interpretation(state):
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

    issue = report(state=state).issues[0]

    assert issue.issue == 20
    assert issue.blocked.value is IssueFactValue.TRUE
    assert issue.availability.value is IssueFactValue.FALSE
    assert issue.availability.evidence == "blocked by GH10"
    assert issue.observed_at == PINNED


def test_an_open_local_assignment_makes_its_observed_issue_claimed_here(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            issue_observations=[observed_issue(issue=13)],
        ),
    )

    issue = report(state=state).issues[0]

    assert issue.claimed_here.value is IssueFactValue.TRUE
    assert issue.availability.value is IssueFactValue.FALSE


def test_a_complete_local_assignment_no_longer_claims_its_observed_issue(state):
    ran(state=state, number=1, purpose=AgentRoundPurpose.WRAP_UP)
    observation = observed_issue(
        issue=13,
        values={"claimed_here": IssueFactValue.TRUE},
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, issue_observations=[observation]),
    )

    issue = report(state=state).issues[0]

    assert issue.claimed_here.value is IssueFactValue.FALSE
    assert issue.availability.value is IssueFactValue.TRUE


def test_an_unobserved_issue_with_an_open_assignment_is_reported_as_unknown(state):
    issue = report(state=state).issues[0]

    assert issue.issue == 13
    assert issue.observed_at is None
    assert issue.is_open.value is IssueFactValue.UNKNOWN
    assert issue.claimed_here.value is IssueFactValue.TRUE
    assert issue.availability.value is IssueFactValue.FALSE


def test_an_unobserved_issue_with_only_a_complete_assignment_is_absent(state):
    ran(state=state, number=1, purpose=AgentRoundPurpose.WRAP_UP)

    assert report(state=state).issues == []


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
        status.assignment.identifier for status in report(state=state).assignments
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


def test_an_observed_issue_with_no_local_assignment_keeps_its_claim_fact(state):
    observation = observed_issue(
        issue=20,
        values={"claimed_here": IssueFactValue.UNKNOWN},
        evidence={"claimed_here": "setup is incomplete"},
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, issue_observations=[observation]),
    )

    issue = report(state=state).issues[0]

    assert issue.claimed_here.value is IssueFactValue.UNKNOWN
    assert issue.claimed_here.evidence == "setup is incomplete"


def test_scheduling_does_not_consume_status_reports():
    assert "dreamcatcher.status" not in inspect.getsource(scheduler_module)


def test_the_tui_does_not_import_scheduling_policy():
    assert "dreamcatcher.scheduler" not in inspect.getsource(tui_module)
