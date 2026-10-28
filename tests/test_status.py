import os
import re
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import ASSIGNMENT_LABEL, PULL_REQUEST, REPOSITORY, compose_comment
from records import (
    HEAD,
    MERGED_INPUT,
    hold_daemon_lock_for_test,
    read_assignments,
    write_assignment,
    write_assignment_round,
    write_daemon_run,
    write_feed,
    write_round,
    write_tick,
)
from rows import UNCLAIMED, compose_request_row
from status_fabrications import compose_feed_line, fabricate_everything

from dreamcatcher.agent_assignments import (
    AssignmentRoundInput,
    cancel_assignment,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    InterruptedAgentRoundEnding,
    LaunchErroredAgentRoundEnding,
    StoppedAgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import AgentWork, find_agent_work
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS
from dreamcatcher.daemon_runs import DaemonRunRecord, RecordedRoute
from dreamcatcher.documents import write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    CheckResult,
    IssueComment,
    PullRequestMergeState,
    PullRequestSignal,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import (
    BlockingIssuesFinding,
    ConflictingLabelsFinding,
    GlobalCooldown,
    IssueReference,
    LabelAppliedByOtherFinding,
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
    read_dreamcatcher_daemon_status,
    read_status_report,
)
from dreamcatcher.status.report import DocumentationLink, SectionGuidance
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
def held_state(state):
    """That state directory held by a daemon with this process identifier."""
    hold_daemon_lock_for_test(path=state.lock)
    return state


def write_feed_lines(
    *, state: StateDirectory, record: AgentRoundRecord, texts: Sequence[str]
) -> None:
    """Write feed lines one minute after the round began."""
    write_feed(
        directory=state.work / ASSIGNMENT_ID,
        number=record.number,
        lines=[compose_feed_line(record=record, text=text) for text in texts],
    )


def read_report(*, state: StateDirectory):
    """Read the fixture's status report at the pinned time."""
    return read_status_report(state=state, clock=lambda: LOOKED_AT)


def read_sole_assignment_status(*, state: StateDirectory):
    """Return the only agent-assignment status in the fixture."""
    assignments = read_report(state=state).work_statuses
    assert len(assignments) == 1
    return assignments[0]


def compose_pull_request_row(
    *,
    new_posts: int = 0,
    state: PullRequestState = PullRequestState.OPEN,
    is_draft: bool = False,
    is_wrap_up_due: bool = False,
    started_round: StartedRound | None = None,
    ended_round: int | None = 1,
) -> RequestRow:
    """Return the row of the fixture's assignment with what its pull request held.

    The tick read the assignment once its first round had ended, unless the
    test says otherwise.
    """
    return compose_request_row(
        issue=13,
        agent_work_identifier=ASSIGNMENT_ID,
        ended_round=ended_round,
        finding=PullRequestFinding(
            number=PULL_REQUEST,
            state=state,
            is_draft=is_draft,
            merge_state=PullRequestMergeState.CLEAN,
            head=HEAD,
            check_result=CheckResult.PASSING,
            has_running_checks=False,
            new_posts=new_posts,
            new_pull_request_signals=[],
            is_check_failure_withheld=False,
            is_wrap_up_due=is_wrap_up_due,
        ),
        started_round=started_round,
    )


def write_tick_rows(*, state: StateDirectory, rows: list[RequestRow]) -> None:
    """Write a tick that wrote these rows."""
    write_tick(
        state=state, tick=SchedulerRecord(at=LOOKED_AT, finished=LOOKED_AT, rows=rows)
    )


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
    assert found.latest_update_finished is None
    assert found.scheduler_failures == ()
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
        guidance=SectionGuidance(
            message=(
                "Assign an issue to yourself and label it with dream:smith "
                "to create an assignment."
            ),
            documentation=None,
        ),
    )


