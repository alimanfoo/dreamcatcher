from pathlib import Path

import pytest
from conftest import CONFIG, SMITH_CLAUDE, SMITH_CODEX

from dreamcatcher.config import (
    DREAMCATCHER_CONFIG_NAME,
    AgentHarness,
    AgentRecipe,
    IssueConversationConfig,
    read_dreamcatcher_config,
)
from dreamcatcher.errors import ReportableError

WITHOUT_CODEX = SMITH_CLAUDE

CLAUDE_RECIPE = AgentRecipe(
    prompt="/dream:smith GH{issue}", model="opus[1m]", effort="xhigh"
)
CODEX_RECIPE = AgentRecipe(
    prompt="$dream:smith GH{issue}", model="gpt-5.6-sol", effort="xhigh"
)
CLAUDE_CONVERSATION_RECIPE = AgentRecipe(
    prompt="/dream:conversation GH{issue}", model="opus[1m]", effort="xhigh"
)
CODEX_CONVERSATION_RECIPE = AgentRecipe(
    prompt="$dream:conversation GH{issue}", model="gpt-5.6-sol", effort="xhigh"
)

CONVERSATION = """
[[conversation]]
label = "dream:conversation"

[conversation.claude]
prompt = "/dream:conversation GH{issue}"
model = "opus[1m]"
effort = "xhigh"
"""

CODEX_CONVERSATION_BLOCK = """
[conversation.codex]
prompt = "$dream:conversation GH{issue}"
model = "gpt-5.6-sol"
effort = "xhigh"
"""

CODEX_CONVERSATION = (
    """
[[conversation]]
label = "dream:conversation"
"""
    + CODEX_CONVERSATION_BLOCK
)


def write_config(*, root: Path, text: str) -> None:
    """Put a config in the repo root."""
    (root / DREAMCATCHER_CONFIG_NAME).write_text(text, encoding="utf-8")


def test_a_valid_config_reads_back(tmp_path):
    write_config(root=tmp_path, text=CONFIG)

    config = read_dreamcatcher_config(root=tmp_path)

    assert [route.label for route in config.dispatch] == ["dream:smith"]
    assert config.dispatch[0].recipes == {
        AgentHarness.CLAUDE: CLAUDE_RECIPE,
        AgentHarness.CODEX: CODEX_RECIPE,
    }
    assert config.conversation == []


def test_an_issue_conversation_is_configured_separately(tmp_path):
    write_config(root=tmp_path, text=CONFIG + CONVERSATION)

    config = read_dreamcatcher_config(root=tmp_path)

    assert config.conversation == [
        IssueConversationConfig(
            label="dream:conversation",
            claude=CLAUDE_CONVERSATION_RECIPE,
        )
    ]
    assert config.conversation_routes == {"dream:conversation": config.conversation[0]}
    assert config.routed_harnesses == {AgentHarness.CLAUDE, AgentHarness.CODEX}


def test_a_conversation_one_harness_can_run_uses_that_one(tmp_path):
    write_config(root=tmp_path, text=WITHOUT_CODEX + CODEX_CONVERSATION)

    config = read_dreamcatcher_config(root=tmp_path)

    assert (
        config.conversation[0].choose_harness(requested_harness=AgentHarness.CLAUDE)
        == AgentHarness.CODEX
    )
    assert config.routed_harnesses == {AgentHarness.CLAUDE, AgentHarness.CODEX}


def test_a_conversation_either_harness_can_run_uses_the_requested_one(tmp_path):
    write_config(root=tmp_path, text=CONFIG + CONVERSATION + CODEX_CONVERSATION_BLOCK)

    conversation = read_dreamcatcher_config(root=tmp_path).conversation[0]

    assert conversation.recipes == {
        AgentHarness.CLAUDE: CLAUDE_CONVERSATION_RECIPE,
        AgentHarness.CODEX: CODEX_CONVERSATION_RECIPE,
    }
    assert (
        conversation.choose_harness(requested_harness=AgentHarness.CLAUDE)
        == AgentHarness.CLAUDE
    )
    assert (
        conversation.choose_harness(requested_harness=AgentHarness.CODEX)
        == AgentHarness.CODEX
    )


def test_the_repository_setting_the_design_gives_a_default_has_it(tmp_path):
    write_config(root=tmp_path, text=CONFIG)

    config = read_dreamcatcher_config(root=tmp_path)

    assert config.assignee == "@me"


def test_a_repository_setting_the_config_names_beats_its_default(tmp_path):
    write_config(root=tmp_path, text='assignee = "alimanfoo"\n' + CONFIG)

    config = read_dreamcatcher_config(root=tmp_path)

    assert config.assignee == "alimanfoo"


def test_a_label_one_harness_can_run_carries_that_block_alone(tmp_path):
    write_config(root=tmp_path, text=WITHOUT_CODEX)

    route = read_dreamcatcher_config(root=tmp_path).dispatch[0]

    assert route.recipes == {AgentHarness.CLAUDE: CLAUDE_RECIPE}


def test_the_config_identifies_dispatch_labels_without_giving_one_precedence(tmp_path):
    write_config(
        root=tmp_path,
        text=CONFIG + SMITH_CLAUDE.replace("dream:smith", "dream:less"),
    )

    config = read_dreamcatcher_config(root=tmp_path)

    assert config.identify_dispatch_labels(
        labels=["maintenance", "DREAM:LESS", "dream:smith"]
    ) == ["dream:less", "dream:smith"]


