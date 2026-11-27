"""Read local status for campaigns."""

import os
import re
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from records import (
    HEAD,
    compose_campaign_identifier,
    hold_daemon_lock_for_test,
    read_campaign,
    write_assignment,
    write_campaign,
    write_daemon_run,
    write_ending,
    write_round,
    write_tick,
    write_work_pull_request,
)
from rows import (
    CAMPAIGN_PULL_REQUEST,
    UNCLAIMED,
    compose_campaign_finding,
    compose_request_row,
)

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
    _AgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import AgentWorkEndReason
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignChildAssignment,
    CampaignChildChange,
    CampaignChildNotification,
    CampaignRoundInput,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import IssueComment, IssueState, PullRequestState
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import (
    IssueCommentsFinding,
    IssueReference,
    ReadFailureFinding,
    RequestFinding,
    RequestRow,
    SchedulerRecord,
    StartedRound,
    StartTimeFinding,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentWorkStatus,
    AgentWorkStatusValue,
    read_agent_work_status,
    read_dreamcatcher_daemon_status,
    read_status_report,
)
from dreamcatcher.status.requests import RequestStatusValue
from dreamcatcher.status.rounds import AgentRoundTriggerNotification

LOOKED_AT = PINNED + timedelta(hours=2)
PARENT = 20
ERRORED = _compose_agent_round_ending(at=PINNED + timedelta(minutes=4), status=2)
SUCCESSFUL = SuccessfulAgentRoundEnding(at=PINNED + timedelta(minutes=3))
NOTHING_NEW = compose_campaign_finding()


@pytest.fixture
def state(tmp_path):
    """Return local state written by a running daemon, holding one campaign."""
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())
    hold_daemon_lock_for_test(path=state.lock)
    directory = write_campaign(state=state, issue=PARENT)
    write_work_pull_request(directory=directory, number=CAMPAIGN_PULL_REQUEST)
    return state


def write_lead_round(
    *,
    state: StateDirectory,
    number: int,
    ending: _AgentRoundEnding | None,
    posts: int | None = 0,
    pull_request_state: PullRequestState = PullRequestState.OPEN,
    children: Sequence[CampaignChild] = (),
    notifications: Sequence[CampaignChildNotification] = (),
) -> None:
    """Write one round of the campaign, given that many posts.

    The round is also given these children and these notifications.
    """
    given = [
        IssueComment(
            id=identifier,
            author="alimanfoo",
            written_at="2026-09-23T01:00:00Z",
            body="Carry on.",
        )
        for identifier in range(1, (posts or 0) + 1)
    ]
    write_round(
        directory=state.work / compose_campaign_identifier(issue=PARENT),
        number=number,
        record=AgentRoundRecord(
            number=number, started=PINNED + timedelta(minutes=number), ending=ending
        ),
        round_input=(
            None
            if posts is None
            else CampaignRoundInput(
                pull_request=CAMPAIGN_PULL_REQUEST,
                pull_request_state=pull_request_state,
                pull_request_head=HEAD,
                signals=[],
                children=children,
                notifications=notifications,
                user_posts=given,
                assignment_routes=[],
            )
        ),
    )


def observe(
    *,
    state: StateDirectory,
    finding: RequestFinding | None,
    ended_round: int | None = None,
    started_round: StartedRound | None = None,
    children: list[CampaignChild] | None = None,
    other_rows: Sequence[RequestRow] = (),
) -> None:
    """Write a tick that saw the campaign with this finding and these children.

    The tick also saw the other rows.
    """
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[
                compose_request_row(
                    issue=PARENT,
                    kind=AgentWorkKind.CAMPAIGN,
                    agent_work_identifier=compose_campaign_identifier(issue=PARENT),
                    ended_round=ended_round,
                    finding=finding,
                    started_round=started_round,
                ).model_copy(update={"children": children}),
                *other_rows,
            ],
        ),
    )


def read_campaign_status(*, state: StateDirectory) -> AgentWorkStatus:
    """Return the status of the campaign at the parent."""
    campaign = read_campaign(state=state, issue=PARENT)
    assert campaign is not None
    return read_agent_work_status(
        state=state,
        work=campaign,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )


def test_a_labelled_parent_with_no_campaign_yet_is_available(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            rows=[
                compose_request_row(
                    issue=PARENT, kind=AgentWorkKind.CAMPAIGN, finding=UNCLAIMED
                )
            ],
        ),
    )

    [request] = read_status_report(
        state=state, clock=lambda: LOOKED_AT
    ).list_request_statuses(kind=AgentWorkKind.CAMPAIGN)

    assert request.value is RequestStatusValue.AVAILABLE
    assert request.issue_facts == ()
    assert request.detail is None


