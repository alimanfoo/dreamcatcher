from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import (
    POST_LIST_PATHS,
    POSTED_AT,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    comment,
    configure,
    pages,
    pull_request,
)
from records import write_assignment, write_round

from dreamcatcher.agent_assignments import (
    advance_user_post_delivery_cursor,
    read_assignments,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    AssignmentRoundPurpose,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    compose_agent_round_ending,
)
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.github import PullRequest, PullRequestState
from dreamcatcher.scheduler.assignments import (
    AssignmentRoundCandidate,
    AssignmentScheduler,
    FirstAssignmentRoundCandidate,
    NewAssignmentCandidate,
)
from dreamcatcher.scheduler.models import AssignmentObservation, derive_round_purpose
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158"


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
        requested_harness=AgentHarness.CLAUDE,
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
    purpose: AssignmentRoundPurpose,
    status: int | None = 0,
    is_recovery: bool = False,
) -> None:
    """Write down a round of that assignment, ended as the status says.

    Each round starts a minute after the one before it, which is the order
    they read back in.
    """
    started = PINNED + timedelta(minutes=number)
    ending = (
        InterruptedAgentRoundEnding()
        if status is None
        else compose_agent_round_ending(at=started, status=status)
    )
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
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


def found(
    *, state
) -> (
    FirstAssignmentRoundCandidate
    | AssignmentRoundCandidate
    | AssignmentObservation
    | None
):
    """What the one assignment in that state directory needs next."""
    assignment = read_assignments(state=state)[0]
    if assignment.is_complete:
        return None
    inspected = create_assignment_scheduler(state=state)._inspect_assignment(
        assignment=assignment,
        most_recent_cooldown_ended=None,
        observed_at=PINNED,
    )
    if inspected.candidate is not None:
        assert not isinstance(inspected.candidate, NewAssignmentCandidate)
        return inspected.candidate
    if inspected.observation.is_round_required or not inspected.observation.is_known:
        return inspected.observation
    return None


def test_an_assignment_that_has_run_no_round_at_all_needs_its_first(state):
    first = found(state=state)

    assert isinstance(first, FirstAssignmentRoundCandidate)
    assert first.assignment.record.issue == 13


