from datetime import timedelta

import pytest
from clocks import PINNED
from records import read_campaign, write_campaign, write_round

from dreamcatcher.agent_assignments import ObservedPullRequest
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    HarnessErroredAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.agent_work import AgentWork, AgentWorkEndReason, create_agent_work
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignChildAssignment,
    CampaignChildChange,
    CampaignChildNotification,
    CampaignRoundInput,
    compare_campaign_children,
    prepare_campaign_round,
    read_delivered_campaign_input,
)
from dreamcatcher.config import (
    AgentHarness,
    AssignmentRoute,
    CampaignRoute,
    ClaudeRecipe,
)
from dreamcatcher.github import (
    CheckResult,
    IssueComment,
    IssueState,
    PullRequestMergeState,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.relay import IssueCommentCursor
from dreamcatcher.state import StateDirectory

PARENT = 20
FIRST = IssueComment(
    id=1, author="alimanfoo", written_at="2026-09-23T01:00:00Z", body="Start."
)
SECOND = IssueComment(
    id=2, author="alimanfoo", written_at="2026-09-23T02:00:00Z", body="Go on."
)

CHILD = CampaignChild(
    issue=21, title="Stage 1", state=IssueState.OPEN, is_settled=True, assignment=None
)
SMITH = AssignmentRoute(
    label="dream:smith",
    claude=ClaudeRecipe(prompt="/dream:smith GH{issue}", model="opus", effort="high"),
)


def compose_lead_input(*, comments: list[IssueComment]) -> CampaignRoundInput:
    """Return an input that delivered these comments, reaching the newest."""
    return CampaignRoundInput(
        issue=PARENT,
        children=[],
        notifications=[],
        comments=comments,
        cursor=IssueCommentCursor(
            written_at=comments[-1].written_at, id=comments[-1].id
        ),
        revision="abc123",
        assignment_routes=[],
    )


def read_parent_campaign(*, state: StateDirectory) -> AgentWork:
    """Return the campaign at the parent, which the test has written."""
    campaign = read_campaign(state=state, issue=PARENT)
    assert campaign is not None
    return campaign


def test_a_campaign_round_starts_from_main_in_a_detached_worktree(cloned):
    state = StateDirectory(root=cloned)
    campaign = create_agent_work(
        state=state,
        route=CampaignRoute(
            label="dream:lead",
            claude=ClaudeRecipe(
                prompt="Acknowledge GH{issue}.", model="opus[1m]", effort="xhigh"
            ),
        ),
        preferred_harness=AgentHarness.CLAUDE,
        issue=PARENT,
        title="Carry the plan through",
        at=PINNED,
    )

    frozen = prepare_campaign_round(
        state=state,
        campaign=campaign,
        children=[CHILD],
        notifications=[],
        comments=[FIRST, SECOND],
        delivered_cursor=None,
        assignment_routes=[SMITH],
    )

    assert campaign.record.kind is AgentWorkKind.CAMPAIGN
    assert campaign.record.instructions == "Acknowledge GH20."
    assert frozen.issue == PARENT
    assert frozen.children == [CHILD]
    assert frozen.comments == [FIRST, SECOND]
    assert frozen.assignment_routes == [SMITH]
    assert frozen.cursor == IssueCommentCursor(written_at=SECOND.written_at, id=2)
    assert frozen.revision
    assert campaign.worktree.joinpath(".git").is_file()


@pytest.mark.parametrize("is_second_round_delivered", [True, False])
def test_the_delivered_input_is_the_newest_that_took_its_turn(
    tmp_path, is_second_round_delivered
):
    state = StateDirectory(root=tmp_path)
    directory = write_campaign(state=state, issue=PARENT)
    later = PINNED + timedelta(minutes=5)
    for number, comments, ending in (
        (1, [FIRST], SuccessfulAgentRoundEnding(at=PINNED)),
        (
            2,
            [SECOND],
            SuccessfulAgentRoundEnding(at=later)
            if is_second_round_delivered
            else HarnessErroredAgentRoundEnding(at=later, status=1),
        ),
    ):
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(number=number, started=PINNED, ending=ending),
            round_input=compose_lead_input(comments=comments),
        )

    delivered = read_delivered_campaign_input(
        campaign=read_parent_campaign(state=state)
    )

    newest = SECOND if is_second_round_delivered else FIRST
    assert delivered == compose_lead_input(comments=[newest])


