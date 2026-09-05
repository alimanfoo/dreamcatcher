import json
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import POST_LIST_PATHS, POSTED_BY, REPOSITORY, pages
from records import write_round, write_session

from dreamcatcher.github import PullRequestState
from dreamcatcher.prompts import CARRY_ON_PROMPT, MARKER
from dreamcatcher.relay import Inbox
from dreamcatcher.resumes import Resume, find_resume, sort_resumes
from dreamcatcher.rounds import Cause, Ending, RoundRecord
from dreamcatcher.sessions import advance_watermark, read_sessions
from dreamcatcher.state import StateDirectory, Waiting

KEY = "GH13-20260819-184158"

PULL_REQUEST = 52

# When the tests say the user posted.
POSTED_AT = "2026-09-03T22:19:55Z"


def comment(**fields: object) -> dict:
    """What gh answers one comment on the pull request's conversation with."""
    return {
        "id": 1,
        "user": {"login": POSTED_BY},
        "created_at": POSTED_AT,
        "body": "have another look at the filter",
    } | fields


@pytest.fixture
def state(tmp_path):
    """A state directory holding one session, with no round run yet."""
    directory = StateDirectory(tmp_path)
    write_session(directory, KEY, 13)
    return directory


@pytest.fixture
def gh(gh_with_no_posts):
    """A gh answering with one open pull request that nobody has posted on."""
    gh_with_no_posts.replies(
        json.dumps([{"number": PULL_REQUEST, "state": "OPEN"}]), to="pr list"
    )
    return gh_with_no_posts


def ran(state, number: int, cause: Cause, status: int | None = 0) -> None:
    """Write down a round of that session, ended as the status says.

    Each round starts a minute after the one before it, which is the order
    they read back in.
    """
    started = PINNED + timedelta(minutes=number)
    ending = None if status is None else Ending(at=started, status=status)
    write_round(
        state.sessions / KEY,
        number,
        RoundRecord(started=started, pid=1, cause=cause, ending=ending),
    )


def found(state) -> Resume | Waiting | None:
    """What the one session in that state directory needs next."""
    return find_resume(REPOSITORY, POSTED_BY, read_sessions(state)[0])


def test_a_session_that_has_run_no_round_at_all_waits_for_a_person(state):
    assert found(state) == Waiting(session=KEY, issue=13, reason="no round has run yet")


def test_a_session_whose_last_round_was_interrupted_is_carried_on(state):
    ran(state, 1, Cause.DISPATCH, status=None)

    resume = found(state)

    assert isinstance(resume, Resume)
    assert resume.cause is Cause.CARRY_ON
    assert resume.reason == "the last round was interrupted"
    assert resume.prompt == CARRY_ON_PROMPT
    assert resume.inbox is None


def test_a_session_whose_last_round_failed_is_carried_on_with_its_status(state):
    ran(state, 1, Cause.DISPATCH, status=2)

    resume = found(state)

    assert isinstance(resume, Resume)
    assert resume.cause is Cause.CARRY_ON
    assert resume.reason == "the last round failed (exit 2)"


def test_a_round_that_did_not_finish_is_carried_on_before_github_is_asked(state, gh):
    ran(state, 1, Cause.DISPATCH, status=None)

    found(state)

    assert gh.calls == []


def test_a_session_nobody_has_posted_on_needs_nothing(state, gh):
    ran(state, 1, Cause.DISPATCH)

    assert found(state) is None


def test_a_session_the_user_has_posted_on_answers_what_they_said(state, gh):
    ran(state, 1, Cause.DISPATCH)
    gh.replies(pages(comment()), to=f"api {POST_LIST_PATHS['conversation']}")

    resume = found(state)

    assert isinstance(resume, Resume)
    assert resume.cause is Cause.POSTS
    assert resume.reason == "1 new post to answer"
    assert resume.inbox is not None
    assert resume.inbox.state is PullRequestState.OPEN
    assert [post.body for post in resume.inbox.posts] == [
        "have another look at the filter"
    ]
    assert resume.newest_post == POSTED_AT


