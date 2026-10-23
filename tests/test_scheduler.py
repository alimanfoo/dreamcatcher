"""Scheduling decisions and launch operations."""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from clocks import PINNED, Ticking
from conftest import (
    FILED,
    HEAD,
    LATER,
    POST_LIST_PATHS,
    POSTED_AT,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    SMITH_CLAUDE,
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
from records import MERGED_INPUT, read_assignments, write_assignment, write_round
from rows import UNCLAIMED, request_row

import dreamcatcher.scheduler.tick as tick_module
from dreamcatcher.agent_assignments import (
    AssignmentRoundInput,
    cancel_assignment,
    read_assignment_pull_request_number,
    read_user_post_cursor,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    ErroredAgentRoundEnding,
    FinishingErroredAgentRoundEnding,
    HarnessErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    LaunchErroredAgentRoundEnding,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import (
    _HARNESS_SESSION_RECORD_NAME,
    AgentWorkEndReason,
    create_agent_work,
    request_agent_work_retry,
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
from dreamcatcher.github import CheckResult, PullRequestMergeState, PullRequestState
from dreamcatcher.scheduler import Scheduler, SchedulingContext
from dreamcatcher.scheduler.faults import (
    derive_agent_work_fault,
    is_last_round_unfinished,
)
from dreamcatcher.scheduler.models import (
    GlobalCooldown,
    IssueReference,
    PullRequestFinding,
    SchedulerRecord,
    StartedRound,
    StartTimeFinding,
)
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158-assignment"
ASSIGNMENT_BRANCH = f"dreamcatcher-{ASSIGNMENT_ID}"
SECOND_ASSIGNMENT_ID = "GH14-20260819-184158-assignment"
STILL_RUNNING = 30
CREATED_ASSIGNMENT_ID = "GH8-20260819-184158-assignment"
CONVERSATION = POST_LIST_PATHS["conversation"]
HARNESS_SESSION_IDENTIFIER = "abc-123"

# What the tick finds for an assignment whose draft pull request has nothing new.
NOTHING_NEW = PullRequestFinding(
    number=PULL_REQUEST,
    state=PullRequestState.OPEN,
    is_draft=True,
    merge_state=PullRequestMergeState.CLEAN,
    head=HEAD,
    check_result=CheckResult.PASSING,
    has_running_checks=False,
    new_posts=0,
    new_pull_request_signals=[],
    is_check_failure_withheld=False,
    is_wrap_up_due=False,
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
    scheduler = Scheduler(
        context=SchedulingContext(
            repository=REPOSITORY,
            account=POSTED_BY,
            config=config,
            state=state,
            clock=clock,
        ),
        preferred_harness=AgentHarness.CLAUDE,
        rounds={},
        max_agents=max_agents,
    )
    CREATED_SCHEDULERS.append(scheduler)
    return scheduler, clock


def finish_rounds(*, scheduler) -> None:
    """Wait for every round that the scheduler has started."""
    for running in list(scheduler.rounds.values()):
        running.wait()


def sole_failure(*, observed: SchedulerRecord) -> str:
    """Return the one failure that held back a tick."""
    [failure] = observed.failures
    return failure


def record_of(*, scheduler: Scheduler, number: int) -> AgentRoundRecord:
    """Return what the assignment's numbered round recorded."""
    return AgentRoundRecord.model_validate_json(
        written_round(scheduler=scheduler, number=number, name="round.json")
    )


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
    status: int | None = 0,
    round_input: AssignmentRoundInput | None = None,
) -> None:
    """Write down a round of the assignment on disk, ended as the status says.

    Every one of them runs the hour before the pinned clock reads unless the
    test needs an explicit ending time.
    """
    started = PINNED.replace(hour=17, minute=number)
    ending = (
        None
        if status is None
        else _compose_agent_round_ending(at=started, status=status)
    )
    write_round(
        directory=StateDirectory(root=root).work / ASSIGNMENT_ID,
        number=number,
        record=AgentRoundRecord(
            number=number,
            started=started,
            pid=1,
            ending=ending,
        ),
        round_input=round_input,
    )


def write_faulted_assignment(*, root, identifier: str, issue: int) -> None:
    """Write an assignment whose two latest rounds both exited with errors."""
    write_assignment(
        state=StateDirectory(root=root), identifier=identifier, issue=issue
    )
    directory = StateDirectory(root=root).work / identifier
    for number, status in ((1, 1), (2, 2)):
        started = PINNED.replace(hour=17, minute=number)
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=started,
                pid=1,
                ending=_compose_agent_round_ending(at=started, status=status),
            ),
        )


def written_round(*, scheduler: Scheduler, number: int, name: str) -> str:
    """What the assignment's round wrote into the file of that name."""
    directory = scheduler.context.state.work / ASSIGNMENT_ID / "rounds" / str(number)
    return (directory / name).read_text(encoding="utf-8")


def forget_harness_session_identifier(*, root) -> None:
    """Remove the assignment's recorded harness session identifier."""
    state = StateDirectory(root=root)
    assignment = read_assignments(state=state)[0]
    (assignment.directory / _HARNESS_SESSION_RECORD_NAME).unlink()


def test_a_tick_assigns_the_oldest_issue_nothing_stands_in_the_way_of(
    ready_repo, harnesses
):
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assignment = scheduler.context.state.work / CREATED_ASSIGNMENT_ID
    assert (
        scheduler.context.state.worktrees / CREATED_ASSIGNMENT_ID / "README.md"
    ).exists()
    assert (assignment / "work.json").exists()
    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    assert observed.rows == [
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=UNCLAIMED,
            started_round=StartedRound(number=1),
        )
    ]
    assert (
        harnesses["claude"].calls[0].directory
        == (scheduler.context.state.worktrees / CREATED_ASSIGNMENT_ID).resolve()
    )


