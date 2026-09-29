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
    pages,
    pull_request,
)
from records import write_agent_assignment, write_round

from dreamcatcher.agent_assignments import (
    AgentAssignmentRoundInput,
    advance_user_post_delivery_cursor,
    read_agent_assignments,
)
from dreamcatcher.agent_rounds import (
    AgentAssignmentRoundPurpose,
    AgentRoundPlan,
    AgentRoundRecord,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    compose_agent_round_ending,
)
from dreamcatcher.github import PullRequestState
from dreamcatcher.prompts import AGENT_POST_MARKER, RECOVERY_PROMPT
from dreamcatcher.scheduler import (
    NO_ROUND_HAS_RUN,
    AgentAssignmentObservation,
    FaultedAgentAssignment,
    RequiredAgentRound,
    inspect_agent_assignment,
    prioritize_required_rounds,
)
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158"


@pytest.fixture
def state(tmp_path):
    """A state directory holding one assignment, with no round run yet."""
    directory = StateDirectory(root=tmp_path)
    write_agent_assignment(state=directory, identifier=ASSIGNMENT_ID, issue=13)
    return directory


@pytest.fixture
def gh(gh_with_no_posts):
    """A gh answering with one open pull request that nobody has posted on."""
    gh_with_no_posts.replies(stdout=pull_request(state="OPEN"), to="pr view")
    return gh_with_no_posts


def ran(
    *,
    state,
    number: int,
    purpose: AgentAssignmentRoundPurpose,
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
) -> RequiredAgentRound | FaultedAgentAssignment | AgentAssignmentObservation | None:
    """What the one assignment in that state directory needs next."""
    assignment = read_agent_assignments(state=state)[0]
    return inspect_agent_assignment(
        repository=REPOSITORY,
        account=POSTED_BY,
        assignment=assignment,
        most_recent_cooldown_ended=None,
        observed_at=PINNED,
    )


def test_an_assignment_that_has_run_no_round_at_all_needs_its_first(state):
    first = found(state=state)

    assert isinstance(first, RequiredAgentRound)
    assert first.plan.purpose is AgentAssignmentRoundPurpose.IMPLEMENT
    assert not first.plan.is_recovery
    assert first.reason == NO_ROUND_HAS_RUN
    assert first.prompt == "/dream:smith GH13"


def test_an_assignment_whose_last_round_was_interrupted_is_a_recovery(state, gh):
    ran(
        state=state,
        number=1,
        purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
        status=None,
    )

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert resume.plan.purpose is AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK
    assert resume.plan.is_recovery
    assert resume.reason == "the last round was interrupted"
    assert resume.prompt == RECOVERY_PROMPT
    assert resume.plan.input is None
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_an_interruption_breaks_an_error_sequence(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT, status=2)
    ran(
        state=state,
        number=2,
        purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
        status=None,
    )

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert resume.plan.is_recovery
    assert resume.reason == "the last round was interrupted"


def test_an_assignment_whose_last_round_failed_is_carried_on_with_its_status(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT, status=2)

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert resume.plan.purpose is AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK
    assert resume.plan.is_recovery
    assert resume.reason == "the last round failed (exit 2)"
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_a_terminal_pull_request_makes_an_interrupted_round_a_recovery_wrap_up(
    state, gh
):
    ran(
        state=state,
        number=1,
        purpose=AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK,
        status=None,
    )
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert resume.plan.purpose is AgentAssignmentRoundPurpose.WRAP_UP
    assert resume.plan.is_recovery
    assert resume.plan.input is not None
    assert resume.plan.input.pull_request_state is PullRequestState.MERGED
    assert [post.body for post in resume.plan.input.user_posts] == [
        "have another look at the filter"
    ]
    assert f"pull request #{PULL_REQUEST}" in resume.prompt

    ran(
        state=state,
        number=2,
        purpose=resume.plan.purpose,
        is_recovery=True,
    )

    assert found(state=state) is None


def test_an_assignment_nobody_has_posted_on_needs_nothing(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)

    assert found(state=state) is None
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_a_stopped_assignment_waits_for_feedback(state, gh):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
            started=started,
            pid=1,
            ending=StoppedAgentRoundEnding(at=started),
        ),
    )

    assert found(state=state) is None


def test_a_stopped_assignment_uses_new_feedback_without_recovery(state, gh):
    started = PINNED + timedelta(minutes=1)
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
            started=started,
            pid=1,
            ending=StoppedAgentRoundEnding(at=started),
        ),
    )
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert not resume.plan.is_recovery
    assert resume.prompt.startswith("The user stopped your previous round")