def test_a_label_either_harness_can_run_runs_on_the_one_the_run_named(tmp_path):
    write_config(root=tmp_path, text=CONFIG)

    route = read_dreamcatcher_config(root=tmp_path).dispatch[0]

    assert (
        route.choose_harness(requested_harness=AgentHarness.CLAUDE)
        == AgentHarness.CLAUDE
    )
    assert (
        route.choose_harness(requested_harness=AgentHarness.CODEX) == AgentHarness.CODEX
    )


def test_a_label_one_harness_can_run_runs_on_that_one_whatever_the_run_named(tmp_path):
    write_config(root=tmp_path, text=WITHOUT_CODEX)

    route = read_dreamcatcher_config(root=tmp_path).dispatch[0]

    assert (
        route.choose_harness(requested_harness=AgentHarness.CODEX)
        == AgentHarness.CLAUDE
    )


@pytest.mark.parametrize(
    ("mistake", "text", "fault"),
    [
        (
            "a missing setting",
            CONFIG.replace('model = "opus[1m]"\n', ""),
            "dispatch.0.claude.model: Field required",
        ),
        (
            "a mistyped setting",
            "intervl = 5\n" + CONFIG,
            "intervl: Extra inputs are not permitted",
        ),
        (
            "a daemon interval",
            "interval = 300\n" + CONFIG,
            "interval: Extra inputs are not permitted",
        ),
        (
            "an agent cap",
            "max_agents = 3\n" + CONFIG,
            "max_agents: Extra inputs are not permitted",
        ),
        (
            "no dispatch routes",
            "dispatch = []\n",
            "dispatch: List should have at least 1 item after validation, not 0",
        ),
        (
            "a label no harness can run",
            '[[dispatch]]\nlabel = "dream:smith"\n',
            "dispatch.0: Value error, label dream:smith has no harness block",
        ),
        (
            "a block for a harness that does not exist",
            CONFIG.replace("[dispatch.codex]", "[dispatch.gemini]"),
            "dispatch.0.gemini: Input should be 'claude' or 'codex'",
        ),
        (
            "a recipe block that is not a block",
            '[[dispatch]]\nlabel = "dream:smith"\nclaude = "opus"\n',
            "dispatch.0.claude: Input should be a valid dictionary or instance of "
            "AgentRecipe",
        ),
        (
            "one label routed twice",
            CONFIG + SMITH_CLAUDE + SMITH_CODEX,
            "Value error, more than one dispatch entry uses the label dream:smith",
        ),
        (
            "one label routed twice with different case",
            CONFIG + SMITH_CLAUDE.replace("dream:smith", "DREAM:SMITH"),
            "Value error, more than one dispatch entry uses the label dream:smith",
        ),
        (
            "one conversation label routed twice",
            CONFIG + CONVERSATION + CONVERSATION,
            "Value error, more than one conversation entry uses the label "
            "dream:conversation",
        ),
        (
            "the old single conversation table",
            CONFIG + CONVERSATION.replace("[[conversation]]", "[conversation]"),
            "conversation: Input should be a valid list",
        ),
    ],
)
def test_a_config_mistake_names_the_setting_and_the_fault(
    tmp_path, mistake, text, fault
):
    write_config(root=tmp_path, text=text)

    with pytest.raises(ReportableError) as error:
        read_dreamcatcher_config(root=tmp_path)

    assert (
        str(error.value)
        == f"{tmp_path / DREAMCATCHER_CONFIG_NAME} is not valid:\n  {fault}"
    )


# A prompt is left out, because a round writes it to a file for the harness to
# read rather than putting it on a command line.
@pytest.mark.parametrize("setting", ["model", "effort"])
def test_a_setting_a_harness_cannot_be_given_names_itself(tmp_path, setting):
    write_config(
        root=tmp_path, text=CONFIG.replace(f'{setting} = "', f'{setting} = "%TIME% ', 1)
    )

    with pytest.raises(ReportableError) as error:
        read_dreamcatcher_config(root=tmp_path)

    assert str(error.value) == (
        f"{tmp_path / DREAMCATCHER_CONFIG_NAME} is not valid:\n"
        f"  dispatch.0.claude.{setting}: Value error, cannot hold a percent "
        "sign, because on Windows cmd.exe acts on the text rather than passing "
        "it to the harness"
    )


def test_a_prompt_may_hold_what_no_command_line_could_carry(tmp_path):
    written = "/dream:smith GH{issue}\\nfinish 50% of it"
    write_config(
        root=tmp_path, text=CONFIG.replace("/dream:smith GH{issue}", written, 1)
    )

    route = read_dreamcatcher_config(root=tmp_path).dispatch[0]

    assert route.recipes[AgentHarness.CLAUDE].prompt == (
        "/dream:smith GH{issue}\nfinish 50% of it"
    )


def test_a_repo_with_no_config_says_which_file_is_missing(tmp_path):
    with pytest.raises(ReportableError, match=DREAMCATCHER_CONFIG_NAME):
        read_dreamcatcher_config(root=tmp_path)
