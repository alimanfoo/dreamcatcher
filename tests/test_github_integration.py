"""What the real gh answers about this repository. Read-only, and never in CI."""

from pathlib import Path

import pytest

from dreamcatcher.github import (
    Issue,
    IssuePullRequestContext,
    PullRequest,
    PullRequestState,
    _identify_github_account,
    _identify_github_repository,
    can_push_to_repository,
    list_blocking_issues,
    list_issues,
    list_labels,
    list_pull_requests,
    read_issue,
    read_issue_pull_request_context,
)

pytestmark = pytest.mark.integration

REPOSITORY = "alimanfoo/dreamcatcher"
CHECKOUT = Path(__file__).parent.parent
# The pull request that carried the skeleton's second phase. It is merged, so it
# answers the same way for good.
MERGED = 25
MERGED_BRANCH = "dream-catcher-GH7-20260819-184158"
# The phase 4 issue, which the phase 3 issue blocks.
BLOCKED = 9
BLOCKING = 8


def test_this_checkout_is_this_repository():
    assert _identify_github_repository(root=CHECKOUT) == REPOSITORY


def test_gh_is_signed_in_as_somebody():
    assert _identify_github_account()


def test_gh_says_whether_the_account_can_push_here():
    assert isinstance(can_push_to_repository(repository=REPOSITORY), bool)


def test_this_repository_holds_its_dispatch_labels():
    labels = list_labels(repository=REPOSITORY)

    assert isinstance(labels, list)
    assert "dream:smith" in [label.name for label in labels]


def test_gh_takes_the_whole_issue_listing_command():
    assert isinstance(
        list_issues(repository=REPOSITORY, label="dream:smith", assignee="@me"), list
    )


def test_gh_reports_one_issues_state_assignees_and_labels():
    assert isinstance(read_issue(repository=REPOSITORY, issue=145), Issue)


def test_a_merged_pull_request_comes_back_merged():
    found = list_pull_requests(repository=REPOSITORY, branch=MERGED_BRANCH)

    assert isinstance(found, list)
    assert (
        PullRequest(number=MERGED, state=PullRequestState.MERGED, isDraft=False)
        in found
    )


def test_a_branch_that_never_existed_comes_back_empty():
    assert (
        list_pull_requests(
            repository=REPOSITORY, branch="dreamcatcher-GH0-19700101-000000"
        )
        == []
    )


def test_gh_takes_the_linked_pull_requests_command():
    assert isinstance(
        read_issue_pull_request_context(repository=REPOSITORY, issue=BLOCKED),
        IssuePullRequestContext,
    )


def test_a_blocked_issue_names_what_blocks_it():
    found = list_blocking_issues(repository=REPOSITORY, issue=BLOCKED)

    assert isinstance(found, list)
    assert BLOCKING in [blocker.number for blocker in found]
