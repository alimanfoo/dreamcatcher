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
    pull_requests,
)
from records import write_round, write_session

from dreamcatcher.github import PullRequestState
from dreamcatcher.prompts import CARRY_ON_PROMPT, MARKER
from dreamcatcher.relay import Inbox
from dreamcatcher.rounds import Cause, Ending, RoundRecord
from dreamcatcher.sessions import advance_watermark, read_sessions
from dreamcatcher.state import NO_ROUND_HAS_RUN, StateDirectory, WaitingSession
from dreamcatcher.wakeups import Wakeup, judge_session, sort_wakeups

KEY = "GH13-20260819-184158"


@pytest.fixture
def state(tmp_path):
    """A state directory holding one session, with no round run yet."""
    directory = StateDirectory(root=tmp_path)
    write_session(state=directory, key=KEY, issue=13)
    return directory


@pytest.fixture
def gh(gh_with_no_posts):
    """A gh answering with one open pull request that nobody has posted on."""
    gh_with_no_posts.replies(
        stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list"
    )
    return gh_with_no_posts


def ran(*, state, number: int, cause: Cause, status: int | None = 0) -> None:
    """Write down a round of that session, ended as the status says.

    Each round starts a minute after the one before it, which is the order
    they read back in.
    """
    started = PINNED + timedelta(minutes=number)
    ending = None if status is None else Ending(at=started, status=status)
    write_round(
        directory=state.sessions / KEY,
        number=number,
        record=RoundRecord(started=started, pid=1, cause=cause, ending=ending),
    )


def found(*, state) -> Wakeup | WaitingSession | None:
    """What the one session in that state directory needs next."""
    return judge_session(
        repository=REPOSITORY, account=POSTED_BY, session=read_sessions(state=state)[0]
    )


def test_a_session_that_has_run_no_round_at_all_waits_for_a_person(state):
    assert found(state=state) == WaitingSession(
        session=KEY, issue=13, reason=NO_ROUND_HAS_RUN, is_stuck=True
    )


def test_a_session_whose_last_round_was_interrupted_is_carried_on(state):
    ran(state=state, number=1, cause=Cause.DISPATCH, status=None)

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.cause is Cause.CARRY_ON
    assert resume.reason == "the last round was interrupted"
    assert resume.prompt == CARRY_ON_PROMPT
    assert resume.inbox is None


def test_a_session_whose_last_round_failed_is_carried_on_with_its_status(state):
    ran(state=state, number=1, cause=Cause.DISPATCH, status=2)

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.cause is Cause.CARRY_ON
    assert resume.reason == "the last round failed (exit 2)"


def test_a_round_that_did_not_finish_is_carried_on_before_github_is_asked(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH, status=None)

    found(state=state)

    assert gh.calls == []


def test_a_session_nobody_has_posted_on_needs_nothing(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)

    assert found(state=state) is None


def test_a_session_the_user_has_posted_on_answers_what_they_said(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.cause is Cause.POSTS
    assert resume.reason == "1 new post to answer"
    assert resume.inbox is not None
    assert resume.inbox.state is PullRequestState.OPEN
    assert [post.body for post in resume.inbox.posts] == [
        "have another look at the filter"
    ]
    assert resume.newest_post == POSTED_AT


def test_a_batch_of_posts_says_how_many_it_holds(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.replies(
        stdout=pages(
            posts=[comment(), comment(id=2, created_at="2026-09-03T22:20:55Z")]
        ),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.reason == "2 new posts to answer"


def test_a_post_the_session_has_been_told_about_already_wakes_nothing(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    advance_watermark(session=read_sessions(state=state)[0], newest=POSTED_AT)

    assert found(state=state) is None


def test_the_prompt_of_a_posts_resume_sends_the_session_to_the_next_rounds_inbox(
    state, gh
):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert f"pull request #{PULL_REQUEST}" in resume.prompt
    assert str(resume.session.next_workspace.inbox) in resume.prompt
    assert resume.session.next_workspace.directory.name == "2"
    assert MARKER in resume.prompt


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_calls_for_one_last_round(
    state, gh, state_name
):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, state_name)]), to="pr list")

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.cause is Cause.FINAL
    assert resume.reason == f"the pull request is {state_name.lower()}"
    assert resume.inbox == Inbox(state=state_name, posts=[])
    assert resume.newest_post == ""


def test_a_last_round_carries_what_the_user_said_before_the_merge(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "MERGED")]), to="pr list")
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert resume.cause is Cause.FINAL
    assert resume.inbox is not None
    assert [post.body for post in resume.inbox.posts] == [
        "have another look at the filter"
    ]


def test_a_session_whose_last_round_wound_it_up_needs_nothing(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    ran(state=state, number=2, cause=Cause.FINAL)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "MERGED")]), to="pr list")

    assert found(state=state) is None


def test_a_last_round_that_was_carried_on_is_still_the_last_round(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    ran(state=state, number=2, cause=Cause.FINAL, status=None)
    ran(state=state, number=3, cause=Cause.CARRY_ON)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "MERGED")]), to="pr list")

    assert found(state=state) is None


def test_a_session_with_no_pull_request_of_its_own_waits_for_a_person(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.replies(stdout="[]", to="pr list")

    assert found(state=state) == WaitingSession(
        session=KEY,
        issue=13,
        reason="no pull request has been opened on it",
        is_stuck=True,
    )


def test_an_open_pull_request_outranks_the_ones_that_are_finished(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.replies(
        stdout=pull_requests(listed=[(60, "CLOSED"), (PULL_REQUEST, "OPEN")]),
        to="pr list",
    )
    gh.replies(
        stdout=pages(posts=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert f"pull request #{PULL_REQUEST}" in resume.prompt


def test_the_newest_of_two_finished_pull_requests_is_the_sessions_own(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.replies(
        stdout=pull_requests(listed=[(PULL_REQUEST, "CLOSED"), (40, "MERGED")]),
        to="pr list",
    )

    resume = found(state=state)

    assert isinstance(resume, Wakeup)
    assert f"pull request #{PULL_REQUEST}" in resume.prompt


def test_a_pull_request_read_that_failed_leaves_the_session_waiting(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.fails(stderr="gh: could not connect to github.com", to="pr list")

    waiting = found(state=state)

    assert isinstance(waiting, WaitingSession)
    assert waiting.reason.startswith("cannot tell which pull request it has")
    # A read that could not tell is asked again next tick, so nobody has to act.
    assert not waiting.is_stuck


def test_a_peek_that_failed_leaves_the_session_waiting(state, gh):
    ran(state=state, number=1, cause=Cause.DISPATCH)
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    waiting = found(state=state)

    assert isinstance(waiting, WaitingSession)
    assert waiting.reason.startswith("cannot tell what the user posted")


def test_the_most_open_work_comes_first(state):
    session = read_sessions(state=state)[0]

    def resume(*, cause: Cause) -> Wakeup:
        return Wakeup(session=session, cause=cause, reason="", prompt="")

    ordered = sort_wakeups(
        found=[
            resume(cause=Cause.POSTS),
            resume(cause=Cause.FINAL),
            resume(cause=Cause.CARRY_ON),
        ]
    )

    assert [found.cause for found in ordered] == [
        Cause.CARRY_ON,
        Cause.FINAL,
        Cause.POSTS,
    ]
