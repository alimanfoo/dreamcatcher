from pathlib import Path

import pytest
from conftest import CONFIG

from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.prompts import (
    CARRY_ON_PROMPT,
    MARKER,
    POSTSCRIPT,
    compose_first_round_prompt,
    compose_inbox_prompt,
)

# What each harness's template in the test config renders as for issue 12. A
# harness with no line here fails the test below rather than going untested.
OPENINGS = {
    Harness.CLAUDE: "/dream:smith GH12",
    Harness.CODEX: "$dream:smith GH12",
}


def test_a_template_holding_other_words_in_braces_keeps_them():
    assert compose_first_round_prompt(
        template="read {the design} for GH{issue}", issue=12
    ).startswith("read {the design} for GH12\n")


@pytest.mark.parametrize("harness", list(Harness))
def test_the_prompt_that_opens_an_assignment_is_its_template_then_the_postscript(
    tmp_path, harness
):
    (tmp_path / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    recipe = read_config(root=tmp_path).dispatch[0].assignment_recipes[harness]

    composed = compose_first_round_prompt(template=recipe.prompt, issue=12)

    assert composed == OPENINGS[harness] + POSTSCRIPT


def test_the_prompt_that_carries_a_round_on_says_the_last_one_stopped_short():
    assert CARRY_ON_PROMPT.startswith("Your previous round did not finish.")
    assert CARRY_ON_PROMPT.endswith(POSTSCRIPT)


def test_the_prompt_that_hands_over_an_inbox_names_the_pull_request_and_the_file(
    tmp_path,
):
    inbox = tmp_path / "inbox.json"

    composed = compose_inbox_prompt(pull_request=52, inbox=inbox)

    assert composed.startswith("PR-inbox prompt for pull request #52:")
    assert str(inbox) in composed
    assert composed.endswith(POSTSCRIPT)


def test_every_prompt_the_daemon_composes_asks_for_the_marker():
    composed = [
        compose_first_round_prompt(template="/dream:smith GH12", issue=12),
        CARRY_ON_PROMPT,
        compose_inbox_prompt(pull_request=52, inbox=Path("inbox.json")),
    ]

    assert all(MARKER in prompt for prompt in composed)
