import os
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import ASSIGNMENT_LABEL, PULL_REQUEST, REPOSITORY
from records import (
    MERGED_INPUT,
    hold_daemon_lock_for_test,
    read_assignments,
    write_assignment,
    write_daemon_run,
    write_feed,
    write_round,
    write_tick,
)
from rows import UNCLAIMED, request_row
from status_fabrications import fabricate_everything

from dreamcatcher.agent_assignments import (
    AssignmentRoundInput,
    cancel_assignment,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import AgentWork, find_agent_work
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.github import CheckResult, PullRequestMergeState, PullRequestState
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    GlobalCooldown,
    PullRequestFinding,
    ReadFailureFinding,
    RequestRow,
    SchedulerRecord,
    StartedRound,
    StartTimeFinding,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AGENT_WORK_STATUS_VALUES_IN_ATTENTION_ORDER,
    AgentWorkStatusSection,
    AgentWorkStatusValue,
    DaemonStatusFact,
    DreamcatcherDaemonStatus,
    RequestReason,
    RequestStatus,
    StatusFact,
    read_agent_work_status,
    read_assignment_statuses_for_issue,
    read_dreamcatcher_daemon_status,
    read_status_report,
)
from dreamcatcher.status.requests import RequestStatusValue

ASSIGNMENT_ID = "GH13-20260819-184158-assignment"
LOOKED_AT = PINNED + timedelta(hours=2)


def read_work_status(
    *,
    state: StateDirectory,
    identifier: str,
    daemon: DreamcatcherDaemonStatus,
    clock,
):
    """Read the status of the work with this identifier, as a work page does."""
    work = find_agent_work(state=state, identifier=identifier)
    if work is None:
        return None
    return read_agent_work_status(state=state, work=work, daemon=daemon, clock=clock)


@pytest.fixture
def state(tmp_path):
    """A state directory holding one assignment, and a daemon run routing it."""
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
    status: int | None = 0,
    ended_at=PINNED,
    round_input: AssignmentRoundInput | None = None,
) -> None:
    """Write one round for the fixture's assignment."""
    started = PINNED + timedelta(minutes=number)
    ending = (
        None
        if status is None
        else _compose_agent_round_ending(at=ended_at, status=status)
    )
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=number,
        record=AgentRoundRecord(
            number=number,
            started=started,
            pid=1,
            ending=ending,
        ),
        round_input=round_input,
    )


def said(*, state: StateDirectory, number: int, texts: Sequence[str]) -> None:
    """Write feed lines one minute after the numbered round began."""
    at = PINNED + timedelta(minutes=number + 1)
    write_feed(
        directory=state.work / ASSIGNMENT_ID,
        number=number,
        lines=[FeedLine(at=at, text=text) for text in texts],
    )


def report(*, state: StateDirectory):
    """Read the fixture's status report at the pinned time."""
    return read_status_report(state=state, clock=lambda: LOOKED_AT)


def only_assignment(*, state: StateDirectory):
    """Return the only agent-assignment status in the fixture."""
    assignments = report(state=state).work_statuses
    assert len(assignments) == 1
    return assignments[0]


def pull_request_row(
    *,
    new_posts: int = 0,
    state: PullRequestState = PullRequestState.OPEN,
    is_draft: bool = False,
    is_final_turn_due: bool = False,
    started_round: StartedRound | None = None,
) -> RequestRow:
    """Return the row of the fixture's assignment with what its pull request held."""
    return request_row(
        issue=13,
        agent_work_identifier=ASSIGNMENT_ID,
        finding=PullRequestFinding(
            number=PULL_REQUEST,
            state=state,
            is_draft=is_draft,
            merge_state=PullRequestMergeState.CLEAN,
            check_result=CheckResult.PASSING,
            new_posts=new_posts,
            new_signals=[],
            is_check_failure_withheld=False,
            is_final_turn_due=is_final_turn_due,
        ),
        started_round=started_round,
    )


def tick_with(*, state: StateDirectory, rows: list[RequestRow], at=LOOKED_AT) -> None:
    """Write a tick at that time that wrote these rows."""
    write_tick(state=state, tick=SchedulerRecord(at=at, rows=rows))


def test_an_empty_instance_reports_unknown_capacity_and_no_work(tmp_path):
    found = read_status_report(
        state=StateDirectory(root=tmp_path),
        clock=lambda: LOOKED_AT,
    )

    assert found.at == LOOKED_AT
    assert found.repository is None
    assert found.daemon.pid is None
    assert found.daemon.preferred_harness is None
    assert found.daemon.dreamcatcher_version is None
    assert found.latest_scheduler_tick is None
    assert found.daemon.interval_seconds is None
    assert found.scheduler_failure_summary is None
    assert found.daemon.max_agents is None
    assert found.running_agents == 0
    assert found.active_global_cooldown is None
    assert found.request_statuses == []
    assert found.work_statuses == []