def test_an_empty_campaign_section_says_how_to_start_a_campaign(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_daemon_run(
        state=state,
        pid=os.getpid(),
        routes=[RecordedRoute(label="dream:lead", kind=AgentWorkKind.CAMPAIGN)],
    )

    found = read_status_report(state=state, clock=lambda: LOOKED_AT)

    assert found.describe_section(
        kind=AgentWorkKind.CAMPAIGN
    ) == AgentWorkStatusSection(
        heading="campaigns",
        guidance=SectionGuidance(
            message=(
                "Assign a parent issue to yourself and label it with dream:lead "
                "to start a campaign."
            ),
            documentation=None,
        ),
    )


def test_a_section_gives_no_guidance_before_any_daemon_has_run(tmp_path):
    state = StateDirectory(root=tmp_path)

    found = read_status_report(state=state, clock=lambda: LOOKED_AT)

    assert [found.describe_section(kind=kind) for kind in AgentWorkKind] == [
        AgentWorkStatusSection(heading="assignments", guidance=None),
        AgentWorkStatusSection(heading="conversations", guidance=None),
        AgentWorkStatusSection(heading="campaigns", guidance=None),
    ]


def test_a_kind_the_daemon_does_not_route_says_how_to_route_it(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())

    found = read_status_report(state=state, clock=lambda: LOOKED_AT)

    assert found.describe_section(
        kind=AgentWorkKind.CAMPAIGN
    ) == AgentWorkStatusSection(
        heading="campaigns",
        guidance=SectionGuidance(
            message=(
                "Add a [[campaign]] route to dreamcatcher.toml and restart the "
                "daemon to enable campaigns."
            ),
            documentation=DocumentationLink(
                title="Configure a campaign route",
                url=(
                    "https://alimanfoo.github.io/dreamcatcher/start-a-campaign/"
                    "#configure-a-campaign-route"
                ),
            ),
        ),
    )


def test_the_instance_record_names_the_repository(state):
    write_text(text=f"{REPOSITORY}\n", path=state.repository)

    assert read_report(state=state).repository == REPOSITORY


def test_the_instance_records_name_the_harness_and_version(state):
    write_daemon_run(
        state=state,
        pid=os.getpid(),
        harness=AgentHarness.CODEX,
        version="3.0.0.beta1",
        max_agents=3,
    )

    found = read_report(state=state)

    assert found.daemon.preferred_harness is AgentHarness.CODEX
    assert found.daemon.dreamcatcher_version == "3.0.0.beta1"
    assert not found.daemon.is_running
    assert found.daemon.pid is None


def test_a_live_daemon_that_has_not_named_its_run_has_no_pid(tmp_path):
    state = StateDirectory(root=tmp_path)
    hold_daemon_lock_for_test(path=state.lock)

    found = read_report(state=state)

    assert found.daemon.is_running
    assert found.daemon.pid is None


def test_a_live_round_reports_work_and_its_latest_output(held_state):
    write_feed_lines(
        state=held_state,
        record=write_assignment_round(
            directory=held_state.work / ASSIGNMENT_ID, number=1, status=None
        ),
        texts=["first", "[Bash] pytest"],
    )

    found = read_report(state=held_state)
    status = found.work_statuses[0]

    assert found.daemon.pid == os.getpid()
    assert found.running_agents == 1
    assert status.value is AgentWorkStatusValue.WORKING
    assert status.detail == "round 1, start, running 1h 59m, last output 1h 58m ago"
    assert status.latest_output == "[Bash] pytest"
    assert status.hand_resume_command is None


def test_a_live_round_keeps_the_pull_request_summary_the_tick_read(held_state):
    write_assignment_round(
        directory=held_state.work / ASSIGNMENT_ID, number=1, status=None
    )
    write_tick_rows(state=held_state, rows=[compose_pull_request_row()])

    assert read_sole_assignment_status(state=held_state).pull_request_summary == "ready"


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

    round_status = read_sole_assignment_status(state=state).round_statuses[0]

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
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1, status=None)

    round_status = read_sole_assignment_status(state=state).round_statuses[0]

    assert round_status.outcome_description == outcome_description
    assert round_status.duration_description == ""


def test_status_finds_the_harness_session_and_builds_its_resume_command(tmp_path):
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

    status = read_sole_assignment_status(state=state)

    assert status.harness_session_identifier == "abc-123"
    assert status.hand_resume_command == ["claude", "--resume", "abc-123"]


def test_status_reads_harness_resume_details_only_when_requested(state, monkeypatch):
    calls = []

    def find_harness_session_identifier(assignment, /):
        calls.append(assignment)
        return "abc-123"

    monkeypatch.setattr(
        AgentWork,
        "find_harness_session_identifier",
        find_harness_session_identifier,
    )

    status = read_sole_assignment_status(state=state)

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

    status = read_sole_assignment_status(state=state)

    assert status.harness_session_identifier is None
    assert status.hand_resume_command is None