def test_a_new_assignments_round_records_what_caused_it_and_what_it_said(
    ready_repo,
):
    scheduler, clock = create_scheduler(root=ready_repo)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    written = scheduler.context.state.work / CREATED_ASSIGNMENT_ID / "rounds" / "1"
    assert (
        AgentRoundRecord.model_validate_json(
            (written / "round.json").read_text(encoding="utf-8")
        ).number
        == 1
    )
    assert "what the round said" in (written / "feed.txt").read_text(encoding="utf-8")
    assignment = read_assignments(state=scheduler.context.state)[0]
    assert assignment.harness_session_identifier == "abc-123"


def test_a_tick_fills_free_capacity_with_available_issues(ready_repo, offered):
    offered.replies(
        stdout=listing(issues=[(8, FILED), (9, LATER), (10, "2026-08-21T01:00:00Z")]),
        to="issue list",
    )
    scheduler, clock = create_scheduler(root=ready_repo, max_agents=2)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [
        CREATED_ASSIGNMENT_ID,
        "GH9-20260819-184158-assignment",
    ]
    assert scheduler.is_at_capacity
    assert observed.rows == [
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=UNCLAIMED,
            started_round=StartedRound(number=1),
        ),
        request_row(
            issue=9,
            agent_work_identifier="GH9-20260819-184158-assignment",
            finding=UNCLAIMED,
            started_round=StartedRound(number=1),
        ),
        request_row(issue=10, finding=UNCLAIMED),
    ]
    assert (
        scheduler.context.state.worktrees / "GH9-20260819-184158-assignment"
    ).exists()
    assert not (
        scheduler.context.state.worktrees / "GH10-20260819-184158-assignment"
    ).exists()


def test_a_failed_launch_goes_on_to_the_next_candidate(
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

    def fail_second_creation(**arguments):
        if arguments["issue"] == 9:
            raise ReportableError("could not create an assignment for GH9")
        return create_agent_work(**arguments)

    monkeypatch.setattr(tick_module, "create_agent_work", fail_second_creation)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [
        CREATED_ASSIGNMENT_ID,
        "GH10-20260819-184158-assignment",
    ]
    assert observed.failures == ["could not create an assignment for GH9"]
    assert observed.rows[1] == request_row(issue=9, finding=UNCLAIMED)


def test_a_round_that_cannot_open_its_pull_request_is_named_in_its_row(
    ready_repo, offered
):
    offered.fails(stderr="gh: pull request create failed", to="pr create")
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    [row] = observed.rows
    assert row.agent_work_identifier == CREATED_ASSIGNMENT_ID
    assert row.started_round is not None
    assert row.started_round.number == 1
    assert row.started_round.launch_failure is not None
    assert "pull request create failed" in row.started_round.launch_failure


def test_a_second_tick_judges_an_assigned_issue_handled(ready_repo):
    scheduler, clock = create_scheduler(root=ready_repo, max_agents=2)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert [(row.issue, row.agent_work_identifier) for row in observed.rows] == [
        (8, CREATED_ASSIGNMENT_ID)
    ]


def test_a_completed_assignment_releases_its_issue(ready_repo):
    state = StateDirectory(root=ready_repo)
    assignment = write_assignment(
        state=state,
        identifier="GH8-20260818-184158-assignment",
        issue=8,
    )
    write_round(
        directory=assignment,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=_compose_agent_round_ending(at=PINNED, status=0),
        ),
        round_input=MERGED_INPUT,
    )
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    assert observed.rows == [
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=UNCLAIMED,
            started_round=StartedRound(number=1),
        )
    ]


