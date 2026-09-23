from collections.abc import Sequence

import pytest
from conftest import streamed

from dreamcatcher.claude import (
    CLAUDE_ADAPTER,
    CLAUDE_ASSIGNMENT_ALLOWED_TOOLS,
    CLAUDE_CONVERSATION_DISALLOWED_TOOLS,
)
from dreamcatcher.feed import FeedNote, FeedProse
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    AgentWorkKind,
    HarnessInvocation,
    HarnessOutput,
)

ROUND_LAUNCH_REQUEST = AgentRoundLaunchRequest(
    agent_work_identifier="GH9-20260819-184158",
    model="opus[1m]",
    effort="xhigh",
    prompt="/dream:smith GH9",
)

CLAUDE_BASE_ARGUMENTS = [
    "--print",
    "--output-format",
    "stream-json",
    "--verbose",
    "--permission-mode",
    "auto",
    "--allowedTools",
    " ".join(CLAUDE_ASSIGNMENT_ALLOWED_TOOLS),
    "--name",
    "GH9-20260819-184158",
]


def assistant(*, blocks: Sequence[dict], parent: str | None = None) -> str:
    return streamed(
        type="assistant",
        message={"content": list(blocks)},
        parent_tool_use_id=parent,
    )


# Neither command names the prompt, which is what has Claude read it from stdin.
def test_a_first_round_names_the_model_and_the_effort_it_was_dispatched_with():
    assert CLAUDE_ADAPTER.build_first_round(
        request=ROUND_LAUNCH_REQUEST
    ) == HarnessInvocation(
        program="claude",
        arguments=[*CLAUDE_BASE_ARGUMENTS, "--model", "opus[1m]", "--effort", "xhigh"],
        prompt="/dream:smith GH9",
    )


def test_a_resume_continues_the_harness_session_and_replays_no_settings():
    assert CLAUDE_ADAPTER.build_resumed_round(
        request=ROUND_LAUNCH_REQUEST, harness_session_identifier="abc-123"
    ) == HarnessInvocation(
        program="claude",
        arguments=[*CLAUDE_BASE_ARGUMENTS, "--resume", "abc-123"],
        prompt="/dream:smith GH9",
    )


def test_a_conversation_round_denies_implementation_and_github_tools():
    request = AgentRoundLaunchRequest(
        agent_work_identifier="conversation-GH9",
        model="opus[1m]",
        effort="xhigh",
        prompt="answer the question",
        work_kind=AgentWorkKind.CONVERSATION,
    )

    invocation = CLAUDE_ADAPTER.build_first_round(request=request)

    assert "--allowedTools" not in invocation.arguments
    denied_at = invocation.arguments.index("--disallowedTools")
    assert invocation.arguments[denied_at + 1] == " ".join(
        CLAUDE_CONVERSATION_DISALLOWED_TOOLS
    )


def test_a_person_continues_the_harness_session_where_it_ran():
    assert CLAUDE_ADAPTER.build_hand_resume(harness_session_identifier="abc-123") == [
        "claude",
        "--resume",
        "abc-123",
    ]


def test_the_first_event_names_the_model_and_the_harness_session():
    line = streamed(
        type="system", subtype="init", model="claude-opus-5", session_id="abc-123"
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        FeedNote(label="harness session", detail="model claude-opus-5, id abc-123")
    ]
    assert CLAUDE_ADAPTER.read_output(line=line).harness_session_identifier == "abc-123"


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        "[]",
        streamed(type="assistant"),
        streamed(type="system", subtype="api_retry"),
    ],
)
def test_anything_but_the_first_event_names_no_harness_session(line):
    assert CLAUDE_ADAPTER.read_output(line=line).harness_session_identifier is None


def test_a_non_text_harness_session_identifier_is_left_raw():
    line = streamed(
        type="system", subtype="init", model="claude-opus-5", session_id=None
    )

    output = CLAUDE_ADAPTER.read_output(line=line)

    assert output.harness_session_identifier is None
    assert output.events == [FeedProse(text=line)]


def test_what_the_agent_says_comes_through_whole():
    line = assistant(
        blocks=[{"type": "text", "text": "I read the file.\nIt was empty."}]
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        FeedProse(text="I read the file.\nIt was empty.")
    ]


def test_a_thinking_block_says_only_that_the_agent_thought():
    line = assistant(
        blocks=[{"type": "thinking", "thinking": "", "signature": "opaque"}]
    )

    assert CLAUDE_ADAPTER.read(line=line) == [FeedNote(label="thinking")]


def test_a_tool_call_reports_the_input_that_says_most_about_it():
    line = assistant(
        blocks=[
            {
                "type": "tool_use",
                "name": "Bash",
                "input": {"command": "pytest", "timeout": 5},
            }
        ]
    )

    assert CLAUDE_ADAPTER.read(line=line) == [FeedNote(label="Bash", detail="pytest")]


def test_a_tool_the_chain_does_not_name_reports_its_whole_input():
    line = assistant(
        blocks=[{"type": "tool_use", "name": "Odd", "input": {"where": "here"}}]
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        FeedNote(label="Odd", detail='{"where": "here"}')
    ]


def test_a_tool_result_that_failed_surfaces():
    line = streamed(
        type="user",
        message={
            "content": [
                {"type": "tool_result", "content": "no such file", "is_error": True}
            ]
        },
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        FeedNote(label="failed", detail="no such file")
    ]