def test_a_campaign_whose_lead_has_not_run_is_waiting(state):
    observe(state=state, finding=NOTHING_NEW)

    status = read_campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "no round has run yet"


def test_a_running_lead_is_working_on_its_start(state):
    write_lead_round(state=state, number=1, ending=None)
    observe(state=state, finding=NOTHING_NEW, started_round=StartedRound(number=1))

    status = read_campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.WORKING
    assert status.detail is not None
    assert status.detail.startswith("round 1, start, running ")


def test_a_running_lead_counts_the_sub_issues_that_woke_it(state):
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    write_lead_round(
        state=state,
        number=2,
        ending=None,
        posts=1,
        children=[compose_child(issue=21, state=IssueState.CLOSED)],
        notifications=[
            notify(
                issue=21,
                changes=[CampaignChildChange.ISSUE_STATE, CampaignChildChange.ENDING],
            ),
            notify(issue=22, changes=[CampaignChildChange.REMOVED]),
        ],
    )
    observe(state=state, finding=NOTHING_NEW, started_round=StartedRound(number=2))

    status = read_campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.WORKING
    assert status.detail is not None
    assert status.detail.startswith("round 2, 1 post, 2 sub-issues changed, running ")


@pytest.mark.parametrize(
    ("ending", "detail"),
    [
        (SUCCESSFUL, "needs feedback"),
        (
            StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=2)),
            "needs feedback",
        ),
    ],
)
def test_a_lead_that_took_its_turn_is_idle_with_a_draft_pull_request(
    state, ending, detail
):
    write_lead_round(state=state, number=1, ending=ending)
    observe(state=state, finding=NOTHING_NEW, ended_round=1)

    status = read_campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == detail


def test_a_lead_that_finished_after_the_update_started_it_awaits_the_next(state):
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    observe(state=state, finding=NOTHING_NEW, started_round=StartedRound(number=1))

    status = read_campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == "round 1 ended, awaiting next update"


@pytest.mark.parametrize(
    ("new_posts", "changed_children", "detail"),
    [
        (2, 0, "2 new posts to answer"),
        (0, 1, "1 sub-issue changed"),
        (1, 2, "1 new post to answer, 2 sub-issues changed"),
    ],
)
def test_a_lead_with_new_input_is_waiting_for_it(
    state, new_posts, changed_children, detail
):
    write_lead_round(
        state=state,
        number=1,
        ending=StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=2)),
    )
    observe(
        state=state,
        finding=compose_campaign_finding(
            new_posts=new_posts, changed_children=changed_children
        ),
        ended_round=1,
    )

    status = read_campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == detail


def test_a_lead_whose_round_did_not_finish_waits_to_recover(state):
    write_lead_round(state=state, number=1, ending=InterruptedAgentRoundEnding())
    observe(state=state, finding=NOTHING_NEW, ended_round=1)

    status = read_campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "round 1 interrupted"


def test_two_errored_lead_rounds_are_a_fault(state):
    write_lead_round(state=state, number=1, ending=ERRORED)
    write_lead_round(state=state, number=2, ending=ERRORED)
    observe(state=state, finding=None, ended_round=2)

    status = read_campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.FAULT
    assert status.faulted_round_number == 2


def test_a_finished_campaign_shows_its_merged_pull_request(state):
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    write_lead_round(
        state=state,
        number=2,
        ending=SUCCESSFUL,
        pull_request_state=PullRequestState.MERGED,
    )

    status = read_campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.ENDED
    assert status.words == "completed"
    assert status.issue_state is None
    assert status.pull_request_summary == "merged"
    assert status.detail is None


def test_lead_rounds_name_their_trigger(state):
    write_lead_round(state=state, number=1, ending=ERRORED, posts=1)
    write_lead_round(state=state, number=2, ending=SUCCESSFUL, posts=1)
    write_lead_round(
        state=state,
        number=3,
        ending=SUCCESSFUL,
        posts=2,
        children=[compose_child(issue=21, state=IssueState.OPEN)],
        notifications=[notify(issue=21, changes=[CampaignChildChange.ADDED])],
    )
    write_lead_round(
        state=state,
        number=4,
        ending=SUCCESSFUL,
        children=[compose_child(issue=21, state=IssueState.CLOSED)],
        notifications=[
            notify(
                issue=21,
                changes=[CampaignChildChange.ISSUE_STATE, CampaignChildChange.ENDING],
            ),
            notify(issue=22, changes=[CampaignChildChange.REMOVED]),
        ],
    )
    write_lead_round(state=state, number=5, ending=ERRORED, posts=None)
    write_lead_round(state=state, number=6, ending=SUCCESSFUL)

    rounds = read_campaign_status(state=state).round_statuses

    assert [round_status.trigger.describe() for round_status in rounds] == [
        "start",
        "1 post",
        "2 posts; #21: added",
        "#21: closed, ended; #22: removed",
        "pull request or sub-issue changes",
        "recover",
    ]


