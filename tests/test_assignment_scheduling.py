from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import (
    POST_LIST_PATHS,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    comment,
    configure,
    pages,
    pull_request,
)
from records import MERGED_INPUT, read_assignments, write_assignment, write_round

from dreamcatcher.agent_assignments import (
    AssignmentRoundInput,
    cancel_assignment,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.documents import write_json
from dreamcatcher.github import ConversationComment, PullRequest, PullRequestState
from dreamcatcher.scheduler.assignments import (
    AssignmentRoundCandidate,
    AssignmentScheduler,
    FirstAssignmentRoundCandidate,
    NewAssignmentCandidate,
)
from dreamcatcher.scheduler.models import (
    AgentWorkObservation,
    Truth,
)
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158-assignment"


@pytest.fixture
def state(tmp_path):
    """A state directory holding one assignment, with no round run yet."""
    configure(root=tmp_path)
    directory = StateDirectory(root=tmp_path)
    write_assignment(state=directory, identifier=ASSIGNMENT_ID, issue=13)
    return directory


def create_assignment_scheduler(*, state: StateDirectory) -> AssignmentScheduler:
    """Create the assignment scheduler that inspects this test state."""
    return AssignmentScheduler(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=read_dreamcatcher_config(root=state.root),
        state=state,
        preferred_harness=AgentHarness.CLAUDE,
        clock=lambda: PINNED,
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
        InterruptedAgentRoundEnding()
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


def found(
    *, state
) -> (
    FirstAssignmentRoundCandidate
    | AssignmentRoundCandidate
    | AgentWorkObservation
    | None
):
    """What the one assignment in that state directory needs next."""
    assignment = read_assignments(state=state)[0]
    if not assignment.is_open:
        return None
    inspected = create_assignment_scheduler(state=state)._inspect_assignment(
        assignment=assignment,
        most_recent_cooldown_ended=None,
        observed_at=PINNED,
    )
    if inspected.candidate is not None:
        assert not isinstance(inspected.candidate, NewAssignmentCandidate)
        return inspected.candidate
    if inspected.observation.requires_round.value is not Truth.FALSE:
        return inspected.observation
    return None


def test_an_assignment_that_has_run_no_round_at_all_needs_its_first(state):
    first = found(state=state)

    assert isinstance(first, FirstAssignmentRoundCandidate)
    assert first.assignment.record.issue == 13


def test_an_assignment_whose_last_round_was_interrupted_is_given_its_input_again(
    state, gh
):
    ran(
        state=state,
        number=1,
        status=None,
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert resume.undelivered_posts == []
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_an_interruption_breaks_an_error_sequence(state, gh):
    ran(state=state, number=1, status=2)
    ran(
        state=state,
        number=2,
        status=None,
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)


def test_an_assignment_whose_last_round_failed_is_carried_on_with_its_status(state, gh):
    ran(state=state, number=1, status=2)

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
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

    assert isinstance(resume, AssignmentRoundCandidate)
    assert resume.pull_request.state is PullRequestState.MERGED
    assert [post.body for post in resume.undelivered_posts] == [
        "have another look at the filter"
    ]

    ran(
        state=state,
        number=2,
        round_input=AssignmentRoundInput(
            pull_request_state=resume.pull_request.state,
            user_posts=resume.undelivered_posts,
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

    assert isinstance(resume, AssignmentRoundCandidate)
    assert resume.pull_request.state is PullRequestState(pull_request_state)
    assert resume.undelivered_posts == []


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
            pull_request_state=PullRequestState(pull_request_state), user_posts=[]
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

    assert isinstance(resume, AssignmentRoundCandidate)
    assert len(resume.undelivered_posts) == 1


def test_a_cancelled_assignment_is_not_inspected_for_rounds(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    cancel_assignment(assignment=read_assignments(state=state)[0], at=PINNED)

    inspected = create_assignment_scheduler(state=state)._inspect_assignments(
        assignments=read_assignments(state=state),
        most_recent_cooldown_ended=None,
        observed_at=PINNED,
    )

    assert inspected == []
    assert gh.calls == []


def test_a_round_started_for_an_assignment_cancelled_after_inspection_stops(
    state, harnesses
):
    candidate = FirstAssignmentRoundCandidate(
        assignment=read_assignments(state=state)[0]
    )
    cancel_assignment(assignment=candidate.assignment, at=PINNED)

    started = create_assignment_scheduler(state=state).launch(
        candidate=candidate, at=PINNED
    )
    started.wait()

    assert started.paths.stop_request.is_file()


def test_an_assignment_the_user_has_posted_on_answers_what_they_said(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert resume.pull_request.state is PullRequestState.OPEN
    assert [post.body for post in resume.undelivered_posts] == [
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

    assert isinstance(resume, AssignmentRoundCandidate)


def test_a_batch_of_posts_says_how_many_it_holds(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pages(
            items=[comment(), comment(id=2, created_at="2026-09-03T22:20:55Z")]
        ),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert len(resume.undelivered_posts) == 2


def test_a_post_at_the_assignment_delivery_position_wakes_nothing(state, gh):
    ran(state=state, number=1)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    assignment = read_assignments(state=state)[0]
    write_json(
        document=AssignmentRoundInput(
            pull_request_state=PullRequestState.OPEN,
            user_posts=[ConversationComment.model_validate(comment())],
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

    assert isinstance(resume, AssignmentRoundCandidate)
    assert resume.pull_request.number == PULL_REQUEST
    assert resume.pull_request.state is PullRequestState.OPEN
    assert [post.body for post in resume.undelivered_posts] == [
        "have another look at the filter"
    ]


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_calls_for_one_last_round(
    state, gh, state_name
):
    ran(state=state, number=1)
    gh.replies(stdout=pull_request(state=state_name), to="pr view")

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert resume.pull_request.state is PullRequestState(state_name)
    assert resume.undelivered_posts == []


def test_a_last_round_carries_what_the_user_said_before_the_merge(state, gh):
    ran(state=state, number=1)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert [post.body for post in resume.undelivered_posts] == [
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


def test_a_pull_request_read_that_failed_leaves_the_assignment_waiting(state, gh):
    ran(state=state, number=1)
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")

    waiting = found(state=state)

    assert isinstance(waiting, AgentWorkObservation)
    assert waiting.requires_round.evidence.startswith("cannot read its pull request")
    assert waiting.requires_round.value is Truth.UNKNOWN


def test_a_relay_read_that_failed_leaves_the_assignment_waiting(state, gh):
    ran(state=state, number=1)
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    waiting = found(state=state)

    assert isinstance(waiting, AgentWorkObservation)
    assert waiting.requires_round.evidence.startswith(
        "cannot tell what the user posted"
    )
    assert waiting.requires_round.value is Truth.UNKNOWN


def test_existing_work_comes_before_new_work(state):
    first_assignment = read_assignments(state=state)[0]
    ran(state=state, number=1)
    continued_assignment = read_assignments(state=state)[0]
    new = NewAssignmentCandidate(
        issue=8,
        title="Issue 8",
        route=create_assignment_scheduler(state=state).config.assignment[0],
    )
    continued = AssignmentRoundCandidate(
        assignment=continued_assignment,
        pull_request=PullRequest(
            number=PULL_REQUEST, state=PullRequestState.MERGED, is_draft=False
        ),
        undelivered_posts=[],
    )
    first = FirstAssignmentRoundCandidate(assignment=first_assignment)

    ordered = sorted(
        [new, continued, first], key=create_assignment_scheduler(state=state).rank
    )

    assert ordered == [continued, first, new]
