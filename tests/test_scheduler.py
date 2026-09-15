"""Scheduling decisions and launch operations."""

import json

import pytest
from clocks import PINNED, Ticking
from conftest import (
    FILED,
    LABEL,
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
    pull_requests,
)
from fakes import Line
from records import write_agent_assignment, write_round

from dreamcatcher.config import Harness, read_config
from dreamcatcher.prompts import CARRY_ON_PROMPT
from dreamcatcher.rounds import Cause, Ending, RoundRecord
from dreamcatcher.scheduler import Scheduler
from dreamcatcher.state import (
    NO_ROUND_HAS_RUN,
    CandidateIssue,
    LastTick,
    StateDirectory,
    WaitingAgentAssignment,
)

ASSIGNMENT_ID = "GH13-20260819-184158"
CAUSE = Cause.DISPATCH
STILL_RUNNING = 30
DISPATCHED_ASSIGNMENT_ID = "GH8-20260819-184158"
CONVERSATION = POST_LIST_PATHS["conversation"]


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


def held(*, observed: LastTick) -> str:
    """Return why the scheduler launched nothing in one tick."""
    assert observed.hold is not None
    return observed.hold


def cause_of(*, scheduler: Scheduler, number: int) -> Cause:
    """What the assignment's round of that number says woke it."""
    return RoundRecord.model_validate_json(
        written_round(scheduler=scheduler, number=number, name="round.json")
    ).cause


@pytest.fixture
def resuming(cloned, gh, harnesses):
    """A checkout holding one assignment, with no labelled issue up for dispatch."""
    configure(root=cloned)
    harnesses["claude"].streams(lines=[Line(text="what the round said\n")])
    write_agent_assignment(
        state=StateDirectory(root=cloned), identifier=ASSIGNMENT_ID, issue=13
    )
    return cloned


def ran(*, root, number: int, cause: Cause, status: int | None = 0) -> None:
    """Write down a round of the assignment on disk, ended as the status says.

    Every one of them ran the hour before the pinned clock reads, so a round
    that failed is long enough ago to hold nothing.
    """
    started = PINNED.replace(hour=17, minute=number)
    ending = None if status is None else Ending(at=started, status=status)
    write_round(
        directory=StateDirectory(root=root).assignments / ASSIGNMENT_ID,
        number=number,
        record=RoundRecord(started=started, pid=1, cause=cause, ending=ending),
    )


def written_round(*, scheduler: Scheduler, number: int, name: str) -> str:
    """What the assignment's round wrote into the file of that name."""
    directory = scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / str(number)
    return (directory / name).read_text(encoding="utf-8")


def test_a_tick_dispatches_the_oldest_issue_nothing_stands_in_the_way_of(
    dispatching, harnesses
):
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assignment = scheduler.state.assignments / DISPATCHED_ASSIGNMENT_ID
    assert (scheduler.state.worktrees / DISPATCHED_ASSIGNMENT_ID / "README.md").exists()
    assert (assignment / "assignment.json").exists()
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
        RoundRecord.model_validate_json(
            (written / "round.json").read_text(encoding="utf-8")
        ).cause
        is Cause.DISPATCH
    )
    assert "what the round said" in (written / "feed.txt").read_text(encoding="utf-8")


def test_a_tick_launches_one_round_and_leaves_the_rest_in_the_queue(
    dispatching, offered
):
    configure(root=dispatching, head="max_agents = 2\n\n")
    offered.replies(stdout=listing(issues=[(8, FILED), (9, LATER)]), to="issue list")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.candidates == [
        CandidateIssue(issue=8, label=LABEL),
        CandidateIssue(issue=9, label=LABEL),
    ]
    assert observed.launched == DISPATCHED_ASSIGNMENT_ID
    assert not (scheduler.state.worktrees / "GH9-20260819-184158").exists()


def test_a_second_tick_judges_a_dispatched_issue_handled(dispatching):
    configure(root=dispatching, head="max_agents = 2\n\n")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.launched is None
    assert observed.candidates == [
        CandidateIssue(
            issue=8,
            label=LABEL,
            reason="an assignment in this checkout is working on it",
        )
    ]