def test_an_empty_report_names_the_labels_the_daemon_routes_without_a_config(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())

    found = read_status_report(state=state, clock=lambda: LOOKED_AT)

    assert found.describe_section(
        kind=AgentWorkKind.ASSIGNMENT
    ) == AgentWorkStatusSection(
        heading="assignments",
        empty_message=(
            "Assign an issue to yourself and label it with dream:smith "
            "to create an assignment."
        ),
    )
    assert found.describe_section(kind=AgentWorkKind.CONVERSATION) is None


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

    assert found.daemon.preferred_harness is AgentHarness.CODEX
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
    status = found.work_statuses[0]

    assert found.daemon.pid == os.getpid()
    assert found.running_agents == 1
    assert status.value is AgentWorkStatusValue.WORKING
    assert status.detail == "round 1, start, running 1h 59m, last output 1h 58m ago"
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
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
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
        AgentWork,
        "find_harness_session_identifier",
        recover_harness_session_identifier,
    )

    status = only_assignment(state=state)

    assert calls == []
    assert status.harness_session_identifier == "abc-123"
    assert status.hand_resume_command == ["claude", "--resume", "abc-123"]
    assert len(calls) == 1


def test_status_with_no_harness_session_has_no_resume_command(tmp_path):
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

    assert status.value is AgentWorkStatusValue.WORKING
    assert status.detail == "round 1, start, running 1h 59m, has said nothing yet"
    assert status.latest_output is None


def test_a_round_that_errored_before_its_harness_ran_says_why_without_a_status(
    state,
):
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            ending=ErroredAgentRoundEnding(at=PINNED, reason="git push failed"),
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "round 1 errored: git push failed"
    assert status.round_statuses[0].outcome_description == "errored"


@pytest.mark.parametrize(
    ("round_status", "detail"),
    [
        (None, "round 1 interrupted"),
        (2, "round 1 errored (exit 2)"),
    ],
)
def test_an_unfinished_round_waits_to_be_given_its_input_again(
    state, round_status, detail
):
    ran(state=state, number=1, status=round_status)

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == detail


def test_a_successful_wrap_up_is_complete(state):
    ran(state=state, number=1)
    ran(state=state, number=2, round_input=MERGED_INPUT)

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.ENDED
    assert status.detail == "completed"
    assert status.has_ended


def cancel(*, state: StateDirectory) -> None:
    """Cancel the fixture's assignment."""
    cancel_assignment(assignment=read_assignments(state=state)[0], at=PINNED)


def test_a_cancelled_assignment_has_ended(state):
    ran(state=state, number=1)
    cancel(state=state)

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.ENDED
    assert status.detail == "cancelled"
    assert status.has_ended


def test_a_round_still_running_after_a_cancel_is_working(running):
    ran(state=running, number=1, status=None)
    cancel(state=running)

    status = only_assignment(state=running)

    assert status.value is AgentWorkStatusValue.WORKING
    assert not status.has_ended


def test_a_cancelled_assignment_has_ended_rather_than_being_in_fault(state):
    ran(state=state, number=1, status=1)
    ran(state=state, number=2, status=2)
    cancel(state=state)

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.ENDED


@pytest.mark.parametrize(("is_draft", "words"), [(True, "draft"), (False, "ready")])
def test_an_open_assignment_reports_the_pull_request_state_the_tick_read(
    state, is_draft, words
):
    ran(state=state, number=1)
    tick_with(state=state, rows=[pull_request_row(is_draft=is_draft)])

    assert only_assignment(state=state).pull_request_state == words


def test_an_assignment_the_tick_read_nothing_for_reports_no_pull_request_state(state):
    ran(state=state, number=1, status=None)
    tick_with(
        state=state, rows=[request_row(issue=13, agent_work_identifier=ASSIGNMENT_ID)]
    )

    assert only_assignment(state=state).pull_request_state is None


def test_a_cancelled_assignment_stops_reporting_its_pull_request_state(state):
    ran(state=state, number=1)
    tick_with(state=state, rows=[pull_request_row(is_draft=True)])

    cancel(state=state)

    assert only_assignment(state=state).pull_request_state is None


