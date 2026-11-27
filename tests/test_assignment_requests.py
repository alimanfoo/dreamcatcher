"""Rows for the assignment requests that no open assignment answers yet.

Each test ticks with no agent slot, so the tick reads and records but starts
nothing.
"""

import json
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import LABEL_APPLIED_AT, PINNED
from conftest import (
    ASSIGNMENT_LABEL,
    FILED,
    LATER,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    compose_assignment_issues,
    compose_blocker,
    compose_issue_parent_read,
    compose_labelling_event,
    compose_labelling_event_read,
    compose_page,
    compose_pull_request,
    count_labelling_event_reads,
    offer_issue_parent,
    offer_labelling_events,
    offer_listing,
)
from records import (
    AssignmentRequestFacts,
    read_assignments,
    write_assignment,
    write_campaign,
    write_ending,
    write_work_pull_request,
)
from rows import UNCLAIMED, compose_request_row

from dreamcatcher.agent_work import AgentWorkEndReason
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness, DreamcatcherConfig
from dreamcatcher.pull_request_work import cancel_pull_request_work
from dreamcatcher.scheduler import Scheduler, SchedulingContext
from dreamcatcher.scheduler.models import (
    CampaignPullRequestMissingFinding,
    ConflictingLabelsFinding,
    IssueReference,
    LabelAppliedByOtherFinding,
    ReadFailureFinding,
    RequestConsumedFinding,
    SchedulerRecord,
    StartTimeFinding,
)
from dreamcatcher.state import StateDirectory

SETTINGS = {"prompt": "/dream:smith GH{issue}", "model": "opus[1m]", "effort": "xhigh"}
PARENT = 20
CAMPAIGN_PULL_REQUEST = 60
CAMPAIGN_LABEL = "dream:big"


def compose_config(
    *, labels: Sequence[str], campaign_labels: Sequence[str] = ()
) -> DreamcatcherConfig:
    """Return a config that routes each label to the same harness recipe."""
    return DreamcatcherConfig.model_validate(
        {
            "assignment": [{"label": label, "claude": SETTINGS} for label in labels],
            "campaign": [
                {"label": label, "claude": SETTINGS} for label in campaign_labels
            ],
        }
    )


@pytest.fixture
def gh(fake):
    """Return gh listing one open, assigned issue that nothing claims or blocks."""
    stand_in = fake(program="gh")
    offer_listing(gh=stand_in, issues=compose_assignment_issues(filed=[(8, FILED)]))
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
    stand_in.replies(stdout=compose_page(items=[]), to="api")
    return stand_in


@pytest.fixture
def state(tmp_path):
    """Return local state holding no agent work."""
    return StateDirectory(root=tmp_path)


def list_requests(
    *, state: StateDirectory, config: DreamcatcherConfig, max_agents: int = 0
) -> SchedulerRecord:
    """Return what a tick records for these routes."""
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
        max_agents=max_agents,
    ).tick(at=read_current_time())


def list_request_rows(*, state: StateDirectory, config: DreamcatcherConfig):
    """Return the request rows after asserting that the listing succeeded."""
    found = list_requests(state=state, config=config)
    assert found.failures == []
    return found.rows


def test_an_issue_nothing_claims_or_blocks_is_a_clear_request(gh, state):
    rows = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert rows == [compose_request_row(issue=8, finding=UNCLAIMED)]


@pytest.mark.parametrize("labels", [[], [CAMPAIGN_LABEL.upper()]])
def test_a_parent_without_campaign_history_is_decided_by_its_campaign_label(
    gh, state, labels
):
    offer_issue_parent(gh=gh, issue=8, parent=PARENT, repository=REPOSITORY.upper())
    [parent] = compose_assignment_issues(filed=[(PARENT, FILED)])
    parent["labels"] = [{"name": label} for label in labels]
    gh.replies(stdout=json.dumps(parent), to=f"issue view {PARENT}")

    [row] = list_request_rows(
        state=state,
        config=compose_config(
            labels=[ASSIGNMENT_LABEL], campaign_labels=[CAMPAIGN_LABEL]
        ),
    )

    assert row.finding == (
        CampaignPullRequestMissingFinding(parent=IssueReference(number=PARENT))
        if labels
        else UNCLAIMED
    )