def test_a_tick_at_the_cap_holds_an_assignment_that_needs_a_round(
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
        status=1,
    )
    observed = scheduler.tick(at=clock())

    # The first tick assigned issue 8, and its round is what fills the cap,
    # so the assignment already on disk is the one the cap holds.
    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            ended_round=1,
            finding=NOTHING_NEW,
        ),
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=NOTHING_NEW,
        ),
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
    ran(root=ready_repo, number=1, round_input=MERGED_INPUT)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.rows == [
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=NOTHING_NEW,
        )
    ]


def test_a_tick_at_the_cap_refreshes_the_candidates(ready_repo, offered, harnesses):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    offered.replies(stdout=listing(issues=[(8, FILED), (9, LATER)]), to="issue list")
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert scheduler.is_at_capacity
    assert observed.rows == [
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=NOTHING_NEW,
        ),
        request_row(issue=9, finding=UNCLAIMED),
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
    )
    scheduler, clock = create_scheduler(root=ready_repo)
    scheduler.tick(at=clock())
    offered.fails(stderr="gh: could not connect to github.com", to="issue list")
    observed = scheduler.tick(at=clock())

    assert scheduler.is_at_capacity
    failure = sole_failure(observed=observed)
    assert failure.startswith("could not list issues for dream:smith: ")
    assert "could not connect" in failure
    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            ended_round=1,
            finding=NOTHING_NEW,
        ),
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=NOTHING_NEW,
        ),
    ]


def test_a_tick_with_nothing_eligible_starts_no_assignment(ready_repo, offered):
    offered.replies(
        stdout=pages(
            items=[
                {
                    "number": 7,
                    "state": "open",
                    "repository_url": f"https://api.github.com/repos/{REPOSITORY}",
                }
            ]
        ),
        to="api",
    )
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert observed.rows == [
        request_row(
            issue=8,
            finding=StartTimeFinding(
                linked_pull_requests=[], blocking_issues=[IssueReference(number=7)]
            ),
        )
    ]
    assert not scheduler.context.state.worktrees.exists()


def test_one_errored_round_is_given_its_input_again(ready_repo):
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(root=ready_repo, number=1, status=1)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert observed.cooldown is None
    assert not (scheduler.context.state.worktrees / CREATED_ASSIGNMENT_ID).exists()


def test_one_faulted_assignment_does_not_block_unrelated_work(ready_repo):
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(root=ready_repo, number=1, status=1)
    ran(root=ready_repo, number=2, status=1)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    assert observed.rows == [
        request_row(issue=13, agent_work_identifier=ASSIGNMENT_ID, ended_round=2),
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=UNCLAIMED,
            started_round=StartedRound(number=1),
        ),
    ]


def test_a_deleted_assignment_worktree_errors_twice_while_other_work_runs(
    resuming, gh, offered
):
    ran(root=resuming, number=1)
    missing_worktree = StateDirectory(root=resuming).worktrees / ASSIGNMENT_ID
    missing_worktree.rmdir()
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    first = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    second = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    third = scheduler.tick(at=clock())

    first_failure = first.started_rounds[ASSIGNMENT_ID].launch_failure
    second_failure = second.started_rounds[ASSIGNMENT_ID].launch_failure
    assert first_failure is not None
    assert second_failure is not None
    assert str(missing_worktree) in first_failure
    assert str(missing_worktree) in second_failure
    assert first.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    assert second.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    assert third.started_rounds == {}
    assignment = next(
        assignment
        for assignment in read_assignments(state=scheduler.context.state)
        if assignment.identifier == ASSIGNMENT_ID
    )
    assert len(assignment.rounds) == 3
    assert all(
        isinstance(round_record.ending, ErroredAgentRoundEnding)
        for round_record in assignment.rounds[-2:]
    )


def test_a_user_retry_clears_one_fault_and_starts_a_round(ready_repo):
    write_faulted_assignment(root=ready_repo, identifier=ASSIGNMENT_ID, issue=13)
    state = StateDirectory(root=ready_repo)
    assignment = read_assignments(state=state)[0]
    request_agent_work_retry(work=assignment, at=PINNED)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            ended_round=2,
            finding=NOTHING_NEW,
            started_round=StartedRound(number=3),
        ),
        request_row(issue=8, finding=UNCLAIMED),
    ]


def test_a_successful_round_breaks_the_error_sequence(ready_repo):
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(root=ready_repo, number=1, status=1)
    ran(root=ready_repo, number=2)
    ran(root=ready_repo, number=3, status=1)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]


