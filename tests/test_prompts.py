import pytest
from conftest import CONFIG

from dreamcatcher.agent_rounds import AgentRoundOutcome
from dreamcatcher.config import (
    DREAMCATCHER_CONFIG_NAME,
    AgentHarness,
    read_dreamcatcher_config,
)
from dreamcatcher.prompts import (
    _AGENT_POST_INSTRUCTIONS,
    AGENT_POST_MARKER,
    compose_assignment_input_prompt,
    compose_conversation_input_prompt,
    compose_issue_instructions,
    compose_round_prompt,
)

# What each harness's template in the test config renders as for issue 12. A
# harness with no line here fails the test below rather than going untested.
OPENINGS = {
    AgentHarness.CLAUDE: "/dream:smith GH12",
    AgentHarness.CODEX: "$dream:smith GH12",
}

# The words that direct a round to an input file, for the tests that compose a
# whole prompt around them.
INPUT_PROMPT = "Read the input."


def test_a_template_holding_other_words_in_braces_keeps_them():
    assert compose_issue_instructions(
        template="read {the design} for GH{issue}", issue=12
    ) == ("read {the design} for GH12")


@pytest.mark.parametrize("harness", list(AgentHarness))
def test_a_round_with_nothing_to_relay_is_given_its_instructions_then_the_postscript(
    tmp_path, harness
):
    (tmp_path / DREAMCATCHER_CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    recipe = read_dreamcatcher_config(root=tmp_path).assignment[0].recipes[harness]

    composed = compose_round_prompt(
        instructions=compose_issue_instructions(template=recipe.prompt, issue=12),
        is_resuming=False,
        input_prompt=None,
        previous_outcome=None,
    )

    assert composed == OPENINGS[harness] + _AGENT_POST_INSTRUCTIONS


@pytest.mark.parametrize("is_resuming", [False, True])
def test_a_round_with_no_input_is_given_its_instructions_resumed_or_not(is_resuming):
    composed = compose_round_prompt(
        instructions="/dream:smith GH12",
        is_resuming=is_resuming,
        input_prompt=None,
        previous_outcome=AgentRoundOutcome.ERRORED,
    )

    assert composed == "/dream:smith GH12" + _AGENT_POST_INSTRUCTIONS


def test_a_new_session_is_given_its_instructions_before_its_input():
    composed = compose_round_prompt(
        instructions="/dream:scout GH12",
        is_resuming=False,
        input_prompt=INPUT_PROMPT,
        previous_outcome=None,
    )

    assert composed == (
        f"/dream:scout GH12\n\n{INPUT_PROMPT}{_AGENT_POST_INSTRUCTIONS}"
    )


def test_a_resumed_session_is_given_its_input_alone():
    composed = compose_round_prompt(
        instructions="/dream:smith GH12",
        is_resuming=True,
        input_prompt=INPUT_PROMPT,
        previous_outcome=AgentRoundOutcome.SUCCESSFUL,
    )

    assert composed == INPUT_PROMPT + _AGENT_POST_INSTRUCTIONS


@pytest.mark.parametrize(
    ("previous_outcome", "opening"),
    [
        (
            AgentRoundOutcome.STOPPED,
            "The user stopped your previous round before it\nfinished.",
        ),
        (AgentRoundOutcome.ERRORED, "Your previous round did not finish."),
        (AgentRoundOutcome.INTERRUPTED, "Your previous round did not finish."),
    ],
)
def test_input_after_a_round_that_ended_short_says_why(previous_outcome, opening):
    resumed = compose_round_prompt(
        instructions="/dream:smith GH12",
        is_resuming=True,
        input_prompt=INPUT_PROMPT,
        previous_outcome=previous_outcome,
    )
    fresh = compose_round_prompt(
        instructions="/dream:smith GH12",
        is_resuming=False,
        input_prompt=INPUT_PROMPT,
        previous_outcome=previous_outcome,
    )

    assert resumed.startswith(opening)
    assert "new input says what to do next" in " ".join(resumed.split())
    assert fresh.startswith(f"/dream:smith GH12\n\n{opening}")


def test_the_assignment_input_prompt_names_the_pull_request_and_the_file(
    tmp_path,
):
    round_input = tmp_path / "round-input.json"

    composed = compose_assignment_input_prompt(pull_request=52, round_input=round_input)

    assert composed.startswith("User-posts prompt for pull request #52:")
    assert str(round_input) in composed


def test_the_conversation_input_prompt_names_its_input_and_host_boundary(tmp_path):
    round_input = tmp_path / "round-input.json"

    composed = compose_conversation_input_prompt(issue=52, round_input=round_input)

    assert composed.startswith("Issue-conversation input for GH52:")
    assert str(round_input) in composed
    assert "/dream:conversation" not in composed
    assert "make issue changes on\nGitHub when the user asks" in composed
    assert "do not repeat an action that an earlier attempt completed" in composed
    assert (
        "Do not\nclose the conversation issue or change its assignees or labels"
        in composed
    )
    assert "Do not edit\nproject source, mutate Git, or implement a change" in composed
    assert (
        "closing\nthe issue ends the conversation and removing its label or assignee "
        "pauses it" in composed
    )
    assert "Do\nnot fetch issue comments yourself" in composed
    assert "open or change a pull request" in composed
    assert "post the\nconversation reply yourself" in composed
    assert "revision" in composed


@pytest.mark.parametrize("input_prompt", [None, INPUT_PROMPT])
@pytest.mark.parametrize("is_resuming", [False, True])
def test_every_round_prompt_the_daemon_composes_asks_for_the_marker(
    input_prompt, is_resuming
):
    composed = compose_round_prompt(
        instructions="/dream:smith GH12",
        is_resuming=is_resuming,
        input_prompt=input_prompt,
        previous_outcome=AgentRoundOutcome.STOPPED,
    )

    assert composed.endswith(_AGENT_POST_INSTRUCTIONS)
    assert AGENT_POST_MARKER in composed