def test_a_tick_at_the_cap_says_the_cap_is_what_each_assignment_waits_on(
    dispatching, offered, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    # The first tick dispatched issue 8, and its round is what fills the cap,
    # so the assignment already on disk is the one the cap holds.
    assert observed.waiting == [
        WaitingAgentAssignment(
            assignment=ASSIGNMENT_ID, issue=13, reason="at cap: 1 of 1 rounds running"
        )
    ]
    assert not any(call.arguments[:2] == ["pr", "list"] for call in offered.calls)


def test_a_tick_at_the_cap_leaves_a_wound_up_assignment_waiting_on_nothing(
    dispatching, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    ran(root=dispatching, number=1, cause=Cause.FINAL)
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.waiting == []


def test_a_tick_at_the_cap_refreshes_the_candidates(dispatching, offered, harnesses):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    offered.replies(stdout=listing(issues=[(8, FILED), (9, LATER)]), to="issue list")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())
    observed = scheduler.tick(at=clock())

    assert observed.hold == "at cap: 1 of 1 rounds running"
    assert observed.candidates == [
        CandidateIssue(
            issue=8,
            label=LABEL,
            reason="an assignment in this checkout is working on it",
        ),
        CandidateIssue(issue=9, label=LABEL),
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
    scheduler, clock = create_scheduler(root=dispatching)
    scheduler.tick(at=clock())
    offered.fails(stderr="gh: could not connect to github.com", to="issue list")
    observed = scheduler.tick(at=clock())

    hold = held(observed=observed)
    assert hold.startswith("at cap: 1 of 1 rounds running; could not refresh queue: ")
    assert "could not connect" in hold
    assert observed.candidates == []
    assert observed.waiting == [
        WaitingAgentAssignment(
            assignment=ASSIGNMENT_ID, issue=13, reason="at cap: 1 of 1 rounds running"
        )
    ]


def test_a_tick_with_nothing_eligible_dispatches_nothing(dispatching, offered):
    offered.replies(stdout=pull_requests(listed=[(7, "open")]), to="api")
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.launched is None
    assert observed.candidates == [
        CandidateIssue(issue=8, label=LABEL, reason="blocked by GH7")
    ]
    assert not scheduler.state.worktrees.exists()


def test_a_round_that_failed_lately_holds_every_launch(dispatching):
    directory = write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    write_round(
        directory=directory,
        number=1,
        record=RoundRecord(
            started=PINNED,
            pid=1,
            cause=CAUSE,
            ending=Ending(at=PINNED.replace(minute=35), status=1),
        ),
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert held(observed=observed) == (
        "the last round failed (exit 1) — next attempt at 18:50 UTC"
    )
    assert observed.launched is None
    assert not (scheduler.state.worktrees / DISPATCHED_ASSIGNMENT_ID).exists()


def test_a_round_that_failed_long_enough_ago_holds_nothing(dispatching):
    directory = write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    write_round(
        directory=directory,
        number=1,
        record=RoundRecord(
            started=PINNED,
            pid=1,
            cause=CAUSE,
            ending=Ending(at=PINNED.replace(hour=18, minute=0), status=1),
        ),
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    # That round is the most open work there is, so the launch the cooldown
    # was holding is its carry-on and not the dispatch.
    assert observed.launched == ASSIGNMENT_ID


def test_a_round_that_ended_well_holds_nothing(dispatching):
    directory = write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    write_round(
        directory=directory,
        number=1,
        record=RoundRecord(
            started=PINNED, pid=1, cause=CAUSE, ending=Ending(at=PINNED, status=0)
        ),
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.launched == DISPATCHED_ASSIGNMENT_ID


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
        RoundRecord.model_validate_json(written.read_text(encoding="utf-8")).ending
        is None
    )
    assert observed.waiting == []


def test_an_assignment_with_an_open_pull_request_and_nothing_new_is_not_waiting(
    resuming, gh
):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched is None
    assert observed.waiting == []


def test_an_assignment_with_no_pull_request_of_its_own_reads_as_waiting(resuming):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.waiting == [
        WaitingAgentAssignment(
            assignment=ASSIGNMENT_ID,
            issue=13,
            reason="no pull request has been opened on it",
            is_stuck=True,
        )
    ]


def test_an_assignment_that_has_run_no_round_at_all_waits_for_its_first(dispatching):
    write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    scheduler, clock = create_scheduler(root=dispatching)

    observed = scheduler.tick(at=clock())

    assert observed.waiting == [
        WaitingAgentAssignment(
            assignment=ASSIGNMENT_ID, issue=13, reason=NO_ROUND_HAS_RUN, is_stuck=True
        )
    ]


def test_a_dispatch_whose_round_will_not_start_leaves_no_assignment_behind(dispatching):
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
    assert observed.candidates == [CandidateIssue(issue=8, label=LABEL)]
    assert not (scheduler.state.worktrees / DISPATCHED_ASSIGNMENT_ID).exists()
    branch = f"dreamcatcher-{DISPATCHED_ASSIGNMENT_ID}"
    assert git(arguments=["branch", "--list", branch], cwd=dispatching) == ""


def test_an_assignment_whose_last_round_did_not_finish_is_carried_on(
    resuming, left_running
):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE),
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


def test_a_carried_on_round_says_that_is_what_woke_it(resuming, left_running):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE),
    )
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert cause_of(scheduler=scheduler, number=2) is Cause.CARRY_ON


def test_an_assignment_the_user_has_posted_on_is_told_what_they_said(resuming, gh):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched == ASSIGNMENT_ID
    assert cause_of(scheduler=scheduler, number=2) is Cause.POSTS
    inbox = json.loads(written_round(scheduler=scheduler, number=2, name="inbox.json"))
    assert inbox["state"] == "OPEN"
    assert [post["kind"] for post in inbox["posts"]] == ["comment"]
    assert str(
        scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "2" / "inbox.json"
    ) in (written_round(scheduler=scheduler, number=2, name="prompt.txt"))


def test_an_assignment_told_about_a_batch_hears_it_only_once(resuming, gh):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert (scheduler.state.assignments / ASSIGNMENT_ID / "watermark").read_text(
        encoding="utf-8"
    ) == POSTED_AT
    assert observed.launched is None
    assert not (scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "3").exists()


def test_a_batch_no_round_ever_launched_is_read_again_next_tick(resuming, gh):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
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
    assert not (scheduler.state.assignments / ASSIGNMENT_ID / "watermark").exists()
    peeks = [call for call in gh.calls if call.arguments[:2] == ["api", CONVERSATION]]
    assert len(peeks) == 2


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_gets_one_last_round(resuming, gh, state_name):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, state_name)]), to="pr list")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    assert observed.launched == ASSIGNMENT_ID
    assert cause_of(scheduler=scheduler, number=2) is Cause.FINAL
    assert json.loads(
        written_round(scheduler=scheduler, number=2, name="inbox.json")
    ) == {
        "state": state_name,
        "posts": [],
    }


