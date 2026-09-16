import json
from collections.abc import Sequence

import pytest
from conftest import (
    FILED,
    LABEL,
    LATER,
    REPOSITORY,
    listing,
    pull_request,
)

from dreamcatcher.config import Config
from dreamcatcher.eligibility import judge_issues
from dreamcatcher.github import Unknown
from dreamcatcher.state import CandidateIssue

# A block for one harness, so a label the tests write maps to something.
SETTINGS = {"prompt": "/dream:smith GH{issue}", "model": "opus[1m]", "effort": "xhigh"}


def config_with_routes(*, labels: Sequence[str]) -> Config:
    """A config that routes each label to the same harness recipe."""
    return Config.model_validate(
        {"dispatch": [{"label": label, "claude": SETTINGS} for label in labels]}
    )


@pytest.fixture
def gh(fake):
    """A gh answering an open issue that nothing at all stands in the way of."""
    stand_in = fake(program="gh")
    stand_in.replies(stdout=listing(issues=[(8, FILED)]), to="issue list")
    stand_in.replies(
        stdout=json.dumps({"closedByPullRequestsReferences": []}), to="issue view"
    )
    stand_in.replies(stdout=pull_request(state="OPEN", is_draft=True), to="pr view")
    stand_in.replies(stdout="[]", to="pr list")
    stand_in.replies(stdout=json.dumps([{"number": 7, "state": "closed"}]), to="api")
    return stand_in


def weighed(*, config, claimed=frozenset(), recovery_obstacles=None):
    """The candidates for that config, given that the listing came through."""
    judged = judge_issues(
        repository=REPOSITORY,
        config=config,
        claimed=set(claimed),
        recovery_obstacles=({} if recovery_obstacles is None else recovery_obstacles),
    )
    assert not isinstance(judged, Unknown)
    return judged


def test_an_issue_nothing_stands_in_the_way_of_can_be_dispatched(gh):
    judged = weighed(config=config_with_routes(labels=["dream:smith"]))

    assert judged == [CandidateIssue(issue=8, label=LABEL)]
    assert judged[0].is_eligible


def test_the_issues_come_back_oldest_first(gh):
    gh.replies(stdout=listing(issues=[(8, LATER), (3, FILED)]), to="issue list")

    assert [
        candidate.issue
        for candidate in weighed(config=config_with_routes(labels=["dream:smith"]))
    ] == [3, 8]


def test_a_listing_the_tool_cannot_read_answers_unknown_for_the_whole_tick(gh):
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")

    judged = judge_issues(
        repository=REPOSITORY,
        config=config_with_routes(labels=["dream:smith"]),
        claimed=set(),
        recovery_obstacles={},
    )

    assert isinstance(judged, Unknown)
    assert "could not connect" in judged.reason


def test_an_issue_carrying_more_than_one_dispatch_label_is_skipped(gh):
    assert weighed(config=config_with_routes(labels=["dream:smith", "dream:less"])) == [
        CandidateIssue(
            issue=8,
            label=LABEL,
            reason="carries more than one dispatch label: dream:less, dream:smith",
        ),
        CandidateIssue(
            issue=8,
            label="dream:less",
            reason="carries more than one dispatch label: dream:less, dream:smith",
        ),
    ]


def test_an_issue_an_assignment_of_this_run_is_working_on_is_left_alone(gh):
    assert weighed(config=config_with_routes(labels=["dream:smith"]), claimed={8}) == [
        CandidateIssue(
            issue=8,
            label=LABEL,
            reason="an assignment in this checkout is working on it",
        )
    ]


def test_an_issue_with_a_pull_request_open_on_it_is_left_alone(gh):
    gh.replies(
        stdout=json.dumps({"closedByPullRequestsReferences": [{"number": 28}]}),
        to="issue view",
    )

    assert weighed(config=config_with_routes(labels=["dream:smith"])) == [
        CandidateIssue(issue=8, label=LABEL, reason="a pull request is open on it: #28")
    ]


def test_a_recoverable_local_assignment_is_not_treated_as_an_external_claim(gh):
    assert weighed(
        config=config_with_routes(labels=["dream:smith"]),
        recovery_obstacles={8: None},
    ) == [CandidateIssue(issue=8, label=LABEL)]


def test_an_obstacle_to_local_assignment_recovery_is_reported(gh):
    assert weighed(
        config=config_with_routes(labels=["dream:smith"]),
        recovery_obstacles={8: "cannot reconcile its incomplete setup"},
    ) == [
        CandidateIssue(
            issue=8,
            label=LABEL,
            reason="cannot reconcile its incomplete setup",
        )
    ]


def test_a_pull_request_read_that_failed_reads_as_claimed(gh):
    gh.fails(stderr="gh: the issue is not there", to="issue view")

    assert weighed(config=config_with_routes(labels=["dream:smith"])) == [
        CandidateIssue(
            issue=8,
            label=LABEL,
            reason=(
                "cannot tell whether a pull request claims it: "
                "gh issue view 8 --repo alimanfoo/dreamcatcher --json "
                "closedByPullRequestsReferences failed with status 1: "
                "gh: the issue is not there"
            ),
        )
    ]


def test_an_issue_an_open_issue_blocks_names_what_blocks_it(gh):
    gh.replies(
        stdout=json.dumps(
            [{"number": 7, "state": "closed"}, {"number": 9, "state": "open"}]
        ),
        to="api",
    )

    assert weighed(config=config_with_routes(labels=["dream:smith"])) == [
        CandidateIssue(issue=8, label=LABEL, reason="blocked by GH9")
    ]


def test_a_blocker_read_that_failed_reads_as_blocked(gh):
    gh.fails(stderr="gh: could not connect to github.com", to="api")

    assert weighed(config=config_with_routes(labels=["dream:smith"])) == [
        CandidateIssue(
            issue=8,
            label=LABEL,
            reason=(
                "cannot tell what blocks it: gh api "
                f"repos/{REPOSITORY}/issues/8/dependencies/blocked_by "
                "failed with status 1: gh: could not connect to github.com"
            ),
        )
    ]