def test_a_failure_that_came_back_as_blocks_reads_as_the_json_it_was():
    line = streamed(
        type="user",
        message={
            "content": [
                {
                    "type": "tool_result",
                    "content": [{"type": "text", "text": "no such file"}],
                    "is_error": True,
                }
            ]
        },
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        FeedNote(label="failed", detail='[{"type": "text", "text": "no such file"}]')
    ]


def test_a_tool_result_that_worked_writes_nothing():
    line = streamed(
        type="user", message={"content": [{"type": "tool_result", "content": "ok"}]}
    )

    assert CLAUDE_ADAPTER.read(line=line) == []


def test_a_subagents_own_words_are_left_to_its_report():
    line = assistant(blocks=[{"type": "text", "text": "counting"}], parent="toolu_1")

    assert CLAUDE_ADAPTER.read(line=line) == []


def test_a_subagent_that_thinks_is_marked_as_one():
    line = assistant(blocks=[{"type": "thinking", "thinking": ""}], parent="toolu_1")

    assert CLAUDE_ADAPTER.read(line=line) == [
        FeedNote(label="thinking", is_subagent=True)
    ]


def test_a_subagents_tool_call_is_marked_as_one():
    line = assistant(
        blocks=[{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
        parent="toolu_1",
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        FeedNote(label="Bash", detail="ls", is_subagent=True)
    ]


def test_a_finished_subagent_reports_what_it_did():
    line = streamed(
        type="system",
        subtype="task_notification",
        status="completed",
        summary="Two files.",
        usage={"output_tokens": 21},
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        FeedNote(label="report", detail="completed", is_subagent=True),
        FeedProse(text="Two files.", is_subagent=True),
    ]


def test_a_background_command_finishing_is_not_a_report():
    line = streamed(
        type="system",
        subtype="task_notification",
        status="completed",
        summary='Background command "sleep 3; echo finished" completed (exit code 0)',
    )

    assert CLAUDE_ADAPTER.read(line=line) == []


def test_a_round_being_retried_says_what_it_is_waiting_on():
    line = streamed(
        type="system",
        subtype="api_retry",
        attempt=3,
        max_retries=10,
        retry_delay_ms=2310,
        error_status=429,
        error="rate_limit",
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        FeedNote(label="retry", detail="rate_limit (429), attempt 3 of 10")
    ]


SPENT = {
    "output_tokens": 226,
    "input_tokens": 6,
    "cache_read_input_tokens": 90437,
    "cache_creation_input_tokens": 8676,
}

SPEND = FeedNote(
    label="usage",
    detail="$0.0826, 226 output, 6 input, 90437 cache read, 8676 cache write",
)


def test_a_round_that_ended_well_says_what_it_spent_and_how_it_ended():
    line = streamed(
        type="result",
        subtype="success",
        is_error=False,
        total_cost_usd=0.0825951,
        usage=SPENT,
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        SPEND,
        FeedNote(label="result", detail="success"),
    ]


def test_a_successful_round_exposes_its_final_output_separately():
    line = streamed(
        type="result",
        subtype="success",
        is_error=False,
        result="The answer.",
        total_cost_usd=0.0825951,
        usage=SPENT,
    )

    assert CLAUDE_ADAPTER.read_output(line=line) == HarnessOutput(
        events=[SPEND, FeedNote(label="result", detail="success")],
        final_output="The answer.",
    )


def test_a_round_that_failed_closes_with_what_went_wrong():
    line = streamed(
        type="result",
        subtype="success",
        is_error=True,
        result="no such model",
        total_cost_usd=0.0825951,
        usage=SPENT,
    )

    assert CLAUDE_ADAPTER.read(line=line) == [
        SPEND,
        FeedNote(label="failed", detail="no such model"),
    ]


def test_an_event_the_feed_has_no_line_for_writes_nothing():
    assert (
        CLAUDE_ADAPTER.read(line=streamed(type="rate_limit_event", rate_limit_info={}))
        == []
    )
    assert (
        CLAUDE_ADAPTER.read(line=streamed(type="system", subtype="hook_started")) == []
    )
    assert (
        CLAUDE_ADAPTER.read(line=assistant(blocks=[{"type": "image", "source": {}}]))
        == []
    )


def test_a_line_that_is_not_json_comes_through_unchanged():
    assert CLAUDE_ADAPTER.read(line="a warning nobody wrapped in JSON\n") == [
        FeedProse(text="a warning nobody wrapped in JSON\n")
    ]


def test_a_line_of_json_that_is_not_an_event_comes_through_unchanged():
    assert CLAUDE_ADAPTER.read(line='"just a string"') == [
        FeedProse(text='"just a string"')
    ]


def test_an_event_shaped_in_a_way_the_parser_cannot_read_comes_through_unchanged():
    line = streamed(type="assistant", message={"content": [{"type": "text"}]})

    assert CLAUDE_ADAPTER.read(line=line) == [FeedProse(text=line)]


def test_a_tool_input_that_is_not_a_mapping_comes_through_unchanged():
    line = assistant(
        blocks=[{"type": "tool_use", "name": "Odd", "input": ["not", "a", "map"]}]
    )

    assert CLAUDE_ADAPTER.read(line=line) == [FeedProse(text=line)]