def test_a_batch_of_posts_says_how_many_it_holds(state, gh):
    ran(state, 1, Cause.DISPATCH)
    gh.replies(
        pages(comment(), comment(id=2, created_at="2026-09-03T22:20:55Z")),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    resume = found(state)

    assert isinstance(resume, Resume)
    assert resume.reason == "2 new posts to answer"


def test_a_post_the_session_has_been_told_about_already_wakes_nothing(state, gh):
    ran(state, 1, Cause.DISPATCH)
    gh.replies(pages(comment()), to=f"api {POST_LIST_PATHS['conversation']}")
    advance_watermark(read_sessions(state)[0], POSTED_AT)

    assert found(state) is None


def test_the_prompt_of_a_posts_resume_sends_the_session_to_the_next_rounds_inbox(
    state, gh
):
    ran(state, 1, Cause.DISPATCH)
    gh.replies(pages(comment()), to=f"api {POST_LIST_PATHS['conversation']}")

    resume = found(state)

    assert isinstance(resume, Resume)
    assert f"pull request #{PULL_REQUEST}" in resume.prompt
    assert str(resume.session.next_workspace.inbox) in resume.prompt
    assert resume.session.next_workspace.directory.name == "2"
    assert MARKER in resume.prompt


@pytest.mark.parametrize("state_name", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_finished_calls_for_one_last_round(
    state, gh, state_name
):
    ran(state, 1, Cause.DISPATCH)
    gh.replies(
        json.dumps([{"number": PULL_REQUEST, "state": state_name}]), to="pr list"
    )

    resume = found(state)

    assert isinstance(resume, Resume)
    assert resume.cause is Cause.FINAL
    assert resume.reason == f"the pull request is {state_name.lower()}"
    assert resume.inbox == Inbox(state=state_name, posts=[])
    assert resume.newest_post == ""


def test_a_last_round_carries_what_the_user_said_before_the_merge(state, gh):
    ran(state, 1, Cause.DISPATCH)
    gh.replies(json.dumps([{"number": PULL_REQUEST, "state": "MERGED"}]), to="pr list")
    gh.replies(pages(comment()), to=f"api {POST_LIST_PATHS['conversation']}")

    resume = found(state)

    assert isinstance(resume, Resume)
    assert resume.cause is Cause.FINAL
    assert resume.inbox is not None
    assert [post.body for post in resume.inbox.posts] == [
        "have another look at the filter"
    ]


def test_a_session_whose_last_round_wound_it_up_needs_nothing(state, gh):
    ran(state, 1, Cause.DISPATCH)
    ran(state, 2, Cause.FINAL)
    gh.replies(json.dumps([{"number": PULL_REQUEST, "state": "MERGED"}]), to="pr list")

    assert found(state) is None


def test_a_last_round_that_was_carried_on_is_still_the_last_round(state, gh):
    ran(state, 1, Cause.DISPATCH)
    ran(state, 2, Cause.FINAL, status=None)
    ran(state, 3, Cause.CARRY_ON)
    gh.replies(json.dumps([{"number": PULL_REQUEST, "state": "MERGED"}]), to="pr list")

    assert found(state) is None


def test_a_session_with_no_pull_request_of_its_own_waits_for_a_person(state, gh):
    ran(state, 1, Cause.DISPATCH)
    gh.replies("[]", to="pr list")

    assert found(state) == Waiting(
        session=KEY, issue=13, reason="no pull request has been opened on it"
    )


def test_an_open_pull_request_outranks_the_ones_that_are_finished(state, gh):
    ran(state, 1, Cause.DISPATCH)
    gh.replies(
        json.dumps(
            [
                {"number": 60, "state": "CLOSED"},
                {"number": PULL_REQUEST, "state": "OPEN"},
            ]
        ),
        to="pr list",
    )
    gh.replies(pages(comment()), to=f"api {POST_LIST_PATHS['conversation']}")

    resume = found(state)

    assert isinstance(resume, Resume)
    assert f"pull request #{PULL_REQUEST}" in resume.prompt


def test_the_newest_of_two_finished_pull_requests_is_the_sessions_own(state, gh):
    ran(state, 1, Cause.DISPATCH)
    gh.replies(
        json.dumps(
            [
                {"number": PULL_REQUEST, "state": "CLOSED"},
                {"number": 40, "state": "MERGED"},
            ]
        ),
        to="pr list",
    )

    resume = found(state)

    assert isinstance(resume, Resume)
    assert f"pull request #{PULL_REQUEST}" in resume.prompt


def test_a_pull_request_read_that_failed_leaves_the_session_waiting(state, gh):
    ran(state, 1, Cause.DISPATCH)
    gh.fails("gh: could not connect to github.com", to="pr list")

    waiting = found(state)

    assert isinstance(waiting, Waiting)
    assert waiting.reason.startswith("cannot tell which pull request it has")


def test_a_peek_that_failed_leaves_the_session_waiting(state, gh):
    ran(state, 1, Cause.DISPATCH)
    gh.fails(
        "gh: could not connect to github.com",
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    waiting = found(state)

    assert isinstance(waiting, Waiting)
    assert waiting.reason.startswith("cannot tell what the user posted")


def test_the_most_open_work_comes_first(state):
    session = read_sessions(state)[0]

    def resume(cause: Cause) -> Resume:
        return Resume(session=session, cause=cause, reason="", prompt="")

    ordered = sort_resumes(
        [resume(Cause.POSTS), resume(Cause.FINAL), resume(Cause.CARRY_ON)]
    )

    assert [found.cause for found in ordered] == [
        Cause.CARRY_ON,
        Cause.FINAL,
        Cause.POSTS,
    ]
