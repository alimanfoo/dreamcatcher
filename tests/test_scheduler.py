"""Scheduling decisions and launch operations."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from clocks import PINNED, Ticking
from conftest import (
    FILED,
    LATER,
    POST_LIST_PATHS,
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
from records import write_agent_assignment, write_round

from dreamcatcher.agent_assignments import (
    read_agent_assignments,
    request_agent_assignment_retry,
)
from dreamcatcher.agent_rounds import (
    AgentRoundPurpose,
    AgentRoundRecord,
    compose_agent_round_ending,
)
from dreamcatcher.config import Harness, read_config
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.git import (
    add_worktree,
    fetch,
    make_empty_commit,
    push_branch,
)
from dreamcatcher.prompts import CARRY_ON_PROMPT
from dreamcatcher.scheduler import (
    AgentAssignmentObservation,
    GlobalCooldown,
    IssueFactValue,
    Scheduler,
    SchedulerRecord,
    derive_issue_availability,
)
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158"
SECOND_ASSIGNMENT_ID = "GH14-20260819-184158"
PURPOSE = AgentRoundPurpose.IMPLEMENT
STILL_RUNNING = 30
DISPATCHED_ASSIGNMENT_ID = "GH8-20260819-184158"
CONVERSATION = POST_LIST_PATHS["conversation"]
HARNESS_SESSION_IDENTIFIER = "abc-123"


CREATED_SCHEDULERS: list[Scheduler] = []


@pytest.fixture(autouse=True)
def stop_scheduler_rounds():
    """Stop every round that a scheduler test started."""
    yield
    for scheduler in CREATED_SCHEDULERS:
        for running in scheduler.rounds.values():
            running.stop()
    CREATED_SCHEDULERS.clear()


def create_scheduler(*, root) -> tuple[Scheduler, Ticking]:
    """Create a scheduler and a clock that advances between explicit ticks."""
    clock = Ticking(step=300)
    scheduler = Scheduler(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=read_config(root=root),
        state=StateDirectory(root=root),
        harness=Harness.CLAUDE,
        clock=clock,
        rounds={},
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
    """Return each observed issue's derived availability in dispatch order."""
    return [
        derive_issue_availability(observation=observation).value
        for observation in tick.issue_observations
    ]


