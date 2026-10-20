from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import (
    POST_LIST_PATHS,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    check_run,
    comment,
    configure,
    pages,
    pull_request,
)
from records import HEAD, MERGED_INPUT, read_assignments, write_assignment, write_round

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
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.documents import write_json
from dreamcatcher.github import (
    IssueComment,
    PullRequestSignal,
    PullRequestState,
)
from dreamcatcher.scheduler import Scheduler, SchedulingContext
from dreamcatcher.scheduler.assignments import inspect_open_assignment
from dreamcatcher.scheduler.inspection import Inspection
from dreamcatcher.scheduler.models import PullRequestFinding, ReadFailureFinding
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158-assignment"

# Head commits that the agent pushed after the tests' own HEAD, in order.
PUSHED = "b4e9a1c2d3f405162738495a6b7c8d9e0f1a2b3c"
PUSHED_AGAIN = "c5f0b2d3e4a516273849506b7c8d9e0f1a2b3c4d"

# What gh reports among the checks of a pull request whose build went red.
RED = (check_run(conclusion="FAILURE"),)

# What found answers for an assignment whose next round opens its pull request.
OPENS_PULL_REQUEST = "opens the pull request"


@pytest.fixture
def state(tmp_path):
    """A state directory holding one assignment, with no round run yet."""
    configure(root=tmp_path)
    directory = StateDirectory(root=tmp_path)
    write_assignment(state=directory, identifier=ASSIGNMENT_ID, issue=13)
    return directory


def create_scheduling_context(*, state: StateDirectory) -> SchedulingContext:
    """Create the context that inspects this test state."""
    return SchedulingContext(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=read_dreamcatcher_config(root=state.root),
        state=state,
        clock=lambda: PINNED,
    )


def inspect(*, state: StateDirectory, is_fault: bool = False) -> Inspection:
    """Inspect the one assignment in that state directory."""
    return inspect_open_assignment(
        context=create_scheduling_context(state=state),
        assignment=read_assignments(state=state)[0],
        is_fault=is_fault,
    )


@pytest.fixture
def gh(gh_with_no_posts):
    """A gh answering with one open pull request that nobody has posted on."""
    gh_with_no_posts.replies(stdout=pull_request(state="OPEN"), to="pr view")
    return gh_with_no_posts


def ran(
    *,
    state,
    number: int,
    status: int | None = 0,
    round_input: AssignmentRoundInput | None = None,
) -> None:
    """Write down a round of that assignment, ended as the status says.

    Each round starts a minute after the one before it, which is the order
    they read back in.
    """
    started = PINNED + timedelta(minutes=number)
    ending = (
        InterruptedAgentRoundEnding(at=started)
        if status is None
        else _compose_agent_round_ending(at=started, status=status)
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


def create_scheduler(*, state: StateDirectory) -> Scheduler:
    """Create a scheduler for this test state with no free agent slot to fill."""
    return Scheduler(
        context=create_scheduling_context(state=state),
        preferred_harness=AgentHarness.CLAUDE,
        rounds={},
        max_agents=0,
    )


def found(*, state) -> AssignmentRoundInput | str | ReadFailureFinding | None:
    """What the one assignment in that state directory needs next.

    A round that relays the pull request answers with the input it would be
    given. The round that opens the pull request is given no input prompt, and
    answers OPENS_PULL_REQUEST.
    """
    assignment = read_assignments(state=state)[0]
    inspected = inspect(state=state)
    if inspected.candidate is not None:
        plan = inspected.candidate.compose_round(work=assignment)
        if plan.input_prompt is None:
            return OPENS_PULL_REQUEST
        round_input = plan.prepare_round()
        assert isinstance(round_input, AssignmentRoundInput)
        return round_input
    if isinstance(inspected.row.finding, ReadFailureFinding):
        return inspected.row.finding
    return None


def test_an_assignment_with_no_pull_request_yet_needs_its_first_round(tmp_path):
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13, pull_request=None)

    assert found(state=state) == OPENS_PULL_REQUEST


def test_a_first_round_that_failed_before_its_pull_request_is_tried_again(
    tmp_path,
):
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13, pull_request=None)
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            ending=ErroredAgentRoundEnding(at=PINNED, reason="git push failed"),
        ),
    )

    assert found(state=state) == OPENS_PULL_REQUEST
    assert inspect(state=state).row.finding is None


def test_an_assignment_in_fault_reads_nothing_and_counts_its_fault(tmp_path):
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13, pull_request=None)
    for number in (1, 2):
        write_round(
            directory=state.work / ASSIGNMENT_ID,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=PINNED + timedelta(minutes=number),
                ending=ErroredAgentRoundEnding(
                    at=PINNED + timedelta(minutes=number), reason="git push failed"
                ),
            ),
        )

    inspected = inspect(state=state, is_fault=True)

    assert inspected.candidate is None
    assert inspected.row.finding is None
    assert inspected.is_counted_fault