@pytest.mark.parametrize(
    ("ending", "pull_request_state", "is_available"),
    [
        (None, None, False),
        (None, "OPEN", True),
        (AgentWorkEndReason.CANCELLED, "OPEN", True),
        (None, "MERGED", False),
        (None, "CLOSED", False),
        (AgentWorkEndReason.COMPLETED, "OPEN", False),
    ],
)
def test_a_campaign_sub_issue_can_start_only_into_an_open_campaign_pull_request(
    gh, state, ending, pull_request_state, is_available
):
    offer_issue_parent(gh=gh, issue=8, parent=PARENT)
    campaign = write_campaign(state=state, issue=PARENT)
    if ending is not None:
        write_ending(directory=campaign, reason=ending, at=PINNED)
    if pull_request_state is not None:
        write_work_pull_request(directory=campaign, number=CAMPAIGN_PULL_REQUEST)
        gh.replies(
            stdout=compose_pull_request(
                number=CAMPAIGN_PULL_REQUEST, state=pull_request_state
            ),
            to=f"pr view {CAMPAIGN_PULL_REQUEST}",
        )

    rows = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    [row] = [row for row in rows if row.issue == 8]
    assert row.finding == (
        UNCLAIMED
        if is_available
        else CampaignPullRequestMissingFinding(parent=IssueReference(number=PARENT))
    )
    assert sum(call.arguments[:2] == ["pr", "view"] for call in gh.calls) == int(
        pull_request_state is not None and ending is not AgentWorkEndReason.COMPLETED
    )


def test_a_parent_in_another_repository_does_not_match_a_local_campaign(gh, state):
    write_campaign(state=state, issue=PARENT)
    offer_issue_parent(gh=gh, issue=8, parent=PARENT, repository="another/repository")

    rows = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    [row] = [row for row in rows if row.issue == 8]
    assert row.finding == UNCLAIMED


@pytest.mark.parametrize("is_incomplete", [False, True])
def test_an_unknown_parent_does_not_start_an_assignment(gh, state, is_incomplete):
    command = compose_issue_parent_read(issue=8)
    if is_incomplete:
        gh.replies(stdout='{"data":{"repository":{"issue":{}}}}', to=command)
    else:
        gh.fails(stderr="gh: could not connect to github.com", to=command)

    tick = list_requests(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL]), max_agents=1
    )

    [row] = tick.rows
    assert isinstance(row.finding, ReadFailureFinding)
    assert tick.launched_agent_work_identifiers == []
    assert read_assignments(state=state) == []


@pytest.mark.parametrize("recorded_campaign", [False, True])
def test_a_failed_read_of_the_campaign_leaves_the_assignment_request_unknown(
    gh, state, recorded_campaign
):
    offer_issue_parent(gh=gh, issue=8, parent=PARENT)
    if recorded_campaign:
        campaign = write_campaign(state=state, issue=PARENT)
        write_work_pull_request(directory=campaign, number=CAMPAIGN_PULL_REQUEST)
        write_ending(directory=campaign, reason=AgentWorkEndReason.CANCELLED, at=PINNED)
        command = f"pr view {CAMPAIGN_PULL_REQUEST}"
    else:
        command = f"issue view {PARENT}"
    gh.fails(stderr="gh: could not connect to github.com", to=command)

    [row] = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert isinstance(row.finding, ReadFailureFinding)
    assert "could not connect" in row.finding.reason


def test_sub_issues_share_the_newest_campaign_pull_request_read_for_one_tick(gh, state):
    offer_listing(
        gh=gh, issues=compose_assignment_issues(filed=[(8, FILED), (9, LATER)])
    )
    for issue in (8, 9):
        offer_issue_parent(gh=gh, issue=issue, parent=PARENT)
    older = write_campaign(state=state, issue=PARENT)
    write_work_pull_request(directory=older, number=CAMPAIGN_PULL_REQUEST - 1)
    write_ending(directory=older, reason=AgentWorkEndReason.CANCELLED, at=PINNED)
    newer = write_campaign(
        state=state,
        issue=PARENT,
        at=PINNED - timedelta(hours=1),
        label_applied_at=LABEL_APPLIED_AT + timedelta(hours=1),
    )
    write_work_pull_request(directory=newer, number=CAMPAIGN_PULL_REQUEST)
    write_ending(directory=newer, reason=AgentWorkEndReason.CANCELLED, at=PINNED)
    gh.replies(
        stdout=compose_pull_request(number=CAMPAIGN_PULL_REQUEST, state="OPEN"),
        to=f"pr view {CAMPAIGN_PULL_REQUEST}",
    )
    config = compose_config(labels=[ASSIGNMENT_LABEL])

    rows = list_request_rows(state=state, config=config)

    assert [row.finding for row in rows] == [UNCLAIMED, UNCLAIMED]
    assert [
        call.arguments[:3] for call in gh.calls if call.arguments[:2] == ["pr", "view"]
    ] == [["pr", "view", str(CAMPAIGN_PULL_REQUEST)]]

    gh.replies(
        stdout=compose_pull_request(number=CAMPAIGN_PULL_REQUEST, state="CLOSED"),
        to=f"pr view {CAMPAIGN_PULL_REQUEST}",
    )
    rows = list_request_rows(state=state, config=config)

    assert [row.finding for row in rows] == [
        CampaignPullRequestMissingFinding(parent=IssueReference(number=PARENT))
    ] * 2


