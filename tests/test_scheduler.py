"""Scheduling decisions and launch operations."""

import json
import sys
from contextlib import suppress

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
from records import write_round, write_session

from dreamcatcher.commands import spawn
from dreamcatcher.config import Harness, read_config
from dreamcatcher.prompts import CARRY_ON_PROMPT
from dreamcatcher.rounds import Cause, Ending, Round, RoundRecord
from dreamcatcher.scheduler import Scheduler
from dreamcatcher.state import (
    NO_ROUND_HAS_RUN,
    CandidateIssue,
    LastTick,
    StateDirectory,
    WaitingSession,
)

KEY = "GH13-20260819-184158"
CAUSE = Cause.DISPATCH
STILL_RUNNING = 30
DISPATCHED_KEY = "GH8-20260819-184158"
CONVERSATION = POST_LIST_PATHS["conversation"]


@pytest.fixture
def left_running(tmp_path):
    """A process standing in for a round left without a recorded ending."""
    child = spawn(
        program=sys.executable,
        arguments=["-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    yield child
    with suppress(OSError):
        child.process.kill()
    child.process.wait()


class Interrupting:
    """A test wait that advances scheduling before it interrupts the loop."""

    def __init__(self, *, ticks: int, settle=lambda: None) -> None:
        self.ticks = ticks
        self.settle = settle
        self.waited: list[float] = []

    def __call__(self, seconds: float, /) -> None:
        self.settle()
        self.waited.append(seconds)
        if len(self.waited) == self.ticks:
            raise KeyboardInterrupt


class Scheduling:
    """Drive a scheduler for a bounded number of ticks."""

    def __init__(self, *, scheduler: Scheduler, clock: Ticking, wait: Interrupting):
        self.scheduler = scheduler
        self.clock = clock
        self.wait = wait
        self.observed: LastTick | None = None

    @property
    def state(self) -> StateDirectory:
        """Return the state paths that the scheduler uses."""
        return self.scheduler.state

    @property
    def rounds(self) -> dict[str, Round]:
        """Return the rounds that the scheduler supervises."""
        return self.scheduler.rounds

    def run(self) -> None:
        """Tick until the test wait interrupts, then stop every test process."""
        at = self.clock()
        try:
            with suppress(KeyboardInterrupt):
                while True:
                    self.observed = self.scheduler.tick(at=at)
                    self.wait(300)
                    at = self.clock()
        finally:
            for running in self.rounds.values():
                running.stop()


def idling(*, root, ticks: int = 2) -> tuple[Scheduling, Interrupting, Ticking]:
    waiting = Interrupting(ticks=ticks)
    ticking = Ticking(step=300)
    state = StateDirectory(root=root)
    rounds: dict[str, Round] = {}
    scheduler = Scheduler(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=read_config(root=root),
        state=state,
        harness=Harness.CLAUDE,
        clock=ticking,
        rounds=rounds,
    )
    return (
        Scheduling(scheduler=scheduler, clock=ticking, wait=waiting),
        waiting,
        ticking,
    )


def settling(*, root, ticks: int = 1) -> Scheduling:
    """Return scheduling that lets every launched round finish before the next."""
    scheduling, waiting, _ = idling(root=root, ticks=ticks)

    def settle() -> None:
        for running in list(scheduling.rounds.values()):
            running.wait()

    waiting.settle = settle
    return scheduling


def held(*, scheduling) -> str:
    """Why the scheduler's most recent tick launched nothing at all."""
    hold = recorded(scheduling=scheduling).hold
    assert hold is not None
    return hold


def cause_of(*, scheduling, number: int) -> Cause:
    """What the session's round of that number says woke it."""
    return RoundRecord.model_validate_json(
        written_round(scheduling=scheduling, number=number, name="round.json")
    ).cause


def recorded(*, scheduling) -> LastTick:
    """What the scheduler's most recent tick returned."""
    assert scheduling.observed is not None
    return scheduling.observed


@pytest.fixture
def resuming(cloned, gh, harnesses):
    """A checkout holding one session, with no labelled issue up for dispatch."""
    configure(root=cloned)
    harnesses["claude"].streams(lines=[Line(text="what the round said\n")])
    write_session(state=StateDirectory(root=cloned), key=KEY, issue=13)
    return cloned


def ran(*, root, number: int, cause: Cause, status: int | None = 0) -> None:
    """Write down a round of the session on disk, ended as the status says.

    Every one of them ran the hour before the pinned clock reads, so a round
    that failed is long enough ago to hold nothing.
    """
    started = PINNED.replace(hour=17, minute=number)
    ending = None if status is None else Ending(at=started, status=status)
    write_round(
        directory=StateDirectory(root=root).sessions / KEY,
        number=number,
        record=RoundRecord(started=started, pid=1, cause=cause, ending=ending),
    )


def written_round(*, scheduling, number: int, name: str) -> str:
    """What the session's round wrote into the file of that name."""
    directory = scheduling.state.sessions / KEY / "rounds" / str(number)
    return (directory / name).read_text(encoding="utf-8")


def test_a_tick_dispatches_the_oldest_issue_nothing_stands_in_the_way_of(
    dispatching, harnesses
):
    scheduling = settling(root=dispatching)

    scheduling.run()

    session = scheduling.state.sessions / DISPATCHED_KEY
    assert (scheduling.state.worktrees / DISPATCHED_KEY / "README.md").exists()
    assert (session / "session.json").exists()
    assert recorded(scheduling=scheduling).launched == DISPATCHED_KEY
    assert (
        harnesses["claude"].calls[0].directory
        == (scheduling.state.worktrees / DISPATCHED_KEY).resolve()
    )


def test_a_dispatched_round_records_what_caused_it_and_what_it_said(dispatching):
    scheduling = settling(root=dispatching)

    scheduling.run()

    written = scheduling.state.sessions / DISPATCHED_KEY / "rounds" / "1"
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
    scheduling, _, _ = idling(root=dispatching, ticks=1)

    scheduling.run()

    assert recorded(scheduling=scheduling).candidates == [
        CandidateIssue(issue=8, label=LABEL),
        CandidateIssue(issue=9, label=LABEL),
    ]
    assert recorded(scheduling=scheduling).launched == DISPATCHED_KEY
    assert not (scheduling.state.worktrees / "GH9-20260819-184158").exists()


def test_a_second_tick_judges_a_dispatched_issue_handled(dispatching):
    configure(root=dispatching, head="max_agents = 2\n\n")
    scheduling, _, _ = idling(root=dispatching, ticks=2)

    scheduling.run()

    assert recorded(scheduling=scheduling).launched is None
    assert recorded(scheduling=scheduling).candidates == [
        CandidateIssue(
            issue=8, label=LABEL, reason="a session in this checkout is working on it"
        )
    ]


def test_a_tick_at_the_cap_says_the_cap_is_what_each_session_waits_on(
    dispatching, offered, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    write_session(state=StateDirectory(root=dispatching), key=KEY, issue=13)
    scheduling, _, _ = idling(root=dispatching, ticks=2)

    scheduling.run()

    # The first tick dispatched issue 8, and its round is what fills the cap,
    # so the session already on disk is the one the cap holds.
    assert recorded(scheduling=scheduling).waiting == [
        WaitingSession(session=KEY, issue=13, reason="at cap: 1 of 1 rounds running")
    ]
    assert not any(call.arguments[:2] == ["pr", "list"] for call in offered.calls)


def test_a_tick_at_the_cap_leaves_a_wound_up_session_waiting_on_nothing(
    dispatching, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    write_session(state=StateDirectory(root=dispatching), key=KEY, issue=13)
    ran(root=dispatching, number=1, cause=Cause.FINAL)
    scheduling, _, _ = idling(root=dispatching, ticks=2)

    scheduling.run()

    assert recorded(scheduling=scheduling).waiting == []


def test_a_tick_at_the_cap_refreshes_the_candidates(dispatching, offered, harnesses):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    offered.replies(stdout=listing(issues=[(8, FILED), (9, LATER)]), to="issue list")
    scheduling, _, _ = idling(root=dispatching, ticks=2)

    scheduling.run()

    assert recorded(scheduling=scheduling).hold == "at cap: 1 of 1 rounds running"
    assert recorded(scheduling=scheduling).candidates == [
        CandidateIssue(
            issue=8,
            label=LABEL,
            reason="a session in this checkout is working on it",
        ),
        CandidateIssue(issue=9, label=LABEL),
    ]


def test_a_tick_at_the_cap_records_a_candidate_listing_failure(
    dispatching, offered, harnesses
):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    write_session(state=StateDirectory(root=dispatching), key=KEY, issue=13)
    scheduling, waiting, _ = idling(root=dispatching, ticks=2)
    waiting.settle = lambda: offered.fails(
        stderr="gh: could not connect to github.com", to="issue list"
    )

    scheduling.run()

    hold = held(scheduling=scheduling)
    assert hold.startswith("at cap: 1 of 1 rounds running; could not refresh queue: ")
    assert "could not connect" in hold
    assert recorded(scheduling=scheduling).candidates == []
    assert recorded(scheduling=scheduling).waiting == [
        WaitingSession(session=KEY, issue=13, reason="at cap: 1 of 1 rounds running")
    ]


def test_a_tick_with_nothing_eligible_dispatches_nothing(dispatching, offered):
    offered.replies(stdout=pull_requests(listed=[(7, "open")]), to="api")
    scheduling, _, _ = idling(root=dispatching, ticks=1)

    scheduling.run()

    assert recorded(scheduling=scheduling).launched is None
    assert recorded(scheduling=scheduling).candidates == [
        CandidateIssue(issue=8, label=LABEL, reason="blocked by GH7")
    ]
    assert not scheduling.state.worktrees.exists()


def test_a_round_that_failed_lately_holds_every_launch(dispatching):
    directory = write_session(state=StateDirectory(root=dispatching), key=KEY, issue=13)
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
    scheduling, _, _ = idling(root=dispatching, ticks=1)

    scheduling.run()

    assert held(scheduling=scheduling) == (
        "the last round failed (exit 1) — next attempt at 18:50 UTC"
    )
    assert recorded(scheduling=scheduling).launched is None
    assert not (scheduling.state.worktrees / DISPATCHED_KEY).exists()


def test_a_round_that_failed_long_enough_ago_holds_nothing(dispatching):
    directory = write_session(state=StateDirectory(root=dispatching), key=KEY, issue=13)
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
    scheduling, _, _ = idling(root=dispatching, ticks=1)

    scheduling.run()

    # That round is the most open work there is, so the launch the cooldown
    # was holding is its carry-on and not the dispatch.
    assert recorded(scheduling=scheduling).launched == KEY


def test_a_round_that_ended_well_holds_nothing(dispatching):
    directory = write_session(state=StateDirectory(root=dispatching), key=KEY, issue=13)
    write_round(
        directory=directory,
        number=1,
        record=RoundRecord(
            started=PINNED, pid=1, cause=CAUSE, ending=Ending(at=PINNED, status=0)
        ),
    )
    scheduling, _, _ = idling(root=dispatching, ticks=1)

    scheduling.run()

    assert recorded(scheduling=scheduling).launched == DISPATCHED_KEY


def test_a_session_the_scheduler_is_running_a_round_for_is_not_waiting(
    dispatching, harnesses
):
    configure(root=dispatching, head="max_agents = 2\n\n")
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    scheduling, _, _ = idling(root=dispatching, ticks=2)

    scheduling.run()

    # The round the scheduling held recorded no ending, so the session would have
    # read as interrupted had the scheduling not been running it.
    written = scheduling.state.sessions / DISPATCHED_KEY / "rounds" / "1" / "round.json"
    assert (
        RoundRecord.model_validate_json(written.read_text(encoding="utf-8")).ending
        is None
    )
    assert recorded(scheduling=scheduling).waiting == []


def test_a_session_with_an_open_pull_request_and_nothing_new_is_not_waiting(
    resuming, gh
):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    scheduling, _, _ = idling(root=resuming, ticks=1)

    scheduling.run()

    assert recorded(scheduling=scheduling).launched is None
    assert recorded(scheduling=scheduling).waiting == []


def test_a_session_with_no_pull_request_of_its_own_reads_as_waiting(resuming):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    scheduling, _, _ = idling(root=resuming, ticks=1)

    scheduling.run()

    assert recorded(scheduling=scheduling).waiting == [
        WaitingSession(
            session=KEY,
            issue=13,
            reason="no pull request has been opened on it",
            is_stuck=True,
        )
    ]


def test_a_session_that_has_run_no_round_at_all_waits_for_its_first(dispatching):
    write_session(state=StateDirectory(root=dispatching), key=KEY, issue=13)
    scheduling, _, _ = idling(root=dispatching, ticks=1)

    scheduling.run()

    assert recorded(scheduling=scheduling).waiting == [
        WaitingSession(session=KEY, issue=13, reason=NO_ROUND_HAS_RUN, is_stuck=True)
    ]


def test_a_dispatch_whose_round_will_not_start_leaves_no_session_behind(dispatching):
    # A file where the session's rounds go, so no round can record its start.
    occupied = StateDirectory(root=dispatching).sessions / DISPATCHED_KEY / "rounds"
    occupied.parent.mkdir(parents=True)
    occupied.write_text("something else is here\n", encoding="utf-8")
    scheduling, _, _ = idling(root=dispatching, ticks=1)

    scheduling.run()

    assert "cannot write" in held(scheduling=scheduling)
    assert recorded(scheduling=scheduling).candidates == [
        CandidateIssue(issue=8, label=LABEL)
    ]
    assert not (scheduling.state.worktrees / DISPATCHED_KEY).exists()
    branch = f"dreamcatcher-{DISPATCHED_KEY}"
    assert git(arguments=["branch", "--list", branch], cwd=dispatching) == ""


def test_a_session_whose_last_round_did_not_finish_is_carried_on(
    resuming, left_running
):
    write_round(
        directory=StateDirectory(root=resuming).sessions / KEY,
        number=1,
        record=RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE),
    )
    scheduling = settling(root=resuming)

    scheduling.run()

    assert recorded(scheduling=scheduling).launched == KEY
    assert (
        written_round(scheduling=scheduling, number=2, name="prompt.txt")
        == CARRY_ON_PROMPT
    )
    assert not (
        scheduling.state.sessions / KEY / "rounds" / "2" / "inbox.json"
    ).exists()


def test_a_carried_on_round_says_that_is_what_woke_it(resuming, left_running):
    write_round(
        directory=StateDirectory(root=resuming).sessions / KEY,
        number=1,
        record=RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE),
    )
    scheduling = settling(root=resuming)

    scheduling.run()

    assert cause_of(scheduling=scheduling, number=2) is Cause.CARRY_ON


def test_a_session_the_user_has_posted_on_is_told_what_they_said(resuming, gh):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduling = settling(root=resuming)

    scheduling.run()

    assert recorded(scheduling=scheduling).launched == KEY
    assert cause_of(scheduling=scheduling, number=2) is Cause.POSTS
    inbox = json.loads(
        written_round(scheduling=scheduling, number=2, name="inbox.json")
    )
    assert inbox["state"] == "OPEN"
    assert [post["kind"] for post in inbox["posts"]] == ["comment"]
    assert str(scheduling.state.sessions / KEY / "rounds" / "2" / "inbox.json") in (
        written_round(scheduling=scheduling, number=2, name="prompt.txt")
    )


def test_a_session_told_about_a_batch_hears_it_only_once(resuming, gh):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    scheduling = settling(root=resuming, ticks=2)

    scheduling.run()

    assert (scheduling.state.sessions / KEY / "watermark").read_text(
        encoding="utf-8"
    ) == POSTED_AT
    assert recorded(scheduling=scheduling).launched is None
    assert not (scheduling.state.sessions / KEY / "rounds" / "3").exists()


def test_a_batch_no_round_ever_launched_is_read_again_next_tick(resuming, gh):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    # A file where the round's own directory goes, so no round can ever start.
    occupied = StateDirectory(root=resuming).sessions / KEY / "rounds" / "2"
    occupied.parent.mkdir(parents=True, exist_ok=True)
    occupied.write_text("something else is here\n", encoding="utf-8")
    scheduling, _, _ = idling(root=resuming, ticks=2)

    scheduling.run()

    assert "cannot write" in held(scheduling=scheduling)
    assert not (scheduling.state.sessions / KEY / "watermark").exists()
    peeks = [call for call in gh.calls if call.arguments[:2] == ["api", CONVERSATION]]
    assert len(peeks) == 2


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_gets_one_last_round(resuming, gh, state_name):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, state_name)]), to="pr list")
    scheduling = settling(root=resuming)

    scheduling.run()

    assert recorded(scheduling=scheduling).launched == KEY
    assert cause_of(scheduling=scheduling, number=2) is Cause.FINAL
    assert json.loads(
        written_round(scheduling=scheduling, number=2, name="inbox.json")
    ) == {
        "state": state_name,
        "posts": [],
    }


