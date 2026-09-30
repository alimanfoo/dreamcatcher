from pathlib import Path

import pytest
from conftest import streamed

from dreamcatcher.codex import CODEX_ADAPTER, STDIN_ARGUMENT
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedNote, FeedProse
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    AgentWorkKind,
    HarnessInvocation,
)

ROUND_LAUNCH_REQUEST = AgentRoundLaunchRequest(
    agent_work_identifier="GH9-20260819-184158",
    model="gpt-5.6-sol",
    effort="xhigh",
    prompt="$dream:smith GH9",
)
CONVERSATION_LAUNCH_REQUEST = AgentRoundLaunchRequest(
    agent_work_identifier="conversation-GH9",
    model="gpt-5.6-sol",
    effort="xhigh",
    prompt="Answer GH9.",
    work_kind=AgentWorkKind.CONVERSATION,
)

CODEX_ROUND_SETTINGS = [
    "--model",
    "gpt-5.6-sol",
    "-c",
    'model_reasoning_effort="xhigh"',
]
FINAL_OUTPUT_PATH = Path("rounds") / "1" / "final.md"


def completed(**item) -> str:
    return streamed(type="item.completed", item=item)


# Each command ends in the word that has Codex read its prompt from stdin.
def test_a_first_round_runs_where_it_is_launched_under_codexs_own_reviewer():
    assert CODEX_ADAPTER.build_first_round(
        request=ROUND_LAUNCH_REQUEST,
        final_output_path=FINAL_OUTPUT_PATH,
    ) == HarnessInvocation(
        program="codex",
        arguments=[
            "exec",
            "--json",
            "--approve-for-me",
            *CODEX_ROUND_SETTINGS,
            "-c",
            "sandbox_workspace_write.network_access=true",
            STDIN_ARGUMENT,
        ],
        prompt="$dream:smith GH9",
    )


def test_a_resume_replays_the_settings_and_the_permissions_codex_forgets():
    assert CODEX_ADAPTER.build_resumed_round(
        request=ROUND_LAUNCH_REQUEST,
        harness_session_identifier="01a0213c-9c67",
        final_output_path=FINAL_OUTPUT_PATH,
    ) == HarnessInvocation(
        program="codex",
        arguments=[
            "exec",
            "resume",
            "--json",
            *CODEX_ROUND_SETTINGS,
            "-c",
            'sandbox_mode="workspace-write"',
            "-c",
            "sandbox_workspace_write.network_access=true",
            "-c",
            'approval_policy="on-request"',
            "-c",
            'approvals_reviewer="auto_review"',
            "01a0213c-9c67",
            STDIN_ARGUMENT,
        ],
        prompt="$dream:smith GH9",
    )


def test_a_first_conversation_round_can_write_and_reach_github_without_approval():
    assert CODEX_ADAPTER.build_first_round(
        request=CONVERSATION_LAUNCH_REQUEST,
        final_output_path=FINAL_OUTPUT_PATH,
    ) == HarnessInvocation(
        program="codex",
        arguments=[
            "exec",
            "--json",
            *CODEX_ROUND_SETTINGS,
            "-c",
            'sandbox_mode="workspace-write"',
            "-c",
            "sandbox_workspace_write.network_access=true",
            "-c",
            'approval_policy="never"',
            "--output-last-message",
            str(FINAL_OUTPUT_PATH),
            STDIN_ARGUMENT,
        ],
        prompt="Answer GH9.",
    )


def test_a_resumed_conversation_can_write_and_reach_github_without_approval():
    assert CODEX_ADAPTER.build_resumed_round(
        request=CONVERSATION_LAUNCH_REQUEST,
        harness_session_identifier="01a0213c-9c67",
        final_output_path=FINAL_OUTPUT_PATH,
    ) == HarnessInvocation(
        program="codex",
        arguments=[
            "exec",
            "resume",
            "--json",
            *CODEX_ROUND_SETTINGS,
            "-c",
            'sandbox_mode="workspace-write"',
            "-c",
            "sandbox_workspace_write.network_access=true",
            "-c",
            'approval_policy="never"',
            "--output-last-message",
            str(FINAL_OUTPUT_PATH),
            "01a0213c-9c67",
            STDIN_ARGUMENT,
        ],
        prompt="Answer GH9.",
    )


def test_a_conversation_refuses_a_final_output_path_windows_cannot_carry():
    with pytest.raises(ReportableError, match="percent sign"):
        CODEX_ADAPTER.build_first_round(
            request=CONVERSATION_LAUNCH_REQUEST,
            final_output_path=Path("rounds") / "%TEMP%" / "final.md",
        )


def test_a_person_continues_the_harness_session_with_codexs_interactive_resume():
    assert CODEX_ADAPTER.build_hand_resume(
        harness_session_identifier="01a0213c-9c67"
    ) == [
        "codex",
        "resume",
        "01a0213c-9c67",
    ]


def test_the_first_event_names_the_harness_session():
    line = streamed(type="thread.started", thread_id="01a0213c-9c67")

    assert CODEX_ADAPTER.read(line=line) == [
        FeedNote(label="harness session", detail="id 01a0213c-9c67")
    ]
    assert (
        CODEX_ADAPTER.read_output(line=line).harness_session_identifier
        == "01a0213c-9c67"
    )