def test_an_assignment_whose_last_round_was_interrupted_is_given_its_input_again(
    state, gh
):
    ran(
        state=state,
        number=1,
        status=None,
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.user_posts == []
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_an_interruption_breaks_an_error_sequence(state, gh):
    ran(state=state, number=1, status=2)
    ran(
        state=state,
        number=2,
        status=None,
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)


def test_an_assignment_whose_last_round_failed_is_carried_on_with_its_status(state, gh):
    ran(state=state, number=1, status=2)

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_a_terminal_pull_request_makes_an_interrupted_round_a_wrap_up(state, gh):
    ran(
        state=state,
        number=1,
        status=None,
    )
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.pull_request_state is PullRequestState.MERGED
    assert [post.body for post in resume.user_posts] == [
        "have another look at the filter"
    ]

    ran(
        state=state,
        number=2,
        round_input=AssignmentRoundInput(
            pull_request_state=resume.pull_request_state,
            pull_request_head=HEAD,
            signals=[],
            user_posts=resume.user_posts,
        ),
    )

    assert found(state=state) is None


def test_an_assignment_nobody_has_posted_on_needs_nothing(state, gh):
    ran(state=state, number=1)

    assert found(state=state) is None
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_a_stopped_assignment_waits_for_feedback(state, gh):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=started,
            pid=1,
            ending=StoppedAgentRoundEnding(at=started),
        ),
    )

    assert found(state=state) is None


@pytest.mark.parametrize("pull_request_state", ["CLOSED", "MERGED"])
def test_a_terminal_pull_request_wraps_up_a_stopped_assignment(
    state, gh_with_no_posts, pull_request_state
):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=started,
            pid=1,
            ending=StoppedAgentRoundEnding(at=started),
        ),
    )
    gh_with_no_posts.replies(
        stdout=pull_request(state=pull_request_state), to="pr view"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.pull_request_state is PullRequestState(pull_request_state)
    assert resume.user_posts == []


@pytest.mark.parametrize("pull_request_state", ["CLOSED", "MERGED"])
def test_a_stopped_last_round_is_not_given_the_finished_pull_request_again(
    state, gh_with_no_posts, pull_request_state
):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=started,
            pid=1,
            ending=StoppedAgentRoundEnding(at=started),
        ),
    )
    write_json(
        document=AssignmentRoundInput(
            pull_request_state=PullRequestState(pull_request_state),
            pull_request_head=HEAD,
            signals=[],
            user_posts=[],
        ),
        path=read_assignments(state=state)[0].compose_round_paths(number=1).round_input,
    )
    gh_with_no_posts.replies(
        stdout=pull_request(state=pull_request_state), to="pr view"
    )

    assert found(state=state) is None


def test_a_stopped_assignment_uses_new_feedback(state, gh):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=started,
            pid=1,
            ending=StoppedAgentRoundEnding(at=started),
        ),
    )
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert len(resume.user_posts) == 1


