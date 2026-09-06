import json

import pytest
from conftest import FILED, LABEL, LATER, REPOSITORY, listing

from dreamcatcher.config import Config
from dreamcatcher.eligibility import judge_issues
from dreamcatcher.github import Unknown
from dreamcatcher.state import CandidateIssue

# A block for one harness, so a label the tests write maps to something.
SETTINGS = {"prompt": "/dream:smith GH{issue}", "model": "opus[1m]", "effort": "xhigh"}


def mapping(*labels: str) -> Config:
    """A config mapping each of these labels to the same harness block."""
    return Config.model_validate(
        {"dispatch": [{"label": label, "claude": SETTINGS} for label in labels]}
    )


@pytest.fixture
def gh(fake):
    """A gh answering an open issue that nothing at all stands in the way of."""
    stand_in = fake("gh")
    stand_in.replies(listing((8, FILED)), to="issue list")
    stand_in.replies(
        json.dumps({"closedByPullRequestsReferences": []}), to="issue view"
    )
    stand_in.replies(json.dumps([{"number": 7, "state": "closed"}]), to="api")
    return stand_in


def weighed(config, claimed=frozenset()):
    """The candidates for that config, given that the listing came through."""
    judged = judge_issues(REPOSITORY, config, claimed=set(claimed))
    assert not isinstance(judged, Unknown)
    return judged


def test_an_issue_nothing_stands_in_the_way_of_can_be_dispatched(gh):
    judged = weighed(mapping("dream:smith"))

    assert judged == [CandidateIssue(issue=8, label=LABEL)]
    assert judged[0].is_eligible


def test_the_issues_come_back_oldest_first(gh):
    gh.replies(listing((8, LATER), (3, FILED)), to="issue list")

    assert [candidate.issue for candidate in weighed(mapping("dream:smith"))] == [3, 8]


def test_a_listing_the_tool_cannot_read_answers_unknown_for_the_whole_tick(gh):
    gh.fails("gh: could not connect to github.com", to="issue list")

    judged = judge_issues(REPOSITORY, mapping("dream:smith"), claimed=set())

    assert isinstance(judged, Unknown)
    assert "could not connect" in judged.reason


def test_an_issue_carrying_more_than_one_mapped_label_is_skipped(gh):
    assert weighed(mapping("dream:smith", "dream:less")) == [
        CandidateIssue(
            issue=8,
            label=LABEL,
            reason="carries more than one mapped label: dream:less, dream:smith",
        ),
        CandidateIssue(
            issue=8,
            label="dream:less",
            reason="carries more than one mapped label: dream:less, dream:smith",
        ),
    ]


def test_an_issue_a_session_of_this_run_is_working_on_is_left_alone(gh):
    assert weighed(mapping("dream:smith"), claimed={8}) == [
        CandidateIssue(
            issue=8, label=LABEL, reason="a session in this checkout is working on it"
        )
    ]


def test_an_issue_with_a_pull_request_open_on_it_is_left_alone(gh):
    gh.replies(
        json.dumps({"closedByPullRequestsReferences": [{"number": 28}]}),
        to="issue view",
    )

    assert weighed(mapping("dream:smith")) == [
        CandidateIssue(issue=8, label=LABEL, reason="a pull request is open on it: #28")
    ]


def test_a_pull_request_read_that_failed_reads_as_claimed(gh):
    gh.fails("gh: the issue is not there", to="issue view")

    assert weighed(mapping("dream:smith")) == [
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
        json.dumps([{"number": 7, "state": "closed"}, {"number": 9, "state": "open"}]),
        to="api",
    )

    assert weighed(mapping("dream:smith")) == [
        CandidateIssue(issue=8, label=LABEL, reason="blocked by GH9")
    ]


def test_a_blocker_read_that_failed_reads_as_blocked(gh):
    gh.fails("gh: could not connect to github.com", to="api")

    assert weighed(mapping("dream:smith")) == [
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
