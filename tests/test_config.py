from pathlib import Path

import pytest
from conftest import CONFIG, CONFIG_HEAD, SMITH_CLAUDE, SMITH_CODEX

from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.documents import DocumentError

PIN = 'label = "dream:smith"\n'

WITHOUT_CODEX = CONFIG_HEAD + SMITH_CLAUDE


def write(root: Path, text: str) -> Path:
    config = root / CONFIG_NAME
    config.write_text(text, encoding="utf-8")
    return config


def read(root: Path, text: str):
    write(root, text)
    return read_config(root)


def fault(root: Path, text: str) -> str:
    config = write(root, text)

    with pytest.raises(DocumentError) as error:
        read_config(root)

    return str(error.value).removeprefix(f"{config} is not valid:\n  ")


def test_a_valid_config_reads_back(tmp_path):
    config = read(tmp_path, CONFIG)

    assert config.interval == 300
    assert config.harness is Harness.CLAUDE
    assert [mapping.label for mapping in config.dispatch] == ["dream:smith"]
    assert config.dispatch[0].claude.model == "opus[1m]"
    assert config.dispatch[0].codex.prompt == "$dream:smith GH{issue}"


def test_the_settings_the_design_gives_defaults_for_have_them(tmp_path):
    config = read(tmp_path, CONFIG.replace("interval = 300\n", ""))

    assert config.interval == 120
    assert config.max_agents == 1
    assert config.assignee == "@me"


def test_a_setting_the_config_names_beats_its_default(tmp_path):
    named = 'max_agents = 3\nassignee = "alimanfoo"\n' + CONFIG

    config = read(tmp_path, named)

    assert config.max_agents == 3
    assert config.assignee == "alimanfoo"


def test_an_unpinned_label_dispatches_with_the_run_harness(tmp_path):
    mapping = read(tmp_path, CONFIG).dispatch[0]

    assert mapping.settings_for(Harness.CLAUDE).model == "opus[1m]"
    assert mapping.settings_for(Harness.CODEX).model == "gpt-5.6-sol"


def test_a_pinned_label_dispatches_with_its_pin(tmp_path):
    pinned = WITHOUT_CODEX.replace(PIN, PIN + 'harness = "claude"\n')

    mapping = read(tmp_path, pinned).dispatch[0]

    assert mapping.harness is Harness.CLAUDE
    assert mapping.settings_for(Harness.CODEX).model == "opus[1m]"


@pytest.mark.parametrize(
    ("mistake", "text", "message"),
    [
        (
            "a missing setting",
            CONFIG.replace('model = "opus[1m]"\n', ""),
            "dispatch entry 1, claude block: model is required",
        ),
        (
            "a mistyped setting",
            "intervl = 5\n" + CONFIG,
            "dreamcatcher has no setting called intervl",
        ),
        (
            "a harness that does not exist",
            CONFIG.replace('harness = "claude"', 'harness = "cloud"'),
            "harness: input should be 'claude' or 'codex'",
        ),
        (
            "an interval of zero",
            CONFIG.replace("interval = 300", "interval = 0"),
            "interval: input should be greater than 0",
        ),
        (
            "no dispatch mappings",
            'interval = 300\nharness = "claude"\ndispatch = []\n',
            "dispatch: list should have at least 1 item after validation, not 0",
        ),
        (
            "a label a run harness cannot dispatch",
            WITHOUT_CODEX,
            "dispatch entry 1: label dream:smith has no codex block",
        ),
        (
            "a pin with no block of its own",
            WITHOUT_CODEX.replace(PIN, PIN + 'harness = "codex"\n'),
            "dispatch entry 1: label dream:smith has no codex block",
        ),
        (
            "one label mapped twice",
            CONFIG + SMITH_CLAUDE + SMITH_CODEX,
            "more than one dispatch entry uses the label dream:smith",
        ),
        (
            "a settings block that is not a block",
            CONFIG_HEAD + '[[dispatch]]\nlabel = "dream:smith"\nclaude = "opus"\n',
            "dispatch entry 1: claude must be a block of settings",
        ),
    ],
)
def test_a_config_mistake_reads_as_plain_words(tmp_path, mistake, text, message):
    assert fault(tmp_path, text) == message


def test_a_repo_with_no_config_says_which_file_is_missing(tmp_path):
    with pytest.raises(DocumentError, match=CONFIG_NAME):
        read_config(tmp_path)
