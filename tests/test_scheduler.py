"""Scheduling decisions and launch operations."""

import json
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from clocks import PINNED, Ticking
from conftest import (
    FILED,
    LATER,
    POST_LIST_PATHS,
    POSTED_AT,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    comment,
    configure,
    git,
    listing,
    pages,
    pull_request,
    pull_requests,
)
from fakes import Line
from pydantic import ValidationError
from records import write_assignment, write_round

from dreamcatcher.agent_assignments import (
    PullRequestObservation,
    read_assignments,
    request_assignment_retry,
)
from dreamcatcher.agent_rounds import (
    AgentRoundPurpose,
    AgentRoundRecord,
    AssignmentRoundPurpose,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    compose_agent_round_ending,
)
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    add_worktree,
    fetch_main,
    make_empty_commit,
    push_branch,
)
from dreamcatcher.github import PullRequestState
from dreamcatcher.prompts import RECOVERY_PROMPT
from dreamcatcher.scheduler import AssignmentScheduler, ConversationScheduler, Scheduler
from dreamcatcher.scheduler.models import (
    AgentWorkObservation,
    GlobalCooldown,
    IssueFact,
    IssueFactValue,
    SchedulerRecord,
    derive_issue_availability,
)
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158"
SECOND_ASSIGNMENT_ID = "GH14-20260819-184158"
PURPOSE = AssignmentRoundPurpose.IMPLEMENT
STILL_RUNNING = 30
CREATED_ASSIGNMENT_ID = "GH8-20260819-184158"
CONVERSATION = POST_LIST_PATHS["conversation"]
HARNESS_SESSION_IDENTIFIER = "abc-123"


def observed_assignment(
    *,
    identifier: str,
    issue: int,
    evidence: str,
    value: IssueFactValue = IssueFactValue.TRUE,
) -> AgentWorkObservation:
    return AgentWorkObservation(
        identifier=identifier,
        issue=issue,
        requires_round=IssueFact(value=value, evidence=evidence),
    )


CREATED_SCHEDULERS: list[Scheduler] = []


@pytest.fixture(autouse=True)
def stop_scheduler_rounds():
    """Stop every round that a scheduler test started."""
    yield
    for scheduler in CREATED_SCHEDULERS:
        for running in scheduler.rounds.values():
            running.interrupt()
    CREATED_SCHEDULERS.clear()


def create_scheduler(*, root, max_agents: int = 1) -> tuple[Scheduler, Ticking]:
    """Create a scheduler and a clock that advances between explicit ticks."""
    clock = Ticking(step=300)
    config = read_dreamcatcher_config(root=root)
    state = StateDirectory(root=root)
    assignments = AssignmentScheduler(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=config,
        state=state,
        requested_harness=AgentHarness.CLAUDE,
        clock=clock,
    )
    conversations = ConversationScheduler(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=config,
        state=state,
        requested_harness=AgentHarness.CLAUDE,
        clock=clock,
    )
    scheduler = Scheduler(
        assignments=assignments,
        conversations=conversations,
        rounds={},
        max_agents=max_agents,
    )
    CREATED_SCHEDULERS.append(scheduler)
    return scheduler, clock


def finish_rounds(*, scheduler) -> None:
    """Wait for every round that the scheduler has started."""
    for running in list(scheduler.rounds.values()):
        running.wait()


def held(*, observed: SchedulerRecord) -> str:
    """Return why the scheduler launched nothing in one tick."""
    assert observed.hold is not None
    return observed.hold


def observed_issues(*, tick: SchedulerRecord) -> list[int]:
    """Return the issue numbers that one tick observed in dispatch order."""
    return [observation.issue for observation in tick.issue_observations]


def availability_values(*, tick: SchedulerRecord) -> list[IssueFactValue]:
    """Return each observed issue's availability in dispatch order."""
    return [
        derive_issue_availability(observation=observation).value
        for observation in tick.issue_observations
    ]


def record_of(*, scheduler: Scheduler, number: int) -> AgentRoundRecord:
    """Return what the assignment's numbered round recorded."""
    return AgentRoundRecord.model_validate_json(
        written_round(scheduler=scheduler, number=number, name="round.json")
    )


def purpose_of(*, scheduler: Scheduler, number: int) -> AgentRoundPurpose:
    """What work the assignment's numbered round advances."""
    return record_of(scheduler=scheduler, number=number).purpose


