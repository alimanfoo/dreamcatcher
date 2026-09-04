from pathlib import Path

import pytest
from conftest import CONFIG, CONFIG_HEAD, SMITH_CLAUDE, SMITH_CODEX

from dreamcatcher.config import CONFIG_NAME, Harness, HarnessSettings, read_config
from dreamcatcher.errors import ReportableError

WITHOUT_CODEX = CONFIG_HEAD + SMITH_CLAUDE

CLAUDE_SETTINGS = HarnessSettings(
    prompt="/dream:smith GH{issue}", model="opus[1m]", effort="xhigh"
)
CODEX_SETTINGS = HarnessSettings(
    prompt="$dream:smith GH{issue}", model="gpt-5.6-sol", effort="xhigh"
)


def write_config(root: Path, text: str) -> None:
    """Put a config in the repo root."""
    (root / CONFIG_NAME).write_text(text, encoding="utf-8")


def test_a_valid_config_reads_back(tmp_path):
    write_config(tmp_path, CONFIG)

    config = read_config(tmp_path)

    assert config.interval == 300
    assert [mapping.label for mapping in config.dispatch] == ["dream:smith"]
    assert config.dispatch[0].harness_settings == {
        Harness.CLAUDE: CLAUDE_SETTINGS,
        Harness.CODEX: CODEX_SETTINGS,
    }


def test_the_settings_the_design_gives_defaults_for_have_them(tmp_path):
    write_config(tmp_path, CONFIG.replace("interval = 300\n", ""))

    config = read_config(tmp_path)

    assert config.interval == 120
    assert config.max_agents == 1
    assert config.assignee == "@me"


def test_a_setting_the_config_names_beats_its_default(tmp_path):
    write_config(tmp_path, 'max_agents = 3\nassignee = "alimanfoo"\n' + CONFIG)

    config = read_config(tmp_path)

    assert config.max_agents == 3
    assert config.assignee == "alimanfoo"


def test_a_label_one_harness_can_run_carries_that_block_alone(tmp_path):
    write_config(tmp_path, WITHOUT_CODEX)

    mapping = read_config(tmp_path).dispatch[0]

    assert mapping.harness_settings == {Harness.CLAUDE: CLAUDE_SETTINGS}


def test_a_label_either_harness_can_run_runs_on_the_one_the_run_named(tmp_path):
    write_config(tmp_path, CONFIG)

    mapping = read_config(tmp_path).dispatch[0]

    assert mapping.choose_harness(Harness.CLAUDE) == Harness.CLAUDE
    assert mapping.choose_harness(Harness.CODEX) == Harness.CODEX


def test_a_label_one_harness_can_run_runs_on_that_one_whatever_the_run_named(tmp_path):
    write_config(tmp_path, WITHOUT_CODEX)

    mapping = read_config(tmp_path).dispatch[0]

    assert mapping.choose_harness(Harness.CODEX) == Harness.CLAUDE


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
            "an interval of zero",
            CONFIG.replace("interval = 300", "interval = 0"),
            "interval: Input should be greater than 0",
        ),
        (
            "no dispatch mappings",
            "interval = 300\ndispatch = []\n",
            "dispatch: List should have at least 1 item after validation, not 0",
        ),
        (
            "a label no harness can run",
            CONFIG_HEAD + '[[dispatch]]\nlabel = "dream:smith"\n',
            "dispatch.0: Value error, label dream:smith has no harness block",
        ),
        (
            "a block for a harness that does not exist",
            CONFIG.replace("[dispatch.codex]", "[dispatch.gemini]"),
            "dispatch.0.gemini: Input should be 'claude' or 'codex'",
        ),
        (
            "a settings block that is not a block",
            CONFIG_HEAD + '[[dispatch]]\nlabel = "dream:smith"\nclaude = "opus"\n',
            "dispatch.0.claude: Input should be a valid dictionary or instance of "
            "HarnessSettings",
        ),
        (
            "one label mapped twice",
            CONFIG + SMITH_CLAUDE + SMITH_CODEX,
            "Value error, more than one dispatch entry uses the label dream:smith",
        ),
    ],
)
def test_a_config_mistake_names_the_setting_and_the_fault(
    tmp_path, mistake, text, fault
):
    write_config(tmp_path, text)

    with pytest.raises(ReportableError) as error:
        read_config(tmp_path)

    assert str(error.value) == f"{tmp_path / CONFIG_NAME} is not valid:\n  {fault}"


# A prompt is left out, because a round writes it to a file for the harness to
# read rather than putting it on a command line.
@pytest.mark.parametrize("setting", ["model", "effort"])
def test_a_setting_a_harness_cannot_be_given_names_itself(tmp_path, setting):
    write_config(tmp_path, CONFIG.replace(f'{setting} = "', f'{setting} = "%TIME% ', 1))

    with pytest.raises(ReportableError) as error:
        read_config(tmp_path)

    assert str(error.value) == (
        f"{tmp_path / CONFIG_NAME} is not valid:\n"
        f"  dispatch.0.claude.{setting}: Value error, cannot hold a percent "
        "sign, because on Windows cmd.exe acts on the text rather than passing "
        "it to the harness"
    )


def test_a_prompt_may_hold_what_no_command_line_could_carry(tmp_path):
    written = "/dream:smith GH{issue}\\nfinish 50% of it"
    write_config(tmp_path, CONFIG.replace("/dream:smith GH{issue}", written, 1))

    mapping = read_config(tmp_path).dispatch[0]

    assert mapping.harness_settings[Harness.CLAUDE].prompt == (
        "/dream:smith GH{issue}\nfinish 50% of it"
    )


def test_a_repo_with_no_config_says_which_file_is_missing(tmp_path):
    with pytest.raises(ReportableError, match=CONFIG_NAME):
        read_config(tmp_path)
