from conftest import streamed

from dreamcatcher.adapters import Launch
from dreamcatcher.claude import ALLOWED_TOOLS, CLAUDE
from dreamcatcher.feed import Note, Prose

LAUNCH = Launch(
    session="GH9-20260819-184158",
    model="opus[1m]",
    effort="xhigh",
    prompt="/dream:smith GH9",
)

BASE = [
    "claude",
    "--print",
    "--output-format",
    "stream-json",
    "--verbose",
    "--permission-mode",
    "auto",
    "--allowedTools",
    " ".join(ALLOWED_TOOLS),
    "--name",
    "GH9-20260819-184158",
]


def assistant(*blocks, parent: str | None = None) -> str:
    return streamed(
        type="assistant",
        message={"content": list(blocks)},
        parent_tool_use_id=parent,
    )


def test_a_first_round_names_the_model_and_the_effort_it_was_dispatched_with():
    assert CLAUDE.first_round(LAUNCH) == [
        *BASE,
        "--model",
        "opus[1m]",
        "--effort",
        "xhigh",
        "/dream:smith GH9",
    ]


def test_a_resume_continues_the_session_and_replays_no_settings():
    assert CLAUDE.resume(LAUNCH) == [*BASE, "--continue", "/dream:smith GH9"]


def test_the_first_event_names_the_model_and_the_session():
    line = streamed(
        type="system", subtype="init", model="claude-opus-5", session_id="abc-123"
    )

    assert CLAUDE.read(line) == [Note("session", "model claude-opus-5, id abc-123")]


def test_what_the_agent_says_comes_through_whole():
    line = assistant({"type": "text", "text": "I read the file.\nIt was empty."})

    assert CLAUDE.read(line) == [Prose("I read the file.\nIt was empty.")]


def test_a_thinking_block_says_only_that_the_agent_thought():
    line = assistant({"type": "thinking", "thinking": "", "signature": "opaque"})

    assert CLAUDE.read(line) == [Note("thinking")]


def test_a_tool_call_reports_the_input_that_says_most_about_it():
    line = assistant(
        {
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "pytest", "timeout": 5},
        }
    )

    assert CLAUDE.read(line) == [Note("Bash", "pytest")]


def test_a_tool_the_chain_does_not_name_reports_its_whole_input():
    line = assistant({"type": "tool_use", "name": "Odd", "input": {"where": "here"}})

    assert CLAUDE.read(line) == [Note("Odd", '{"where": "here"}')]


def test_a_tool_result_that_failed_surfaces():
    line = streamed(
        type="user",
        message={
            "content": [
                {"type": "tool_result", "content": "no such file", "is_error": True}
            ]
        },
    )

    assert CLAUDE.read(line) == [Note("failed", "no such file")]


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

    assert CLAUDE.read(line) == [
        Note("failed", '[{"type": "text", "text": "no such file"}]')
    ]


def test_a_tool_result_that_worked_writes_nothing():
    line = streamed(
        type="user", message={"content": [{"type": "tool_result", "content": "ok"}]}
    )

    assert CLAUDE.read(line) == []


def test_a_subagents_own_words_are_left_to_its_report():
    line = assistant({"type": "text", "text": "counting"}, parent="toolu_1")

    assert CLAUDE.read(line) == []


def test_a_subagent_that_thinks_is_marked_as_one():
    line = assistant({"type": "thinking", "thinking": ""}, parent="toolu_1")

    assert CLAUDE.read(line) == [Note("thinking", subagent=True)]


def test_a_subagents_tool_call_is_marked_as_one():
    line = assistant(
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
        parent="toolu_1",
    )

    assert CLAUDE.read(line) == [Note("Bash", "ls", subagent=True)]


def test_a_finished_subagent_reports_what_it_did():
    line = streamed(
        type="system",
        subtype="task_notification",
        status="completed",
        summary="Two files.",
        usage={"output_tokens": 21},
    )

    assert CLAUDE.read(line) == [
        Note("report", "completed", subagent=True),
        Prose("Two files.", subagent=True),
    ]


def test_a_background_command_finishing_is_not_a_report():
    line = streamed(
        type="system",
        subtype="task_notification",
        status="completed",
        summary='Background command "sleep 3; echo finished" completed (exit code 0)',
    )

    assert CLAUDE.read(line) == []


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

    assert CLAUDE.read(line) == [Note("retry", "rate_limit (429), attempt 3 of 10")]


SPENT = {
    "output_tokens": 226,
    "input_tokens": 6,
    "cache_read_input_tokens": 90437,
    "cache_creation_input_tokens": 8676,
}

SPEND = Note(
    "usage", "$0.0826, 226 output, 6 input, 90437 cache read, 8676 cache write"
)


def test_a_round_that_ended_well_says_what_it_spent_and_how_it_ended():
    line = streamed(
        type="result",
        subtype="success",
        is_error=False,
        total_cost_usd=0.0825951,
        usage=SPENT,
    )

    assert CLAUDE.read(line) == [SPEND, Note("result", "success")]


def test_a_round_that_failed_closes_with_what_went_wrong():
    line = streamed(
        type="result",
        subtype="success",
        is_error=True,
        result="no such model",
        total_cost_usd=0.0825951,
        usage=SPENT,
    )

    assert CLAUDE.read(line) == [SPEND, Note("failed", "no such model")]


def test_an_event_the_feed_has_no_line_for_writes_nothing():
    assert CLAUDE.read(streamed(type="rate_limit_event", rate_limit_info={})) == []
    assert CLAUDE.read(streamed(type="system", subtype="hook_started")) == []
    assert CLAUDE.read(assistant({"type": "image", "source": {}})) == []


def test_a_line_that_is_not_json_comes_through_unchanged():
    assert CLAUDE.read("a warning nobody wrapped in JSON\n") == [
        Prose("a warning nobody wrapped in JSON\n")
    ]


def test_a_line_of_json_that_is_not_an_event_comes_through_unchanged():
    assert CLAUDE.read('"just a string"') == [Prose('"just a string"')]


def test_an_event_shaped_in_a_way_the_parser_cannot_read_comes_through_unchanged():
    line = streamed(type="assistant", message={"content": [{"type": "text"}]})

    assert CLAUDE.read(line) == [Prose(line)]


def test_a_tool_input_that_is_not_a_mapping_comes_through_unchanged():
    line = assistant({"type": "tool_use", "name": "Odd", "input": ["not", "a", "map"]})

    assert CLAUDE.read(line) == [Prose(line)]