def test_a_clock_correction_does_not_make_an_older_label_application_available(
    gh, state
):
    for date, applied_at in (
        ("20260821", LABEL_APPLIED_AT),
        ("20260820", LABEL_APPLIED_AT + timedelta(hours=2)),
    ):
        directory = write_assignment(
            state=state,
            identifier=f"GH8-{date}-184158-assignment",
            issue=8,
            request_facts=AssignmentRequestFacts(label_applied_at=applied_at),
        )
        write_ending(
            directory=directory,
            reason=AgentWorkEndReason.COMPLETED,
            at=PINNED + timedelta(days=3),
        )
    issue = compose_assignment_issues(filed=[(8, FILED)])[0]
    issue["labels"] = [{"name": "dream:less"}]
    offer_listing(gh=gh, issues=[issue])
    offer_labelling_events(
        gh=gh,
        issue=8,
        events=[
            compose_labelling_event(
                label="dream:less", applied_at=LABEL_APPLIED_AT + timedelta(hours=1)
            )
        ],
    )

    rows = list_request_rows(state=state, config=compose_config(labels=["dream:less"]))

    assert rows == [
        compose_request_row(
            issue=8, label="dream:less", finding=RequestConsumedFinding()
        )
    ]
    assert not any(call.arguments[:3] == ["api", "graphql", "-F"] for call in gh.calls)


def test_requests_are_ordered_oldest_issue_first(gh, state):
    offer_listing(
        gh=gh, issues=compose_assignment_issues(filed=[(8, LATER), (3, FILED)])
    )

    rows = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert [row.issue for row in rows] == [3, 8]


def test_a_listing_failure_leaves_no_rows_and_is_a_failure(gh, state):
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")

    found = list_requests(state=state, config=compose_config(labels=[ASSIGNMENT_LABEL]))

    assert found.rows == []
    [failure] = found.failures
    assert "could not connect" in failure


def test_a_request_names_the_open_issues_that_block_it(gh, state):
    gh.replies(
        stdout=compose_page(
            items=[
                compose_blocker(number=7, state="closed"),
                compose_blocker(number=9, state="open"),
            ]
        ),
        to="api",
    )

    [row] = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert row.finding == StartTimeFinding(
        linked_pull_requests=[], blocking_issues=[IssueReference(number=9)]
    )
    assert not any(call.arguments[:3] == ["api", "graphql", "-F"] for call in gh.calls)


def test_a_request_names_the_repository_of_a_blocker_in_another_one(gh, state):
    gh.replies(
        stdout=compose_page(
            items=[
                compose_blocker(number=9, state="open", repository=REPOSITORY.upper()),
                compose_blocker(
                    number=1016, state="open", repository="alimanfoo/dream"
                ),
            ]
        ),
        to="api",
    )

    [row] = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

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
        stdout=compose_pull_request(state="OPEN", number=28, is_draft=True),
        to="pr view",
    )

    [row] = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert row.finding == StartTimeFinding(
        linked_pull_requests=[28], blocking_issues=[]
    )
    assert not row.finding.is_clear
    assert not any(call.arguments[:3] == ["api", "graphql", "-F"] for call in gh.calls)


