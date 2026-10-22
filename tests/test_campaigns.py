import pytest
from clocks import PINNED

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    HarnessErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkRecord,
    _record_agent_work,
    create_agent_work,
    find_agent_work,
)
from dreamcatcher.campaigns import (
    CampaignRoundInput,
    prepare_campaign_round,
    read_delivered_campaign_input,
)
from dreamcatcher.config import AgentHarness, CampaignRoute, ClaudeRecipe
from dreamcatcher.documents import write_json
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory

IDENTIFIER = "GH20-20260923-010000-campaign"


def write_campaign(*, state: StateDirectory) -> AgentWork:
    return _record_agent_work(
        state=state,
        identifier=IDENTIFIER,
        record=AgentWorkRecord(
            issue=20,
            title="Carry the plan through",
            dispatch_label="dream:lead",
            kind=AgentWorkKind.CAMPAIGN,
            harness=AgentHarness.CLAUDE,
            model="opus[1m]",
            effort="xhigh",
            instructions="Acknowledge GH20.",
        ),
    )


def write_round(
    *,
    campaign: AgentWork,
    number: int,
    ending: SuccessfulAgentRoundEnding
    | StoppedAgentRoundEnding
    | HarnessErroredAgentRoundEnding
    | InterruptedAgentRoundEnding
    | None,
    revision: str | None = "abc123",
) -> None:
    paths = campaign.compose_round_paths(number=number)
    if revision is not None:
        write_json(
            document=CampaignRoundInput(issue=20, revision=revision),
            path=paths.round_input,
        )
    write_json(
        document=AgentRoundRecord(number=number, started=PINNED, ending=ending),
        path=paths.record,
    )


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


def test_a_new_campaign_has_delivered_no_input(tmp_path):
    campaign = write_campaign(state=StateDirectory(root=tmp_path))

    assert read_delivered_campaign_input(campaign=campaign) is None


@pytest.mark.parametrize(
    ("second_round_ending", "delivered_revision"),
    [
        (SuccessfulAgentRoundEnding(at=PINNED), "def456"),
        (StoppedAgentRoundEnding(at=PINNED), "def456"),
        (None, "def456"),
        (HarnessErroredAgentRoundEnding(at=PINNED, status=1), "abc123"),
        (InterruptedAgentRoundEnding(), "abc123"),
    ],
)
def test_the_lead_was_given_the_input_of_its_newest_round_that_took_its_turn(
    tmp_path, second_round_ending, delivered_revision
):
    state = StateDirectory(root=tmp_path)
    campaign = write_campaign(state=state)
    write_round(
        campaign=campaign, number=1, ending=SuccessfulAgentRoundEnding(at=PINNED)
    )
    write_round(
        campaign=campaign, number=2, ending=second_round_ending, revision="def456"
    )
    reread = find_agent_work(state=state, identifier=IDENTIFIER)
    assert reread is not None

    delivered = read_delivered_campaign_input(campaign=reread)

    assert delivered == CampaignRoundInput(issue=20, revision=delivered_revision)


def test_a_round_that_did_not_finish_delivered_nothing(tmp_path):
    state = StateDirectory(root=tmp_path)
    campaign = write_campaign(state=state)
    write_round(campaign=campaign, number=1, ending=InterruptedAgentRoundEnding())
    reread = find_agent_work(state=state, identifier=IDENTIFIER)
    assert reread is not None

    assert read_delivered_campaign_input(campaign=reread) is None