REVIEWED = ObservedPullRequest(
    state=PullRequestState.OPEN,
    is_draft=False,
    merge_state=PullRequestMergeState.UNKNOWN,
    head="a1",
    check_result=CheckResult.PASSING,
    has_running_checks=False,
)


def compose_reviewed_pull_request(**fields) -> ObservedPullRequest:
    """Return the child's pull request as read, ready with passing checks."""
    return REVIEWED.model_copy(update=fields)


def compose_child_assignment(**fields) -> CampaignChildAssignment:
    """Return the child's assignment, whose first round took its turn."""
    return CampaignChildAssignment.model_validate(
        {
            "identifier": "GH21-20260923-010000-assignment",
            "pull_request": 52,
            "observed_pull_request": REVIEWED,
            "finished_turn": 1,
            "ending": None,
            "is_fault": False,
        }
        | fields
    )


def compose_stage(**fields) -> CampaignChild:
    """Return the first child, settled with its assignment."""
    return CampaignChild.model_validate(
        {
            "issue": 21,
            "title": "Stage 1",
            "state": IssueState.OPEN,
            "is_settled": True,
            "assignment": compose_child_assignment(),
        }
        | fields
    )


SECOND_STAGE = compose_stage(issue=22, title="Stage 2", assignment=None)
ENDED = compose_child_assignment(
    observed_pull_request=None, ending=AgentWorkEndReason.COMPLETED
)
FAULTED = compose_child_assignment(observed_pull_request=None, is_fault=True)
REPLACEMENT = "GH21-20260924-010000-assignment"
CHANGES = CampaignChildChange


@pytest.mark.parametrize(
    ("previous", "current", "changes"),
    [
        ([], [compose_stage(is_settled=False)], [CHANGES.ADDED]),
        (
            [compose_stage()],
            [compose_stage(state=IssueState.CLOSED)],
            [CHANGES.ISSUE_STATE],
        ),
        (
            [compose_stage(is_settled=False)],
            [compose_stage(assignment=compose_child_assignment(finished_turn=2))],
            [CHANGES.HANDBACK],
        ),
        ([compose_stage(is_settled=False)], [compose_stage()], [CHANGES.HANDBACK]),
        (
            [compose_stage()],
            [compose_stage(assignment=compose_child_assignment(finished_turn=2))],
            [CHANGES.HANDBACK],
        ),
        (
            [compose_stage(assignment=None)],
            [compose_stage()],
            [CHANGES.HANDBACK, CHANGES.PULL_REQUEST, CHANGES.CHECK_COMPLETION],
        ),
        (
            [compose_stage(assignment=ENDED)],
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        identifier=REPLACEMENT, finished_turn=1
                    )
                )
            ],
            [CHANGES.HANDBACK, CHANGES.PULL_REQUEST, CHANGES.CHECK_COMPLETION],
        ),
        (
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            is_draft=True
                        )
                    )
                )
            ],
            [compose_stage()],
            [CHANGES.PULL_REQUEST],
        ),
        (
            [compose_stage()],
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(head="b2")
                    )
                )
            ],
            [CHANGES.PULL_REQUEST, CHANGES.CHECK_COMPLETION],
        ),
        (
            [compose_stage()],
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            head="b2", check_result=CheckResult.NONE
                        )
                    )
                )
            ],
            [CHANGES.PULL_REQUEST],
        ),
        (
            [compose_stage()],
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            state=PullRequestState.MERGED
                        )
                    )
                )
            ],
            [CHANGES.PULL_REQUEST],
        ),
        (
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            check_result=CheckResult.RUNNING, has_running_checks=True
                        )
                    )
                )
            ],
            [compose_stage()],
            [CHANGES.CHECK_COMPLETION],
        ),
        (
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            check_result=CheckResult.FAILING, has_running_checks=True
                        )
                    )
                )
            ],
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            check_result=CheckResult.FAILING
                        )
                    )
                )
            ],
            [CHANGES.CHECK_COMPLETION],
        ),
        (
            [compose_stage()],
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            check_result=CheckResult.FAILING
                        )
                    )
                )
            ],
            [CHANGES.CHECK_COMPLETION],
        ),
        (
            [compose_stage()],
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            merge_state=PullRequestMergeState.CLEAN
                        )
                    )
                )
            ],
            [CHANGES.MERGEABLE],
        ),
        ([compose_stage()], [compose_stage(assignment=ENDED)], [CHANGES.ENDING]),
        (
            [compose_stage(assignment=ENDED)],
            [
                compose_stage(
                    assignment=ENDED.model_copy(update={"identifier": REPLACEMENT})
                )
            ],
            [CHANGES.HANDBACK, CHANGES.ENDING],
        ),
        ([compose_stage()], [compose_stage(assignment=FAULTED)], [CHANGES.FAULT]),
        (
            [compose_stage(assignment=FAULTED)],
            [
                compose_stage(
                    assignment=FAULTED.model_copy(update={"identifier": REPLACEMENT})
                )
            ],
            [CHANGES.HANDBACK, CHANGES.FAULT],
        ),
    ],
    ids=[
        "added while working",
        "issue closed",
        "turn finished",
        "settled again",
        "turn finished between updates",
        "first assignment",
        "replacement",
        "marked ready",
        "new head",
        "new head with no checks",
        "merged",
        "checks finished",
        "last running check of a failure finished",
        "result changed",
        "became mergeable",
        "ended",
        "replacement ended",
        "fault",
        "replacement in fault",
    ],
)
def test_a_change_to_a_child_notifies_the_lead(previous, current, changes):
    notifications = compare_campaign_children(
        previous=[*previous, SECOND_STAGE], current=[*current, SECOND_STAGE]
    )

    assert notifications == [CampaignChildNotification(issue=21, changes=changes)]


