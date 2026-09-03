"""The prompts the daemon composes, with the golden beside each one.

The golden is the review surface: read it as the session will read it, and
judge the prompt by it.
"""

import pytest
from conftest import CONFIG, FIXTURES

from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.prompts import first_round

PROMPTS = FIXTURES / "prompts"


def test_the_issues_number_replaces_the_word_the_template_holds_for_it():
    assert first_round("/dream:smith GH{issue}", 12).startswith("/dream:smith GH12\n")


def test_a_template_holding_other_words_in_braces_keeps_them():
    assert first_round("read {the design} for GH{issue}", 12).startswith(
        "read {the design} for GH12\n"
    )


@pytest.mark.parametrize("harness", list(Harness))
def test_the_prompt_that_opens_a_session_reads_as_its_golden(tmp_path, harness):
    (tmp_path / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    settings = read_config(tmp_path).dispatch[0].harness_settings[harness]

    composed = first_round(settings.prompt, 12)

    assert composed == (PROMPTS / f"{harness}.txt").read_text(encoding="utf-8")
