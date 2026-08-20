"""What the real gh answers about this repository. Read-only, and never in CI."""

from pathlib import Path

import pytest

from dreamcatcher.github import (
    PullRequest,
    PullRequestState,
    blockers,
    identify,
    issues,
    login,
    pull_request,
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
    assert identify(CHECKOUT) == REPOSITORY


def test_gh_is_signed_in_as_somebody():
    assert login()


def test_the_dispatch_label_lists_the_issues_it_carries():
    assert isinstance(issues(REPOSITORY, label="dream:smith", assignee="@me"), list)


def test_a_merged_pull_request_comes_back_merged():
    found = pull_request(REPOSITORY, MERGED_BRANCH)

    assert isinstance(found, PullRequest)
    assert found.number == MERGED
    assert found.state is PullRequestState.MERGED


def test_a_branch_that_never_existed_has_no_pull_request():
    assert pull_request(REPOSITORY, "dreamcatcher-GH0-19700101-000000") is None


def test_a_blocked_issue_names_what_blocks_it():
    found = blockers(REPOSITORY, BLOCKED)

    assert isinstance(found, list)
    assert BLOCKING in [blocker.number for blocker in found]