def test_a_running_assignment_is_observed_without_starting_another_round(
    ready_repo, gh, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    scheduler, clock = create_scheduler(root=ready_repo, max_agents=2)

    scheduler.tick(at=clock())
    gh.replies(
        stdout=pages(items=[comment()]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )
    observed = scheduler.tick(at=clock())

    written = (
        scheduler.context.state.work
        / CREATED_ASSIGNMENT_ID
        / "rounds"
        / "1"
        / "round.json"
    )
    assert (
        AgentRoundRecord.model_validate_json(written.read_text(encoding="utf-8")).ending
        is None
    )
    assert observed.rows == [
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=NOTHING_NEW.model_copy(update={"new_posts": 1}),
        )
    ]
    assert list(scheduler.rounds) == [CREATED_ASSIGNMENT_ID]
    assert not (written.parent.parent / "2" / "round.json").exists()


def test_an_ended_round_is_inspected_while_its_runner_finishes(resuming):
    ran(root=resuming, number=1)
    scheduler, clock = create_scheduler(root=resuming)
    scheduler.rounds[ASSIGNMENT_ID] = Mock(is_alive=True)

    observed = scheduler.tick(at=clock())

    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            ended_round=1,
            finding=NOTHING_NEW,
        )
    ]


def test_a_round_that_replaces_a_finishing_runner_is_reported(resuming, gh):
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming, max_agents=2)
    scheduler.rounds[ASSIGNMENT_ID] = Mock(is_alive=True)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    finish_rounds(scheduler=scheduler)


def test_an_assignment_with_nothing_new_reads_only_its_pull_request_and_posts(
    resuming, gh
):
    ran(root=resuming, number=1)
    gh.replies(stdout=listing(issues=[(13, FILED)]), to="issue list")
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assignment = read_assignments(state=scheduler.context.state)[0]
    assert assignment.record.title == "Issue 13"
    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            ended_round=1,
            finding=PullRequestFinding(
                number=PULL_REQUEST,
                state=PullRequestState.OPEN,
                is_draft=False,
                merge_state=PullRequestMergeState.CLEAN,
                head=HEAD,
                check_result=CheckResult.PASSING,
                has_running_checks=False,
                new_posts=0,
                new_pull_request_signals=[],
                is_check_failure_withheld=False,
                is_wrap_up_due=False,
            ),
        )
    ]
    assert read_assignment_pull_request_number(assignment=assignment) == 52
    calls = [" ".join(call.arguments) for call in gh.calls]
    assert not [
        call
        for call in calls
        if call.startswith("issue view") or "/dependencies/" in call
    ]


def test_an_assignment_that_has_run_no_round_at_all_gets_its_first(ready_repo):
    state = StateDirectory(root=ready_repo)
    write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13, pull_request=None)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    first = record_of(scheduler=scheduler, number=1)
    assert first.number == 1
    assert written_round(scheduler=scheduler, number=1, name="prompt.txt").startswith(
        "/dream:smith GH13\n\nEnd every post you make on GitHub"
    )
    [assignment] = read_assignments(state=state)
    assert read_assignment_pull_request_number(assignment=assignment) == PULL_REQUEST