@pytest.mark.parametrize("status", [0, None])
def test_a_wrapped_up_assignment_reports_the_state_its_last_round_was_given(
    state, status
):
    ran(state=state, number=1)
    ran(state=state, number=2, status=status, round_input=MERGED_INPUT)
    tick_with(
        state=state, rows=[request_row(issue=13, agent_work_identifier=ASSIGNMENT_ID)]
    )

    assert only_assignment(state=state).pull_request_state == "merged"


def test_an_assignment_that_has_run_no_round_waits_for_its_first(state):
    tick_with(state=state, rows=[])

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "no round has run yet"
    assert not status.has_ended


def test_new_posts_found_by_the_tick_make_the_assignment_wait(state):
    ran(state=state, number=1)
    tick_with(state=state, rows=[pull_request_row(new_posts=1)])

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "1 new post to answer"


@pytest.mark.parametrize("pull_request_state", ["MERGED", "CLOSED"])
def test_a_finished_pull_request_waits_for_the_final_turn(state, pull_request_state):
    ran(state=state, number=1)
    tick_with(
        state=state,
        rows=[
            pull_request_row(
                state=PullRequestState(pull_request_state), is_final_turn_due=True
            )
        ],
    )

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == f"the pull request is {pull_request_state.lower()}"


def test_a_failed_read_makes_the_assignment_unknown_with_the_reason(state):
    ran(state=state, number=1)
    tick_with(
        state=state,
        rows=[
            request_row(
                issue=13,
                agent_work_identifier=ASSIGNMENT_ID,
                finding=ReadFailureFinding(reason="unavailable"),
            )
        ],
    )

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.UNKNOWN
    assert status.detail == "cannot tell: unavailable"


def test_an_assignment_before_any_update_is_unknown(state):
    ran(state=state, number=1)

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.UNKNOWN
    assert status.detail == "not seen by the latest update"


@pytest.mark.parametrize("is_launched_observed", [False, True])
def test_a_round_ending_after_the_latest_tick_waits_for_the_next_update(
    state, is_launched_observed
):
    ran(state=state, number=1, ended_at=LOOKED_AT + timedelta(minutes=1))
    tick_with(
        state=state,
        rows=(
            [pull_request_row(new_posts=1, started_round=StartedRound(number=1))]
            if is_launched_observed
            else []
        ),
    )

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "round 1 ended, awaiting next update"


@pytest.mark.parametrize("ended_at", [LOOKED_AT - timedelta(minutes=1), LOOKED_AT])
def test_an_assignment_the_latest_update_did_not_see_is_unknown(state, ended_at):
    ran(state=state, number=1, ended_at=ended_at)
    tick_with(state=state, rows=[])

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.UNKNOWN
    assert status.detail == "not seen by the latest update"


def test_what_the_latest_update_read_stays_current_when_a_round_ends_after_it(state):
    ran(state=state, number=1, ended_at=LOOKED_AT + timedelta(minutes=1))
    tick_with(state=state, rows=[pull_request_row()])

    assert only_assignment(state=state).value is AgentWorkStatusValue.IDLE


def test_a_ready_pull_request_with_nothing_new_is_idle_ready_for_review(state):
    ran(state=state, number=1)
    tick_with(state=state, rows=[pull_request_row()])

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == "ready for review"


def test_a_draft_pull_request_with_nothing_new_is_idle_as_a_draft(state):
    ran(state=state, number=1)
    tick_with(state=state, rows=[pull_request_row(is_draft=True)])

    assert only_assignment(state=state).detail == "draft"


def test_a_finished_pull_request_whose_final_turn_was_taken_is_idle(state):
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=4)),
        ),
        round_input=MERGED_INPUT,
    )
    tick_with(state=state, rows=[pull_request_row(state=PullRequestState.MERGED)])

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == "merged"


def test_a_stopped_assignment_is_idle(state):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=started,
            pid=1,
            ending=StoppedAgentRoundEnding(at=started + timedelta(minutes=4)),
        ),
    )
    tick_with(state=state, rows=[pull_request_row()])

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.round_statuses[0].duration_description == "ran 4m"
    assert status.round_statuses[0].outcome_description == "stopped"


def test_two_current_errors_put_an_assignment_in_fault(state):
    ran(state=state, number=1, status=1)
    ran(state=state, number=2, status=2)
    said(state=state, number=2, texts=["[failed] You hit your spend cap."])

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.FAULT
    assert status.detail == "round 2 errored (exit 2)"
    assert status.latest_output == "[failed] You hit your spend cap."
    assert not status.has_ended


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

    assert found.work_statuses[0].value is AgentWorkStatusValue.WAITING
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
    assert found.instance_facts == (
        StatusFact(label="preferred harness", value="claude"),
        StatusFact(label="next update in", value="0s"),
        StatusFact(label="agent capacity", value="0 of 3 working"),
        StatusFact(label="global cooldown", value="ends in 1m", is_warning=True),
        StatusFact(
            label="scheduler failures",
            value="could not start assignment; could not read comments for GH8",
            is_warning=True,
        ),
    )


