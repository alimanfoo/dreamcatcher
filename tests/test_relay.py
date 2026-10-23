import pytest
from conftest import (
    HUNK,
    POST_LIST_PATHS,
    POSTED_AT,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    compose_comment,
    compose_inline_comment,
    compose_page,
    compose_review,
)

from dreamcatcher.github import (
    InlineReviewComment,
    IssueComment,
    PullRequestReview,
    PullRequestReviewVerdict,
    UnknownGitHubResponse,
    UserPost,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.relay import (
    IssueCommentCursor,
    list_issue_comments_past_cursor,
    list_user_posts_past_cursor,
)

# A time before anything the tests say the user posted.
BEFORE = "2026-09-03T16:49:35Z"


def list_posts_past_cursor(*, cursor: str = "") -> list[UserPost]:
    """What the user newly posted, given that gh answered every post list."""
    found = list_user_posts_past_cursor(
        repository=REPOSITORY,
        pull_request=PULL_REQUEST,
        account=POSTED_BY,
        cursor=cursor,
    )
    assert not isinstance(found, UnknownGitHubResponse)
    return found


def test_a_pull_request_nobody_has_posted_on_has_nothing_to_relay(gh_with_no_posts):
    assert list_posts_past_cursor() == []


def test_an_assignment_with_an_empty_cursor_receives_the_whole_history(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_comment()]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert [post.id for post in list_posts_past_cursor()] == [1]


def test_a_post_at_the_assignment_cursor_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_comment()]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert list_posts_past_cursor(cursor=POSTED_AT) == []


def test_the_posts_come_back_oldest_first_whichever_list_each_came_from(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_comment(created_at="2026-09-03T23:47:28Z")]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )
    gh_with_no_posts.replies(
        stdout=compose_page(
            items=[compose_review(submitted_at=BEFORE, body="see inline")]
        ),
        to=f"api {POST_LIST_PATHS['reviews']}",
    )
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_inline_comment()]),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    assert [type(post) for post in list_posts_past_cursor()] == [
        PullRequestReview,
        InlineReviewComment,
        IssueComment,
    ]


def test_a_post_carrying_the_marker_is_the_assignments_own_and_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=compose_page(
            items=[
                compose_comment(body=f"opened the pull request\n\n{AGENT_POST_MARKER}")
            ]
        ),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert list_posts_past_cursor() == []


def test_a_post_from_another_account_does_not_come_back(gh_with_no_posts):
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_comment(user={"login": "somebody-else"})]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert list_posts_past_cursor() == []


def test_a_post_from_the_account_written_in_other_capitals_comes_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_comment(user={"login": POSTED_BY.upper()})]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert [type(post) for post in list_posts_past_cursor()] == [IssueComment]


def test_a_post_whose_body_is_only_whitespace_does_not_come_back(gh_with_no_posts):
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_comment(body=" \n\t")]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert list_posts_past_cursor() == []


def test_a_post_whose_account_github_no_longer_knows_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_comment(user=None)]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert list_posts_past_cursor() == []


def test_the_empty_review_github_wrapped_an_inline_reply_in_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_review()]),
        to=f"api {POST_LIST_PATHS['reviews']}",
    )
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_inline_comment()]),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    assert [type(post) for post in list_posts_past_cursor()] == [InlineReviewComment]


@pytest.mark.parametrize(
    "verdict",
    [PullRequestReviewVerdict.APPROVED, PullRequestReviewVerdict.CHANGES_REQUESTED],
    ids=str,
)
def test_a_review_that_reached_a_verdict_comes_back_with_an_empty_body(
    gh_with_no_posts, verdict
):
    gh_with_no_posts.replies(
        stdout=compose_page(items=[compose_review(state=verdict)]),
        to=f"api {POST_LIST_PATHS['reviews']}",
    )

    assert [post.id for post in list_posts_past_cursor()] == [2]