def test_a_removed_child_notifies_after_the_current_children():
    notifications = compare_campaign_children(
        previous=[compose_stage(), SECOND_STAGE],
        current=[SECOND_STAGE, compose_stage(issue=23)],
    )

    assert notifications == [
        CampaignChildNotification(issue=23, changes=[CHANGES.ADDED]),
        CampaignChildNotification(issue=21, changes=[CHANGES.REMOVED]),
    ]


@pytest.mark.parametrize(
    ("previous", "current"),
    [
        ([compose_stage(), SECOND_STAGE], [SECOND_STAGE, compose_stage()]),
        (
            [compose_stage(is_settled=False)],
            [
                compose_stage(
                    is_settled=False,
                    state=IssueState.CLOSED,
                    assignment=compose_child_assignment(
                        finished_turn=2,
                        observed_pull_request=compose_reviewed_pull_request(
                            head="b2", merge_state=PullRequestMergeState.CLEAN
                        ),
                    ),
                )
            ],
        ),
        (
            [compose_stage()],
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            check_result=CheckResult.FAILING, has_running_checks=True
                        )
                    )
                )
            ],
        ),
        (
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            merge_state=PullRequestMergeState.CLEAN
                        )
                    )
                )
            ],
            [
                compose_stage(
                    assignment=compose_child_assignment(
                        observed_pull_request=compose_reviewed_pull_request(
                            merge_state=PullRequestMergeState.UNSTABLE
                        )
                    )
                )
            ],
        ),
        ([compose_stage(assignment=ENDED)], [compose_stage(assignment=ENDED)]),
        ([compose_stage(assignment=FAULTED)], [compose_stage(assignment=FAULTED)]),
        ([compose_stage(assignment=None)], [compose_stage(assignment=None)]),
    ],
    ids=[
        "reordered",
        "working",
        "checks still running",
        "mergeable still",
        "still ended",
        "still in fault",
        "no assignment yet",
    ],
)
def test_a_child_with_nothing_new_for_the_lead_notifies_nothing(previous, current):
    assert compare_campaign_children(previous=previous, current=current) == []