def test_another_event_names_no_harness_session():
    line = streamed(type="turn.started")

    assert CODEX_ADAPTER.read_output(line=line).harness_session_identifier is None


def test_a_non_text_harness_session_identifier_is_left_raw():
    line = streamed(type="thread.started", thread_id=None)

    output = CODEX_ADAPTER.read_output(line=line)

    assert output.harness_session_identifier is None
    assert output.events == [FeedProse(text=line)]


def test_what_the_agent_says_comes_through_whole():
    line = completed(type="agent_message", text="I read the file.\nIt was empty.")

    assert CODEX_ADAPTER.read(line=line) == [
        FeedProse(text="I read the file.\nIt was empty.")
    ]


def test_a_command_that_ran_reports_what_it_was():
    line = completed(
        type="command_execution",
        command="/bin/zsh -lc 'pytest'",
        aggregated_output="1 passed\n",
        exit_code=0,
        status="completed",
    )

    assert CODEX_ADAPTER.read(line=line) == [
        FeedNote(label="command_execution", detail="/bin/zsh -lc 'pytest'")
    ]


def test_a_command_that_failed_reports_what_it_said():
    line = completed(
        type="command_execution",
        command="/bin/zsh -lc 'cat nope.txt'",
        aggregated_output="cat: nope.txt: No such file or directory\n",
        exit_code=1,
        status="failed",
    )

    assert CODEX_ADAPTER.read(line=line) == [
        FeedNote(label="command_execution", detail="/bin/zsh -lc 'cat nope.txt'"),
        FeedNote(label="failed", detail="cat: nope.txt: No such file or directory\n"),
    ]


def test_a_command_the_reviewer_declined_reads_as_declined():
    line = completed(
        type="command_execution",
        command="/bin/zsh -lc 'rm -rf /'",
        aggregated_output="",
        exit_code=None,
        status="declined",
    )

    assert CODEX_ADAPTER.read(line=line) == [
        FeedNote(label="command_execution", detail="/bin/zsh -lc 'rm -rf /'"),
        FeedNote(label="declined", detail=""),
    ]


def test_a_patch_reports_each_file_it_touched_as_what_it_did_to_it():
    line = completed(
        type="file_change",
        changes=[
            {"path": "/repo/gamma.txt", "kind": "add"},
            {"path": "/repo/alpha.txt", "kind": "delete"},
        ],
        status="completed",
    )

    assert CODEX_ADAPTER.read(line=line) == [
        FeedNote(label="add", detail="/repo/gamma.txt"),
        FeedNote(label="delete", detail="/repo/alpha.txt"),
    ]


def test_a_web_search_reports_what_it_looked_for():
    line = completed(
        type="web_search",
        query="latest ripgrep release",
        action={"type": "search", "query": "latest ripgrep release"},
    )

    assert CODEX_ADAPTER.read(line=line) == [
        FeedNote(label="web_search", detail="latest ripgrep release")
    ]


def test_an_error_the_round_survived_reads_as_an_error_not_a_failure():
    line = completed(type="error", message="Model metadata not found.")

    assert CODEX_ADAPTER.read(line=line) == [
        FeedNote(label="error", detail="Model metadata not found.")
    ]


def test_a_round_that_ended_well_says_what_it_spent():
    line = streamed(
        type="turn.completed",
        usage={
            "input_tokens": 84921,
            "cached_input_tokens": 69632,
            "cache_write_input_tokens": 0,
            "output_tokens": 621,
            "reasoning_output_tokens": 137,
        },
    )

    assert CODEX_ADAPTER.read(line=line) == [
        FeedNote(
            label="usage",
            detail=(
                "621 output, 137 reasoning, 84921 input, "
                "69632 cache read, 0 cache write"
            ),
        )
    ]


def test_a_round_that_failed_closes_with_what_went_wrong():
    line = streamed(type="turn.failed", error={"message": "no such model"})

    assert CODEX_ADAPTER.read(line=line) == [
        FeedNote(label="failed", detail="no such model")
    ]


def test_an_event_the_feed_has_no_line_for_writes_nothing():
    assert CODEX_ADAPTER.read(line=streamed(type="turn.started")) == []
    assert (
        CODEX_ADAPTER.read(
            line=streamed(type="error", message="said again as the ending")
        )
        == []
    )
    assert (
        CODEX_ADAPTER.read(
            line=streamed(type="item.started", item={"type": "web_search"})
        )
        == []
    )
    assert CODEX_ADAPTER.read(line=completed(type="todo_list", items=[])) == []


def test_a_line_that_is_not_json_comes_through_unchanged():
    assert CODEX_ADAPTER.read(line="a warning nobody wrapped in JSON\n") == [
        FeedProse(text="a warning nobody wrapped in JSON\n")
    ]


def test_a_line_of_json_that_is_not_an_event_comes_through_unchanged():
    assert CODEX_ADAPTER.read(line='"just a string"') == [
        FeedProse(text='"just a string"')
    ]


def test_an_event_shaped_in_a_way_the_parser_cannot_read_comes_through_unchanged():
    line = completed(type="agent_message")

    assert CODEX_ADAPTER.read(line=line) == [FeedProse(text=line)]


def test_an_item_that_is_not_a_mapping_comes_through_unchanged():
    line = streamed(type="item.completed", item=["not", "a", "map"])

    assert CODEX_ADAPTER.read(line=line) == [FeedProse(text=line)]