def test_a_cancelled_assignment_is_not_inspected_for_rounds(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    gh.replies(stdout="[]", to="issue list")
    cancel_assignment(assignment=read_assignments(state=state)[0], at=PINNED)

    observed = create_scheduler(state=state).tick(at=PINNED)

    assert observed.rows == []
    assert [call.arguments[:2] for call in gh.calls] == [["issue", "list"]]


def test_a_round_started_for_an_assignment_cancelled_after_inspection_stops(
    state, gh, harnesses
):
    ran(state=state, number=1, status=2)
    inspected = inspect(state=state)
    assert inspected.candidate is not None
    cancel_assignment(assignment=read_assignments(state=state)[0], at=PINNED)

    started = create_scheduler(state=state)._launch(
        row=inspected.row, candidate=inspected.candidate, at=PINNED
    )
    started.wait()

    assert started.paths.stop_request.is_file()


def test_an_assignment_the_user_has_posted_on_answers_what_they_said(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.pull_request_state is PullRequestState.OPEN
    assert [post.body for post in resume.user_posts] == [
        "have another look at the filter"
    ]


def test_a_post_on_a_draft_pull_request_wakes_its_assignment(state, gh_with_no_posts):
    ran(state=state, number=1)
    gh_with_no_posts.replies(
        stdout=pull_request(state="OPEN", is_draft=True), to="pr view"
    )
    gh_with_no_posts.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)


def test_a_batch_of_posts_says_how_many_it_holds(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pages(
            items=[comment(), comment(id=2, created_at="2026-09-03T22:20:55Z")]
        ),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert len(resume.user_posts) == 2


def test_a_post_at_the_assignment_cursor_wakes_nothing(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    assignment = read_assignments(state=state)[0]
    write_json(
        document=AssignmentRoundInput(
            pull_request_state=PullRequestState.OPEN,
            pull_request_head=HEAD,
            signals=[],
            user_posts=[IssueComment.model_validate(comment())],
        ),
        path=assignment.compose_round_paths(number=1).round_input,
    )

    assert found(state=state) is None


def test_a_posts_resume_carries_the_facts_launch_will_prepare(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.pull_request_state is PullRequestState.OPEN
    assert [post.body for post in resume.user_posts] == [
        "have another look at the filter"
    ]


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_calls_for_one_last_round(
    state, gh, state_name
):
    ran(state=state, number=1)
    gh.replies(stdout=pull_request(state=state_name), to="pr view")

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.pull_request_state is PullRequestState(state_name)
    assert resume.user_posts == []


def test_a_last_round_carries_what_the_user_said_before_the_merge(state, gh):
    ran(state=state, number=1)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert [post.body for post in resume.user_posts] == [
        "have another look at the filter"
    ]


def test_an_assignment_whose_last_round_wound_it_up_needs_nothing(state, gh):
    ran(state=state, number=1)
    ran(state=state, number=2, round_input=MERGED_INPUT)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")

    assert found(state=state) is None


def test_a_last_round_that_was_carried_on_is_still_the_last_round(state, gh):
    ran(state=state, number=1)
    ran(state=state, number=2, status=None, round_input=MERGED_INPUT)
    ran(state=state, number=3, round_input=MERGED_INPUT)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")

    assert found(state=state) is None


def test_a_failed_pull_request_read_leaves_the_assignment_unknown(state, gh):
    ran(state=state, number=1)
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")

    waiting = found(state=state)

    assert isinstance(waiting, ReadFailureFinding)
    assert "could not connect" in waiting.reason


def test_a_failed_user_post_read_leaves_the_assignment_unknown(state, gh):
    ran(state=state, number=1)
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    waiting = found(state=state)

    assert isinstance(waiting, ReadFailureFinding)
    assert "could not connect" in waiting.reason


def relayed(
    *, signals: list[PullRequestSignal], head: str = HEAD, posts: int = 0
) -> AssignmentRoundInput:
    """Return the input of a round that relayed these signals at this head."""
    return AssignmentRoundInput(
        pull_request_state=PullRequestState.OPEN,
        pull_request_head=head,
        signals=signals,
        user_posts=[
            IssueComment.model_validate(comment(id=number))
            for number in range(1, posts + 1)
        ],
    )


def pull_request_finding(*, state) -> PullRequestFinding:
    """Return what the tick found of the one assignment's pull request."""
    finding = inspect(state=state).row.finding
    assert isinstance(finding, PullRequestFinding)
    return finding


@pytest.mark.parametrize("merge_state", ["BEHIND", "DIRTY"])
def test_a_ready_pull_request_that_main_moved_under_wakes_its_assignment(
    state, gh, merge_state
):
    ran(state=state, number=1)
    gh.replies(stdout=pull_request(state="OPEN", merge_state=merge_state), to="pr view")

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.signals == [PullRequestSignal.OUT_OF_DATE]
    assert resume.pull_request_head == HEAD
    assert pull_request_finding(state=state).new_pull_request_signals == [
        PullRequestSignal.OUT_OF_DATE
    ]


def test_an_out_of_date_pull_request_is_relayed_once_at_each_head(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.OUT_OF_DATE]),
    )
    gh.replies(stdout=pull_request(state="OPEN", merge_state="BEHIND"), to="pr view")

    assert found(state=state) is None


def test_main_moving_again_after_a_push_wakes_the_assignment_again(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.OUT_OF_DATE]),
    )
    gh.replies(
        stdout=pull_request(state="OPEN", merge_state="BEHIND", head=PUSHED),
        to="pr view",
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.signals == [PullRequestSignal.OUT_OF_DATE]
    assert resume.pull_request_head == PUSHED


@pytest.mark.parametrize(
    "checks", [(check_run(),), (check_run(status="IN_PROGRESS"),), ()]
)
def test_a_green_running_or_unchecked_pull_request_wakes_nothing(state, gh, checks):
    ran(state=state, number=1)
    gh.replies(stdout=pull_request(state="OPEN", checks=checks), to="pr view")

    assert found(state=state) is None


def test_a_red_check_wakes_the_assignment(state, gh):
    ran(state=state, number=1)
    gh.replies(stdout=pull_request(state="OPEN", checks=RED), to="pr view")

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.signals == [PullRequestSignal.CHECK_FAILURE]


def test_a_red_check_is_relayed_once_at_each_head(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE]),
    )
    gh.replies(stdout=pull_request(state="OPEN", checks=RED), to="pr view")

    assert found(state=state) is None
    assert not pull_request_finding(state=state).is_check_failure_withheld