def test_a_review_nobody_has_submitted_yet_does_not_come_back(gh_with_no_posts):
    unsubmitted = compose_review(
        state=PullRequestReviewVerdict.PENDING, body="half a thought"
    )
    del unsubmitted["submitted_at"]
    gh_with_no_posts.replies(
        stdout=compose_page(items=[unsubmitted]), to=f"api {POST_LIST_PATHS['reviews']}"
    )

    assert list_posts_past_cursor() == []


def test_a_suggestion_over_a_range_comes_back_with_its_lines_and_its_diff(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=compose_page(
            items=[
                compose_inline_comment(
                    body="```suggestion\nfrom dreamcatcher.github import posts\n```",
                    start_line=1,
                    line=3,
                )
            ]
        ),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    suggestion = list_posts_past_cursor()[0]

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

    found = list_user_posts_past_cursor(
        repository=REPOSITORY,
        pull_request=PULL_REQUEST,
        account=POSTED_BY,
        cursor=POSTED_AT,
    )

    assert isinstance(found, UnknownGitHubResponse)
    assert "could not connect" in found.reason


def test_every_post_the_user_said_something_in_on_a_real_pull_request_comes_back(
    gh_with_recorded_posts,
):
    # The three lists interleave by the time each post was written, and the
    # three empty reviews GitHub wrapped the last three inline comments in are
    # gone, while those inline comments come through on their own.
    assert [type(post) for post in list_posts_past_cursor()] == [
        IssueComment,
        IssueComment,
        IssueComment,
        IssueComment,
        IssueComment,
        IssueComment,
        InlineReviewComment,
        InlineReviewComment,
        InlineReviewComment,
        PullRequestReview,
        IssueComment,
        InlineReviewComment,
        InlineReviewComment,
        InlineReviewComment,
        IssueComment,
        IssueComment,
    ]


def test_a_comment_on_a_whole_file_says_so_rather_than_naming_line_one(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        stdout=compose_page(
            items=[compose_inline_comment(subject_type="file", line=1)]
        ),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    written = list_posts_past_cursor()

    assert [type(post) for post in written] == [InlineReviewComment]
    assert [
        (post.subject_type, post.line)
        for post in written
        if isinstance(post, InlineReviewComment)
    ] == [("file", 1)]


def test_a_comment_gh_says_nothing_about_the_subject_of_reads_as_one_on_a_line(
    gh_with_no_posts,
):
    answered = compose_inline_comment()
    del answered["subject_type"]
    gh_with_no_posts.replies(
        stdout=compose_page(items=[answered]),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    assert [
        post.subject_type
        for post in list_posts_past_cursor()
        if isinstance(post, InlineReviewComment)
    ] == ["line"]


def test_only_eligible_issue_comments_past_the_cursor_come_back(fake):
    fake(program="gh").replies(
        stdout=compose_page(
            items=[
                compose_comment(id=4, created_at=POSTED_AT, body="later in the list"),
                compose_comment(id=1, created_at=BEFORE, body="before the cursor"),
                compose_comment(
                    id=3, created_at=POSTED_AT, body="first after the cursor"
                ),
                compose_comment(id=5, user={"login": "mallory"}, body="somebody else"),
                compose_comment(id=6, body=f"agent answer\n{AGENT_POST_MARKER}"),
                compose_comment(id=7, body="  "),
            ]
        )
    )

    def list_comments_past_cursor(*, cursor: IssueCommentCursor | None) -> list[int]:
        found = list_issue_comments_past_cursor(
            repository=REPOSITORY, issue=8, account=POSTED_BY.upper(), cursor=cursor
        )
        assert not isinstance(found, UnknownGitHubResponse)
        return [item.id for item in found]

    assert list_comments_past_cursor(
        cursor=IssueCommentCursor(written_at=POSTED_AT, id=2)
    ) == [3, 4]
    assert list_comments_past_cursor(cursor=None) == [1, 3, 4]
