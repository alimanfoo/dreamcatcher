import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import POST_LIST_PATHS, POSTED_BY, PULL_REQUEST, pages

from dreamcatcher.github import (
    AnyPost,
    Blocker,
    BlockerState,
    Comment,
    InlineComment,
    Issue,
    LinkedPullRequest,
    PullRequest,
    PullRequestState,
    Review,
    Unknown,
    Verdict,
    identify_account,
    identify_repository,
    list_blockers,
    list_issues,
    list_linked_pull_requests,
    list_posts,
    list_pull_requests,
)

REPOSITORY = "alimanfoo/dreamcatcher"
BRANCH = "dreamcatcher-GH8-20260820-000456"

# The least of each kind of post that gh could answer with. Every other field
# the projection reads has a default, so this is what says which fields it
# insists on.
COMMENT = {"id": 1, "user": {"login": POSTED_BY}, "created_at": "2026-09-03T16:49:35Z"}

REVIEW = {"id": 2, "state": "COMMENTED", "submitted_at": "2026-09-03T22:27:20Z"}

INLINE_COMMENT = {
    "id": 3,
    "created_at": "2026-09-03T22:19:55Z",
    "path": "src/dreamcatcher/prompts.py",
    "side": "RIGHT",
    "line": 29,
    "diff_hunk": "@@ -0,0 +1,36 @@",
}


def test_the_repository_comes_from_the_checkouts_own_remote(fake, tmp_path):
    gh = fake("gh")
    gh.replies(json.dumps({"nameWithOwner": REPOSITORY}))

    assert identify_repository(tmp_path) == REPOSITORY
    assert gh.calls[0].arguments == ["repo", "view", "--json", "nameWithOwner"]
    assert gh.calls[0].directory == tmp_path.resolve()


def test_the_signed_in_account_is_the_one_gh_names(fake):
    gh = fake("gh")
    gh.replies(json.dumps({"login": "alimanfoo"}))

    assert identify_account() == "alimanfoo"
    assert gh.calls[0].arguments == ["api", "user"]


def test_a_listing_carries_each_issue_and_when_it_was_filed(fake):
    gh = fake("gh")
    gh.replies(json.dumps([{"number": 8, "createdAt": "2026-08-19T18:41:58Z"}]))

    found = list_issues(REPOSITORY, label="dream:smith", assignee="@me")

    assert found == [
        Issue(number=8, created_at=datetime(2026, 8, 19, 18, 41, 58, tzinfo=UTC))
    ]
    assert gh.calls[0].arguments == [
        "issue",
        "list",
        "--repo",
        REPOSITORY,
        "--assignee",
        "@me",
        "--label",
        "dream:smith",
        "--state",
        "open",
        "--limit",
        "500",
        "--json",
        "number,createdAt",
    ]


def test_the_pull_requests_of_a_branch_come_back_with_their_states(fake):
    gh = fake("gh")
    gh.replies(
        json.dumps([{"number": 28, "state": "OPEN"}, {"number": 25, "state": "MERGED"}])
    )

    assert list_pull_requests(REPOSITORY, BRANCH) == [
        PullRequest(number=28, state=PullRequestState.OPEN),
        PullRequest(number=25, state=PullRequestState.MERGED),
    ]
    assert gh.calls[0].arguments == [
        "pr",
        "list",
        "--repo",
        REPOSITORY,
        "--head",
        BRANCH,
        "--state",
        "all",
        "--json",
        "number,state",
    ]


def test_a_branch_with_no_pull_request_comes_back_empty(fake):
    gh = fake("gh")
    gh.replies("[]")

    assert list_pull_requests(REPOSITORY, BRANCH) == []


def test_the_pull_requests_linked_to_an_issue_come_back(fake):
    gh = fake("gh")
    gh.replies(json.dumps({"closedByPullRequestsReferences": [{"number": 28}]}))

    assert list_linked_pull_requests(REPOSITORY, 8) == [LinkedPullRequest(number=28)]
    assert gh.calls[0].arguments == [
        "issue",
        "view",
        "8",
        "--repo",
        REPOSITORY,
        "--json",
        "closedByPullRequestsReferences",
    ]


def test_an_issue_nobody_has_claimed_has_no_linked_pull_request(fake):
    gh = fake("gh")
    gh.replies(json.dumps({"closedByPullRequestsReferences": []}))

    assert list_linked_pull_requests(REPOSITORY, 8) == []


def test_the_blockers_of_an_issue_come_back_with_their_states(fake):
    gh = fake("gh")
    gh.replies(
        json.dumps([{"number": 7, "state": "closed"}, {"number": 8, "state": "open"}])
    )

    assert list_blockers(REPOSITORY, 9) == [
        Blocker(number=7, state=BlockerState.CLOSED),
        Blocker(number=8, state=BlockerState.OPEN),
    ]
    assert gh.calls[0].arguments == [
        "api",
        f"repos/{REPOSITORY}/issues/9/dependencies/blocked_by",
    ]


def posted() -> list[AnyPost]:
    """The pull request's posts, given that gh answered every one of its lists."""
    found = list_posts(REPOSITORY, PULL_REQUEST)
    assert not isinstance(found, Unknown)
    return found


def test_a_pull_request_nobody_has_posted_on_comes_back_with_no_posts(gh_with_no_posts):
    assert posted() == []