def test_a_dispatch_whose_round_will_not_start_keeps_the_assignment_for_next_time(
    ready_repo, offered
):
    # A file where the assignment's rounds go, so no round can record its start.
    occupied = StateDirectory(root=ready_repo).work / CREATED_ASSIGNMENT_ID / "rounds"
    occupied.parent.mkdir(parents=True)
    occupied.write_text("something else is here\n", encoding="utf-8")
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert "cannot write" in sole_failure(observed=observed)
    [assignment] = read_assignments(state=scheduler.context.state)
    assert assignment.identifier == CREATED_ASSIGNMENT_ID
    assert assignment.rounds == []
    assert not assignment.worktree.exists()

    occupied.unlink()
    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [CREATED_ASSIGNMENT_ID]
    record = scheduler.context.state.work / CREATED_ASSIGNMENT_ID / "rounds" / "1"
    assert (record / "round.json").is_file()
    created = [call for call in offered.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == 1


@pytest.mark.parametrize("checkpoint", ["worktree", "commit", "push", "pull request"])
def test_a_round_after_one_that_failed_part_way_finishes_its_preparation(
    ready_repo, offered, checkpoint
):
    state = StateDirectory(root=ready_repo)
    directory = write_assignment(
        state=state,
        identifier=ASSIGNMENT_ID,
        issue=13,
        harness_session_identifier=None,
        pull_request=None,
    )
    started = PINNED.replace(hour=17)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=started,
            ending=LaunchErroredAgentRoundEnding(at=started, reason="git push failed"),
        ),
    )
    branch = f"dreamcatcher-{ASSIGNMENT_ID}"
    worktree = state.worktrees / ASSIGNMENT_ID
    worktree.rmdir()
    fetch_main(root=ready_repo)
    add_worktree(root=ready_repo, path=worktree, branch=branch)
    if checkpoint != "worktree":
        make_empty_commit(worktree=worktree, message="GH13")
    if checkpoint in {"push", "pull request"}:
        push_branch(root=ready_repo, branch=branch)
    if checkpoint == "pull request":
        offered.replies(stdout=pull_requests(numbers=[PULL_REQUEST]), to="pr list")
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert record_of(scheduler=scheduler, number=2).number == 2
    commits = git(arguments=["rev-list", "--count", "origin/main..HEAD"], cwd=worktree)
    assert commits.strip() == "1"
    remote = git(arguments=["ls-remote", "--heads", "origin", branch], cwd=ready_repo)
    assert f"refs/heads/{branch}" in remote
    created = [call for call in offered.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == (0 if checkpoint == "pull request" else 1)
    [assignment] = read_assignments(state=state)
    assert read_assignment_pull_request_number(assignment=assignment) == PULL_REQUEST


def test_an_assignment_with_a_round_that_has_no_ending_starts_nothing(resuming):
    write_round(
        directory=StateDirectory(root=resuming).work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(number=1, started=PINNED, pid=1),
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            finding=NOTHING_NEW,
        )
    ]
    assert not (
        scheduler.context.state.work
        / ASSIGNMENT_ID
        / "rounds"
        / "2"
        / "round-input.json"
    ).exists()


def test_a_resume_finds_the_harness_session_in_the_first_rounds_raw_stream(
    resuming, harnesses
):
    ran(root=resuming, number=1, status=1)
    forget_harness_session_identifier(root=resuming)
    raw = (
        StateDirectory(root=resuming).work
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
    assignment = read_assignments(state=scheduler.context.state)[0]
    assert assignment.harness_session_identifier == HARNESS_SESSION_IDENTIFIER
    assert harnesses["claude"].calls[-1].arguments[-2:] == [
        "--resume",
        HARNESS_SESSION_IDENTIFIER,
    ]


def test_a_codex_assignment_round_passes_its_recorded_harness_config(
    ready_repo, harnesses
):
    state = StateDirectory(root=ready_repo)
    write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13, pull_request=None)
    record = read_assignments(state=state)[0].record
    write_json(
        document=record.model_copy(
            update={
                "harness": AgentHarness.CODEX,
                "harness_config": {"model_context_window": 1000000},
            }
        ),
        path=state.work / ASSIGNMENT_ID / "work.json",
    )
    harnesses["codex"].streams(lines=[])
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    arguments = harnesses["codex"].calls[-1].arguments
    setting = arguments.index("model_context_window=1000000")
    assert arguments[setting - 1] == "-c"


def test_an_unfinished_round_without_a_harness_session_starts_a_new_session(
    resuming, harnesses
):
    ran(root=resuming, number=1, status=1)
    forget_harness_session_identifier(root=resuming)
    harnesses["claude"].streams(lines=[], status=1)
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    faulted = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert written_round(scheduler=scheduler, number=2, name="prompt.txt").startswith(
        "/dream:smith GH13\n\nYour previous round did not finish."
    )
    assert "--resume" not in harnesses["claude"].calls[-1].arguments
    assert faulted.rows == [
        request_row(issue=13, agent_work_identifier=ASSIGNMENT_ID, ended_round=2)
    ]


def test_a_follow_up_without_a_harness_session_starts_a_new_one_with_its_input(
    resuming, gh, harnesses
):
    ran(root=resuming, number=1)
    forget_harness_session_identifier(root=resuming)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    prompt = written_round(scheduler=scheduler, number=2, name="prompt.txt")
    assert prompt.startswith("/dream:smith GH13\n\nAssignment input")
    assert "unfinished assignment" not in prompt
    assert "--resume" not in harnesses["claude"].calls[-1].arguments


def test_a_terminal_round_after_an_error_without_a_session_receives_wrap_up_input(
    resuming, gh, harnesses
):
    ran(root=resuming, number=1, status=1)
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
    assert prompt.startswith("/dream:smith GH13\n\nYour previous round did not finish.")
    assert "Assignment input for pull request" in prompt
    round_input = json.loads(
        written_round(scheduler=scheduler, number=2, name="round-input.json")
    )
    assert round_input["pull_request_state"] == PullRequestState.MERGED
    assert "--resume" not in harnesses["claude"].calls[-1].arguments
    assignment = read_assignments(state=scheduler.context.state)[0]
    assert read_user_post_cursor(assignment=assignment) == POSTED_AT