def test_a_stopped_daemon_has_no_current_scheduler_failures(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(at=PINNED, failures=["could not start assignment"]),
    )

    assert report(state=state).scheduler_failure_summary is None


def test_a_blocked_request_names_its_claims_and_blockers_as_numbers(state):
    blocked = request_row(
        issue=20,
        finding=StartTimeFinding(linked_pull_requests=[28], blocking_issues=[10, 11]),
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[blocked],
        ),
    )

    [request] = report(state=state).request_statuses

    assert request == RequestStatus(
        row=blocked,
        value=RequestStatusValue.BLOCKED,
        reasons=(
            RequestReason(words="claimed by", pull_requests=(28,)),
            RequestReason(words="blocked by", issues=(10, 11)),
        ),
    )


def test_a_request_that_an_open_pull_request_claims_is_blocked(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(
                    issue=20,
                    finding=StartTimeFinding(
                        linked_pull_requests=[28], blocking_issues=[]
                    ),
                )
            ],
        ),
    )

    [request] = report(state=state).request_statuses

    assert request.value is RequestStatusValue.BLOCKED
    assert request.reasons == (RequestReason(words="claimed by", pull_requests=(28,)),)


def test_an_assignment_whose_pull_request_is_not_yet_open_waits_for_it(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13, pull_request=None)
    ran(state=state, number=1)
    tick_with(
        state=state,
        rows=[request_row(issue=13, agent_work_identifier=ASSIGNMENT_ID)],
    )

    status = only_assignment(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "no pull request yet"


def test_a_request_nothing_claims_or_blocks_is_available(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED, rows=[request_row(issue=20, finding=UNCLAIMED)]
        ),
    )

    [request] = report(state=state).request_statuses

    assert request.value is RequestStatusValue.AVAILABLE
    assert request.reasons == (RequestReason(words="available"),)


def test_two_labels_of_one_kind_are_a_routing_conflict_named_in_each_row(state):
    conflict = ConflictingLabelsFinding(labels=["dream:less", ASSIGNMENT_LABEL])
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(issue=20, label="dream:less", finding=conflict),
                request_row(issue=20, finding=conflict),
            ],
        ),
    )

    requests = report(state=state).request_statuses

    assert [(request.row.dispatch_label, request.value) for request in requests] == [
        ("dream:less", RequestStatusValue.ROUTING_CONFLICT),
        (ASSIGNMENT_LABEL, RequestStatusValue.ROUTING_CONFLICT),
    ]
    assert requests[0].reasons == (
        RequestReason(words="multiple assignment labels: dream:less, dream:smith"),
    )


def test_a_request_whose_read_failed_is_unknown_with_the_reason(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(issue=20, finding=ReadFailureFinding(reason="gh: offline"))
            ],
        ),
    )

    [request] = report(state=state).request_statuses

    assert request.value is RequestStatusValue.UNKNOWN
    assert request.reasons == (RequestReason(words="cannot tell: gh: offline"),)


def test_a_request_that_led_to_open_work_is_reported_through_its_work(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(
                    issue=13, agent_work_identifier=ASSIGNMENT_ID, finding=UNCLAIMED
                )
            ],
        ),
    )

    assert report(state=state).request_statuses == []


def test_requests_keep_the_order_the_tick_saw_them_in(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(issue=21, finding=UNCLAIMED),
                request_row(issue=20, finding=UNCLAIMED),
            ],
        ),
    )

    requests = report(state=state).request_statuses

    assert [request.row.issue for request in requests] == [21, 20]


def test_assignments_are_ordered_by_issue_with_the_newest_at_an_issue_first(state):
    write_assignment(
        state=state,
        identifier="GH13-20260820-090000-assignment",
        issue=13,
    )
    write_assignment(
        state=state,
        identifier="GH9-20260819-184158-assignment",
        issue=9,
    )

    identifiers = [
        status.work.identifier for status in report(state=state).work_statuses
    ]

    assert identifiers == [
        "GH9-20260819-184158-assignment",
        "GH13-20260820-090000-assignment",
        ASSIGNMENT_ID,
    ]