def test_a_red_check_after_one_attempt_wakes_the_assignment_a_second_time(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE]),
    )
    gh.replies(stdout=pull_request(state="OPEN", checks=RED, head=PUSHED), to="pr view")

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.signals == [PullRequestSignal.CHECK_FAILURE]


def test_a_red_check_after_two_attempts_waits_for_the_user(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE]),
    )
    ran(
        state=state,
        number=3,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE], head=PUSHED),
    )
    gh.replies(
        stdout=pull_request(state="OPEN", checks=RED, head=PUSHED_AGAIN), to="pr view"
    )

    assert found(state=state) is None
    finding = pull_request_finding(state=state)
    assert finding.new_pull_request_signals == []
    assert finding.is_check_failure_withheld


def test_a_post_after_two_attempts_still_wakes_the_assignment(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE]),
    )
    ran(
        state=state,
        number=3,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE], head=PUSHED),
    )
    gh.replies(
        stdout=pull_request(state="OPEN", checks=RED, head=PUSHED_AGAIN), to="pr view"
    )
    gh.replies(
        stdout=pages(items=[comment(created_at="2026-09-04T09:00:00Z")]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.signals == []
    assert len(resume.user_posts) == 1


def test_a_round_woken_by_a_post_breaks_a_run_of_red_checks(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE]),
    )
    ran(state=state, number=3, round_input=relayed(signals=[], head=PUSHED, posts=1))
    gh.replies(
        stdout=pull_request(state="OPEN", checks=RED, head=PUSHED_AGAIN), to="pr view"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.signals == [PullRequestSignal.CHECK_FAILURE]


def test_a_round_that_errored_does_not_count_as_an_attempt(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE]),
    )
    ran(
        state=state,
        number=3,
        status=1,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE], head=PUSHED),
    )
    gh.replies(stdout=pull_request(state="OPEN", checks=RED, head=PUSHED), to="pr view")

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.signals == [PullRequestSignal.CHECK_FAILURE]


def test_a_draft_raises_neither_signal(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pull_request(
            state="OPEN", is_draft=True, merge_state="BEHIND", checks=RED
        ),
        to="pr view",
    )

    assert found(state=state) is None
    assert pull_request_finding(state=state).new_pull_request_signals == []


def test_a_merged_pull_request_raises_no_signal_in_its_last_round(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pull_request(state="MERGED", merge_state="UNKNOWN", checks=RED),
        to="pr view",
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.pull_request_state is PullRequestState.MERGED
    assert resume.signals == []


def test_a_round_woken_by_a_signal_is_told_of_it_before_its_input(state, gh):
    ran(state=state, number=1)
    gh.replies(stdout=pull_request(state="OPEN", checks=RED), to="pr view")
    candidate = inspect(state=state).candidate
    assert candidate is not None

    plan = candidate.compose_round(work=read_assignments(state=state)[0])

    assert plan.input_prompt is not None
    assert plan.input_prompt.startswith("Checks failed on your pull request's")


def test_each_signal_is_relayed_against_its_own_last_head(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE], head=PUSHED),
    )
    ran(
        state=state,
        number=3,
        round_input=relayed(signals=[PullRequestSignal.OUT_OF_DATE], head=PUSHED_AGAIN),
    )
    gh.replies(
        stdout=pull_request(
            state="OPEN", merge_state="BEHIND", checks=RED, head=PUSHED_AGAIN
        ),
        to="pr view",
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.signals == [PullRequestSignal.CHECK_FAILURE]


def test_a_withheld_check_failure_leaves_an_out_of_date_signal_to_relay(state, gh):
    ran(state=state, number=1)
    ran(
        state=state,
        number=2,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE]),
    )
    ran(
        state=state,
        number=3,
        round_input=relayed(signals=[PullRequestSignal.CHECK_FAILURE], head=PUSHED),
    )
    gh.replies(
        stdout=pull_request(
            state="OPEN", merge_state="DIRTY", checks=RED, head=PUSHED_AGAIN
        ),
        to="pr view",
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundInput)
    assert resume.signals == [PullRequestSignal.OUT_OF_DATE]
    assert pull_request_finding(state=state).is_check_failure_withheld
