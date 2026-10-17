"""Rows for the assignment requests that no open assignment answers yet."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from conftest import (
    ASSIGNMENT_LABEL,
    FILED,
    LATER,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    listing,
    pages,
)
from records import read_assignments, write_assignment
from rows import UNCLAIMED, request_row

from dreamcatcher.agent_assignments import cancel_assignment
from dreamcatcher.agent_work import AgentWork
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness, DreamcatcherConfig
from dreamcatcher.scheduler.assignments import AssignmentScheduler
from dreamcatcher.scheduler.issues import (
    AssignmentRequestListing,
    list_assignment_requests,
)
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    ReadFailure,
    StartTimeFinding,
)
from dreamcatcher.state import StateDirectory

SETTINGS = {"prompt": "/dream:smith GH{issue}", "model": "opus[1m]", "effort": "xhigh"}


def config_with_routes(*, labels: Sequence[str]) -> DreamcatcherConfig:
    """Return a config that routes each label to the same harness recipe."""
    return DreamcatcherConfig.model_validate(
        {
            "assignment": [{"label": label, "claude": SETTINGS} for label in labels],
        }
    )


@pytest.fixture
def gh(fake):
    """Return gh listing one open, assigned issue that nothing claims or blocks."""
    stand_in = fake(program="gh")
    stand_in.replies(stdout=listing(issues=[(8, FILED)]), to="issue list")
    stand_in.replies(
        stdout=json.dumps(
            {
                "number": 8,
                "title": "The issue title",
                "closedByPullRequestsReferences": [],
            }
        ),
        to="issue view",
    )
    stand_in.replies(stdout=pages(items=[]), to="api")
    return stand_in


def list_requests(
    *,
    config: DreamcatcherConfig,
    assignments: Sequence[AgentWork] = (),
) -> AssignmentRequestListing:
    """Return the assignment request rows and failures for these routes."""
    return list_assignment_requests(
        scheduler=AssignmentScheduler(
            repository=REPOSITORY,
            account=POSTED_BY,
            config=config,
            state=StateDirectory(root=Path()),
            preferred_harness=AgentHarness.CLAUDE,
            clock=read_current_time,
        ),
        assignments=list(assignments),
    )


def rows_for(*, config: DreamcatcherConfig, assignments: Sequence[AgentWork] = ()):
    """Return the request rows after asserting that the listing succeeded."""
    found = list_requests(config=config, assignments=assignments)
    assert found.failures == []
    return found.rows


def test_an_issue_nothing_claims_or_blocks_is_a_clear_request(gh):
    rows = rows_for(config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert rows == [request_row(issue=8, finding=UNCLAIMED)]
    assert UNCLAIMED.is_clear


def test_requests_are_ordered_oldest_issue_first(gh):
    gh.replies(stdout=listing(issues=[(8, LATER), (3, FILED)]), to="issue list")

    rows = rows_for(config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert [row.issue for row in rows] == [3, 8]


def test_a_listing_failure_leaves_no_rows_and_is_a_failure(gh):
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")

    found = list_requests(config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert found.rows == []
    [failure] = found.failures
    assert "could not connect" in failure


def test_a_later_route_failure_keeps_the_rows_of_earlier_routes(gh):
    gh.replies(
        stdout=listing(issues=[(8, FILED)]),
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} "
            f"--label {ASSIGNMENT_LABEL}"
        ),
    )
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=(
            f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} --label dream:less"
        ),
    )

    found = list_requests(
        config=config_with_routes(labels=[ASSIGNMENT_LABEL, "dream:less"])
    )

    [failure] = found.failures
    assert "could not connect" in failure
    assert [row.issue for row in found.rows] == [8]


def test_a_request_names_the_open_issues_that_block_it(gh):
    gh.replies(
        stdout=pages(
            items=[
                {"number": 7, "state": "closed"},
                {"number": 9, "state": "open"},
            ]
        ),
        to="api",
    )

    [row] = rows_for(config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert row.finding == StartTimeFinding(linked_pull_requests=[], blocking_issues=[9])


def test_a_request_names_the_open_pull_requests_that_claim_it(gh):
    gh.replies(
        stdout=json.dumps(
            {"number": 8, "closedByPullRequestsReferences": [{"number": 28}]}
        ),
        to="issue view",
    )
    gh.replies(
        stdout=json.dumps({"number": 28, "state": "OPEN", "isDraft": True}),
        to="pr view",
    )

    [row] = rows_for(config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert row.finding == StartTimeFinding(
        linked_pull_requests=[28], blocking_issues=[]
    )
    assert not row.finding.is_clear


def test_a_cancelled_assignments_pull_request_claims_its_issue(gh, tmp_path):
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier="GH8-20260819-184158-assignment", issue=8)
    cancel_assignment(
        assignment=read_assignments(state=state)[0], at=read_current_time()
    )
    gh.replies(
        stdout=json.dumps(
            {
                "number": 8,
                "title": "The issue title",
                "closedByPullRequestsReferences": [{"number": PULL_REQUEST}],
            }
        ),
        to="issue view",
    )
    gh.replies(
        stdout=json.dumps({"number": PULL_REQUEST, "state": "OPEN", "isDraft": False}),
        to="pr view",
    )

    [row] = rows_for(
        config=config_with_routes(labels=[ASSIGNMENT_LABEL]),
        assignments=read_assignments(state=state),
    )

    assert row.finding == StartTimeFinding(
        linked_pull_requests=[PULL_REQUEST], blocking_issues=[]
    )


def test_each_of_two_assignment_labels_is_a_request_with_conflicting_labels(gh):
    issue = json.loads(listing(issues=[(8, FILED)]))[0]
    issue["labels"] = [{"name": ASSIGNMENT_LABEL}, {"name": "dream:less"}]
    gh.replies(stdout=json.dumps([issue]), to="issue list")

    rows = rows_for(config=config_with_routes(labels=[ASSIGNMENT_LABEL, "dream:less"]))

    conflict = ConflictingLabelsFinding(labels=["dream:less", ASSIGNMENT_LABEL])
    assert [(row.dispatch_label, row.finding) for row in rows] == [
        ("dream:less", conflict),
        (ASSIGNMENT_LABEL, conflict),
    ]
    assert [call.arguments[:2] for call in gh.calls] == [["issue", "list"]] * 2


@pytest.mark.parametrize("read", ["issue view", "api"])
def test_a_failed_start_time_read_leaves_the_request_unknown(gh, read):
    gh.fails(stderr="gh: could not connect to github.com", to=read)

    [row] = rows_for(config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert isinstance(row.finding, ReadFailure)
    assert "could not connect" in row.finding.reason


def test_an_issue_with_an_open_assignment_has_no_request_row_of_its_own(gh, tmp_path):
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier="GH8-20260819-184158-assignment", issue=8)

    rows = rows_for(
        config=config_with_routes(labels=[ASSIGNMENT_LABEL]),
        assignments=read_assignments(state=state),
    )

    assert rows == []
    assert [call.arguments[:2] for call in gh.calls] == [["issue", "list"]]