@pytest.fixture
def resuming(cloned, gh, harnesses):
    """A checkout holding one assignment, with no labelled issue awaiting one."""
    configure(root=cloned)
    harnesses["claude"].streams(
        lines=[
            Line(
                text=json.dumps(
                    {
                        "type": "system",
                        "subtype": "init",
                        "model": "claude-opus-5",
                        "session_id": HARNESS_SESSION_IDENTIFIER,
                    }
                )
                + "\n"
            ),
            Line(text="what the round said\n"),
        ]
    )
    write_assignment(
        state=StateDirectory(root=cloned),
        identifier=ASSIGNMENT_ID,
        issue=13,
        harness_session_identifier=HARNESS_SESSION_IDENTIFIER,
    )
    return cloned


def ran(
    *,
    root,
    number: int,
    purpose: AssignmentRoundPurpose,
    status: int | None = 0,
    is_recovery: bool = False,
) -> None:
    """Write down a round of the assignment on disk, ended as the status says.

    Every one of them runs the hour before the pinned clock reads unless the
    test needs an explicit ending time.
    """
    started = PINNED.replace(hour=17, minute=number)
    ending = (
        None
        if status is None
        else compose_agent_round_ending(at=started, status=status)
    )
    write_round(
        directory=StateDirectory(root=root).assignments / ASSIGNMENT_ID,
        number=number,
        record=AgentRoundRecord(
            number=number,
            purpose=purpose,
            is_recovery=is_recovery,
            started=started,
            pid=1,
            ending=ending,
        ),
    )


def write_faulted_assignment(*, root, identifier: str, issue: int) -> None:
    """Write an assignment whose two latest rounds both exited with errors."""
    write_assignment(
        state=StateDirectory(root=root), identifier=identifier, issue=issue
    )
    directory = StateDirectory(root=root).assignments / identifier
    for number, status in ((1, 1), (2, 2)):
        started = PINNED.replace(hour=17, minute=number)
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                purpose=PURPOSE,
                is_recovery=number == 2,
                started=started,
                pid=1,
                ending=compose_agent_round_ending(at=started, status=status),
            ),
        )


def written_round(*, scheduler: Scheduler, number: int, name: str) -> str:
    """What the assignment's round wrote into the file of that name."""
    directory = (
        scheduler.assignments.state.assignments / ASSIGNMENT_ID / "rounds" / str(number)
    )
    return (directory / name).read_text(encoding="utf-8")


def forget_harness_session_identifier(*, root) -> None:
    """Remove the harness session identifier from the assignment's record."""
    state = StateDirectory(root=root)
    assignment = read_assignments(state=state)[0]
    write_json(
        document=assignment.record.model_copy(
            update={"harness_session_identifier": None}
        ),
        path=assignment.directory / "assignment.json",
    )


def test_a_tick_assigns_the_oldest_issue_nothing_stands_in_the_way_of(
    ready_repo, harnesses
):
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assignment = scheduler.assignments.state.assignments / CREATED_ASSIGNMENT_ID
    assert (
        scheduler.assignments.state.worktrees / CREATED_ASSIGNMENT_ID / "README.md"
    ).exists()
    assert (assignment / "assignment.json").exists()
    assert observed.issue_observations[0].observed_at == observed.at
    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    assert (
        harnesses["claude"].calls[0].directory
        == (scheduler.assignments.state.worktrees / CREATED_ASSIGNMENT_ID).resolve()
    )


def test_a_new_assignments_round_records_what_caused_it_and_what_it_said(
    ready_repo,
):
    scheduler, clock = create_scheduler(root=ready_repo)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    written = (
        scheduler.assignments.state.assignments / CREATED_ASSIGNMENT_ID / "rounds" / "1"
    )
    assert (
        AgentRoundRecord.model_validate_json(
            (written / "round.json").read_text(encoding="utf-8")
        ).purpose
        is AssignmentRoundPurpose.IMPLEMENT
    )
    assert "what the round said" in (written / "feed.txt").read_text(encoding="utf-8")
    assignment = read_assignments(state=scheduler.assignments.state)[0]
    assert assignment.record.harness_session_identifier == "abc-123"


def test_a_tick_fills_free_capacity_with_available_issues(ready_repo, offered):
    offered.replies(
        stdout=listing(issues=[(8, FILED), (9, LATER), (10, "2026-08-21T01:00:00Z")]),
        to="issue list",
    )
    scheduler, clock = create_scheduler(root=ready_repo, max_agents=2)

    observed = scheduler.tick(at=clock())

    assert observed_issues(tick=observed) == [8, 9, 10]
    assert availability_values(tick=observed) == [
        IssueFactValue.TRUE,
        IssueFactValue.TRUE,
        IssueFactValue.TRUE,
    ]
    assert observed.launched_agent_work_identifiers == [
        CREATED_ASSIGNMENT_ID,
        "GH9-20260819-184158",
    ]
    assert observed.hold == "at cap: 2 of 2 agents running"
    assert (scheduler.assignments.state.worktrees / "GH9-20260819-184158").exists()
    assert not (scheduler.assignments.state.worktrees / "GH10-20260819-184158").exists()