def test_a_round_after_an_errored_one_is_given_its_posts_again(resuming, gh, harnesses):
    ran(root=resuming, number=1, status=1)
    forget_harness_session_identifier(root=resuming)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    harnesses["claude"].streams(lines=[], status=1)
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    assignment = read_assignments(state=scheduler.context.state)[0]
    assert read_user_post_cursor(assignment=assignment) == ""
    ending = assignment.rounds[-1].ending
    assert isinstance(ending, ErroredAgentRoundEnding)
    request_agent_work_retry(work=assignment, at=ending.at + timedelta(seconds=1))

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    round_input = json.loads(
        written_round(scheduler=scheduler, number=3, name="round-input.json")
    )
    assert [post["kind"] for post in round_input["user_posts"]] == ["comment"]


def test_a_round_after_an_interrupted_one_is_given_the_input_again(resuming):
    write_round(
        directory=StateDirectory(root=resuming).work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=InterruptedAgentRoundEnding(),
        ),
    )
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    prompt = written_round(scheduler=scheduler, number=2, name="prompt.txt")
    assert prompt.startswith("Your previous round did not finish.")
    assert "continue the unfinished assignment" in prompt
    assert json.loads(
        written_round(scheduler=scheduler, number=2, name="round-input.json")
    ) == {
        "pull_request_state": "OPEN",
        "pull_request_head": HEAD,
        "signals": [],
        "user_posts": [],
    }


def test_an_assignment_the_user_has_posted_on_is_told_what_they_said(resuming, gh):
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    round_input = json.loads(
        written_round(scheduler=scheduler, number=2, name="round-input.json")
    )
    assert round_input["pull_request_state"] == "OPEN"
    assert [post["kind"] for post in round_input["user_posts"]] == ["comment"]
    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            ended_round=1,
            finding=PullRequestFinding(
                number=PULL_REQUEST,
                state=PullRequestState.OPEN,
                is_draft=False,
                merge_state=PullRequestMergeState.CLEAN,
                head=HEAD,
                check_result=CheckResult.PASSING,
                has_running_checks=False,
                new_posts=1,
                new_pull_request_signals=[],
                is_check_failure_withheld=False,
                is_wrap_up_due=False,
            ),
            started_round=StartedRound(number=2),
        )
    ]
    assert str(
        scheduler.context.state.work
        / ASSIGNMENT_ID
        / "rounds"
        / "2"
        / "round-input.json"
    ) in (written_round(scheduler=scheduler, number=2, name="prompt.txt"))


def test_an_assignment_receives_a_batch_only_once(resuming, gh):
    ran(root=resuming, number=1)
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
    assert not (scheduler.context.state.work / ASSIGNMENT_ID / "rounds" / "3").exists()


def test_a_batch_no_round_ever_launched_is_read_again_next_tick(
    resuming, gh, harnesses
):
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    # A file where the round's own directory goes, so no round can ever start.
    occupied = StateDirectory(root=resuming).work / ASSIGNMENT_ID / "rounds" / "2"
    occupied.parent.mkdir(parents=True, exist_ok=True)
    occupied.write_text("something else is here\n", encoding="utf-8")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert "cannot write" in sole_failure(observed=observed)
    relay_reads = [
        call for call in gh.calls if call.arguments[:2] == ["api", CONVERSATION]
    ]
    assert len(relay_reads) == 2
    assert harnesses["claude"].calls == []


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_gets_one_last_round(resuming, gh, state_name):
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state=state_name), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert json.loads(
        written_round(scheduler=scheduler, number=2, name="round-input.json")
    ) == {
        "pull_request_state": state_name,
        "pull_request_head": HEAD,
        "signals": [],
        "user_posts": [],
    }
    [completed] = read_assignments(state=scheduler.context.state)
    assert completed.ending is not None
    assert completed.ending.reason is AgentWorkEndReason.COMPLETED


def check_out_assignment(*, root) -> Path:
    """Put the assignment's worktree on its branch, and return the worktree."""
    worktree = StateDirectory(root=root).worktrees / ASSIGNMENT_ID
    worktree.rmdir()
    fetch_main(root=root)
    add_worktree(root=root, path=worktree, branch=ASSIGNMENT_BRANCH)
    return worktree


def list_branches(*, root) -> str:
    """Return the names of the checkout's local branches."""
    return git(arguments=["branch", "--format=%(refname:short)"], cwd=root)