def test_a_live_round_that_has_said_nothing_reports_that(held_state):
    write_assignment_round(
        directory=held_state.work / ASSIGNMENT_ID, number=1, status=None
    )

    status = read_sole_assignment_status(state=held_state)

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
            ending=LaunchErroredAgentRoundEnding(at=PINNED, reason="git push failed"),
        ),
    )

    status = read_sole_assignment_status(state=state)

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
    write_assignment_round(
        directory=state.work / ASSIGNMENT_ID, number=1, status=round_status
    )
    write_tick_rows(state=state, rows=[compose_pull_request_row()])

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == detail


def test_a_successful_wrap_up_is_complete(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_assignment_round(
        directory=state.work / ASSIGNMENT_ID, number=2, round_input=MERGED_INPUT
    )

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.ENDED
    assert status.words == "completed"
    assert status.detail is None
    assert status.has_ended


def cancel(*, state: StateDirectory) -> None:
    """Cancel the fixture's assignment."""
    cancel_assignment(assignment=read_assignments(state=state)[0], at=PINNED)


def test_a_cancelled_assignment_has_ended(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    cancel(state=state)

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.ENDED
    assert status.words == "cancelled"
    assert status.detail is None
    assert status.has_ended


def test_a_round_still_running_after_a_cancel_is_working(held_state):
    write_assignment_round(
        directory=held_state.work / ASSIGNMENT_ID, number=1, status=None
    )
    cancel(state=held_state)

    status = read_sole_assignment_status(state=held_state)

    assert status.value is AgentWorkStatusValue.WORKING
    assert status.words == "working"
    assert not status.has_ended


def test_a_cancelled_assignment_has_ended_rather_than_being_in_fault(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1, status=1)
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=2, status=2)
    cancel(state=state)

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.ENDED


def compose_pull_request_row_with(**facts: object) -> RequestRow:
    """Return the row of the fixture's assignment, its pull request holding these."""
    row = compose_pull_request_row()
    assert row.finding is not None
    finding = PullRequestFinding.model_validate(row.finding.model_dump() | facts)
    return row.model_copy(update={"finding": finding})


@pytest.mark.parametrize(
    ("facts", "words"),
    [
        ({"is_draft": True}, "draft"),
        ({"check_result": CheckResult.NONE}, "ready"),
        (
            {"is_draft": True, "check_result": CheckResult.RUNNING},
            "draft, checks running",
        ),
        (
            {
                "merge_state": PullRequestMergeState.BEHIND,
                "check_result": CheckResult.RUNNING,
            },
            "ready, behind main, checks running",
        ),
        (
            {
                "merge_state": PullRequestMergeState.DIRTY,
                "check_result": CheckResult.FAILING,
            },
            "ready, conflicts with main, checks failing",
        ),
    ],
)
def test_an_open_assignment_reports_where_the_tick_found_its_pull_request(
    state, facts, words
):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(state=state, rows=[compose_pull_request_row_with(**facts)])

    assert read_sole_assignment_status(state=state).pull_request_summary == words


@pytest.mark.parametrize(
    ("facts", "detail"),
    [
        (
            {
                "merge_state": PullRequestMergeState.BEHIND,
                "check_result": CheckResult.FAILING,
                "is_check_failure_withheld": True,
            },
            "checks failing after two attempts",
        ),
        (
            {
                "merge_state": PullRequestMergeState.BEHIND,
                "check_result": CheckResult.FAILING,
            },
            "ready for review",
        ),
        ({"check_result": CheckResult.FAILING}, "ready for review"),
        ({"check_result": CheckResult.RUNNING}, "ready for review"),
        ({"check_result": CheckResult.NONE}, "ready for review"),
    ],
)
def test_a_ready_pull_request_with_nothing_new_says_where_it_has_got_to(
    state, facts, detail
):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(state=state, rows=[compose_pull_request_row_with(**facts)])

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == detail


def test_signals_found_by_the_tick_make_the_assignment_wait(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(
        state=state,
        rows=[
            compose_pull_request_row_with(
                new_posts=1,
                new_pull_request_signals=[
                    PullRequestSignal.OUT_OF_DATE,
                    PullRequestSignal.CHECK_FAILURE,
                ],
            )
        ],
    )

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "1 new post to answer, main moved, checks failed"


@pytest.mark.parametrize(
    ("signals", "posts", "trigger"),
    [
        ([PullRequestSignal.CHECK_FAILURE], 0, "checks failed"),
        ([PullRequestSignal.OUT_OF_DATE], 1, "1 post, main moved"),
        ([], 0, "recover"),
    ],
)
def test_a_round_says_which_signals_woke_it(state, signals, posts, trigger):
    write_assignment_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        round_input=AssignmentRoundInput(
            pull_request_state=PullRequestState.OPEN,
            pull_request_head=HEAD,
            signals=signals,
            user_posts=[IssueComment.model_validate(compose_comment())] * posts,
        ),
    )

    round_status = read_sole_assignment_status(state=state).round_statuses[0]

    assert round_status.trigger.describe() == trigger


def test_an_unreadable_round_input_fails_the_status_naming_the_file(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    (assignment,) = read_assignments(state=state)
    round_input = assignment.compose_round_paths(number=1).round_input
    round_input.write_bytes(b"not json")

    found = read_sole_assignment_status(state=state)

    with pytest.raises(ReportableError, match=re.escape(str(round_input))):
        _ = found.round_statuses


def test_a_round_with_no_input_was_the_start(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)

    round_status = read_sole_assignment_status(state=state).round_statuses[0]

    assert round_status.trigger.describe() == "start"


def test_an_assignment_the_tick_read_nothing_for_reports_no_pull_request_state(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1, status=None)
    write_tick_rows(
        state=state,
        rows=[compose_request_row(issue=13, agent_work_identifier=ASSIGNMENT_ID)],
    )

    status = read_sole_assignment_status(state=state)

    assert status.pull_request_summary is None
    assert not status.is_pull_request_ready_for_review


def test_a_cancelled_assignment_stops_reporting_its_pull_request_state(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(state=state, rows=[compose_pull_request_row()])

    cancel(state=state)

    status = read_sole_assignment_status(state=state)
    assert status.pull_request_summary is None
    assert not status.is_pull_request_ready_for_review


@pytest.mark.parametrize("status", [0, None])
def test_a_wrapped_up_assignment_reports_the_state_its_last_round_was_given(
    state, status
):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_assignment_round(
        directory=state.work / ASSIGNMENT_ID,
        number=2,
        status=status,
        round_input=MERGED_INPUT,
    )
    write_tick_rows(
        state=state,
        rows=[compose_request_row(issue=13, agent_work_identifier=ASSIGNMENT_ID)],
    )

    assert read_sole_assignment_status(state=state).pull_request_summary == "merged"


def test_an_assignment_that_has_run_no_round_waits_for_its_first(state):
    write_tick_rows(state=state, rows=[])

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "no round has run yet"
    assert not status.has_ended


def test_new_posts_found_by_the_tick_make_the_assignment_wait(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(state=state, rows=[compose_pull_request_row(new_posts=1)])

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "1 new post to answer"


@pytest.mark.parametrize("pull_request_state", ["MERGED", "CLOSED"])
def test_a_finished_pull_request_waits_for_its_wrap_up_round(state, pull_request_state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(
        state=state,
        rows=[
            compose_pull_request_row(
                state=PullRequestState(pull_request_state), is_wrap_up_due=True
            )
        ],
    )

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "awaiting wrap-up"


def test_a_failed_read_makes_the_assignment_unknown_with_the_reason(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(
        state=state,
        rows=[
            compose_request_row(
                issue=13,
                agent_work_identifier=ASSIGNMENT_ID,
                finding=ReadFailureFinding(reason="unavailable"),
            )
        ],
    )

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.UNKNOWN
    assert status.detail == "unavailable"


def test_an_assignment_before_any_update_is_unknown(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.UNKNOWN
    assert status.detail == "not seen by the latest update"


def test_a_round_ending_after_the_latest_tick_is_idle_until_the_next_update(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(
        state=state,
        rows=[
            compose_pull_request_row(
                new_posts=1, started_round=StartedRound(number=1), ended_round=None
            )
        ],
    )

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == "round 1 ended, awaiting next update"


def test_an_assignment_the_latest_update_did_not_see_is_unknown(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(state=state, rows=[])

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.UNKNOWN
    assert status.detail == "not seen by the latest update"


def test_a_later_update_replaces_the_read_that_predated_a_rounds_ending(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(
        state=state, rows=[compose_pull_request_row(is_draft=True, ended_round=None)]
    )

    awaiting_update = read_sole_assignment_status(state=state)

    assert awaiting_update.value is AgentWorkStatusValue.IDLE
    assert awaiting_update.detail == "round 1 ended, awaiting next update"
    assert awaiting_update.pull_request_summary == "draft"

    write_tick_rows(state=state, rows=[compose_pull_request_row(is_draft=True)])

    refreshed = read_sole_assignment_status(state=state)

    assert refreshed.value is AgentWorkStatusValue.IDLE
    assert refreshed.detail == "needs feedback"
    assert refreshed.pull_request_summary == "draft"


def test_a_stopped_round_ending_after_the_latest_tick_is_idle_until_the_next_update(
    state,
):
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=LOOKED_AT - timedelta(minutes=1),
            pid=1,
            ending=StoppedAgentRoundEnding(at=LOOKED_AT + timedelta(minutes=1)),
        ),
    )
    write_tick_rows(state=state, rows=[compose_pull_request_row(ended_round=None)])

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == "round 1 ended, awaiting next update"


def test_new_posts_found_while_a_round_ran_wait_after_it_ends(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(
        state=state, rows=[compose_pull_request_row(new_posts=1, ended_round=None)]
    )

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "1 new post to answer"


def test_a_ready_pull_request_with_nothing_new_is_idle_ready_for_review(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(state=state, rows=[compose_pull_request_row()])

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == "ready for review"


def test_a_draft_pull_request_with_nothing_new_is_idle_needing_feedback(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(state=state, rows=[compose_pull_request_row(is_draft=True)])

    assert read_sole_assignment_status(state=state).detail == "needs feedback"


def test_a_finished_pull_request_whose_wrap_up_round_took_its_turn_is_idle(state):
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
    write_tick_rows(
        state=state, rows=[compose_pull_request_row(state=PullRequestState.MERGED)]
    )

    status = read_sole_assignment_status(state=state)

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
    write_tick_rows(state=state, rows=[compose_pull_request_row()])

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.round_statuses[0].duration_description == "ran 4m"
    assert status.round_statuses[0].outcome_description == "stopped"


def test_two_current_errors_put_an_assignment_in_fault(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1, status=1)
    write_feed_lines(
        state=state,
        record=write_assignment_round(
            directory=state.work / ASSIGNMENT_ID, number=2, status=2
        ),
        texts=["[failed] You hit your spend cap."],
    )

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.FAULT
    assert status.detail == "round 2 errored (exit 2)"
    assert status.latest_output == "[failed] You hit your spend cap."
    assert not status.has_ended


def test_a_fault_with_no_output_names_the_latest_round_ending(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1, status=1)
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=2, status=2)

    status = read_sole_assignment_status(state=state)

    assert status.detail == "round 2 errored (exit 2)"
    assert status.latest_output is None


def test_an_elapsed_cooldown_clears_the_fault_and_the_cooldown(state):
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1, status=1)
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=2, status=2)
    ended = PINNED + timedelta(minutes=15)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            cooldown=GlobalCooldown(started=PINNED, ends=ended),
        ),
    )

    found = read_report(state=state)

    assert found.work_statuses[0].value is AgentWorkStatusValue.WAITING
    assert found.active_global_cooldown is None


def test_an_active_cooldown_is_an_instance_fact_and_failures_are_listed(held_state):
    cooldown = GlobalCooldown(started=PINNED, ends=LOOKED_AT + timedelta(minutes=1))
    write_tick(
        state=held_state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            failures=["could not start assignment", "could not read comments for GH8"],
            cooldown=cooldown,
        ),
    )

    found = read_report(state=held_state)

    assert found.latest_update_finished == PINNED
    assert found.scheduler_failures == (
        "could not start assignment",
        "could not read comments for GH8",
    )
    assert found.daemon.max_agents == 3
    assert found.active_global_cooldown == cooldown
    assert found.instance_facts == (
        StatusFact(label="preferred harness", value="claude"),
        StatusFact(label="next update", value="updating", is_in_progress=True),
        StatusFact(label="agent capacity", value="0 of 3 working"),
        StatusFact(label="global cooldown", value="ends in 1m", is_warning=True),
    )


def read_next_update(*, state: StateDirectory) -> StatusFact | None:
    """Return the next-update fact of the fixture's status report, if it has one."""
    facts = read_report(state=state).instance_facts
    return next((fact for fact in facts if fact.label == "next update"), None)


def test_the_countdown_runs_from_when_the_last_update_finished(held_state):
    write_tick(
        state=held_state,
        tick=SchedulerRecord(
            at=LOOKED_AT - timedelta(seconds=200),
            finished=LOOKED_AT - timedelta(seconds=80),
        ),
    )

    assert read_next_update(state=held_state) == StatusFact(
        label="next update", value="in 40s"
    )


def test_an_update_is_running_once_the_countdown_runs_out(held_state):
    write_tick(
        state=held_state,
        tick=SchedulerRecord(
            at=LOOKED_AT - timedelta(seconds=130),
            finished=LOOKED_AT - timedelta(seconds=DEFAULT_INTERVAL_SECONDS),
        ),
    )

    assert read_next_update(state=held_state) == StatusFact(
        label="next update", value="updating", is_in_progress=True
    )


def test_an_update_is_running_before_the_daemon_runs_first_finishes(held_state):
    assert read_next_update(state=held_state) == StatusFact(
        label="next update", value="updating", is_in_progress=True
    )


def test_an_earlier_daemon_runs_update_counts_nothing_down(held_state):
    write_tick(
        state=held_state,
        tick=SchedulerRecord(
            at=LOOKED_AT - timedelta(seconds=20),
            finished=LOOKED_AT - timedelta(seconds=10),
        ),
    )
    write_daemon_run(
        state=held_state,
        pid=os.getpid(),
        started=LOOKED_AT - timedelta(seconds=5),
    )

    assert read_next_update(state=held_state) == StatusFact(
        label="next update", value="updating", is_in_progress=True
    )


def test_a_stopped_daemon_has_no_next_update(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT - timedelta(seconds=20),
            finished=LOOKED_AT - timedelta(seconds=10),
        ),
    )

    assert read_next_update(state=state) is None


def test_a_stopped_daemon_has_no_current_scheduler_failures(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED, finished=PINNED, failures=["could not start assignment"]
        ),
    )

    assert read_report(state=state).scheduler_failures == ()


def test_a_blocked_request_names_its_claims_and_blockers_as_numbers(state):
    blocked = compose_request_row(
        issue=20,
        finding=StartTimeFinding(
            linked_pull_requests=[28],
            blocking_issues=[IssueReference(number=10), IssueReference(number=11)],
        ),
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[blocked],
        ),
    )

    [request] = read_report(state=state).request_statuses

    assert request == RequestStatus(
        row=blocked,
        value=RequestStatusValue.BLOCKED,
        reasons=(
            RequestReason(words="claimed by", pull_requests=(28,)),
            RequestReason(
                words="blocked by",
                issues=(IssueReference(number=10), IssueReference(number=11)),
            ),
        ),
    )


def test_a_campaign_request_names_the_issues_that_block_its_parent(state):
    blocked = compose_request_row(
        issue=20,
        kind=AgentWorkKind.CAMPAIGN,
        finding=BlockingIssuesFinding(
            blocking_issues=[
                IssueReference(number=10),
                IssueReference(number=1016, repository="alimanfoo/dream"),
            ]
        ),
    )
    write_tick(
        state=state, tick=SchedulerRecord(at=PINNED, finished=PINNED, rows=[blocked])
    )

    [request] = read_report(state=state).request_statuses

    assert request == RequestStatus(
        row=blocked,
        value=RequestStatusValue.BLOCKED,
        reasons=(
            RequestReason(
                words="blocked by",
                issues=(
                    IssueReference(number=10),
                    IssueReference(number=1016, repository="alimanfoo/dream"),
                ),
            ),
        ),
    )


def test_a_request_that_an_open_pull_request_claims_is_blocked(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[
                compose_request_row(
                    issue=20,
                    finding=StartTimeFinding(
                        linked_pull_requests=[28], blocking_issues=[]
                    ),
                )
            ],
        ),
    )

    [request] = read_report(state=state).request_statuses

    assert request.value is RequestStatusValue.BLOCKED
    assert request.reasons == (RequestReason(words="claimed by", pull_requests=(28,)),)


def test_an_assignment_whose_pull_request_is_not_yet_open_waits_for_it(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13, pull_request=None)
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1)
    write_tick_rows(
        state=state,
        rows=[
            compose_request_row(
                issue=13, agent_work_identifier=ASSIGNMENT_ID, ended_round=1
            )
        ],
    )

    status = read_sole_assignment_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "no pull request yet"


