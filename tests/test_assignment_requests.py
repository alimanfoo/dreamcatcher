"""Rows for the assignment requests that no open assignment answers yet.

Each test ticks with no agent slot, so the tick reads and records but starts
nothing.
"""

import json
from collections.abc import Sequence

import pytest
from conftest import (
    ASSIGNMENT_LABEL,
    FILED,
    LATER,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    blocker,
    listing,
    pages,
    pull_request,
)
from records import read_assignments, write_assignment
from rows import UNCLAIMED, request_row

from dreamcatcher.agent_assignments import cancel_assignment
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness, DreamcatcherConfig
from dreamcatcher.scheduler import Scheduler, SchedulingContext
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueReference,
    ReadFailureFinding,
    SchedulerRecord,
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


@pytest.fixture
def state(tmp_path):
    """Return local state holding no agent work."""
    return StateDirectory(root=tmp_path)


def list_requests(
    *, state: StateDirectory, config: DreamcatcherConfig
) -> SchedulerRecord:
    """Return what a tick with no free agent slot records for these routes."""
    return Scheduler(
        context=SchedulingContext(
            repository=REPOSITORY,
            account=POSTED_BY,
            config=config,
            state=state,
            clock=read_current_time,
        ),
        preferred_harness=AgentHarness.CLAUDE,
        rounds={},
        max_agents=0,
    ).tick(at=read_current_time())


def rows_for(*, state: StateDirectory, config: DreamcatcherConfig):
    """Return the request rows after asserting that the listing succeeded."""
    found = list_requests(state=state, config=config)
    assert found.failures == []
    return found.rows


def test_an_issue_nothing_claims_or_blocks_is_a_clear_request(gh, state):
    rows = rows_for(state=state, config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert rows == [request_row(issue=8, finding=UNCLAIMED)]


def test_requests_are_ordered_oldest_issue_first(gh, state):
    gh.replies(stdout=listing(issues=[(8, LATER), (3, FILED)]), to="issue list")

    rows = rows_for(state=state, config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert [row.issue for row in rows] == [3, 8]


def test_a_listing_failure_leaves_no_rows_and_is_a_failure(gh, state):
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")

    found = list_requests(
        state=state, config=config_with_routes(labels=[ASSIGNMENT_LABEL])
    )

    assert found.rows == []
    [failure] = found.failures
    assert "could not connect" in failure


def test_a_request_names_the_open_issues_that_block_it(gh, state):
    gh.replies(
        stdout=pages(
            items=[
                blocker(number=7, state="closed"),
                blocker(number=9, state="open"),
            ]
        ),
        to="api",
    )

    [row] = rows_for(state=state, config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert row.finding == StartTimeFinding(
        linked_pull_requests=[], blocking_issues=[IssueReference(number=9)]
    )


def test_a_request_names_the_repository_of_a_blocker_in_another_one(gh, state):
    gh.replies(
        stdout=pages(
            items=[
                blocker(number=9, state="open", repository=REPOSITORY.upper()),
                blocker(number=1016, state="open", repository="alimanfoo/dream"),
            ]
        ),
        to="api",
    )

    [row] = rows_for(state=state, config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert row.finding == StartTimeFinding(
        linked_pull_requests=[],
        blocking_issues=[
            IssueReference(number=9),
            IssueReference(number=1016, repository="alimanfoo/dream"),
        ],
    )


def test_a_request_names_the_open_pull_requests_that_claim_it(gh, state):
    gh.replies(
        stdout=json.dumps(
            {"number": 8, "closedByPullRequestsReferences": [{"number": 28}]}
        ),
        to="issue view",
    )
    gh.replies(
        stdout=pull_request(state="OPEN", number=28, is_draft=True),
        to="pr view",
    )

    [row] = rows_for(state=state, config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert row.finding == StartTimeFinding(
        linked_pull_requests=[28], blocking_issues=[]
    )
    assert not row.finding.is_clear


def test_a_cancelled_assignments_pull_request_claims_its_issue(gh, state):
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
        stdout=pull_request(state="OPEN"),
        to="pr view",
    )

    [row] = rows_for(state=state, config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert row.finding == StartTimeFinding(
        linked_pull_requests=[PULL_REQUEST], blocking_issues=[]
    )


def test_each_of_two_assignment_labels_is_a_request_with_conflicting_labels(gh, state):
    issue = json.loads(listing(issues=[(8, FILED)]))[0]
    issue["labels"] = [{"name": ASSIGNMENT_LABEL}, {"name": "dream:less"}]
    gh.replies(stdout=json.dumps([issue]), to="issue list")

    rows = rows_for(
        state=state,
        config=config_with_routes(labels=[ASSIGNMENT_LABEL, "dream:less"]),
    )

    conflict = ConflictingLabelsFinding(labels=["dream:less", ASSIGNMENT_LABEL])
    assert [(row.dispatch_label, row.finding) for row in rows] == [
        ("dream:less", conflict),
        (ASSIGNMENT_LABEL, conflict),
    ]
    assert [call.arguments[:2] for call in gh.calls] == [["issue", "list"]]


@pytest.mark.parametrize("read", ["issue view", "api"])
def test_a_failed_start_time_read_leaves_the_request_unknown(gh, state, read):
    gh.fails(stderr="gh: could not connect to github.com", to=read)

    [row] = rows_for(state=state, config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert isinstance(row.finding, ReadFailureFinding)
    assert "could not connect" in row.finding.reason


def test_an_issue_with_an_open_assignment_has_no_request_row_of_its_own(gh, state):
    write_assignment(state=state, identifier="GH8-20260819-184158-assignment", issue=8)

    rows = rows_for(state=state, config=config_with_routes(labels=[ASSIGNMENT_LABEL]))

    assert [row.agent_work_identifier for row in rows] == [
        "GH8-20260819-184158-assignment"
    ]
    assert ["issue", "view"] not in [call.arguments[:2] for call in gh.calls]