def test_reading_one_issue_returns_only_its_assignments_newest_first(state):
    write_assignment(
        state=state,
        identifier="GH13-20260820-090000-assignment",
        issue=13,
    )
    write_assignment(
        state=state,
        identifier="GH9-20260819-184158-assignment",
        issue=9,
    )

    statuses = read_assignment_statuses_for_issue(
        state=state,
        issue=13,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )

    assert [status.work.identifier for status in statuses] == [
        "GH13-20260820-090000-assignment",
        ASSIGNMENT_ID,
    ]


def test_reading_one_assignment_uses_its_exact_identifier(state):
    other_identifier = "GH13-20260820-090000-assignment"
    write_assignment(
        state=state,
        identifier=other_identifier,
        issue=13,
    )

    status = read_work_status(
        state=state,
        identifier=other_identifier,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )

    assert status is not None
    assert status.work.identifier == other_identifier


def test_reading_one_assignment_uses_the_daemon_status_it_is_given(state):
    ran(state=state, number=1, status=None)

    status = read_work_status(
        state=state,
        identifier=ASSIGNMENT_ID,
        daemon=DreamcatcherDaemonStatus(is_running=True, run=None),
        clock=lambda: LOOKED_AT,
    )

    assert status is not None
    assert status.round_statuses[0].outcome_description == "running"


def test_reading_an_unknown_assignment_finds_nothing(state):
    assert (
        read_work_status(
            state=state,
            identifier="GH99-20260820-090000-assignment",
            daemon=read_dreamcatcher_daemon_status(state=state),
            clock=lambda: LOOKED_AT,
        )
        is None
    )


def test_reading_a_worktree_with_no_work_record_finds_nothing(state):
    identifier = "GH99-20260820-090000-assignment"
    (state.worktrees / identifier).mkdir()

    assert (
        read_work_status(
            state=state,
            identifier=identifier,
            daemon=read_dreamcatcher_daemon_status(state=state),
            clock=lambda: LOOKED_AT,
        )
        is None
    )


def test_reading_one_assignment_does_not_read_an_unrelated_assignment(state):
    corrupt_identifier = "GH99-20260820-090000-assignment"
    write_assignment(
        state=state,
        identifier=corrupt_identifier,
        issue=99,
    )
    record = state.work / corrupt_identifier / "work.json"
    record.write_bytes(b"{")

    status = read_work_status(
        state=state,
        identifier=ASSIGNMENT_ID,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )
    unknown = read_work_status(
        state=state,
        identifier="GH100-20260820-090000-assignment",
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )

    assert status is not None
    assert status.work.identifier == ASSIGNMENT_ID
    assert unknown is None


def test_a_report_orders_active_assignments_by_attention_and_ended_ones_newest_first(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    found = report(state=state)

    attention = [
        AGENT_WORK_STATUS_VALUES_IN_ATTENTION_ORDER.index(status.value)
        for status in found.list_active_work_statuses(kind=AgentWorkKind.ASSIGNMENT)
    ]
    assert attention == sorted(attention)
    assert len(set(attention)) > 1
    assert [
        status.work.record.issue
        for status in found.list_ended_work_statuses(kind=AgentWorkKind.ASSIGNMENT)
    ] == [70, 12]


def test_an_assignment_keeps_its_section_after_its_routes_are_removed(state):
    write_daemon_run(state=state, pid=os.getpid(), routes=[])

    found = report(state=state)

    assert found.describe_section(
        kind=AgentWorkKind.ASSIGNMENT
    ) == AgentWorkStatusSection(heading="assignments", empty_message=None)


@pytest.mark.parametrize(
    ("is_running", "run", "expected"),
    [
        (
            False,
            None,
            DaemonStatusFact(
                label="daemon", state="not running", version=None, process=None
            ),
        ),
        (
            True,
            None,
            DaemonStatusFact(
                label="daemon", state="running", version=None, process=None
            ),
        ),
        (
            True,
            DaemonRunRecord(
                pid=42,
                harness=AgentHarness.CLAUDE,
                version="5.3.0",
                max_agents=3,
                interval_seconds=DEFAULT_INTERVAL_SECONDS,
                routes=[],
            ),
            DaemonStatusFact(
                label="daemon",
                state="running",
                version="dreamcatcher v5.3.0",
                process="pid 42",
            ),
        ),
    ],
)
def test_a_daemon_fact_says_whether_it_runs_and_which_run_it_is(
    is_running, run, expected
):
    daemon = DreamcatcherDaemonStatus(is_running=is_running, run=run)

    assert daemon.status_fact == expected