def test_a_request_nothing_claims_or_blocks_is_available(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[compose_request_row(issue=20, finding=UNCLAIMED)],
        ),
    )

    [request] = read_report(state=state).request_statuses

    assert request.value is RequestStatusValue.AVAILABLE
    assert request.reasons == (RequestReason(words="available"),)


def test_two_labels_of_one_kind_are_a_routing_conflict_named_in_each_row(state):
    conflict = ConflictingLabelsFinding(labels=["dream:less", ASSIGNMENT_LABEL])
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[
                compose_request_row(issue=20, label="dream:less", finding=conflict),
                compose_request_row(issue=20, finding=conflict),
            ],
        ),
    )

    requests = read_report(state=state).request_statuses

    assert [(request.row.dispatch_label, request.value) for request in requests] == [
        ("dream:less", RequestStatusValue.ROUTING_CONFLICT),
        (ASSIGNMENT_LABEL, RequestStatusValue.ROUTING_CONFLICT),
    ]
    assert requests[0].reasons == (
        RequestReason(words="multiple assignment labels: dream:less, dream:smith"),
    )


def test_a_request_whose_label_someone_else_applied_is_held_naming_them(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[
                compose_request_row(
                    issue=20, finding=LabelAppliedByOtherFinding(applier="colleague")
                )
            ],
        ),
    )

    [request] = read_report(state=state).request_statuses

    assert request.value is RequestStatusValue.HELD
    assert request.reasons == (
        RequestReason(
            words="label applied by colleague: remove and re-add it yourself"
        ),
    )