def test_an_assignment_the_user_has_posted_on_answers_what_they_said(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert resume.plan.purpose is AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK
    assert not resume.plan.is_recovery
    assert resume.reason == "1 new post to answer"
    assert resume.plan.input is not None
    assert resume.plan.input.pull_request_state is PullRequestState.OPEN
    assert [post.body for post in resume.plan.input.user_posts] == [
        "have another look at the filter"
    ]


def test_a_draft_pull_request_keeps_implementation_as_its_purpose(
    state, gh_with_no_posts
):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    gh_with_no_posts.replies(
        stdout=pull_request(state="OPEN", is_draft=True), to="pr view"
    )
    gh_with_no_posts.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert resume.plan.purpose is AgentAssignmentRoundPurpose.IMPLEMENT
    assert not resume.plan.is_recovery


def test_a_batch_of_posts_says_how_many_it_holds(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(
            items=[comment(), comment(id=2, created_at="2026-09-03T22:20:55Z")]
        ),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert resume.reason == "2 new posts to answer"


def test_a_post_at_the_assignment_delivery_cursor_wakes_nothing(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    advance_user_post_delivery_cursor(
        assignment=read_agent_assignments(state=state)[0], newest=POSTED_AT
    )

    assert found(state=state) is None


def test_the_prompt_of_a_posts_resume_sends_the_assignment_to_the_next_rounds_inbox(
    state, gh
):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    pull_request_state, user_posts = AgentAssignmentRoundInput.model_fields
    assert f"Read {pull_request_state} before anything else." in resume.prompt
    assert f"act on {user_posts}" in resume.prompt
    assert f"pull request #{PULL_REQUEST}" in resume.prompt
    paths = resume.assignment.compose_round_paths(
        number=resume.assignment.next_round_number
    )
    assert str(paths.round_input) in resume.prompt
    assert paths.directory.name == "2"
    assert AGENT_POST_MARKER in resume.prompt


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_calls_for_one_last_round(
    state, gh, state_name
):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state=state_name), to="pr view")

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert resume.plan.purpose is AgentAssignmentRoundPurpose.WRAP_UP
    assert resume.reason == f"the pull request is {state_name.lower()}"
    assert resume.plan.input == AgentAssignmentRoundInput(
        pull_request_state=state_name, user_posts=[]
    )


def test_a_last_round_carries_what_the_user_said_before_the_merge(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, RequiredAgentRound)
    assert resume.plan.purpose is AgentAssignmentRoundPurpose.WRAP_UP
    assert resume.plan.input is not None
    assert [post.body for post in resume.plan.input.user_posts] == [
        "have another look at the filter"
    ]


def test_an_assignment_whose_last_round_wound_it_up_needs_nothing(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    ran(state=state, number=2, purpose=AgentAssignmentRoundPurpose.WRAP_UP)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")

    assert found(state=state) is None


def test_a_last_round_that_was_carried_on_is_still_the_last_round(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    ran(state=state, number=2, purpose=AgentAssignmentRoundPurpose.WRAP_UP, status=None)
    ran(
        state=state,
        number=3,
        purpose=AgentAssignmentRoundPurpose.WRAP_UP,
        is_recovery=True,
    )
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")

    assert found(state=state) is None


def test_a_pull_request_read_that_failed_leaves_the_assignment_waiting(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")

    waiting = found(state=state)

    assert isinstance(waiting, AgentAssignmentObservation)
    assert waiting.reason.startswith("cannot read its pull request")
    assert not waiting.is_known


def test_a_relay_read_that_failed_leaves_the_assignment_waiting(state, gh):
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    waiting = found(state=state)

    assert isinstance(waiting, AgentAssignmentObservation)
    assert waiting.reason.startswith("cannot tell what the user posted")
    assert not waiting.is_known


def test_the_most_open_work_comes_first(state):
    first_assignment = read_agent_assignments(state=state)[0]
    ran(state=state, number=1, purpose=AgentAssignmentRoundPurpose.IMPLEMENT)
    continued_assignment = read_agent_assignments(state=state)[0]

    def resume(
        *, assignment, purpose: AgentAssignmentRoundPurpose, is_recovery: bool = False
    ) -> RequiredAgentRound:
        return RequiredAgentRound(
            assignment=assignment,
            plan=AgentRoundPlan(purpose=purpose, is_recovery=is_recovery),
            reason="",
            prompt="",
        )

    ordered = prioritize_required_rounds(
        required_rounds=[
            resume(
                assignment=continued_assignment,
                purpose=AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK,
            ),
            resume(
                assignment=continued_assignment,
                purpose=AgentAssignmentRoundPurpose.WRAP_UP,
            ),
            resume(
                assignment=continued_assignment,
                purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
                is_recovery=True,
            ),
            resume(
                assignment=first_assignment,
                purpose=AgentAssignmentRoundPurpose.IMPLEMENT,
            ),
        ]
    )

    assert [
        (not found.assignment.rounds, found.plan.is_recovery, found.plan.purpose)
        for found in ordered
    ] == [
        (True, False, AgentAssignmentRoundPurpose.IMPLEMENT),
        (False, True, AgentAssignmentRoundPurpose.IMPLEMENT),
        (False, False, AgentAssignmentRoundPurpose.WRAP_UP),
        (False, False, AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK),
    ]