def test_an_assignment_whose_last_round_was_interrupted_is_a_recovery(state, gh):
    ran(
        state=state,
        number=1,
        purpose=AssignmentRoundPurpose.IMPLEMENT,
        status=None,
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert derive_round_purpose(pull_request=resume.pull_request) is (
        AssignmentRoundPurpose.ADDRESS_FEEDBACK
    )
    assert resume.recovery_reason == "the last round was interrupted"
    assert resume.undelivered_posts == []
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_an_interruption_breaks_an_error_sequence(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT, status=2)
    ran(
        state=state,
        number=2,
        purpose=AssignmentRoundPurpose.IMPLEMENT,
        status=None,
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert resume.recovery_reason == "the last round was interrupted"


def test_an_assignment_whose_last_round_failed_is_carried_on_with_its_status(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT, status=2)

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert derive_round_purpose(pull_request=resume.pull_request) is (
        AssignmentRoundPurpose.ADDRESS_FEEDBACK
    )
    assert resume.recovery_reason == "the last round failed (exit 2)"
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_a_terminal_pull_request_makes_an_interrupted_round_a_recovery_wrap_up(
    state, gh
):
    ran(
        state=state,
        number=1,
        purpose=AssignmentRoundPurpose.ADDRESS_FEEDBACK,
        status=None,
    )
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert derive_round_purpose(pull_request=resume.pull_request) is (
        AssignmentRoundPurpose.WRAP_UP
    )
    assert resume.recovery_reason == "the last round was interrupted"
    assert resume.pull_request.state is PullRequestState.MERGED
    assert [post.body for post in resume.undelivered_posts] == [
        "have another look at the filter"
    ]

    ran(
        state=state,
        number=2,
        purpose=derive_round_purpose(pull_request=resume.pull_request),
        is_recovery=True,
    )

    assert found(state=state) is None


def test_an_assignment_nobody_has_posted_on_needs_nothing(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)

    assert found(state=state) is None
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_a_stopped_assignment_waits_for_feedback(state, gh):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
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
        directory=state.assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AssignmentRoundPurpose.WRAP_UP,
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
    assert derive_round_purpose(pull_request=resume.pull_request) is (
        AssignmentRoundPurpose.WRAP_UP
    )
    assert resume.recovery_reason is None
    assert resume.pull_request.state is PullRequestState(pull_request_state)
    assert resume.undelivered_posts == []


def test_a_stopped_assignment_uses_new_feedback_without_recovery(state, gh):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
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
    assert resume.recovery_reason is None
    assert len(resume.undelivered_posts) == 1


def test_an_assignment_the_user_has_posted_on_answers_what_they_said(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert derive_round_purpose(pull_request=resume.pull_request) is (
        AssignmentRoundPurpose.ADDRESS_FEEDBACK
    )
    assert resume.recovery_reason is None
    assert resume.pull_request.state is PullRequestState.OPEN
    assert [post.body for post in resume.undelivered_posts] == [
        "have another look at the filter"
    ]


def test_a_draft_pull_request_keeps_implementation_as_its_purpose(
    state, gh_with_no_posts
):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh_with_no_posts.replies(
        stdout=pull_request(state="OPEN", is_draft=True), to="pr view"
    )
    gh_with_no_posts.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert derive_round_purpose(pull_request=resume.pull_request) is (
        AssignmentRoundPurpose.IMPLEMENT
    )
    assert resume.recovery_reason is None


def test_a_batch_of_posts_says_how_many_it_holds(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(
            items=[comment(), comment(id=2, created_at="2026-09-03T22:20:55Z")]
        ),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert len(resume.undelivered_posts) == 2


def test_a_post_at_the_assignment_delivery_cursor_wakes_nothing(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    advance_user_post_delivery_cursor(
        assignment=read_assignments(state=state)[0], newest=POSTED_AT
    )

    assert found(state=state) is None


def test_a_posts_resume_carries_the_facts_launch_will_prepare(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
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
    assert resume.recovery_reason is None


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_calls_for_one_last_round(
    state, gh, state_name
):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state=state_name), to="pr view")

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert derive_round_purpose(pull_request=resume.pull_request) is (
        AssignmentRoundPurpose.WRAP_UP
    )
    assert resume.pull_request.state is PullRequestState(state_name)
    assert resume.undelivered_posts == []


def test_a_last_round_carries_what_the_user_said_before_the_merge(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, AssignmentRoundCandidate)
    assert derive_round_purpose(pull_request=resume.pull_request) is (
        AssignmentRoundPurpose.WRAP_UP
    )
    assert [post.body for post in resume.undelivered_posts] == [
        "have another look at the filter"
    ]


def test_an_assignment_whose_last_round_wound_it_up_needs_nothing(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    ran(state=state, number=2, purpose=AssignmentRoundPurpose.WRAP_UP)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")

    assert found(state=state) is None


def test_a_last_round_that_was_carried_on_is_still_the_last_round(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    ran(state=state, number=2, purpose=AssignmentRoundPurpose.WRAP_UP, status=None)
    ran(
        state=state,
        number=3,
        purpose=AssignmentRoundPurpose.WRAP_UP,
        is_recovery=True,
    )
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")

    assert found(state=state) is None


def test_a_pull_request_read_that_failed_leaves_the_assignment_waiting(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")

    waiting = found(state=state)

    assert isinstance(waiting, AssignmentObservation)
    assert waiting.reason.startswith("cannot read its pull request")
    assert not waiting.is_known


def test_a_relay_read_that_failed_leaves_the_assignment_waiting(state, gh):
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    waiting = found(state=state)

    assert isinstance(waiting, AssignmentObservation)
    assert waiting.reason.startswith("cannot tell what the user posted")
    assert not waiting.is_known


def test_the_most_open_work_comes_first(state):
    first_assignment = read_assignments(state=state)[0]
    ran(state=state, number=1, purpose=AssignmentRoundPurpose.IMPLEMENT)
    continued_assignment = read_assignments(state=state)[0]

    def resume(
        *, assignment, purpose: AssignmentRoundPurpose, is_recovery: bool = False
    ) -> AssignmentRoundCandidate:
        is_open = purpose is not AssignmentRoundPurpose.WRAP_UP
        return AssignmentRoundCandidate(
            assignment=assignment,
            pull_request=PullRequest(
                number=PULL_REQUEST,
                state=(PullRequestState.OPEN if is_open else PullRequestState.MERGED),
                is_draft=purpose is AssignmentRoundPurpose.IMPLEMENT,
            ),
            undelivered_posts=[],
            recovery_reason="unfinished" if is_recovery else None,
        )

    scheduler = create_assignment_scheduler(state=state)
    ordered = sorted(
        [
            resume(
                assignment=continued_assignment,
                purpose=AssignmentRoundPurpose.ADDRESS_FEEDBACK,
            ),
            resume(
                assignment=continued_assignment,
                purpose=AssignmentRoundPurpose.WRAP_UP,
            ),
            resume(
                assignment=continued_assignment,
                purpose=AssignmentRoundPurpose.IMPLEMENT,
                is_recovery=True,
            ),
            FirstAssignmentRoundCandidate(assignment=first_assignment),
        ],
        key=scheduler.rank,
    )

    assert [
        (
            isinstance(found, FirstAssignmentRoundCandidate),
            (
                False
                if isinstance(found, FirstAssignmentRoundCandidate)
                else found.recovery_reason is not None
            ),
            (
                AssignmentRoundPurpose.IMPLEMENT
                if isinstance(found, FirstAssignmentRoundCandidate)
                else derive_round_purpose(pull_request=found.pull_request)
            ),
        )
        for found in ordered
    ] == [
        (True, False, AssignmentRoundPurpose.IMPLEMENT),
        (False, True, AssignmentRoundPurpose.IMPLEMENT),
        (False, False, AssignmentRoundPurpose.WRAP_UP),
        (False, False, AssignmentRoundPurpose.ADDRESS_FEEDBACK),
    ]
