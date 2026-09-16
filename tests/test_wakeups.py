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
    advance_assignment_watermark,
    read_agent_assignments,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    InterruptedAgentRoundEnding,
    RoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.github import PullRequestState
from dreamcatcher.prompts import CARRY_ON_PROMPT, MARKER
from dreamcatcher.relay import Inbox
from dreamcatcher.state import NO_ROUND_HAS_RUN, StateDirectory, WaitingAgentAssignment
from dreamcatcher.wakeups import Wakeup, judge_assignment, sort_wakeups

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
    purpose: RoundPurpose,
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


def found(*, state) -> Wakeup | WaitingAgentAssignment | None:
    """What the one assignment in that state directory needs next."""
    return judge_assignment(
        repository=REPOSITORY,
        account=POSTED_BY,
        assignment=read_agent_assignments(state=state)[0],
    )


def test_an_assignment_that_has_run_no_round_at_all_needs_its_first(state):
    first = found(state=state)

    assert isinstance(first, Wakeup)
    assert first.purpose is RoundPurpose.IMPLEMENT
    assert not first.is_recovery
    assert first.reason == NO_ROUND_HAS_RUN
    assert first.prompt == "/dream:smith GH13"


def test_an_assignment_whose_last_round_was_interrupted_is_a_recovery(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT, status=None)

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.purpose is RoundPurpose.ADDRESS_FEEDBACK
    assert resume.is_recovery
    assert resume.reason == "the last round was interrupted"
    assert resume.prompt == CARRY_ON_PROMPT
    assert resume.inbox is None
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_an_assignment_whose_last_round_failed_is_carried_on_with_its_status(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT, status=2)

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.purpose is RoundPurpose.ADDRESS_FEEDBACK
    assert resume.is_recovery
    assert resume.reason == "the last round failed (exit 2)"
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_a_terminal_pull_request_makes_an_interrupted_round_a_recovery_wrap_up(
    state, gh
):
    ran(
        state=state,
        number=1,
        purpose=RoundPurpose.ADDRESS_FEEDBACK,
        status=None,
    )
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.purpose is RoundPurpose.WRAP_UP
    assert resume.is_recovery
    assert resume.inbox is not None
    assert resume.inbox.state is PullRequestState.MERGED
    assert [post.body for post in resume.inbox.posts] == [
        "have another look at the filter"
    ]
    assert f"pull request #{PULL_REQUEST}" in resume.prompt

    ran(
        state=state,
        number=2,
        purpose=resume.purpose,
        is_recovery=True,
    )

    assert found(state=state) is None


def test_an_assignment_nobody_has_posted_on_needs_nothing(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)

    assert found(state=state) is None
    assert gh.calls[0].arguments[:3] == ["pr", "view", str(PULL_REQUEST)]


def test_an_assignment_the_user_has_posted_on_answers_what_they_said(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.purpose is RoundPurpose.ADDRESS_FEEDBACK
    assert not resume.is_recovery
    assert resume.reason == "1 new post to answer"
    assert resume.inbox is not None
    assert resume.inbox.state is PullRequestState.OPEN
    assert [post.body for post in resume.inbox.posts] == [
        "have another look at the filter"
    ]
    assert resume.newest_post == POSTED_AT


def test_a_draft_pull_request_keeps_implementation_as_its_purpose(
    state, gh_with_no_posts
):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    gh_with_no_posts.replies(
        stdout=pull_request(state="OPEN", is_draft=True), to="pr view"
    )
    gh_with_no_posts.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.purpose is RoundPurpose.IMPLEMENT
    assert not resume.is_recovery


def test_a_batch_of_posts_says_how_many_it_holds(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(
            posts=[comment(), comment(id=2, created_at="2026-09-03T22:20:55Z")]
        ),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.reason == "2 new posts to answer"


def test_a_post_the_assignment_has_been_told_about_already_wakes_nothing(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    advance_assignment_watermark(
        assignment=read_agent_assignments(state=state)[0], newest=POSTED_AT
    )

    assert found(state=state) is None


def test_the_prompt_of_a_posts_resume_sends_the_assignment_to_the_next_rounds_inbox(
    state, gh
):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert f"pull request #{PULL_REQUEST}" in resume.prompt
    paths = resume.assignment.round_paths(number=resume.assignment.next_round_number)
    assert str(paths.inbox) in resume.prompt
    assert paths.directory.name == "2"
    assert MARKER in resume.prompt


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_calls_for_one_last_round(
    state, gh, state_name
):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state=state_name), to="pr view")

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.purpose is RoundPurpose.WRAP_UP
    assert resume.reason == f"the pull request is {state_name.lower()}"
    assert resume.inbox == Inbox(state=state_name, posts=[])
    assert resume.newest_post == ""


def test_a_last_round_carries_what_the_user_said_before_the_merge(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.purpose is RoundPurpose.WRAP_UP
    assert resume.inbox is not None
    assert [post.body for post in resume.inbox.posts] == [
        "have another look at the filter"
    ]


def test_an_assignment_whose_last_round_wound_it_up_needs_nothing(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    ran(state=state, number=2, purpose=RoundPurpose.WRAP_UP)
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")

    assert found(state=state) is None


def test_a_last_round_that_was_carried_on_is_still_the_last_round(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    ran(state=state, number=2, purpose=RoundPurpose.WRAP_UP, status=None)
    ran(
        state=state,
        number=3,
        purpose=RoundPurpose.WRAP_UP,
        is_recovery=True,
    )
    gh.replies(stdout=pull_request(state="MERGED"), to="pr view")

    assert found(state=state) is None


def test_a_pull_request_read_that_failed_leaves_the_assignment_waiting(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")

    waiting = found(state=state)

    assert isinstance(waiting, WaitingAgentAssignment)
    assert waiting.reason.startswith("cannot read its pull request")
    # A read that could not tell is asked again next tick, so nobody has to act.
    assert not waiting.is_stuck


def test_a_peek_that_failed_leaves_the_assignment_waiting(state, gh):
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    waiting = found(state=state)

    assert isinstance(waiting, WaitingAgentAssignment)
    assert waiting.reason.startswith("cannot tell what the user posted")


def test_the_most_open_work_comes_first(state):
    first_assignment = read_agent_assignments(state=state)[0]
    ran(state=state, number=1, purpose=RoundPurpose.IMPLEMENT)
    continued_assignment = read_agent_assignments(state=state)[0]

    def resume(
        *, assignment, purpose: RoundPurpose, is_recovery: bool = False
    ) -> Wakeup:
        return Wakeup(
            assignment=assignment,
            purpose=purpose,
            is_recovery=is_recovery,
            reason="",
            prompt="",
        )

    ordered = sort_wakeups(
        found=[
            resume(
                assignment=continued_assignment,
                purpose=RoundPurpose.ADDRESS_FEEDBACK,
            ),
            resume(assignment=continued_assignment, purpose=RoundPurpose.WRAP_UP),
            resume(
                assignment=continued_assignment,
                purpose=RoundPurpose.IMPLEMENT,
                is_recovery=True,
            ),
            resume(assignment=first_assignment, purpose=RoundPurpose.IMPLEMENT),
        ]
    )

    assert [
        (not found.assignment.rounds, found.is_recovery, found.purpose)
        for found in ordered
    ] == [
        (True, False, RoundPurpose.IMPLEMENT),
        (False, True, RoundPurpose.IMPLEMENT),
        (False, False, RoundPurpose.WRAP_UP),
        (False, False, RoundPurpose.ADDRESS_FEEDBACK),
    ]