def test_a_request_whose_read_failed_is_unknown_with_the_reason(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[
                compose_request_row(
                    issue=20, finding=ReadFailureFinding(reason="gh: offline")
                )
            ],
        ),
    )

    [request] = read_report(state=state).request_statuses

    assert request.value is RequestStatusValue.UNKNOWN
    assert request.reasons == (RequestReason(words="gh: offline"),)


def test_a_request_that_led_to_open_work_is_reported_through_its_work(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[
                compose_request_row(
                    issue=13, agent_work_identifier=ASSIGNMENT_ID, finding=UNCLAIMED
                )
            ],
        ),
    )

    assert read_report(state=state).request_statuses == []


def test_a_request_that_open_work_answers_before_the_tick_ends_is_hidden(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[compose_request_row(issue=13, finding=UNCLAIMED)],
        ),
    )

    report = read_report(state=state)

    assert report.request_statuses == []
    assert [status.work.identifier for status in report.work_statuses] == [
        ASSIGNMENT_ID
    ]


def test_a_request_at_an_issue_whose_work_ended_still_shows(state):
    cancel_assignment(assignment=read_assignments(state=state)[0], at=PINNED)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[compose_request_row(issue=13, finding=UNCLAIMED)],
        ),
    )

    [request] = read_report(state=state).request_statuses

    assert request.row.issue == 13


def test_requests_keep_the_order_the_tick_saw_them_in(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[
                compose_request_row(issue=21, finding=UNCLAIMED),
                compose_request_row(issue=20, finding=UNCLAIMED),
            ],
        ),
    )

    requests = read_report(state=state).request_statuses

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
        status.work.identifier for status in read_report(state=state).work_statuses
    ]

    assert identifiers == [
        "GH9-20260819-184158-assignment",
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
    write_assignment_round(directory=state.work / ASSIGNMENT_ID, number=1, status=None)

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

    found = read_report(state=state)

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


def test_active_assignments_give_no_guidance_after_their_routes_are_removed(state):
    write_daemon_run(state=state, pid=os.getpid(), routes=[])

    found = read_report(state=state)

    assert found.describe_section(
        kind=AgentWorkKind.ASSIGNMENT
    ) == AgentWorkStatusSection(heading="assignments", guidance=None)


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
                started=PINNED,
                preferred_harness=AgentHarness.CLAUDE,
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