def test_a_cancelled_assignments_pull_request_holds_a_reapplied_label(gh, state):
    write_assignment(state=state, identifier="GH8-20260819-184158-assignment", issue=8)
    cancel_pull_request_work(
        assignment=read_assignments(state=state)[0], at=read_current_time()
    )
    offer_labelling_events(
        gh=gh,
        issue=8,
        events=[
            compose_labelling_event(label=ASSIGNMENT_LABEL),
            compose_labelling_event(
                label=ASSIGNMENT_LABEL, applied_at=LABEL_APPLIED_AT + timedelta(hours=1)
            ),
        ],
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
        stdout=compose_pull_request(state="OPEN"),
        to="pr view",
    )

    [row] = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert row.finding == StartTimeFinding(
        linked_pull_requests=[PULL_REQUEST], blocking_issues=[]
    )


def test_each_of_two_assignment_labels_is_a_request_with_conflicting_labels(gh, state):
    [issue] = compose_assignment_issues(filed=[(8, FILED)])
    issue["labels"] = [{"name": ASSIGNMENT_LABEL}, {"name": "dream:less"}]
    offer_listing(gh=gh, issues=[issue])

    rows = list_request_rows(
        state=state,
        config=compose_config(labels=[ASSIGNMENT_LABEL, "dream:less"]),
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

    [row] = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert isinstance(row.finding, ReadFailureFinding)
    assert "could not connect" in row.finding.reason


def test_an_issue_with_an_open_assignment_has_no_request_row_of_its_own(gh, state):
    write_assignment(state=state, identifier="GH8-20260819-184158-assignment", issue=8)

    rows = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert [row.agent_work_identifier for row in rows] == [
        "GH8-20260819-184158-assignment"
    ]
    assert ["issue", "view"] not in [call.arguments[:2] for call in gh.calls]


@pytest.mark.parametrize(
    ("appliers", "finding"),
    [
        (["colleague"], LabelAppliedByOtherFinding(applier="colleague")),
        ([POSTED_BY, "colleague"], LabelAppliedByOtherFinding(applier="colleague")),
        (["colleague", POSTED_BY.upper()], UNCLAIMED),
        ([None], LabelAppliedByOtherFinding(applier="")),
    ],
)
def test_the_latest_account_to_apply_the_label_decides_whether_work_may_start(
    gh, state, appliers, finding
):
    offer_labelling_events(
        gh=gh,
        issue=8,
        events=[
            compose_labelling_event(label=ASSIGNMENT_LABEL.upper(), applier=applier)
            for applier in appliers
        ],
    )

    rows = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert rows == [compose_request_row(issue=8, finding=finding)]


def test_only_events_that_apply_the_requests_label_decide(gh, state):
    offer_labelling_events(
        gh=gh,
        issue=8,
        events=[
            compose_labelling_event(label=ASSIGNMENT_LABEL),
            compose_labelling_event(label="bug", applier="colleague"),
        ],
    )

    rows = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert rows == [compose_request_row(issue=8, finding=UNCLAIMED)]


def test_a_label_that_no_event_applied_yet_leaves_the_request_unknown(gh, state):
    offer_labelling_events(gh=gh, issue=8, events=[])

    rows = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert rows == [
        compose_request_row(
            issue=8,
            finding=ReadFailureFinding(
                reason="GitHub has not yet recorded who applied the label"
            ),
        )
    ]


def test_a_failed_read_of_the_issues_events_leaves_the_request_unknown(gh, state):
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=compose_labelling_event_read(issue=8),
    )

    [row] = list_request_rows(
        state=state, config=compose_config(labels=[ASSIGNMENT_LABEL])
    )

    assert isinstance(row.finding, ReadFailureFinding)
    assert "could not connect" in row.finding.reason


def test_a_held_request_asks_no_start_time_questions(gh, state):
    offer_labelling_events(
        gh=gh,
        issue=8,
        events=[compose_labelling_event(label=ASSIGNMENT_LABEL, applier="colleague")],
    )

    list_request_rows(state=state, config=compose_config(labels=[ASSIGNMENT_LABEL]))

    listing, _ = gh.calls
    assert listing.arguments[:2] == ["issue", "list"]
    assert count_labelling_event_reads(gh=gh, issue=8) == 1


def test_an_open_assignment_reads_no_events(gh, state):
    write_assignment(state=state, identifier="GH8-20260819-184158-assignment", issue=8)

    list_request_rows(state=state, config=compose_config(labels=[ASSIGNMENT_LABEL]))

    assert count_labelling_event_reads(gh=gh, issue=8) == 0