def test_an_assignment_that_has_had_its_last_round_gets_no_other(resuming, gh):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    ran(root=resuming, number=2, cause=Cause.FINAL)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "MERGED")]), to="pr list")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched is None
    assert not (scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "3").exists()


def test_a_last_round_that_was_interrupted_is_carried_on_as_the_last_round(
    resuming, gh, left_running
):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=2,
        record=RoundRecord(
            started=PINNED.replace(hour=17, minute=2),
            pid=left_running.pid,
            cause=Cause.FINAL,
        ),
    )
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "MERGED")]), to="pr list")
    scheduler, clock = create_scheduler(root=resuming)

    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)
    scheduler.tick(at=clock())
    finish_rounds(scheduler=scheduler)

    # The carry-on finished what the last round started, so no second one runs.
    assert cause_of(scheduler=scheduler, number=3) is Cause.CARRY_ON
    assert not (scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "4").exists()


def test_open_work_is_carried_on_before_a_new_issue_is_dispatched(
    resuming, gh, offered, left_running
):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE),
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert observed.launched == ASSIGNMENT_ID
    assert not (scheduler.state.worktrees / DISPATCHED_ASSIGNMENT_ID).exists()
    assert observed.candidates == [CandidateIssue(issue=8, label=LABEL)]


def test_a_failed_issue_listing_leaves_open_work_for_a_later_tick(
    resuming, gh, left_running
):
    write_round(
        directory=StateDirectory(root=resuming).assignments / ASSIGNMENT_ID,
        number=1,
        record=RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE),
    )
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert "could not connect" in held(observed=observed)
    assert observed.launched is None
    assert not (scheduler.state.assignments / ASSIGNMENT_ID / "rounds" / "2").exists()


def test_a_cooling_tick_still_says_what_each_assignment_is_waiting_on(
    resuming, offered
):
    directory = StateDirectory(root=resuming).assignments / ASSIGNMENT_ID
    write_round(
        directory=directory,
        number=1,
        record=RoundRecord(
            started=PINNED,
            pid=1,
            cause=CAUSE,
            ending=Ending(at=PINNED.replace(minute=35), status=1),
        ),
    )
    scheduler, clock = create_scheduler(root=resuming)

    observed = scheduler.tick(at=clock())

    assert "next attempt at 18:50 UTC" in held(observed=observed)
    assert observed.waiting == [
        WaitingAgentAssignment(
            assignment=ASSIGNMENT_ID, issue=13, reason="the last round failed (exit 1)"
        )
    ]
    assert observed.candidates == [CandidateIssue(issue=8, label=LABEL)]
