from pathlib import Path

import pytest
from conftest import CONFIG

from dreamcatcher.config import (
    DREAMCATCHER_CONFIG_NAME,
    AgentHarness,
    read_dreamcatcher_config,
)
from dreamcatcher.prompts import (
    AGENT_POST_INSTRUCTIONS,
    AGENT_POST_MARKER,
    ISSUE_CONVERSATION_RECOVERY_PROMPT,
    RECOVERY_PROMPT,
    compose_first_round_prompt,
    compose_issue_conversation_prompt,
    compose_issue_conversation_round_prompt,
    compose_user_posts_prompt,
)

# What each harness's template in the test config renders as for issue 12. A
# harness with no line here fails the test below rather than going untested.
OPENINGS = {
    AgentHarness.CLAUDE: "/dream:smith GH12",
    AgentHarness.CODEX: "$dream:smith GH12",
}


def test_a_template_holding_other_words_in_braces_keeps_them():
    assert compose_first_round_prompt(
        template="read {the design} for GH{issue}", issue=12
    ).startswith("read {the design} for GH12\n")


@pytest.mark.parametrize("harness", list(AgentHarness))
def test_the_prompt_that_opens_an_assignment_is_its_template_then_the_postscript(
    tmp_path, harness
):
    (tmp_path / DREAMCATCHER_CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    recipe = read_dreamcatcher_config(root=tmp_path).dispatch[0].recipes[harness]

    composed = compose_first_round_prompt(template=recipe.prompt, issue=12)

    assert composed == OPENINGS[harness] + AGENT_POST_INSTRUCTIONS


def test_the_prompt_that_carries_a_round_on_says_the_last_one_stopped_short():
    assert RECOVERY_PROMPT.startswith("Your previous round did not finish.")
    assert RECOVERY_PROMPT.endswith(AGENT_POST_INSTRUCTIONS)


def test_conversation_recovery_returns_a_complete_postable_answer():
    prompt = " ".join(ISSUE_CONVERSATION_RECOVERY_PROMPT.split())

    assert "cut short, or its answer could not be posted" in prompt
    assert "Nothing from that round reached the issue." in prompt
    assert prompt.endswith(
        "complete answer, as Markdown ready for Dreamcatcher to post, or exactly "
        "NO_REPLY."
    )
    assert AGENT_POST_MARKER not in ISSUE_CONVERSATION_RECOVERY_PROMPT


def test_the_prompt_that_hands_over_user_posts_names_the_pull_request_and_the_file(
    tmp_path,
):
    inbox = tmp_path / "inbox.json"

    composed = compose_user_posts_prompt(pull_request=52, round_input=inbox)

    assert composed.startswith("PR-inbox prompt for pull request #52:")
    assert str(inbox) in composed
    assert composed.endswith(AGENT_POST_INSTRUCTIONS)


def test_input_after_a_stop_explains_why_the_previous_round_ended(tmp_path):
    inbox = tmp_path / "inbox.json"

    assignment = compose_user_posts_prompt(
        pull_request=52, round_input=inbox, was_stopped=True
    )
    conversation = compose_issue_conversation_round_prompt(
        issue=52, round_input=inbox, was_stopped=True
    )

    opening = "The user stopped your previous round before it\nfinished."
    assert assignment.startswith(opening)
    assert conversation.startswith(opening)
    assert "new input says what to do next" in assignment


def test_the_issue_conversation_prompt_names_its_input_and_host_boundary(tmp_path):
    inbox = tmp_path / "inbox.json"

    composed = compose_issue_conversation_prompt(
        template="/dream:conversation GH{issue}", issue=52, round_input=inbox
    )

    assert composed.startswith("/dream:conversation GH52")
    assert str(inbox) in composed
    assert "mutate Git, mutate GitHub" in composed
    assert composed.endswith("or exactly NO_REPLY when no\nreply is needed.")
    assert AGENT_POST_MARKER not in composed


def test_the_issue_conversation_round_prompt_names_only_its_new_input(tmp_path):
    inbox = tmp_path / "inbox.json"

    composed = compose_issue_conversation_round_prompt(issue=52, round_input=inbox)

    assert composed.startswith("Issue-conversation input for GH52:")
    assert str(inbox) in composed
    assert "/dream:conversation" not in composed
    assert "mutate Git, mutate GitHub" in composed
    assert "revision" in composed


def test_every_assignment_prompt_the_daemon_composes_asks_for_the_marker():
    composed = [
        compose_first_round_prompt(template="/dream:smith GH12", issue=12),
        RECOVERY_PROMPT,
        compose_user_posts_prompt(
            pull_request=52,
            round_input=Path("inbox.json"),
        ),
    ]

    assert all(AGENT_POST_MARKER in prompt for prompt in composed)
