import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dreamcatcher.github import (
    Blocker,
    BlockerState,
    Issue,
    LinkedPullRequest,
    PullRequest,
    PullRequestState,
    Unknown,
    blockers,
    identify,
    issues,
    linked_pull_requests,
    login,
    pull_requests,
)

REPOSITORY = "alimanfoo/dreamcatcher"
BRANCH = "dreamcatcher-GH8-20260820-000456"


def test_the_repository_comes_from_the_checkouts_own_remote(fake, tmp_path):
    gh = fake("gh")
    gh.replies(json.dumps({"nameWithOwner": REPOSITORY}))

    assert identify(tmp_path) == REPOSITORY
    assert gh.calls[0].arguments == ["repo", "view", "--json", "nameWithOwner"]
    assert gh.calls[0].directory == tmp_path.resolve()


def test_the_signed_in_account_is_the_one_gh_names(fake):
    gh = fake("gh")
    gh.replies(json.dumps({"login": "alimanfoo"}))

    assert login() == "alimanfoo"
    assert gh.calls[0].arguments == ["api", "user"]


def test_a_listing_carries_each_issue_and_when_it_was_filed(fake):
    gh = fake("gh")
    gh.replies(json.dumps([{"number": 8, "createdAt": "2026-08-19T18:41:58Z"}]))

    found = issues(REPOSITORY, label="dream:smith", assignee="@me")

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

    assert pull_requests(REPOSITORY, BRANCH) == [
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

    assert pull_requests(REPOSITORY, BRANCH) == []


def test_the_pull_requests_linked_to_an_issue_come_back(fake):
    gh = fake("gh")
    gh.replies(json.dumps({"closedByPullRequestsReferences": [{"number": 28}]}))

    assert linked_pull_requests(REPOSITORY, 8) == [LinkedPullRequest(number=28)]
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

    assert linked_pull_requests(REPOSITORY, 8) == []


def test_the_blockers_of_an_issue_come_back_with_their_states(fake):
    gh = fake("gh")
    gh.replies(
        json.dumps([{"number": 7, "state": "closed"}, {"number": 8, "state": "open"}])
    )

    assert blockers(REPOSITORY, 9) == [
        Blocker(number=7, state=BlockerState.CLOSED),
        Blocker(number=8, state=BlockerState.OPEN),
    ]
    assert gh.calls[0].arguments == [
        "api",
        f"repos/{REPOSITORY}/issues/9/dependencies/blocked_by",
    ]


@pytest.mark.parametrize(
    "ask",
    [
        pytest.param(lambda: identify(Path.cwd()), id="the repository"),
        pytest.param(login, id="the account"),
        pytest.param(
            lambda: issues(REPOSITORY, label="dream:smith", assignee="@me"),
            id="a listing",
        ),
        pytest.param(lambda: pull_requests(REPOSITORY, BRANCH), id="the pull requests"),
        pytest.param(
            lambda: linked_pull_requests(REPOSITORY, 9), id="the linked pull requests"
        ),
        pytest.param(lambda: blockers(REPOSITORY, 9), id="the blockers"),
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

    answered = issues(REPOSITORY, label="dream:smith", assignee="@me")

    assert isinstance(answered, Unknown)
    assert "cannot read" in answered.reason
