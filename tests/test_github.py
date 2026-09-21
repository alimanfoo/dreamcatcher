import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import POST_LIST_PATHS, POSTED_BY, PULL_REQUEST, pages

from dreamcatcher.github import (
    BlockingIssue,
    ConversationComment,
    GitHubIssueLabel,
    GitHubUserAccount,
    InlineReviewComment,
    Issue,
    IssuePullRequestContext,
    IssueState,
    LinkedPullRequest,
    PullRequest,
    PullRequestReview,
    PullRequestReviewVerdict,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    create_pull_request,
    identify_github_account,
    identify_github_repository,
    list_blocking_issues,
    list_issues,
    list_pull_requests,
    list_user_posts,
    read_issue,
    read_issue_pull_request_context,
    read_pull_request,
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
    gh = fake(program="gh")
    gh.replies(stdout=json.dumps({"nameWithOwner": REPOSITORY}))

    assert identify_github_repository(root=tmp_path) == REPOSITORY
    assert gh.calls[0].arguments == ["repo", "view", "--json", "nameWithOwner"]
    assert gh.calls[0].directory == tmp_path.resolve()


def test_the_signed_in_account_is_the_one_gh_names(fake):
    gh = fake(program="gh")
    gh.replies(stdout=json.dumps({"login": "alimanfoo"}))

    assert identify_github_account() == "alimanfoo"
    assert gh.calls[0].arguments == ["api", "user"]


def test_a_listing_carries_each_issue_and_when_it_was_filed(fake):
    gh = fake(program="gh")
    issue = {
        "number": 8,
        "createdAt": "2026-08-19T18:41:58Z",
        "state": "OPEN",
        "assignees": [{"login": "alimanfoo"}],
        "labels": [{"name": "dream:smith"}],
    }
    gh.replies(stdout=json.dumps([issue]))

    found = list_issues(repository=REPOSITORY, label="dream:smith", assignee="@me")

    assert found == [
        Issue(
            number=8,
            created_at=datetime(2026, 8, 19, 18, 41, 58, tzinfo=UTC),
            state=IssueState.OPEN,
            assignees=[GitHubUserAccount(login="alimanfoo")],
            labels=[GitHubIssueLabel(name="dream:smith")],
        )
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
        "number,createdAt,state,assignees,labels",
    ]


def test_one_issue_carries_its_state_assignees_and_labels(fake):
    gh = fake(program="gh")
    issue = {
        "number": 8,
        "createdAt": "2026-08-19T18:41:58Z",
        "state": "CLOSED",
        "assignees": [],
        "labels": [{"name": "maintenance"}],
    }
    gh.replies(stdout=json.dumps(issue))

    found = read_issue(repository=REPOSITORY, issue=8)

    assert found == Issue(
        number=8,
        created_at=datetime(2026, 8, 19, 18, 41, 58, tzinfo=UTC),
        state=IssueState.CLOSED,
        assignees=[],
        labels=[GitHubIssueLabel(name="maintenance")],
    )
    assert gh.calls[0].arguments == [
        "issue",
        "view",
        "8",
        "--repo",
        REPOSITORY,
        "--json",
        "number,createdAt,state,assignees,labels",
    ]


def test_the_pull_requests_of_a_branch_come_back_with_their_states(fake):
    gh = fake(program="gh")
    gh.replies(
        stdout=json.dumps(
            [
                {"number": 28, "state": "OPEN", "isDraft": True},
                {"number": 25, "state": "MERGED", "isDraft": False},
            ]
        )
    )

    assert list_pull_requests(repository=REPOSITORY, branch=BRANCH) == [
        PullRequest(number=28, state=PullRequestState.OPEN, isDraft=True),
        PullRequest(number=25, state=PullRequestState.MERGED, isDraft=False),
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
        "number,state,isDraft",
    ]


def test_a_branch_with_no_pull_request_comes_back_empty(fake):
    gh = fake(program="gh")
    gh.replies(stdout="[]")

    assert list_pull_requests(repository=REPOSITORY, branch=BRANCH) == []


def test_a_linked_draft_pull_request_is_opened_for_the_assignment_branch(fake):
    gh = fake(program="gh")
    gh.replies(
        stdout="https://github.com/alimanfoo/dreamcatcher/pull/28\n", to="pr create"
    )
    gh.replies(
        stdout=json.dumps({"number": 28, "state": "OPEN", "isDraft": True}),
        to="pr view",
    )

    context = IssuePullRequestContext(
        issue=8, title="Use the issue title", pull_requests=[]
    )
    created = create_pull_request(repository=REPOSITORY, branch=BRANCH, context=context)

    assert created == PullRequest(number=28, state=PullRequestState.OPEN, isDraft=True)
    assert gh.calls[0].arguments == [
        "pr",
        "create",
        "--repo",
        REPOSITORY,
        "--base",
        "main",
        "--head",
        BRANCH,
        "--draft",
        "--title",
        "Use the issue title",
        "--body",
        "Closes #8",
    ]
    assert gh.calls[1].arguments == [
        "pr",
        "view",
        "https://github.com/alimanfoo/dreamcatcher/pull/28",
        "--repo",
        REPOSITORY,
        "--json",
        "number,state,isDraft",
    ]


def test_a_pull_request_is_read_by_its_persisted_identity(fake):
    gh = fake(program="gh")
    gh.replies(stdout=json.dumps({"number": 28, "state": "MERGED", "isDraft": False}))

    found = read_pull_request(repository=REPOSITORY, pull_request=28)

    assert found == PullRequest(number=28, state=PullRequestState.MERGED, isDraft=False)
    assert gh.calls[0].arguments == [
        "pr",
        "view",
        "28",
        "--repo",
        REPOSITORY,
        "--json",
        "number,state,isDraft",
    ]


def test_the_issue_title_and_its_linked_pull_requests_come_back_together(fake):
    gh = fake(program="gh")
    gh.replies(
        stdout=json.dumps(
            {
                "number": 8,
                "title": "The issue title",
                "closedByPullRequestsReferences": [{"number": 28}],
            }
        ),
        to="issue view",
    )
    gh.replies(
        stdout=json.dumps({"number": 28, "state": "OPEN", "isDraft": True}),
        to="pr view",
    )

    assert read_issue_pull_request_context(
        repository=REPOSITORY, issue=8
    ) == IssuePullRequestContext(
        issue=8,
        title="The issue title",
        pull_requests=[LinkedPullRequest(number=28)],
    )
    assert gh.calls[0].arguments == [
        "issue",
        "view",
        "8",
        "--repo",
        REPOSITORY,
        "--json",
        "number,title,closedByPullRequestsReferences",
    ]
    assert gh.calls[1].arguments == [
        "pr",
        "view",
        "28",
        "--repo",
        REPOSITORY,
        "--json",
        "number,state,isDraft",
    ]


def test_a_finished_linked_pull_request_does_not_claim_the_issue(fake):
    gh = fake(program="gh")
    gh.replies(
        stdout=json.dumps(
            {
                "number": 8,
                "title": "The issue title",
                "closedByPullRequestsReferences": [{"number": 28}],
            }
        ),
        to="issue view",
    )
    gh.replies(
        stdout=json.dumps({"number": 28, "state": "MERGED", "isDraft": False}),
        to="pr view",
    )

    assert read_issue_pull_request_context(
        repository=REPOSITORY, issue=8
    ) == IssuePullRequestContext(issue=8, title="The issue title", pull_requests=[])


def test_a_linked_pull_request_whose_state_cannot_be_read_is_unknown(fake):
    gh = fake(program="gh")
    gh.replies(
        stdout=json.dumps(
            {
                "number": 8,
                "title": "The issue title",
                "closedByPullRequestsReferences": [{"number": 28}],
            }
        ),
        to="issue view",
    )
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")

    answered = read_issue_pull_request_context(repository=REPOSITORY, issue=8)

    assert isinstance(answered, UnknownGitHubResponse)
    assert "could not connect" in answered.reason


def test_an_issue_nobody_has_claimed_has_no_linked_pull_request(fake):
    gh = fake(program="gh")
    gh.replies(
        stdout=json.dumps(
            {
                "number": 8,
                "title": "The issue title",
                "closedByPullRequestsReferences": [],
            }
        )
    )

    assert read_issue_pull_request_context(
        repository=REPOSITORY, issue=8
    ) == IssuePullRequestContext(issue=8, title="The issue title", pull_requests=[])


def test_the_blockers_of_an_issue_come_back_with_their_states(fake):
    gh = fake(program="gh")
    gh.replies(
        stdout=pages(
            items=[
                {"number": 7, "state": "closed"},
                {"number": 8, "state": "open"},
            ]
        )
    )

    assert list_blocking_issues(repository=REPOSITORY, issue=9) == [
        BlockingIssue(number=7, state=IssueState.CLOSED),
        BlockingIssue(number=8, state=IssueState.OPEN),
    ]
    assert gh.calls[0].arguments == [
        "api",
        f"repos/{REPOSITORY}/issues/9/dependencies/blocked_by?per_page=100",
        "--paginate",
        "--slurp",
    ]


def test_an_open_blocker_on_the_second_page_comes_back(fake):
    gh = fake(program="gh")
    gh.replies(
        stdout=json.dumps(
            [
                [{"number": 7, "state": "closed"}],
                [{"number": 8, "state": "open"}],
            ]
        )
    )

    found = list_blocking_issues(repository=REPOSITORY, issue=9)

    assert isinstance(found, list)
    assert [blocker.number for blocker in found] == [7, 8]


def posted() -> list[UserPost]:
    """The pull request's posts, given that gh answered every one of its lists."""
    found = list_user_posts(repository=REPOSITORY, pull_request=PULL_REQUEST)
    assert not isinstance(found, UnknownGitHubResponse)
    return found


def test_a_pull_request_nobody_has_posted_on_comes_back_with_no_posts(gh_with_no_posts):
    assert posted() == []


def test_the_posts_of_a_pull_request_come_from_all_three_of_its_lists(gh_with_no_posts):
    gh_with_no_posts.replies(
        stdout=pages(items=[COMMENT]), to=f"api {POST_LIST_PATHS['conversation']}"
    )
    gh_with_no_posts.replies(
        stdout=pages(items=[REVIEW]), to=f"api {POST_LIST_PATHS['reviews']}"
    )
    gh_with_no_posts.replies(
        stdout=pages(items=[INLINE_COMMENT]),
        to=f"api {POST_LIST_PATHS['inline-comments']}",
    )

    assert [(type(post), post.id) for post in posted()] == [
        (ConversationComment, 1),
        (PullRequestReview, 2),
        (InlineReviewComment, 3),
    ]


def test_each_of_the_three_lists_is_read_whole(gh_with_no_posts):
    posted()

    assert [call.arguments for call in gh_with_no_posts.calls] == [
        ["api", path, "--paginate", "--slurp"] for path in POST_LIST_PATHS.values()
    ]


def test_the_pages_of_one_list_come_back_as_one_list(gh_with_no_posts):
    gh_with_no_posts.replies(
        stdout=json.dumps([[COMMENT], [COMMENT | {"id": 9}]]),
        to=f"api {POST_LIST_PATHS['conversation']}",
    )

    assert [post.id for post in posted()] == [1, 9]


def test_a_post_that_is_not_a_document_at_all_is_unknown(gh_with_no_posts):
    gh_with_no_posts.replies(
        stdout=json.dumps([[None]]), to=f"api {POST_LIST_PATHS['inline-comments']}"
    )

    answered = list_user_posts(repository=REPOSITORY, pull_request=PULL_REQUEST)

    assert isinstance(answered, UnknownGitHubResponse)
    assert "cannot read" in answered.reason


def test_every_post_a_real_pull_request_carries_reads_back(gh_with_recorded_posts):
    found = posted()

    assert [type(post) for post in found] == (
        [ConversationComment] * 9 + [PullRequestReview] * 4 + [InlineReviewComment] * 6
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
    submitted = [post for post in posted() if isinstance(post, PullRequestReview)]

    assert [review.verdict for review in submitted] == [
        PullRequestReviewVerdict.COMMENTED
    ] * 4
    assert submitted[0].written_at == "2026-09-03T22:27:20Z"


def test_the_reviews_github_wrapped_the_inline_comments_in_say_nothing(
    gh_with_recorded_posts,
):
    submitted = [post for post in posted() if isinstance(post, PullRequestReview)]

    assert [review.is_speaking for review in submitted] == [True, False, False, False]


def test_a_recorded_inline_comment_reads_the_line_it_was_written_against(
    gh_with_recorded_posts,
):
    inline = [post for post in posted() if isinstance(post, InlineReviewComment)]

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
    inline = [post for post in posted() if isinstance(post, InlineReviewComment)]

    assert inline[0].side == "RIGHT"
    assert inline[0].start_line is None
    assert inline[0].diff_hunk.startswith('@@ -0,0 +1,36 @@\n+"""Compose what the da')


@pytest.mark.parametrize(
    "ask",
    [
        pytest.param(
            lambda: identify_github_repository(root=Path.cwd()), id="the repository"
        ),
        pytest.param(identify_github_account, id="the account"),
        pytest.param(
            lambda: list_issues(
                repository=REPOSITORY, label="dream:smith", assignee="@me"
            ),
            id="a listing",
        ),
        pytest.param(lambda: read_issue(repository=REPOSITORY, issue=9), id="an issue"),
        pytest.param(
            lambda: list_pull_requests(repository=REPOSITORY, branch=BRANCH),
            id="the pull requests",
        ),
        pytest.param(
            lambda: read_issue_pull_request_context(repository=REPOSITORY, issue=9),
            id="the issue pull request context",
        ),
        pytest.param(
            lambda: list_blocking_issues(repository=REPOSITORY, issue=9),
            id="the blockers",
        ),
        pytest.param(
            lambda: list_user_posts(repository=REPOSITORY, pull_request=PULL_REQUEST),
            id="the posts",
        ),
    ],
)
def test_a_read_that_fails_answers_unknown_with_what_gh_said(fake, ask):
    gh = fake(program="gh")
    gh.fails(stderr="gh: could not connect to github.com")

    answered = ask()

    assert isinstance(answered, UnknownGitHubResponse)
    assert "could not connect" in answered.reason


def test_a_read_gh_answers_strangely_is_unknown_too(fake):
    gh = fake(program="gh")
    gh.replies(stdout=json.dumps({"number": 8}))

    answered = list_issues(repository=REPOSITORY, label="dream:smith", assignee="@me")

    assert isinstance(answered, UnknownGitHubResponse)
    assert "cannot read" in answered.reason
