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
    CampaignRoundInput,
    prepare_campaign_round,
    read_parent_comment_cursor,
)
from dreamcatcher.config import AgentHarness, CampaignRoute, ClaudeRecipe
from dreamcatcher.github import IssueComment
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


def lead_input(*, comments: list[IssueComment]) -> CampaignRoundInput:
    """Return an input that delivered these comments, reaching the newest."""
    return CampaignRoundInput(
        issue=PARENT,
        comments=comments,
        cursor=IssueCommentCursor(
            written_at=comments[-1].written_at, id=comments[-1].id
        ),
        revision="abc123",
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
        state=state, campaign=campaign, comments=[FIRST, SECOND]
    )

    assert campaign.record.kind is AgentWorkKind.CAMPAIGN
    assert campaign.record.instructions == "Acknowledge GH20."
    assert frozen.issue == PARENT
    assert frozen.comments == [FIRST, SECOND]
    assert frozen.cursor == IssueCommentCursor(written_at=SECOND.written_at, id=2)
    assert frozen.revision
    assert campaign.worktree.joinpath(".git").is_file()


def test_a_round_with_no_new_comment_carries_the_delivered_cursor_forward(cloned):
    state = StateDirectory(root=cloned)
    directory = write_campaign(state=state, issue=PARENT)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, ending=SuccessfulAgentRoundEnding(at=PINNED)
        ),
        round_input=lead_input(comments=[FIRST]),
    )

    frozen = prepare_campaign_round(
        state=state, campaign=campaign_at(state=state), comments=[]
    )

    assert frozen.comments == []
    assert frozen.cursor == IssueCommentCursor(written_at=FIRST.written_at, id=1)


@pytest.mark.parametrize("is_second_round_delivered", [True, False])
def test_the_cursor_is_the_newest_delivered_inputs(tmp_path, is_second_round_delivered):
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

    cursor = read_parent_comment_cursor(campaign=campaign_at(state=state))

    newest = SECOND if is_second_round_delivered else FIRST
    assert cursor == IssueCommentCursor(written_at=newest.written_at, id=newest.id)


def test_a_campaign_given_no_input_reads_the_parent_from_the_start(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_campaign(state=state, issue=PARENT)

    assert read_parent_comment_cursor(campaign=campaign_at(state=state)) is (None)