def test_the_posts_of_a_pull_request_come_from_all_three_of_its_lists(gh_with_no_posts):
    gh_with_no_posts.replies(
        pages(COMMENT), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    gh_with_no_posts.replies(pages(REVIEW), to=f"api {POST_LIST_PATHS['reviews']}")
    gh_with_no_posts.replies(
        pages(INLINE_COMMENT), to=f"api {POST_LIST_PATHS['inline-comments']}"
    )

    assert [(type(post), post.id) for post in posted()] == [
        (Comment, 1),
        (Review, 2),
        (InlineComment, 3),
    ]


def test_each_of_the_three_lists_is_read_whole(gh_with_no_posts):
    posted()

    assert [call.arguments for call in gh_with_no_posts.calls] == [
        ["api", path, "--paginate", "--slurp"] for path in POST_LIST_PATHS.values()
    ]


def test_the_pages_of_one_list_come_back_as_one_list(gh_with_no_posts):
    gh_with_no_posts.replies(
        json.dumps([[COMMENT], [COMMENT | {"id": 9}]]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert [post.id for post in posted()] == [1, 9]


def test_a_post_that_is_not_a_document_at_all_is_unknown(gh_with_no_posts):
    gh_with_no_posts.replies(
        json.dumps([[None]]), to=f"api {POST_LIST_PATHS['inline-comments']}"
    )

    answered = list_posts(REPOSITORY, PULL_REQUEST)

    assert isinstance(answered, Unknown)
    assert "cannot read" in answered.reason


def test_every_post_a_real_pull_request_carries_reads_back(gh_with_recorded_posts):
    found = posted()

    assert [type(post) for post in found] == (
        [Comment] * 9 + [Review] * 4 + [InlineComment] * 6
    )
    assert all(post.author == POSTED_BY for post in found)


def test_a_recorded_comment_reads_back_as_the_user_wrote_it(gh_with_recorded_posts):
    first = posted()[0]

    assert first.id == 5529066022
    assert first.written_at == "2026-09-03T16:49:35Z"
    assert first.body == "## Session input\n\n- #12\n\n> written by an agent"


def test_a_recorded_review_reads_back_when_it_was_submitted_and_its_verdict(
    gh_with_recorded_posts,
):
    submitted = [post for post in posted() if isinstance(post, Review)]

    assert [review.verdict for review in submitted] == [Verdict.COMMENTED] * 4
    assert submitted[0].written_at == "2026-09-03T22:27:20Z"


def test_the_reviews_github_wrapped_the_inline_comments_in_say_nothing(
    gh_with_recorded_posts,
):
    submitted = [post for post in posted() if isinstance(post, Review)]

    assert [review.is_speaking for review in submitted] == [True, False, False, False]


def test_a_recorded_inline_comment_reads_the_line_it_was_written_against(
    gh_with_recorded_posts,
):
    inline = [post for post in posted() if isinstance(post, InlineComment)]

    # The code four of these were written against has moved since, so GitHub
    # answers no line for them and keeps the line each was written against as
    # the original. The other two are still where they were.
    assert [(comment.path, comment.line) for comment in inline] == [
        ("src/dreamcatcher/prompts.py", 29),
        ("src/dreamcatcher/sessions.py", 68),
        ("src/dreamcatcher/sessions.py", 59),
        ("src/dreamcatcher/prompts.py", 29),
        ("src/dreamcatcher/sessions.py", 59),
        ("src/dreamcatcher/sessions.py", 68),
    ]


def test_a_recorded_inline_comment_carries_the_diff_it_was_written_against(
    gh_with_recorded_posts,
):
    inline = [post for post in posted() if isinstance(post, InlineComment)]

    assert inline[0].side == "RIGHT"
    assert inline[0].start_line is None
    assert inline[0].diff_hunk.startswith('@@ -0,0 +1,36 @@\n+"""Compose what the da')


@pytest.mark.parametrize(
    "ask",
    [
        pytest.param(lambda: identify_repository(Path.cwd()), id="the repository"),
        pytest.param(identify_account, id="the account"),
        pytest.param(
            lambda: list_issues(REPOSITORY, label="dream:smith", assignee="@me"),
            id="a listing",
        ),
        pytest.param(
            lambda: list_pull_requests(REPOSITORY, BRANCH), id="the pull requests"
        ),
        pytest.param(
            lambda: list_linked_pull_requests(REPOSITORY, 9),
            id="the linked pull requests",
        ),
        pytest.param(lambda: list_blockers(REPOSITORY, 9), id="the blockers"),
        pytest.param(lambda: list_posts(REPOSITORY, PULL_REQUEST), id="the posts"),
    ],
)
def test_a_read_that_fails_answers_unknown_with_what_gh_said(fake, ask):
    gh = fake("gh")
    gh.fails("gh: could not connect to github.com")

    answered = ask()

    assert isinstance(answered, Unknown)
    assert "could not connect" in answered.reason


def test_a_read_gh_answers_strangely_is_unknown_too(fake):
    gh = fake("gh")
    gh.replies(json.dumps({"number": 8}))

    answered = list_issues(REPOSITORY, label="dream:smith", assignee="@me")

    assert isinstance(answered, Unknown)
    assert "cannot read" in answered.reason
