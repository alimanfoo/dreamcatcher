import pytest
from conftest import CONFIG

from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.prompts import POSTSCRIPT, compose_first_round_prompt

# What each harness's template in the test config renders as for issue 12. A
# harness with no line here fails the test below rather than going untested.
OPENINGS = {
    Harness.CLAUDE: "/dream:smith GH12",
    Harness.CODEX: "$dream:smith GH12",
}


def test_a_template_holding_other_words_in_braces_keeps_them():
    assert compose_first_round_prompt("read {the design} for GH{issue}", 12).startswith(
        "read {the design} for GH12\n"
    )


@pytest.mark.parametrize("harness", list(Harness))
def test_the_prompt_that_opens_a_session_is_its_template_then_the_postscript(
    tmp_path, harness
):
    (tmp_path / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    settings = read_config(tmp_path).dispatch[0].harness_settings[harness]

    composed = compose_first_round_prompt(settings.prompt, 12)

    assert composed == OPENINGS[harness] + POSTSCRIPT