@pytest.mark.parametrize(
    ("reason", "is_known"),
    [
        ("at cap: 1 of 1 rounds running", True),
        ("cannot read its pull request: unavailable", False),
        ("cannot tell what the user posted: unavailable", False),
    ],
)
def test_an_old_assignment_observation_recovers_its_certainty(reason, is_known):
    observation = AgentAssignmentObservation.model_validate(
        {"assignment": ASSIGNMENT_ID, "issue": 13, "reason": reason}
    )

    assert observation.is_known is is_known


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
    """A checkout holding one assignment, with no labelled issue up for dispatch."""
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
    write_agent_assignment(
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
    purpose: AgentRoundPurpose,
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
    write_agent_assignment(
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
    directory = scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / str(number)
    return (directory / name).read_text(encoding="utf-8")


def forget_harness_session_identifier(*, root) -> None:
    """Remove the harness session identifier from the assignment's record."""
    state = StateDirectory(root=root)
    assignment = read_agent_assignments(state=state)[0]
    write_json(
        document=assignment.record.model_copy(
            update={"harness_session_identifier": None}
        ),
        path=assignment.directory / "assignment.json",
    )


def test_a_tick_dispatches_the_oldest_issue_nothing_stands_in_the_way_of(
    dispatching, harnesses
):
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assignment = scheduler.state.assignments / DISPATCHED_ASSIGNMENT_ID
    assert (scheduler.state.worktrees / DISPATCHED_ASSIGNMENT_ID / "README.md").exists()
    assert (assignment / "assignment.json").exists()
    assert observed.issue_observations[0].observed_at == observed.at
    assert observed.launched == DISPATCHED_ASSIGNMENT_ID
    assert (
        harnesses["claude"].calls[0].directory
        == (scheduler.state.worktrees / DISPATCHED_ASSIGNMENT_ID).resolve()
    )


def test_a_dispatched_round_records_what_caused_it_and_what_it_said(dispatching):
    scheduler, clock = create_scheduler(root=dispatching)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    written = scheduler.state.assignments / DISPATCHED_ASSIGNMENT_ID / "rounds" / "1"
    assert (
        AgentRoundRecord.model_validate_json(
            (written / "round.json").read_text(encoding="utf-8")
        ).purpose
        is AgentRoundPurpose.IMPLEMENT
    )
    assert "what the round said" in (written / "feed.txt").read_text(encoding="utf-8")
    assignment = read_agent_assignments(state=scheduler.state)[0]
    assert assignment.record.harness_session_identifier == "abc-123"


def test_a_tick_launches_one_round_and_leaves_the_rest_in_the_queue(
    dispatching, offered
):
    configure(root=dispatching, head="max_agents = 2\n\n")
    offered.replies(stdout=listing(issues=[(8, FILED), (9, LATER)]), to="issue list")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed_issues(tick=observed) == [8, 9]
    assert availability_values(tick=observed) == [
        IssueFactValue.TRUE,
        IssueFactValue.TRUE,
    ]
    assert observed.launched == DISPATCHED_ASSIGNMENT_ID
    assert not (scheduler.state.worktrees / "GH9-20260819-184158").exists()


def test_a_second_tick_judges_a_dispatched_issue_handled(dispatching):
    configure(root=dispatching, head="max_agents = 2\n\n")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.launched is None
    assert observed_issues(tick=observed) == [8]
    assert observed.issue_observations[0].claimed_here.value is IssueFactValue.TRUE
    assert availability_values(tick=observed) == [IssueFactValue.FALSE]


def test_a_completed_assignment_releases_its_issue(dispatching):
    state = StateDirectory(root=dispatching)
    assignment = write_agent_assignment(
        state=state,
        identifier="GH8-20260818-184158",
        issue=8,
    )
    write_round(
        directory=assignment,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AgentRoundPurpose.WRAP_UP,
            is_recovery=False,
            started=PINNED,
            pid=1,
            ending=compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed_issues(tick=observed) == [8]
    assert availability_values(tick=observed) == [IssueFactValue.TRUE]
    assert observed.launched == DISPATCHED_ASSIGNMENT_ID


def test_a_tick_at_the_cap_says_the_cap_is_what_each_assignment_waits_on(
    dispatching, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    scheduler, clock = create_scheduler(root=dispatching)

    scheduler.tick(at=clock())
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    ran(
        root=dispatching,
        number=1,
        purpose=AgentRoundPurpose.IMPLEMENT,
        status=1,
    )
    observed = scheduler.tick(at=clock())

    # The first tick dispatched issue 8, and its round is what fills the cap,
    # so the assignment already on disk is the one the cap holds.
    assert observed.assignment_observations == [
        AgentAssignmentObservation(
            assignment=ASSIGNMENT_ID, issue=13, reason="at cap: 1 of 1 rounds running"
        )
    ]


def test_a_tick_at_the_cap_leaves_a_wound_up_assignment_waiting_on_nothing(
    dispatching, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    ran(root=dispatching, number=1, purpose=AgentRoundPurpose.IMPLEMENT)
    ran(root=dispatching, number=1, purpose=AgentRoundPurpose.WRAP_UP)
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.assignment_observations == []


def test_a_tick_at_the_cap_refreshes_the_candidates(dispatching, offered, harnesses):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    offered.replies(stdout=listing(issues=[(8, FILED), (9, LATER)]), to="issue list")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.hold == "at cap: 1 of 1 rounds running"
    assert observed_issues(tick=observed) == [8, 9]
    assert availability_values(tick=observed) == [
        IssueFactValue.FALSE,
        IssueFactValue.TRUE,
    ]


def test_a_tick_at_the_cap_records_a_candidate_listing_failure(
    dispatching, offered, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    ran(root=dispatching, number=1, purpose=AgentRoundPurpose.IMPLEMENT)
    scheduler, clock = create_scheduler(root=dispatching)
    scheduler.tick(at=clock())
    offered.fails(stderr="gh: could not connect to github.com", to="issue list")
    observed = scheduler.tick(at=clock())

    hold = held(observed=observed)
    assert hold.startswith("at cap: 1 of 1 rounds running; could not refresh issues: ")
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
        AgentAssignmentObservation(
            assignment=ASSIGNMENT_ID,
            issue=13,
            reason="no round required",
            is_round_required=False,
        )
    ]


def test_a_tick_with_nothing_eligible_dispatches_nothing(dispatching, offered):
    offered.replies(stdout=pull_requests(listed=[(7, "open")]), to="api")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.launched is None
    assert observed_issues(tick=observed) == [8]
    assert observed.issue_observations[0].blocked.value is IssueFactValue.TRUE
    assert availability_values(tick=observed) == [IssueFactValue.FALSE]
    assert not scheduler.state.worktrees.exists()


def test_one_errored_round_receives_an_ordinary_recovery(dispatching):
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    ran(root=dispatching, number=1, purpose=PURPOSE, status=1)
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.launched == ASSIGNMENT_ID
    assert observed.cooldown is None
    assert not (scheduler.state.worktrees / DISPATCHED_ASSIGNMENT_ID).exists()


def test_one_faulted_assignment_does_not_block_unrelated_work(dispatching):
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    ran(root=dispatching, number=1, purpose=PURPOSE, status=1)
    ran(root=dispatching, number=2, purpose=PURPOSE, status=1, is_recovery=True)
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.launched == DISPATCHED_ASSIGNMENT_ID
    assert observed.assignment_observations == [
        AgentAssignmentObservation(
            assignment=ASSIGNMENT_ID,
            issue=13,
            reason="two consecutive rounds failed",
        )
    ]


def test_a_user_retry_clears_one_fault_and_starts_recovery(dispatching):
    write_faulted_assignment(root=dispatching, identifier=ASSIGNMENT_ID, issue=13)
    state = StateDirectory(root=dispatching)
    assignment = read_agent_assignments(state=state)[0]
    request_agent_assignment_retry(assignment=assignment, at=PINNED)
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.launched == ASSIGNMENT_ID
    assert observed.assignment_observations == []


def test_a_successful_round_breaks_the_error_sequence(dispatching):
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    ran(root=dispatching, number=1, purpose=PURPOSE, status=1)
    ran(root=dispatching, number=2, purpose=PURPOSE)
    ran(root=dispatching, number=3, purpose=PURPOSE, status=1)
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.launched == ASSIGNMENT_ID


def test_an_assignment_the_scheduler_is_running_a_round_for_is_not_waiting(
    dispatching, harnesses
):
    configure(root=dispatching, head="max_agents = 2\n\n")
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    # The round the scheduler held recorded no ending, so the assignment would have
    # read as interrupted had the scheduler not been running it.
    written = (
        scheduler.state.assignments
        / DISPATCHED_ASSIGNMENT_ID
        / "rounds"
        / "1"
        / "round.json"
    )
    assert (
        AgentRoundRecord.model_validate_json(written.read_text(encoding="utf-8")).ending
        is None
    )
    assert observed.assignment_observations == []


def test_an_assignment_with_an_open_pull_request_and_nothing_new_is_not_waiting(
    resuming, gh
):
    ran(root=resuming, number=1, purpose=AgentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched is None
    assert observed.assignment_observations == [
        AgentAssignmentObservation(
            assignment=ASSIGNMENT_ID,
            issue=13,
            reason="no round required",
            is_round_required=False,
        )
    ]


def test_an_assignment_that_has_run_no_round_at_all_gets_its_first(dispatching):
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched == ASSIGNMENT_ID
    first = record_of(scheduler=scheduler, number=1)
    assert first.number == 1
    assert first.purpose is AgentRoundPurpose.IMPLEMENT
    assert not first.is_recovery
    assert written_round(scheduler=scheduler, number=1, name="prompt.txt") == (
        "/dream:smith GH13"
    )


def test_a_dispatch_whose_round_will_not_start_retries_the_prepared_assignment(
    dispatching, offered
):
    # A file where the assignment's rounds go, so no round can record its start.
    occupied = (
        StateDirectory(root=dispatching).assignments
        / DISPATCHED_ASSIGNMENT_ID
        / "rounds"
    )
    occupied.parent.mkdir(parents=True)
    occupied.write_text("something else is here\n", encoding="utf-8")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert "cannot write" in held(observed=observed)
    assert observed_issues(tick=observed) == [8]
    assert availability_values(tick=observed) == [IssueFactValue.TRUE]
    assert (scheduler.state.worktrees / DISPATCHED_ASSIGNMENT_ID).exists()
    branch = f"dreamcatcher-{DISPATCHED_ASSIGNMENT_ID}"
    assert branch in git(arguments=["branch", "--list", branch], cwd=dispatching)

    occupied.unlink()
    offered.replies(
        stdout=json.dumps(
            {"closedByPullRequestsReferences": [{"number": PULL_REQUEST}]}
        ),
        to="issue view",
    )
    offered.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched == DISPATCHED_ASSIGNMENT_ID
    record = scheduler.state.assignments / DISPATCHED_ASSIGNMENT_ID / "rounds" / "1"
    written = AgentRoundRecord.model_validate_json(
        (record / "round.json").read_text(encoding="utf-8")
    )
    assert written.purpose is AgentRoundPurpose.IMPLEMENT
    created = [call for call in offered.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == 1


@pytest.mark.parametrize("checkpoint", ["worktree", "commit", "push", "pull request"])
def test_the_next_tick_recovers_each_incomplete_creation_checkpoint(
    dispatching, offered, checkpoint
):
    state = StateDirectory(root=dispatching)
    branch = f"dreamcatcher-{DISPATCHED_ASSIGNMENT_ID}"
    worktree = state.worktrees / DISPATCHED_ASSIGNMENT_ID
    fetch(root=dispatching)
    add_worktree(root=dispatching, path=worktree, branch=branch)
    if checkpoint != "worktree":
        make_empty_commit(worktree=worktree, message="GH8")
    if checkpoint in {"push", "pull request"}:
        push_branch(root=dispatching, branch=branch)
    if checkpoint == "pull request":
        offered.replies(
            stdout=json.dumps(
                {"closedByPullRequestsReferences": [{"number": PULL_REQUEST}]}
            ),
            to="issue view",
        )
        offered.replies(
            stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list"
        )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched == DISPATCHED_ASSIGNMENT_ID
    round_record = state.assignments / DISPATCHED_ASSIGNMENT_ID / "rounds" / "1"
    assert (
        AgentRoundRecord.model_validate_json(
            (round_record / "round.json").read_text(encoding="utf-8")
        ).purpose
        is AgentRoundPurpose.IMPLEMENT
    )
    assert len(list(state.assignments.iterdir())) == 1
    commits = git(arguments=["rev-list", "--count", "origin/main..HEAD"], cwd=worktree)
    assert commits.strip() == "1"
    remote = git(arguments=["ls-remote", "--heads", "origin", branch], cwd=dispatching)
    assert f"refs/heads/{branch}" in remote
    created = [call for call in offered.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == (0 if checkpoint == "pull request" else 1)


def test_an_assignment_whose_last_round_did_not_finish_is_carried_on(
    resuming, left_running, harnesses
):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, pid=left_running.pid, purpose=PURPOSE
        ),
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched == ASSIGNMENT_ID
    assert (
        written_round(scheduler=scheduler, number=2, name="prompt.txt")
        == CARRY_ON_PROMPT
    )
    assert not (
        scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "2" / "inbox.json"
    ).exists()
    assert harnesses["claude"].calls[-1].arguments[-2:] == [
        "--resume",
        HARNESS_SESSION_IDENTIFIER,
    ]


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

    assert observed.launched == ASSIGNMENT_ID
    assignment = read_agent_assignments(state=scheduler.state)[0]
    assert assignment.record.harness_session_identifier == HARNESS_SESSION_IDENTIFIER
    assert harnesses["claude"].calls[-1].arguments[-2:] == [
        "--resume",
        HARNESS_SESSION_IDENTIFIER,
    ]


def test_a_resume_with_no_harness_session_identifier_reports_why_it_cannot_start(
    resuming, harnesses
):
    ran(root=resuming, number=1, purpose=PURPOSE, status=1)
    forget_harness_session_identifier(root=resuming)
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert held(observed=observed) == (
        f"Could not resume {ASSIGNMENT_ID}: its first round did not report a "
        "harness session identifier."
    )
    assert harnesses["claude"].calls == []


def test_a_carried_on_round_records_recovery_independently(resuming, left_running):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, pid=left_running.pid, purpose=PURPOSE
        ),
    )
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    recovered = record_of(scheduler=scheduler, number=2)
    assert recovered.purpose is AgentRoundPurpose.IMPLEMENT
    assert recovered.is_recovery


def test_an_assignment_the_user_has_posted_on_is_told_what_they_said(resuming, gh):
    ran(root=resuming, number=1, purpose=AgentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched == ASSIGNMENT_ID
    feedback = record_of(scheduler=scheduler, number=2)
    assert feedback.purpose is AgentRoundPurpose.ADDRESS_FEEDBACK
    assert not feedback.is_recovery
    inbox = json.loads(written_round(scheduler=scheduler, number=2, name="inbox.json"))
    assert inbox["state"] == "OPEN"
    assert [post["kind"] for post in inbox["posts"]] == ["comment"]
    assert str(
        scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "2" / "inbox.json"
    ) in (written_round(scheduler=scheduler, number=2, name="prompt.txt"))


def test_an_assignment_receives_a_batch_only_once(resuming, gh):
    ran(root=resuming, number=1, purpose=AgentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched is None
    assert not (scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "3").exists()


def test_a_batch_no_round_ever_launched_is_read_again_next_tick(
    resuming, gh, harnesses
):
    ran(root=resuming, number=1, purpose=AgentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="OPEN"), to="pr view")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
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
    ran(root=resuming, number=1, purpose=AgentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state=state_name), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched == ASSIGNMENT_ID
    wrap_up = record_of(scheduler=scheduler, number=2)
    assert wrap_up.purpose is AgentRoundPurpose.WRAP_UP
    assert not wrap_up.is_recovery
    assert json.loads(
        written_round(scheduler=scheduler, number=2, name="inbox.json")
    ) == {
        "state": state_name,
        "posts": [],
    }


def test_an_assignment_that_has_had_its_last_round_gets_no_other(resuming, gh):
    ran(root=resuming, number=1, purpose=AgentRoundPurpose.IMPLEMENT)
    ran(root=resuming, number=2, purpose=AgentRoundPurpose.WRAP_UP)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched is None
    assert not (scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "3").exists()


def test_a_last_round_that_was_interrupted_is_carried_on_as_the_last_round(
    resuming, gh, left_running
):
    ran(root=resuming, number=1, purpose=AgentRoundPurpose.IMPLEMENT)
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED.replace(hour=17, minute=2),
            pid=left_running.pid,
            purpose=AgentRoundPurpose.WRAP_UP,
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
    assert recovered.purpose is AgentRoundPurpose.WRAP_UP
    assert recovered.is_recovery
    assert not (scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "4").exists()


def test_open_work_is_carried_on_before_a_new_issue_is_dispatched(
    resuming, gh, offered, left_running
):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, pid=left_running.pid, purpose=PURPOSE
        ),
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched == ASSIGNMENT_ID
    assert not (scheduler.state.worktrees / DISPATCHED_ASSIGNMENT_ID).exists()
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
    assert observed.launched is None
    assert not (scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "2").exists()


def test_two_faulted_assignments_start_a_global_cooldown(dispatching):
    write_faulted_assignment(root=dispatching, identifier=ASSIGNMENT_ID, issue=13)
    write_faulted_assignment(
        root=dispatching, identifier=SECOND_ASSIGNMENT_ID, issue=14
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.launched is None
    assert observed.cooldown == GlobalCooldown(
        started=PINNED, ends=PINNED + timedelta(minutes=15)
    )
    assert "next attempt at 18:56:58 UTC" in held(observed=observed)
    assert [one.assignment for one in observed.assignment_observations] == [
        ASSIGNMENT_ID,
        SECOND_ASSIGNMENT_ID,
    ]


def test_an_active_global_cooldown_survives_a_scheduler_restart(dispatching):
    write_faulted_assignment(root=dispatching, identifier=ASSIGNMENT_ID, issue=13)
    write_faulted_assignment(
        root=dispatching, identifier=SECOND_ASSIGNMENT_ID, issue=14
    )
    first, first_clock = create_scheduler(root=dispatching)
    state = StateDirectory(root=dispatching)
    started = first.tick(at=first_clock())
    write_json(document=started, path=state.scheduler_record)
    restarted, restarted_clock = create_scheduler(root=dispatching)

    observed = restarted.tick(at=restarted_clock())

    assert observed.cooldown == started.cooldown
    assert observed.launched is None


def test_a_cooldown_reports_an_issue_listing_failure(dispatching, offered):
    write_faulted_assignment(root=dispatching, identifier=ASSIGNMENT_ID, issue=13)
    write_faulted_assignment(
        root=dispatching, identifier=SECOND_ASSIGNMENT_ID, issue=14
    )
    offered.fails(stderr="gh: could not connect to github.com", to="issue list")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert "global cooldown" in held(observed=observed)
    assert "could not refresh issues" in held(observed=observed)
    assert "could not connect" in held(observed=observed)


def test_the_cooldown_boundary_clears_faults_and_permits_recovery(dispatching):
    write_faulted_assignment(root=dispatching, identifier=ASSIGNMENT_ID, issue=13)
    write_faulted_assignment(
        root=dispatching, identifier=SECOND_ASSIGNMENT_ID, issue=14
    )
    state = StateDirectory(root=dispatching)
    write_json(
        document=SchedulerRecord(
            at=PINNED - timedelta(minutes=15),
            cooldown=GlobalCooldown(
                started=PINNED - timedelta(minutes=15), ends=PINNED
            ),
        ),
        path=state.scheduler_record,
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.cooldown is None
    assert observed.most_recent_cooldown_ended == PINNED
    assert observed.launched == ASSIGNMENT_ID
    assert observed.assignment_observations == [
        AgentAssignmentObservation(
            assignment=SECOND_ASSIGNMENT_ID,
            issue=14,
            reason="the last round failed (exit 2)",
        )
    ]

    finish_rounds(scheduler=scheduler)
    write_json(document=observed, path=state.scheduler_record)
    restarted, restarted_clock = create_scheduler(root=dispatching)

    following = restarted.tick(at=restarted_clock())

    assert following.most_recent_cooldown_ended == PINNED
    assert following.launched == SECOND_ASSIGNMENT_ID


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