def notify(
    *, issue: int, changes: Sequence[CampaignChildChange]
) -> CampaignChildNotification:
    """Return the notification of these changes to one child."""
    return CampaignChildNotification(issue=issue, changes=changes)


@pytest.mark.parametrize(
    ("state_now", "change", "words"),
    [
        (IssueState.OPEN, CampaignChildChange.ADDED, "added"),
        (IssueState.OPEN, CampaignChildChange.ISSUE_STATE, "reopened"),
        (IssueState.CLOSED, CampaignChildChange.ISSUE_STATE, "closed"),
        (IssueState.OPEN, CampaignChildChange.HANDBACK, "handed back"),
        (IssueState.OPEN, CampaignChildChange.PULL_REQUEST, "pull request changed"),
        (IssueState.OPEN, CampaignChildChange.CHECK_COMPLETION, "checks finished"),
        (IssueState.OPEN, CampaignChildChange.MERGEABLE, "mergeable"),
        (IssueState.OPEN, CampaignChildChange.ENDING, "ended"),
        (IssueState.OPEN, CampaignChildChange.FAULT, "fault"),
    ],
)
def test_a_lead_round_names_each_change_to_a_sub_issue(state, state_now, change, words):
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    write_lead_round(
        state=state,
        number=2,
        ending=SUCCESSFUL,
        children=[compose_child(issue=21, state=state_now)],
        notifications=[notify(issue=21, changes=[change])],
    )

    trigger = read_campaign_status(state=state).round_statuses[1].trigger

    assert trigger.notifications == (
        AgentRoundTriggerNotification(issue=21, changes=words),
    )
    assert trigger.describe() == f"#21: {words}"


def compose_child(*, issue: int, state: IssueState) -> CampaignChild:
    """Return one settled child with no assignment, in this state."""
    return CampaignChild(
        issue=issue,
        title=f"Stage {issue}",
        state=state,
        is_settled=True,
        assignment=None,
    )


@pytest.mark.parametrize(
    ("children", "summary"),
    [
        (None, "sub-issues unknown"),
        ([], "no sub-issues"),
        (
            [
                compose_child(issue=21, state=IssueState.CLOSED),
                compose_child(issue=22, state=IssueState.OPEN),
                compose_child(issue=23, state=IssueState.CLOSED),
            ],
            "2 of 3 sub-issues closed",
        ),
    ],
)
def test_an_active_campaign_counts_its_closed_children(state, children, summary):
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    observe(state=state, finding=NOTHING_NEW, ended_round=1, children=children)

    status = read_campaign_status(state=state)

    assert status.children == children
    assert status.closed_children_summary == summary


def test_an_ended_campaign_shows_no_children(state):
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    write_ending(
        directory=state.work / compose_campaign_identifier(issue=PARENT),
        reason=AgentWorkEndReason.COMPLETED,
        at=LOOKED_AT,
    )
    observe(
        state=state,
        finding=None,
        ended_round=1,
        children=[compose_child(issue=21, state=IssueState.CLOSED)],
    )

    status = read_campaign_status(state=state)

    assert (status.children, status.closed_children_summary) == (None, None)


def test_each_child_of_an_active_campaign_has_its_assignment_and_requests(state):
    assignment = "GH21-20260819-184158-assignment"
    write_assignment(state=state, identifier=assignment, issue=21)
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    children = [
        compose_child(issue=21, state=IssueState.OPEN).model_copy(
            update={
                "assignment": CampaignChildAssignment(
                    identifier=assignment,
                    pull_request=52,
                    observed_pull_request=None,
                    finished_turn=None,
                    ending=None,
                    is_in_fault=False,
                )
            }
        ),
        compose_child(issue=22, state=IssueState.OPEN),
        compose_child(issue=23, state=IssueState.CLOSED),
    ]
    observe(
        state=state,
        finding=NOTHING_NEW,
        ended_round=1,
        children=children,
        other_rows=[
            compose_request_row(issue=22, finding=UNCLAIMED),
            compose_request_row(
                issue=23,
                kind=AgentWorkKind.CONVERSATION,
                finding=IssueCommentsFinding(new_comments=0),
            ),
        ],
    )
    report = read_status_report(state=state, clock=lambda: LOOKED_AT)
    [campaign] = report.list_active_work_statuses(kind=AgentWorkKind.CAMPAIGN)

    child_statuses = report.list_campaign_child_statuses(campaign=campaign)

    assert [status.child for status in child_statuses] == children
    assert [
        None if status.assignment is None else status.assignment.work.identifier
        for status in child_statuses
    ] == [assignment, None, None]
    assert [
        [request.row.issue for request in status.requests] for status in child_statuses
    ] == [[], [22], []]