def test_a_later_failed_launch_keeps_the_rounds_already_started(
    ready_repo, offered, monkeypatch
):
    offered.replies(
        stdout=listing(
            issues=[
                (8, FILED),
                (9, LATER),
                (10, "2026-08-21T01:00:00Z"),
            ]
        ),
        to="issue list",
    )
    scheduler, clock = create_scheduler(root=ready_repo, max_agents=3)
    launch_assignment = scheduler.assignments.launch

    def fail_second_launch(self, *, request):
        if request.candidate.issue == 9:
            raise ReportableError("could not create an assignment for GH9")
        return launch_assignment(request=request)

    monkeypatch.setattr(AssignmentScheduler, "launch", fail_second_launch)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    assert observed.hold == "could not create an assignment for GH9"
    assert not (scheduler.assignments.state.worktrees / "GH10-20260819-184158").exists()


def test_a_second_tick_judges_an_assigned_issue_handled(ready_repo):
    scheduler, clock = create_scheduler(root=ready_repo, max_agents=2)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert observed_issues(tick=observed) == [8]
    assert observed.issue_observations[0].claimed_here.value is IssueFactValue.TRUE
    assert availability_values(tick=observed) == [IssueFactValue.FALSE]


def test_a_completed_assignment_releases_its_issue(ready_repo):
    state = StateDirectory(root=ready_repo)
    assignment = write_assignment(
        state=state,
        identifier="GH8-20260818-184158",
        issue=8,
    )
    write_round(
        directory=assignment,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AssignmentRoundPurpose.WRAP_UP,
            is_recovery=False,
            started=PINNED,
            pid=1,
            ending=compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed_issues(tick=observed) == [8]
    assert availability_values(tick=observed) == [IssueFactValue.TRUE]
    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]


