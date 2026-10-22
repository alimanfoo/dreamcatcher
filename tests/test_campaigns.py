from clocks import PINNED

from dreamcatcher.agent_work import (
    create_agent_work,
)
from dreamcatcher.campaigns import (
    prepare_campaign_round,
)
from dreamcatcher.config import AgentHarness, CampaignRoute, ClaudeRecipe
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory


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
        issue=20,
        title="Carry the plan through",
        at=PINNED,
    )

    frozen = prepare_campaign_round(state=state, campaign=campaign)

    assert campaign.record.kind is AgentWorkKind.CAMPAIGN
    assert campaign.record.instructions == "Acknowledge GH20."
    assert frozen.issue == 20
    assert frozen.revision
    assert campaign.worktree.joinpath(".git").is_file()
