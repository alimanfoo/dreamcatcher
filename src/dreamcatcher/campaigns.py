"""Prepare campaign rounds and read back the input delivered to the lead.

A campaign's channel is its parent issue. Every round runs in a detached
worktree refreshed to fetched main, and the lead publishes its own messages, so
a round has no finishing step.
"""

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.documents import WriteOnceDreamcatcherDocument, read_json
from dreamcatcher.git import refresh_detached_worktree
from dreamcatcher.state import StateDirectory


class CampaignRoundInput(WriteOnceDreamcatcherDocument):
    """Model the input frozen for one campaign round."""

    issue: int
    revision: str


def prepare_campaign_round(
    *, state: StateDirectory, campaign: AgentWork
) -> CampaignRoundInput:
    """Reset the worktree to fetched main and freeze the round's input."""
    revision = refresh_detached_worktree(root=state.root, worktree=campaign.worktree)
    return CampaignRoundInput(issue=campaign.record.issue, revision=revision)


def read_campaign_input(*, campaign: AgentWork, number: int) -> CampaignRoundInput:
    """Read the durable input of one campaign round."""
    return read_json(
        model=CampaignRoundInput,
        path=campaign.compose_round_paths(number=number).round_input,
    )


def read_delivered_campaign_input(*, campaign: AgentWork) -> CampaignRoundInput | None:
    """Return the newest input delivered to the lead, if any has been.

    A round that took its turn, or is still running, delivered its input. A
    round that did not finish delivered nothing, so its input is given again.
    """
    delivered = campaign.list_relayed_round_paths()
    if not delivered:
        return None
    return read_campaign_input(campaign=campaign, number=delivered[0].number)