def test_a_tick_at_the_cap_says_the_cap_is_what_each_assignment_waits_on(
    ready_repo, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    scheduler, clock = create_scheduler(root=ready_repo)

    scheduler.tick(at=clock())
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(
        root=ready_repo,
        number=1,
        purpose=AssignmentRoundPurpose.IMPLEMENT,
        status=1,
    )
    observed = scheduler.tick(at=clock())

    # The first tick assigned issue 8, and its round is what fills the cap,
    # so the assignment already on disk is the one the cap holds.
    assert observed.assignment_observations == [
        observed_assignment(
            identifier=ASSIGNMENT_ID,
            issue=13,
            evidence="round 1 errored, to recover",
        )
    ]


def test_a_tick_at_the_cap_leaves_a_wound_up_assignment_waiting_on_nothing(
    ready_repo, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(
        root=ready_repo,
        number=1,
        purpose=AssignmentRoundPurpose.IMPLEMENT,
    )
    ran(root=ready_repo, number=1, purpose=AssignmentRoundPurpose.WRAP_UP)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.assignment_observations == []


def test_a_tick_at_the_cap_refreshes_the_candidates(ready_repo, offered, harnesses):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    offered.replies(stdout=listing(issues=[(8, FILED), (9, LATER)]), to="issue list")
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.hold == "at cap: 1 of 1 agents running"
    assert observed_issues(tick=observed) == [8, 9]
    assert availability_values(tick=observed) == [
        IssueFactValue.FALSE,
        IssueFactValue.TRUE,
    ]


def test_a_tick_at_the_cap_records_a_candidate_listing_failure(
    ready_repo, offered, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(
        root=ready_repo,
        number=1,
        purpose=AssignmentRoundPurpose.IMPLEMENT,
    )
    scheduler, clock = create_scheduler(root=ready_repo)
    scheduler.tick(at=clock())
    offered.fails(stderr="gh: could not connect to github.com", to="issue list")
    observed = scheduler.tick(at=clock())

    hold = held(observed=observed)
    assert hold.startswith(
        "at cap: 1 of 1 agents running; could not list issues for dream:smith: "
    )
    assert "could not connect" in hold
    assert observed_issues(tick=observed) == [8, 13]
    assert all(
        observation.claimed_here.value is IssueFactValue.TRUE
        for observation in observed.issue_observations
    )
    assert all(
        observation.is_open.value is IssueFactValue.UNKNOWN
        for observation in observed.issue_observations
    )
    assert observed.assignment_observations == [
        observed_assignment(
            identifier=ASSIGNMENT_ID,
            issue=13,
            evidence="no round required",
            value=IssueFactValue.FALSE,
        )
    ]


def test_a_tick_with_nothing_eligible_starts_no_assignment(ready_repo, offered):
    offered.replies(
        stdout=pages(items=[{"number": 7, "state": "open"}]),
        to="api",
    )
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert observed_issues(tick=observed) == [8]
    assert observed.issue_observations[0].blocked.value is IssueFactValue.TRUE
    assert availability_values(tick=observed) == [IssueFactValue.FALSE]
    assert not scheduler.assignments.state.worktrees.exists()


def test_one_errored_round_receives_an_ordinary_recovery(ready_repo):
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(root=ready_repo, number=1, purpose=PURPOSE, status=1)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert observed.cooldown is None
    assert not (scheduler.assignments.state.worktrees / CREATED_ASSIGNMENT_ID).exists()


def test_one_faulted_assignment_does_not_block_unrelated_work(ready_repo):
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(root=ready_repo, number=1, purpose=PURPOSE, status=1)
    ran(root=ready_repo, number=2, purpose=PURPOSE, status=1, is_recovery=True)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    assert observed.assignment_observations == [
        observed_assignment(
            identifier=ASSIGNMENT_ID,
            issue=13,
            evidence="in fault",
            value=IssueFactValue.FALSE,
        ),
        observed_assignment(
            identifier=CREATED_ASSIGNMENT_ID,
            issue=8,
            evidence="round 1 started",
            value=IssueFactValue.FALSE,
        ),
    ]


def test_a_user_retry_clears_one_fault_and_starts_recovery(ready_repo):
    write_faulted_assignment(root=ready_repo, identifier=ASSIGNMENT_ID, issue=13)
    state = StateDirectory(root=ready_repo)
    assignment = read_assignments(state=state)[0]
    request_assignment_retry(assignment=assignment, at=PINNED)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert observed.assignment_observations == [
        observed_assignment(
            identifier=ASSIGNMENT_ID,
            issue=13,
            evidence="round 3 started",
            value=IssueFactValue.FALSE,
        )
    ]


def test_a_successful_round_breaks_the_error_sequence(ready_repo):
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(root=ready_repo, number=1, purpose=PURPOSE, status=1)
    ran(root=ready_repo, number=2, purpose=PURPOSE)
    ran(root=ready_repo, number=3, purpose=PURPOSE, status=1)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]


def test_an_assignment_the_scheduler_is_running_a_round_for_is_not_waiting(
    ready_repo, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    scheduler, clock = create_scheduler(root=ready_repo, max_agents=2)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    # The round the scheduler held recorded no ending, so the assignment would have
    # read as interrupted had the scheduler not been running it.
    written = (
        scheduler.assignments.state.assignments
        / CREATED_ASSIGNMENT_ID
        / "rounds"
        / "1"
        / "round.json"
    )
    assert (
        AgentRoundRecord.model_validate_json(written.read_text(encoding="utf-8")).ending
        is None
    )
    assert observed.assignment_observations == []


def test_an_ended_round_is_inspected_while_its_runner_finishes(tmp_path, monkeypatch):
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    directory = write_assignment(
        state=state,
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=PURPOSE,
            started=PINNED,
            pid=1,
            ending=compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    assignment = read_assignments(state=state)[0]
    inspected = Mock()
    monkeypatch.setattr(
        "dreamcatcher.scheduler.assignments.AssignmentScheduler._inspect_assignment",
        lambda _scheduler, **_arguments: inspected,
    )
    scheduler, _ = create_scheduler(root=tmp_path, max_agents=2)
    scheduler.rounds[ASSIGNMENT_ID] = Mock(is_alive=True)

    results = scheduler.assignments._inspect_assignments(
        assignments=[assignment],
        most_recent_cooldown_ended=None,
        observed_at=PINNED,
    )

    assert results == [inspected]


def test_a_round_that_replaces_a_finishing_runner_is_reported(resuming, gh):
    ran(root=resuming, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming, max_agents=2)
    scheduler.rounds[ASSIGNMENT_ID] = Mock(is_alive=True)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    finish_rounds(scheduler=scheduler)


def test_an_assignment_with_an_open_pull_request_and_nothing_new_is_not_waiting(
    resuming, gh
):
    ran(root=resuming, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    issue = json.loads(listing(issues=[(13, FILED)]))[0]
    gh.replies(stdout=json.dumps(issue), to="issue view")
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert observed.assignment_observations == [
        observed_assignment(
            identifier=ASSIGNMENT_ID,
            issue=13,
            evidence="no round required",
            value=IssueFactValue.FALSE,
        )
    ]
    assignment = read_assignments(state=scheduler.assignments.state)[0]
    assert assignment.record.title == "Issue 13"
    assert assignment.record.pull_request_observation == PullRequestObservation(
        state=PullRequestState.OPEN,
        is_draft=False,
        observed_at=PINNED,
    )


def test_an_assignment_that_has_run_no_round_at_all_gets_its_first(ready_repo):
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    first = record_of(scheduler=scheduler, number=1)
    assert first.number == 1
    assert first.purpose is AssignmentRoundPurpose.IMPLEMENT
    assert not first.is_recovery
    assert written_round(scheduler=scheduler, number=1, name="prompt.txt") == (
        "/dream:smith GH13"
    )


def test_a_dispatch_whose_round_will_not_start_retries_the_prepared_assignment(
    ready_repo, offered
):
    # A file where the assignment's rounds go, so no round can record its start.
    occupied = (
        StateDirectory(root=ready_repo).assignments / CREATED_ASSIGNMENT_ID / "rounds"
    )
    occupied.parent.mkdir(parents=True)
    occupied.write_text("something else is here\n", encoding="utf-8")
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert "cannot write" in held(observed=observed)
    assert observed_issues(tick=observed) == [8]
    assert availability_values(tick=observed) == [IssueFactValue.TRUE]
    assert (scheduler.assignments.state.worktrees / CREATED_ASSIGNMENT_ID).exists()
    branch = f"dreamcatcher-{CREATED_ASSIGNMENT_ID}"
    assert branch in git(arguments=["branch", "--list", branch], cwd=ready_repo)

    occupied.unlink()
    offered.replies(
        stdout=json.dumps(
            {
                "number": 8,
                "title": "The issue title",
                "closedByPullRequestsReferences": [{"number": PULL_REQUEST}],
            }
        ),
        to="issue view",
    )
    offered.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    record = (
        scheduler.assignments.state.assignments / CREATED_ASSIGNMENT_ID / "rounds" / "1"
    )
    written = AgentRoundRecord.model_validate_json(
        (record / "round.json").read_text(encoding="utf-8")
    )
    assert written.purpose is AssignmentRoundPurpose.IMPLEMENT
    created = [call for call in offered.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == 1


@pytest.mark.parametrize("checkpoint", ["worktree", "commit", "push", "pull request"])
def test_the_next_tick_recovers_each_incomplete_creation_checkpoint(
    ready_repo, offered, checkpoint
):
    state = StateDirectory(root=ready_repo)
    branch = f"dreamcatcher-{CREATED_ASSIGNMENT_ID}"
    worktree = state.worktrees / CREATED_ASSIGNMENT_ID
    fetch_main(root=ready_repo)
    add_worktree(root=ready_repo, path=worktree, branch=branch)
    if checkpoint != "worktree":
        make_empty_commit(worktree=worktree, message="GH8")
    if checkpoint in {"push", "pull request"}:
        push_branch(root=ready_repo, branch=branch)
    if checkpoint == "pull request":
        offered.replies(
            stdout=json.dumps(
                {
                    "number": 8,
                    "title": "The issue title",
                    "closedByPullRequestsReferences": [{"number": PULL_REQUEST}],
                }
            ),
            to="issue view",
        )
        offered.replies(
            stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list"
        )
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    round_record = state.assignments / CREATED_ASSIGNMENT_ID / "rounds" / "1"
    assert (
        AgentRoundRecord.model_validate_json(
            (round_record / "round.json").read_text(encoding="utf-8")
        ).purpose
        is AssignmentRoundPurpose.IMPLEMENT
    )
    assert len(list(state.assignments.iterdir())) == 1
    commits = git(arguments=["rev-list", "--count", "origin/main..HEAD"], cwd=worktree)
    assert commits.strip() == "1"
    remote = git(arguments=["ls-remote", "--heads", "origin", branch], cwd=ready_repo)
    assert f"refs/heads/{branch}" in remote
    created = [call for call in offered.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == (0 if checkpoint == "pull request" else 1)


def test_a_tick_records_an_incomplete_setup_failure(ready_repo):
    state = StateDirectory(root=ready_repo)
    fetch_main(root=ready_repo)
    add_worktree(
        root=ready_repo,
        path=state.worktrees / CREATED_ASSIGNMENT_ID,
        branch="some-other-branch",
    )
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    setup_failure = observed.issue_observations[0].setup_failure

    assert observed.launched_agent_work_identifiers == []
    assert setup_failure is not None
    assert "some-other-branch, not dreamcatcher" in setup_failure


def test_an_assignment_with_a_round_that_has_no_ending_starts_nothing(resuming):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(number=1, started=PINNED, pid=1, purpose=PURPOSE),
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert observed.assignment_observations == []
    assert not (
        scheduler.assignments.state.assignments
        / ASSIGNMENT_ID
        / "rounds"
        / "2"
        / "inbox.json"
    ).exists()


def test_a_resume_recovers_the_harness_session_from_the_first_rounds_raw_stream(
    resuming, harnesses
):
    ran(root=resuming, number=1, purpose=PURPOSE, status=1)
    forget_harness_session_identifier(root=resuming)
    raw = (
        StateDirectory(root=resuming).assignments
        / ASSIGNMENT_ID
        / "rounds"
        / "1"
        / "raw.jsonl"
    )
    write_text(
        text=(
            "a warning before the event\n"
            + json.dumps(
                {
                    "type": "system",
                    "subtype": "init",
                    "model": "claude-opus-5",
                    "session_id": HARNESS_SESSION_IDENTIFIER,
                }
            )
            + "\n"
        ),
        path=raw,
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assignment = read_assignments(state=scheduler.assignments.state)[0]
    assert assignment.record.harness_session_identifier == HARNESS_SESSION_IDENTIFIER
    assert harnesses["claude"].calls[-1].arguments[-2:] == [
        "--resume",
        HARNESS_SESSION_IDENTIFIER,
    ]


def test_a_recovery_without_a_harness_session_starts_a_new_first_round(
    resuming, harnesses
):
    ran(root=resuming, number=1, purpose=PURPOSE, status=1)
    forget_harness_session_identifier(root=resuming)
    harnesses["claude"].streams(lines=[], status=1)
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    faulted = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert written_round(scheduler=scheduler, number=2, name="prompt.txt") == (
        f"/dream:smith GH13\n\n{RECOVERY_PROMPT}"
    )
    assert "--resume" not in harnesses["claude"].calls[-1].arguments
    recovered = record_of(scheduler=scheduler, number=2)
    assert recovered.is_recovery
    assert faulted.assignment_observations == [
        observed_assignment(
            identifier=ASSIGNMENT_ID,
            issue=13,
            evidence="in fault",
            value=IssueFactValue.FALSE,
        )
    ]


def test_a_follow_up_without_a_harness_session_still_needs_its_session(
    resuming, gh, harnesses
):
    ran(root=resuming, number=1, purpose=PURPOSE)
    forget_harness_session_identifier(root=resuming)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert held(observed=observed) == (
        f"Could not resume {ASSIGNMENT_ID}: its first round did not report a "
        "harness session identifier."
    )
    assert harnesses["claude"].calls == []


def test_a_terminal_recovery_without_a_session_receives_wrap_up_input(
    resuming, gh, harnesses
):
    ran(root=resuming, number=1, purpose=PURPOSE, status=1)
    forget_harness_session_identifier(root=resuming)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    prompt = written_round(scheduler=scheduler, number=2, name="prompt.txt")
    assert prompt.startswith("/dream:smith GH13\n\nPR-inbox prompt")
    inbox = json.loads(written_round(scheduler=scheduler, number=2, name="inbox.json"))
    assert inbox["pull_request_state"] == PullRequestState.MERGED
    assert "--resume" not in harnesses["claude"].calls[-1].arguments
    assignment = read_assignments(state=scheduler.assignments.state)[0]
    assert assignment.user_post_delivery_cursor == POSTED_AT


def test_a_failed_replacement_session_does_not_redeliver_recorded_feedback(
    resuming, gh, harnesses
):
    ran(root=resuming, number=1, purpose=PURPOSE, status=1)
    forget_harness_session_identifier(root=resuming)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    harnesses["claude"].streams(lines=[], status=1)
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    assignment = read_assignments(state=scheduler.assignments.state)[0]
    assert assignment.user_post_delivery_cursor == POSTED_AT
    ending = assignment.rounds[-1].ending
    assert isinstance(ending, ErroredAgentRoundEnding)
    request_assignment_retry(
        assignment=assignment,
        at=ending.at + timedelta(seconds=1),
    )

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    inbox = json.loads(written_round(scheduler=scheduler, number=3, name="inbox.json"))
    assert inbox["user_posts"] == []


def test_a_carried_on_round_records_recovery_independently(resuming):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=PURPOSE,
            ending=InterruptedAgentRoundEnding(),
        ),
    )
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    recovered = record_of(scheduler=scheduler, number=2)
    assert recovered.purpose is AssignmentRoundPurpose.IMPLEMENT
    assert recovered.is_recovery


def test_an_assignment_the_user_has_posted_on_is_told_what_they_said(resuming, gh):
    ran(root=resuming, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    feedback = record_of(scheduler=scheduler, number=2)
    assert feedback.purpose is AssignmentRoundPurpose.ADDRESS_FEEDBACK
    assert not feedback.is_recovery
    inbox = json.loads(written_round(scheduler=scheduler, number=2, name="inbox.json"))
    assert inbox["pull_request_state"] == "OPEN"
    assert [post["kind"] for post in inbox["user_posts"]] == ["comment"]
    assert str(
        scheduler.assignments.state.assignments
        / ASSIGNMENT_ID
        / "rounds"
        / "2"
        / "inbox.json"
    ) in (written_round(scheduler=scheduler, number=2, name="prompt.txt"))


def test_an_assignment_receives_a_batch_only_once(resuming, gh):
    ran(root=resuming, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == []
    assert not (
        scheduler.assignments.state.assignments / ASSIGNMENT_ID / "rounds" / "3"
    ).exists()


def test_a_batch_no_round_ever_launched_is_read_again_next_tick(
    resuming, gh, harnesses
):
    ran(root=resuming, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    # A file where the round's own directory goes, so no round can ever start.
    occupied = (
        StateDirectory(root=resuming).assignments / ASSIGNMENT_ID / "rounds" / "2"
    )
    occupied.parent.mkdir(parents=True, exist_ok=True)
    occupied.write_text("something else is here\n", encoding="utf-8")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert "cannot write" in held(observed=observed)
    relay_reads = [
        call for call in gh.calls if call.arguments[:2] == ["api", CONVERSATION]
    ]
    assert len(relay_reads) == 2
    assert harnesses["claude"].calls == []


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_gets_one_last_round(resuming, gh, state_name):
    ran(root=resuming, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state=state_name), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    wrap_up = record_of(scheduler=scheduler, number=2)
    assert wrap_up.purpose is AssignmentRoundPurpose.WRAP_UP
    assert not wrap_up.is_recovery
    assert json.loads(
        written_round(scheduler=scheduler, number=2, name="inbox.json")
    ) == {
        "pull_request_state": state_name,
        "user_posts": [],
    }


def test_an_assignment_that_has_had_its_last_round_gets_no_other(resuming, gh):
    ran(root=resuming, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    ran(root=resuming, number=2, purpose=AssignmentRoundPurpose.WRAP_UP)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert not (
        scheduler.assignments.state.assignments / ASSIGNMENT_ID / "rounds" / "3"
    ).exists()


def test_a_last_round_that_was_interrupted_is_carried_on_as_the_last_round(
    resuming, gh
):
    ran(root=resuming, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED.replace(hour=17, minute=2),
            pid=1,
            purpose=AssignmentRoundPurpose.WRAP_UP,
            ending=InterruptedAgentRoundEnding(),
        ),
    )
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    # The carry-on finished what the last round started, so no second one runs.
    recovered = record_of(scheduler=scheduler, number=3)
    assert recovered.purpose is AssignmentRoundPurpose.WRAP_UP
    assert recovered.is_recovery
    assert not (
        scheduler.assignments.state.assignments / ASSIGNMENT_ID / "rounds" / "4"
    ).exists()


def test_open_work_is_carried_on_before_a_new_issue_is_assigned(resuming, gh, offered):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=PURPOSE,
            ending=InterruptedAgentRoundEnding(),
        ),
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert not (scheduler.assignments.state.worktrees / CREATED_ASSIGNMENT_ID).exists()
    assert observed_issues(tick=observed) == [8, 13]
    assert observed.issue_observations[1].claimed_here.value is IssueFactValue.TRUE


def test_a_failed_issue_listing_leaves_open_work_for_a_later_tick(
    resuming, gh, left_running
):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, pid=left_running.pid, purpose=PURPOSE
        ),
    )
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert "could not connect" in held(observed=observed)
    assert observed.launched_agent_work_identifiers == []
    assert not (
        scheduler.assignments.state.assignments / ASSIGNMENT_ID / "rounds" / "2"
    ).exists()


def test_two_faulted_assignments_start_a_global_cooldown(ready_repo):
    write_faulted_assignment(root=ready_repo, identifier=ASSIGNMENT_ID, issue=13)
    write_faulted_assignment(root=ready_repo, identifier=SECOND_ASSIGNMENT_ID, issue=14)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert observed.cooldown == GlobalCooldown(
        started=PINNED, ends=PINNED + timedelta(minutes=15)
    )
    assert held(observed=observed) == "global cooldown"
    assert [one.identifier for one in observed.assignment_observations] == [
        ASSIGNMENT_ID,
        SECOND_ASSIGNMENT_ID,
    ]


def test_an_active_global_cooldown_survives_a_scheduler_restart(ready_repo):
    write_faulted_assignment(root=ready_repo, identifier=ASSIGNMENT_ID, issue=13)
    write_faulted_assignment(root=ready_repo, identifier=SECOND_ASSIGNMENT_ID, issue=14)
    first, first_clock = create_scheduler(root=ready_repo)
    state = StateDirectory(root=ready_repo)
    started = first.tick(at=first_clock())
    write_json(document=started, path=state.scheduler_record)
    restarted, restarted_clock = create_scheduler(root=ready_repo)

    observed = restarted.tick(at=restarted_clock())

    assert observed.cooldown == started.cooldown
    assert observed.launched_agent_work_identifiers == []


def test_a_cooldown_reports_an_issue_listing_failure(ready_repo, offered):
    write_faulted_assignment(root=ready_repo, identifier=ASSIGNMENT_ID, issue=13)
    write_faulted_assignment(root=ready_repo, identifier=SECOND_ASSIGNMENT_ID, issue=14)
    offered.fails(stderr="gh: could not connect to github.com", to="issue list")
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert "global cooldown" in held(observed=observed)
    assert "could not list issues for dream:smith" in held(observed=observed)
    assert "could not connect" in held(observed=observed)


def test_the_cooldown_boundary_clears_faults_and_permits_recovery(ready_repo):
    write_faulted_assignment(root=ready_repo, identifier=ASSIGNMENT_ID, issue=13)
    write_faulted_assignment(root=ready_repo, identifier=SECOND_ASSIGNMENT_ID, issue=14)
    state = StateDirectory(root=ready_repo)
    write_json(
        document=SchedulerRecord(
            at=PINNED - timedelta(minutes=15),
            cooldown=GlobalCooldown(
                started=PINNED - timedelta(minutes=15), ends=PINNED
            ),
        ),
        path=state.scheduler_record,
    )
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.cooldown is None
    assert observed.most_recent_cooldown_ended == PINNED
    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert observed.assignment_observations == [
        observed_assignment(
            identifier=ASSIGNMENT_ID,
            issue=13,
            evidence="round 3 started",
            value=IssueFactValue.FALSE,
        ),
        observed_assignment(
            identifier=SECOND_ASSIGNMENT_ID,
            issue=14,
            evidence="round 2 errored, to recover",
        ),
    ]

    finish_rounds(scheduler=scheduler)
    write_json(document=observed, path=state.scheduler_record)
    restarted, restarted_clock = create_scheduler(root=ready_repo)

    following = restarted.tick(at=restarted_clock())

    assert following.most_recent_cooldown_ended == PINNED
    assert following.launched_agent_work_identifiers == [SECOND_ASSIGNMENT_ID]


def test_a_cooldown_normalizes_aware_datetimes_to_utc():
    offset = timezone(timedelta(hours=2))

    cooldown = GlobalCooldown(
        started=datetime(2026, 8, 19, 20, 41, 58, tzinfo=offset),
        ends=datetime(2026, 8, 19, 20, 56, 58, tzinfo=offset),
    )

    assert cooldown.started == PINNED
    assert cooldown.started.tzinfo is UTC
    assert cooldown.ends == PINNED + timedelta(minutes=15)
    assert cooldown.ends.tzinfo is UTC


@pytest.mark.parametrize(
    ("started", "ends", "message"),
    [
        (
            datetime(2026, 8, 19, 18, 41, 58),
            datetime(2026, 8, 19, 18, 56, 58),
            "timezone info",
        ),
        (PINNED, PINNED, "cooldown end must follow its start"),
    ],
)
def test_a_cooldown_refuses_invalid_datetimes(started, ends, message):
    with pytest.raises(ValidationError, match=message):
        GlobalCooldown(started=started, ends=ends)
