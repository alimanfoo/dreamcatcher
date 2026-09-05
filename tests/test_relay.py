import json

import pytest
from conftest import POST_LIST_PATHS, POSTED_BY, PULL_REQUEST, REPOSITORY, pages

from dreamcatcher.documents import write_json
from dreamcatcher.github import (
    AnyPost,
    Comment,
    InlineComment,
    PullRequestState,
    Review,
    Unknown,
    Verdict,
)
from dreamcatcher.prompts import MARKER
from dreamcatcher.relay import Inbox, peek_new_posts

# When the tests say the user posted, and a time before it.
POSTED_AT = "2026-09-03T22:19:55Z"

BEFORE = "2026-09-03T16:49:35Z"

# The diff an inline comment was written against.
HUNK = (
    '@@ -0,0 +1,3 @@\n+"""Carry what the user posts."""\n'
    "+\n+from dreamcatcher import github"
)


def comment(**fields: object) -> dict:
    """What gh answers one comment on the pull request's conversation with."""
    return {
        "id": 1,
        "user": {"login": POSTED_BY},
        "created_at": POSTED_AT,
        "body": "have another look at the filter",
    } | fields


def review(**fields: object) -> dict:
    """What gh answers one review with."""
    return {
        "id": 2,
        "user": {"login": POSTED_BY},
        "submitted_at": POSTED_AT,
        "body": "",
        "state": Verdict.COMMENTED,
    } | fields


def inline_comment(**fields: object) -> dict:
    """What gh answers one comment on a line of the diff with."""
    return {
        "id": 3,
        "user": {"login": POSTED_BY},
        "created_at": POSTED_AT,
        "body": "this reads the watermark twice",
        "path": "src/dreamcatcher/relay.py",
        "side": "RIGHT",
        "line": 3,
        "diff_hunk": HUNK,
    } | fields


def peeked(watermark: str = "") -> list[AnyPost]:
    """What the user newly posted, given that gh answered every post list."""
    found = peek_new_posts(
        REPOSITORY, PULL_REQUEST, account=POSTED_BY, watermark=watermark
    )
    assert not isinstance(found, Unknown)
    return found


def test_a_pull_request_nobody_has_posted_on_has_nothing_to_relay(gh_with_no_posts):
    assert peeked() == []