def test_a_campaign_summary_counts_its_nested_cards_by_the_words_they_show(state):
    write_assignment(
        state=state, identifier="GH21-20260819-184158-assignment", issue=21
    )
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    observe(
        state=state,
        finding=NOTHING_NEW,
        ended_round=1,
        children=[
            compose_child(issue=issue, state=IssueState.OPEN)
            for issue in (21, 22, 23, 24, 25)
        ],
        other_rows=[
            compose_request_row(issue=22, finding=UNCLAIMED),
            compose_request_row(
                issue=23,
                finding=StartTimeFinding(
                    linked_pull_requests=[], blocking_issues=[IssueReference(number=9)]
                ),
            ),
            compose_request_row(
                issue=24, finding=ReadFailureFinding(reason="gh: down")
            ),
        ],
    )
    report = read_status_report(state=state, clock=lambda: LOOKED_AT)
    [campaign] = report.list_active_work_statuses(kind=AgentWorkKind.CAMPAIGN)

    assert report.summarise_campaign_children(campaign=campaign) == (
        "0 of 5 sub-issues closed · 1 waiting, 1 held, 1 unknown, 1 available"
    )


def test_a_campaign_summary_without_nested_cards_gives_githubs_count_alone(state):
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    observe(
        state=state,
        finding=NOTHING_NEW,
        ended_round=1,
        children=[compose_child(issue=21, state=IssueState.CLOSED)],
    )
    report = read_status_report(state=state, clock=lambda: LOOKED_AT)
    [campaign] = report.list_active_work_statuses(kind=AgentWorkKind.CAMPAIGN)

    assert (
        report.summarise_campaign_children(campaign=campaign)
        == "1 of 1 sub-issue closed"
    )


@pytest.mark.parametrize(
    "recorded",
    [None, "GH21-20260819-184158-assignment"],
    ids=["unrecorded", "older-recorded"],
)
def test_a_child_shows_the_newest_local_assignment_at_its_issue(state, recorded):
    newest = "GH21-20260820-090000-assignment"
    if recorded is not None:
        write_assignment(state=state, identifier=recorded, issue=21)
    write_assignment(state=state, identifier=newest, issue=21)
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    child = compose_child(issue=21, state=IssueState.OPEN)
    if recorded is not None:
        child = child.model_copy(
            update={
                "assignment": CampaignChildAssignment(
                    identifier=recorded,
                    pull_request=52,
                    observed_pull_request=None,
                    finished_turn=None,
                    ending=None,
                    is_fault=False,
                )
            }
        )
    observe(state=state, finding=NOTHING_NEW, ended_round=1, children=[child])
    report = read_status_report(state=state, clock=lambda: LOOKED_AT)
    [campaign] = report.list_active_work_statuses(kind=AgentWorkKind.CAMPAIGN)

    [child_status] = report.list_campaign_child_statuses(campaign=campaign)

    assert child_status.assignment is not None
    assert child_status.assignment.work.identifier == newest


def test_a_campaign_whose_children_are_unknown_has_no_child_statuses(state):
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    observe(state=state, finding=NOTHING_NEW, ended_round=1, children=None)
    report = read_status_report(state=state, clock=lambda: LOOKED_AT)
    [campaign] = report.list_active_work_statuses(kind=AgentWorkKind.CAMPAIGN)

    assert report.list_campaign_child_statuses(campaign=campaign) == []


def test_an_unreadable_lead_round_input_fails_the_status_naming_the_file(state):
    write_lead_round(state=state, number=1, ending=SUCCESSFUL)
    campaign = read_campaign(state=state, issue=PARENT)
    assert campaign is not None
    round_input = campaign.compose_round_paths(number=1).round_input
    round_input.write_bytes(b"not json")

    found = read_campaign_status(state=state)

    with pytest.raises(ReportableError, match=re.escape(str(round_input))):
        _ = found.round_statuses
