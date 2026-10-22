from datetime import timedelta

import pytest
from clocks import PINNED
from records import read_campaign, write_campaign, write_round

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    HarnessErroredAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.agent_work import AgentWork, create_agent_work
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignRoundInput,
    prepare_campaign_round,
    read_delivered_campaign_input,
)
from dreamcatcher.config import (
    AgentHarness,
    AssignmentRoute,
    CampaignRoute,
    ClaudeRecipe,
)
from dreamcatcher.github import IssueComment, IssueState
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


def lead_input(*, comments: list[IssueComment]) -> CampaignRoundInput:
    """Return an input that delivered these comments, reaching the newest."""
    return CampaignRoundInput(
        issue=PARENT,
        children=[],
        comments=comments,
        cursor=IssueCommentCursor(
            written_at=comments[-1].written_at, id=comments[-1].id
        ),
        revision="abc123",
        assignment_routes=[],
    )


def campaign_at(*, state: StateDirectory) -> AgentWork:
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
        comments=[FIRST, SECOND],
        previous=None,
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
            round_input=lead_input(comments=comments),
        )

    delivered = read_delivered_campaign_input(campaign=campaign_at(state=state))

    newest = SECOND if is_second_round_delivered else FIRST
    assert delivered == lead_input(comments=[newest])