def test_a_completed_assignment_loses_its_worktree_and_branch_at_the_next_tick(
    resuming, gh
):
    worktree = check_out_assignment(root=resuming)
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)
    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    assert worktree.is_dir()

    observed = scheduler.tick(at=clock())

    assert observed.failures == []
    assert not worktree.exists()
    assert ASSIGNMENT_BRANCH not in list_branches(root=resuming)
    [completed] = read_assignments(state=scheduler.context.state)
    assert completed.ending is not None
    assert completed.ending.reason is AgentWorkEndReason.COMPLETED
    assert [record.number for record in completed.rounds] == [1, 2]
    assert read_assignment_pull_request_number(assignment=completed) == PULL_REQUEST


def test_a_cancelled_assignment_keeps_its_worktree_and_branch(resuming, gh, harnesses):
    worktree = check_out_assignment(root=resuming)
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    scheduler, clock = create_scheduler(root=resuming)
    scheduler.tick(at=clock())
    [assignment] = read_assignments(state=scheduler.context.state)
    cancel_assignment(assignment=assignment, at=clock())
    finish_rounds(scheduler=scheduler)

    observed = scheduler.tick(at=clock())

    assert observed.failures == []
    assert worktree.is_dir()
    assert ASSIGNMENT_BRANCH in list_branches(root=resuming)
    [cancelled] = read_assignments(state=scheduler.context.state)
    assert cancelled.ending is not None
    assert cancelled.ending.reason is AgentWorkEndReason.CANCELLED


def test_a_worktree_that_will_not_go_is_reported_once_and_left(resuming, gh):
    worktree = check_out_assignment(root=resuming)
    git(arguments=["worktree", "lock", str(worktree)], cwd=resuming)
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)
    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    reported = scheduler.tick(at=clock())
    later = scheduler.tick(at=clock())

    assert sole_failure(observed=reported).startswith(
        f"could not remove the worktree of {ASSIGNMENT_ID}: "
    )
    assert later.failures == []
    assert worktree.is_dir()
    assert ASSIGNMENT_BRANCH in list_branches(root=resuming)
    [completed] = read_assignments(state=scheduler.context.state)
    assert completed.ending is not None
    assert completed.ending.reason is AgentWorkEndReason.COMPLETED


def test_a_completed_assignment_with_no_worktree_or_branch_left_reports_nothing(
    resuming, gh
):
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)
    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    observed = scheduler.tick(at=clock())

    assert observed.failures == []


def test_a_branch_that_will_not_go_is_reported(resuming, gh):
    # The main checkout has the branch checked out, so Git will not delete it.
    git(arguments=["switch", "--create", ASSIGNMENT_BRANCH], cwd=resuming)
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)
    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    observed = scheduler.tick(at=clock())

    assert sole_failure(observed=observed).startswith(
        f"could not delete the branch {ASSIGNMENT_BRANCH}: "
    )
    assert ASSIGNMENT_BRANCH in list_branches(root=resuming)


def test_a_last_round_that_fails_leaves_its_assignment_open(resuming, gh, harnesses):
    ran(root=resuming, number=1)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    harnesses["claude"].streams(lines=[], status=1)
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    [assignment] = read_assignments(state=scheduler.context.state)
    assert assignment.is_open


def test_an_assignment_that_has_had_its_last_round_gets_no_other(resuming, gh):
    ran(root=resuming, number=1)
    ran(root=resuming, number=2, round_input=MERGED_INPUT)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert not (scheduler.context.state.work / ASSIGNMENT_ID / "rounds" / "3").exists()


def test_a_last_round_that_was_interrupted_is_carried_on_as_the_last_round(
    resuming, gh
):
    ran(root=resuming, number=1)
    write_round(
        directory=StateDirectory(root=resuming).work / ASSIGNMENT_ID,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED.replace(hour=17, minute=2),
            pid=1,
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
    assert not (scheduler.context.state.work / ASSIGNMENT_ID / "rounds" / "4").exists()


def test_open_work_is_carried_on_before_a_new_issue_is_assigned(resuming, gh, offered):
    write_round(
        directory=StateDirectory(root=resuming).work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=InterruptedAgentRoundEnding(),
        ),
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == [ASSIGNMENT_ID]
    assert not (scheduler.context.state.worktrees / CREATED_ASSIGNMENT_ID).exists()
    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            ended_round=1,
            finding=NOTHING_NEW,
            started_round=StartedRound(number=2),
        ),
        request_row(issue=8, finding=UNCLAIMED),
    ]