def test_a_session_that_has_seen_nothing_yet_is_told_the_whole_history(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        pages(comment()), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    assert [post.id for post in peeked()] == [1]


def test_a_post_the_session_has_been_told_about_already_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        pages(comment()), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    assert peeked(watermark=POSTED_AT) == []


def test_the_posts_come_back_oldest_first_whichever_list_each_came_from(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        pages(comment(created_at="2026-09-03T23:47:28Z")),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )
    gh_with_no_posts.replies(
        pages(review(submitted_at=BEFORE, body="see inline")),
        to=f"api {POST_LIST_PATHS['reviews']}",
    )
    gh_with_no_posts.replies(
        pages(inline_comment()), to=f"api {POST_LIST_PATHS['inline-comments']}"
    )

    assert [type(post) for post in peeked()] == [Review, InlineComment, Comment]


def test_a_post_carrying_the_marker_is_the_sessions_own_and_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        pages(comment(body=f"opened the pull request\n\n{MARKER}")),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert peeked() == []


def test_a_post_from_another_account_does_not_come_back(gh_with_no_posts):
    gh_with_no_posts.replies(
        pages(comment(user={"login": "somebody-else"})),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert peeked() == []


def test_a_post_whose_account_github_no_longer_knows_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        pages(comment(user=None)), to=f"api {POST_LIST_PATHS['conversation']}"
    )

    assert peeked() == []


def test_the_empty_review_github_wrapped_an_inline_reply_in_does_not_come_back(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(pages(review()), to=f"api {POST_LIST_PATHS['reviews']}")
    gh_with_no_posts.replies(
        pages(inline_comment()), to=f"api {POST_LIST_PATHS['inline-comments']}"
    )

    assert [type(post) for post in peeked()] == [InlineComment]


@pytest.mark.parametrize(
    "verdict", [Verdict.APPROVED, Verdict.CHANGES_REQUESTED], ids=str
)
def test_a_review_that_reached_a_verdict_comes_back_with_an_empty_body(
    gh_with_no_posts, verdict
):
    gh_with_no_posts.replies(
        pages(review(state=verdict)), to=f"api {POST_LIST_PATHS['reviews']}"
    )

    assert [post.id for post in peeked()] == [2]


def test_a_review_nobody_has_submitted_yet_does_not_come_back(gh_with_no_posts):
    unsubmitted = review(state=Verdict.PENDING, body="half a thought")
    del unsubmitted["submitted_at"]
    gh_with_no_posts.replies(pages(unsubmitted), to=f"api {POST_LIST_PATHS['reviews']}")

    assert peeked() == []


def test_a_suggestion_over_a_range_comes_back_with_its_lines_and_its_diff(
    gh_with_no_posts,
):
    gh_with_no_posts.replies(
        pages(
            inline_comment(
                body="```suggestion\nfrom dreamcatcher.github import posts\n```",
                start_line=1,
                line=3,
            )
        ),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    suggestion = peeked()[0]

    assert isinstance(suggestion, InlineComment)
    assert (suggestion.start_line, suggestion.line) == (1, 3)
    assert suggestion.path == "src/dreamcatcher/relay.py"
    assert suggestion.side == "RIGHT"
    assert suggestion.diff_hunk == HUNK


def test_a_read_that_failed_says_so_rather_than_reading_as_nothing_posted(
    gh_with_no_posts,
):
    gh_with_no_posts.fails(
        "gh: could not connect to github.com", to=f"api {POST_LIST_PATHS['reviews']}"
    )

    found = peek_new_posts(
        REPOSITORY, PULL_REQUEST, account=POSTED_BY, watermark=POSTED_AT
    )

    assert isinstance(found, Unknown)
    assert "could not connect" in found.reason


def test_every_post_the_user_said_something_in_on_a_real_pull_request_comes_back(
    gh_with_recorded_posts,
):
    # The three lists interleave by the time each post was written, and the
    # three empty reviews GitHub wrapped the last three inline comments in are
    # gone, while those inline comments come through on their own.
    assert [type(post) for post in peeked()] == [
        Comment,
        Comment,
        Comment,
        Comment,
        Comment,
        Comment,
        InlineComment,
        InlineComment,
        InlineComment,
        Review,
        Comment,
        InlineComment,
        InlineComment,
        InlineComment,
        Comment,
        Comment,
    ]


def test_an_inbox_says_where_the_pull_request_got_to_and_what_each_post_is(
    gh_with_no_posts, tmp_path
):
    for source, post in (
        ("conversation", comment()),
        ("reviews", review(body="have a look")),
        ("inline-comments", inline_comment()),
    ):
        gh_with_no_posts.replies(pages(post), to=f"api {POST_LIST_PATHS[source]}")
    written = tmp_path / "inbox.json"

    write_json(Inbox(state=PullRequestState.OPEN, posts=peeked()), written)

    read_back = json.loads(written.read_text(encoding="utf-8"))
    assert read_back["state"] == "OPEN"
    assert [post["kind"] for post in read_back["posts"]] == [
        "comment",
        "review",
        "inlineComment",
    ]
    assert read_back["posts"][2]["diff_hunk"] == HUNK


def test_an_inbox_a_merged_pull_request_woke_carries_no_post(tmp_path):
    written = tmp_path / "inbox.json"

    write_json(Inbox(state=PullRequestState.MERGED, posts=[]), written)

    read_back = json.loads(written.read_text(encoding="utf-8"))
    assert read_back == {"state": "MERGED", "posts": []}