def test_a_session_that_has_had_its_last_round_gets_no_other(resuming, gh):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    ran(root=resuming, number=2, cause=Cause.FINAL)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "MERGED")]), to="pr list")
    scheduling, _, _ = idling(root=resuming, ticks=1)

    scheduling.run()

    assert recorded(scheduling=scheduling).launched is None
    assert not (scheduling.state.sessions / KEY / "rounds" / "3").exists()


def test_a_last_round_that_was_interrupted_is_carried_on_as_the_last_round(
    resuming, gh, left_running
):
    ran(root=resuming, number=1, cause=Cause.DISPATCH)
    write_round(
        directory=StateDirectory(root=resuming).sessions / KEY,
        number=2,
        record=RoundRecord(
            started=PINNED.replace(hour=17, minute=2),
            pid=left_running.pid,
            cause=Cause.FINAL,
        ),
    )
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "MERGED")]), to="pr list")
    scheduling = settling(root=resuming, ticks=2)

    scheduling.run()

    # The carry-on finished what the last round started, so no second one runs.
    assert cause_of(scheduling=scheduling, number=3) is Cause.CARRY_ON
    assert not (scheduling.state.sessions / KEY / "rounds" / "4").exists()


def test_open_work_is_carried_on_before_a_new_issue_is_dispatched(
    resuming, gh, offered, left_running
):
    write_round(
        directory=StateDirectory(root=resuming).sessions / KEY,
        number=1,
        record=RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE),
    )
    scheduling, _, _ = idling(root=resuming, ticks=1)

    scheduling.run()

    assert recorded(scheduling=scheduling).launched == KEY
    assert not (scheduling.state.worktrees / DISPATCHED_KEY).exists()
    assert recorded(scheduling=scheduling).candidates == [
        CandidateIssue(issue=8, label=LABEL)
    ]


def test_a_failed_issue_listing_leaves_open_work_for_a_later_tick(
    resuming, gh, left_running
):
    write_round(
        directory=StateDirectory(root=resuming).sessions / KEY,
        number=1,
        record=RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE),
    )
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")
    scheduling, _, _ = idling(root=resuming, ticks=1)

    scheduling.run()

    assert "could not connect" in held(scheduling=scheduling)
    assert recorded(scheduling=scheduling).launched is None
    assert not (scheduling.state.sessions / KEY / "rounds" / "2").exists()


def test_a_cooling_tick_still_says_what_each_session_is_waiting_on(resuming, offered):
    directory = StateDirectory(root=resuming).sessions / KEY
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
    scheduling, _, _ = idling(root=resuming, ticks=1)

    scheduling.run()

    assert "next attempt at 18:50 UTC" in held(scheduling=scheduling)
    assert recorded(scheduling=scheduling).waiting == [
        WaitingSession(session=KEY, issue=13, reason="the last round failed (exit 1)")
    ]
    assert recorded(scheduling=scheduling).candidates == [
        CandidateIssue(issue=8, label=LABEL)
    ]