def test_a_failed_issue_listing_starts_nothing_for_its_label_alone(ready_repo, offered):
    configure(root=ready_repo, head=SMITH_CLAUDE.replace("dream:smith", "dream:less"))
    write_assignment(
        state=StateDirectory(root=ready_repo),
        identifier=ASSIGNMENT_ID,
        issue=13,
    )
    ran(root=ready_repo, number=1, status=1)
    offered.fails(
        stderr="gh: could not connect to github.com",
        to=f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} --label dream:less",
    )
    scheduler, clock = create_scheduler(root=ready_repo, max_agents=2)

    observed = scheduler.tick(at=clock())

    assert "could not list issues for dream:less" in sole_failure(observed=observed)
    assert observed.launched_agent_work_identifiers == [
        ASSIGNMENT_ID,
        CREATED_ASSIGNMENT_ID,
    ]
    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            ended_round=1,
            finding=NOTHING_NEW,
            started_round=StartedRound(number=2),
        ),
        request_row(
            issue=8,
            agent_work_identifier=CREATED_ASSIGNMENT_ID,
            finding=UNCLAIMED,
            started_round=StartedRound(number=1),
        ),
    ]


def test_two_faulted_assignments_start_a_global_cooldown(ready_repo):
    write_faulted_assignment(root=ready_repo, identifier=ASSIGNMENT_ID, issue=13)
    write_faulted_assignment(root=ready_repo, identifier=SECOND_ASSIGNMENT_ID, issue=14)
    scheduler, clock = create_scheduler(root=ready_repo)

    observed = scheduler.tick(at=clock())

    assert observed.launched_agent_work_identifiers == []
    assert observed.cooldown == GlobalCooldown(
        started=PINNED, ends=PINNED + timedelta(minutes=15)
    )
    assert observed.failures == []
    assert observed.rows == [
        request_row(issue=13, agent_work_identifier=ASSIGNMENT_ID, ended_round=2),
        request_row(
            issue=14, agent_work_identifier=SECOND_ASSIGNMENT_ID, ended_round=2
        ),
        request_row(issue=8, finding=UNCLAIMED),
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

    failure = sole_failure(observed=observed)
    assert observed.cooldown is not None
    assert "could not list issues for dream:smith" in failure
    assert "could not connect" in failure


def test_the_cooldown_boundary_clears_faults_and_permits_rounds(ready_repo):
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
    assert observed.rows == [
        request_row(
            issue=13,
            agent_work_identifier=ASSIGNMENT_ID,
            ended_round=2,
            finding=NOTHING_NEW,
            started_round=StartedRound(number=3),
        ),
        request_row(
            issue=14,
            agent_work_identifier=SECOND_ASSIGNMENT_ID,
            ended_round=2,
            finding=NOTHING_NEW,
        ),
        request_row(issue=8, finding=UNCLAIMED),
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


@pytest.mark.parametrize(
    ("ending", "is_daemon_running", "is_awaited"),
    [
        pytest.param(None, True, False, id="running"),
        pytest.param(None, False, True, id="interrupted-by-daemon-shutdown"),
        pytest.param(InterruptedAgentRoundEnding(), True, True, id="interrupted"),
        pytest.param(
            HarnessErroredAgentRoundEnding(at=PINNED, status=2),
            True,
            True,
            id="errored",
        ),
        pytest.param(
            SuccessfulAgentRoundEnding(at=PINNED), True, False, id="successful"
        ),
        pytest.param(StoppedAgentRoundEnding(at=PINNED), True, False, id="stopped"),
    ],
)
def test_only_an_interrupted_or_errored_last_round_is_unfinished(
    ending, is_daemon_running, is_awaited
):
    record = AgentRoundRecord(
        number=1,
        started=PINNED,
        pid=1,
        ending=ending,
    )

    assert (
        is_last_round_unfinished(rounds=[record], is_daemon_running=is_daemon_running)
        is is_awaited
    )


def test_agent_work_that_has_run_no_round_has_no_unfinished_round():
    assert not is_last_round_unfinished(rounds=[], is_daemon_running=False)


@pytest.mark.parametrize(
    "ending",
    [
        pytest.param(
            LaunchErroredAgentRoundEnding(at=PINNED, reason="git push failed"),
            id="launch",
        ),
        pytest.param(HarnessErroredAgentRoundEnding(at=PINNED, status=2), id="harness"),
        pytest.param(
            FinishingErroredAgentRoundEnding(
                at=PINNED, reason="could not post the answer"
            ),
            id="finishing",
        ),
    ],
)
def test_every_kind_of_errored_round_counts_towards_a_fault(ending):
    rounds = [
        AgentRoundRecord(number=number, started=PINNED, ending=ending)
        for number in (1, 2)
    ]

    assert derive_agent_work_fault(
        rounds=rounds, retry_requested_at=None, most_recent_cooldown_ended=None
    )
