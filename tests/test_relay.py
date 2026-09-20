import pytest
from conftest import (
    HUNK,
    POST_LIST_PATHS,
    POSTED_AT,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    comment,
    inline_comment,
    pages,
    review,
)

from dreamcatcher.github import (
    ConversationComment,
    InlineReviewComment,
    PullRequestReview,
    PullRequestReviewVerdict,
    UnknownGitHubResponse,
    UserPost,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.relay import list_undelivered_user_posts

# A time before anything the tests say the user posted.
BEFORE = "2026-09-03T16:49:35Z"


def undelivered(*, delivery_cursor: str = "") -> list[UserPost]:
    """What the user newly posted, given that gh answered every post list."""
    found = list_undelivered_user_posts(
        repository=REPOSITORY,
        pull_request=PULL_REQUEST,
        account=POSTED_BY,
        delivery_cursor=delivery_cursor,
    )
    assert not isinstance(found, UnknownGitHubResponse)
    return found


def test_a_pull_request_nobody_has_posted_on_has_nothing_to_relay(gh_with_no_posts):
    assert undelivered() == []


def test_an_assignment_with_an_empty_delivery_cursor_receives_the_whole_history(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    assert [post.id for post in undelivered()] == [1]


def test_a_post_at_the_assignment_delivery_cursor_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=pages(items=[comment()]), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    assert undelivered(delivery_cursor=POSTED_AT) == []


def test_the_posts_come_back_oldest_first_whichever_list_each_came_from(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=pages(items=[comment(created_at="2026-09-03T23:47:28Z")]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )
    gh_with_no_posts.replies(
        stdout=pages(items=[review(submitted_at=BEFORE, body="see inline")]),
        to=f"api {POST_LIST_PATHS['reviews']}",
    )
    gh_with_no_posts.replies(
        stdout=pages(items=[inline_comment()]),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    assert [type(post) for post in undelivered()] == [
        PullRequestReview,
        InlineReviewComment,
        ConversationComment,
    ]


def test_a_post_carrying_the_marker_is_the_assignments_own_and_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=pages(
            items=[comment(body=f"opened the pull request\n\n{AGENT_POST_MARKER}")]
        ),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert undelivered() == []


def test_a_post_from_another_account_does_not_come_back(gh_with_no_posts):
    gh_with_no_posts.replies(
        stdout=pages(items=[comment(user={"login": "somebody-else"})]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert undelivered() == []


def test_a_post_whose_account_github_no_longer_knows_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=pages(items=[comment(user=None)]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert undelivered() == []


def test_the_empty_review_github_wrapped_an_inline_reply_in_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=pages(items=[review()]), to=f"api {POST_LIST_PATHS['reviews']}"
    )
    gh_with_no_posts.replies(
        stdout=pages(items=[inline_comment()]),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    assert [type(post) for post in undelivered()] == [InlineReviewComment]


@pytest.mark.parametrize(
    "verdict",
    [PullRequestReviewVerdict.APPROVED, PullRequestReviewVerdict.CHANGES_REQUESTED],
    ids=str,
)
def test_a_review_that_reached_a_verdict_comes_back_with_an_empty_body(
    gh_with_no_posts, verdict
):
    gh_with_no_posts.replies(
        stdout=pages(items=[review(state=verdict)]),
        to=f"api {POST_LIST_PATHS['reviews']}",
    )

    assert [post.id for post in undelivered()] == [2]


def test_a_review_nobody_has_submitted_yet_does_not_come_back(gh_with_no_posts):
    unsubmitted = review(state=PullRequestReviewVerdict.PENDING, body="half a thought")
    del unsubmitted["submitted_at"]
    gh_with_no_posts.replies(
        stdout=pages(items=[unsubmitted]), to=f"api {POST_LIST_PATHS['reviews']}"
    )

    assert undelivered() == []


def test_a_suggestion_over_a_range_comes_back_with_its_lines_and_its_diff(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=pages(
            items=[
                inline_comment(
                    body="```suggestion\nfrom dreamcatcher.github import posts\n```",
                    start_line=1,
                    line=3,
                )
            ]
        ),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    suggestion = undelivered()[0]

    assert isinstance(suggestion, InlineReviewComment)
    assert (suggestion.start_line, suggestion.line) == (1, 3)
    assert suggestion.path == "src/dreamcatcher/relay.py"
    assert suggestion.side == "RIGHT"
    assert suggestion.diff_hunk == HUNK


def test_a_read_that_failed_says_so_rather_than_reading_as_nothing_posted(
    gh_with_no_posts,
):
    gh_with_no_posts.fails(
        stderr="gh: could not connect to github.com",
        to=f"api {POST_LIST_PATHS['reviews']}",
    )

    found = list_undelivered_user_posts(
        repository=REPOSITORY,
        pull_request=PULL_REQUEST,
        account=POSTED_BY,
        delivery_cursor=POSTED_AT,
    )

    assert isinstance(found, UnknownGitHubResponse)
    assert "could not connect" in found.reason


def test_every_post_the_user_said_something_in_on_a_real_pull_request_comes_back(
    gh_with_recorded_posts,
):
    # The three lists interleave by the time each post was written, and the
    # three empty reviews GitHub wrapped the last three inline comments in are
    # gone, while those inline comments come through on their own.
    assert [type(post) for post in undelivered()] == [
        ConversationComment,
        ConversationComment,
        ConversationComment,
        ConversationComment,
        ConversationComment,
        ConversationComment,
        InlineReviewComment,
        InlineReviewComment,
        InlineReviewComment,
        PullRequestReview,
        ConversationComment,
        InlineReviewComment,
        InlineReviewComment,
        InlineReviewComment,
        ConversationComment,
        ConversationComment,
    ]


def test_a_comment_on_a_whole_file_says_so_rather_than_naming_line_one(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=pages(items=[inline_comment(subject_type="file", line=1)]),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    written = undelivered()

    assert [type(post) for post in written] == [InlineReviewComment]
    assert [
        (post.subject_type, post.line)
        for post in written
        if isinstance(post, InlineReviewComment)
    ] == [("file", 1)]


def test_a_comment_gh_says_nothing_about_the_subject_of_reads_as_one_on_a_line(
    gh_with_no_posts,
):
    answered = inline_comment()
    del answered["subject_type"]
    gh_with_no_posts.replies(
        stdout=pages(items=[answered]), to=f"api {POST_LIST_PATHS['inline-comments']}"
    )

    assert [
        post.subject_type
        for post in undelivered()
        if isinstance(post, InlineReviewComment)
    ] == ["line"]
