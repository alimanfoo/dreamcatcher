from conftest import streamed

from dreamcatcher.adapters import Invocation, Launch
from dreamcatcher.codex import CODEX, STDIN
from dreamcatcher.feed import Note, Prose

LAUNCH = Launch(
    assignment_id="GH9-20260819-184158",
    model="gpt-5.6-sol",
    effort="xhigh",
    prompt="$dream:smith GH9",
)

SETTINGS = [
    "--model",
    "gpt-5.6-sol",
    "-c",
    'model_reasoning_effort="xhigh"',
]


def completed(**item) -> str:
    return streamed(type="item.completed", item=item)


# Each command ends in the word that has Codex read its prompt from stdin.
def test_a_first_round_runs_where_it_is_launched_under_codexs_own_reviewer():
    assert CODEX.build_first_round(launch=LAUNCH) == Invocation(
        program="codex",
        arguments=[
            "exec",
            "--json",
            "--approve-for-me",
            *SETTINGS,
            "-c",
            "sandbox_workspace_write.network_access=true",
            STDIN,
        ],
        prompt="$dream:smith GH9",
    )


def test_a_resume_replays_the_settings_and_the_permissions_codex_forgets():
    assert CODEX.build_resumed_round(launch=LAUNCH) == Invocation(
        program="codex",
        arguments=[
            "exec",
            "resume",
            "--last",
            "--json",
            *SETTINGS,
            "-c",
            'sandbox_mode="workspace-write"',
            "-c",
            "sandbox_workspace_write.network_access=true",
            "-c",
            'approval_policy="on-request"',
            "-c",
            'approvals_reviewer="auto_review"',
            STDIN,
        ],
        prompt="$dream:smith GH9",
    )


def test_a_person_continues_the_harness_session_with_codexs_interactive_resume():
    assert CODEX.build_hand_resume() == ["codex", "resume", "--last"]


def test_the_first_event_names_the_harness_session():
    line = streamed(type="thread.started", thread_id="01a0213c-9c67")

    assert CODEX.read(line=line) == [
        Note(label="harness session", detail="id 01a0213c-9c67")
    ]


def test_what_the_agent_says_comes_through_whole():
    line = completed(type="agent_message", text="I read the file.\nIt was empty.")

    assert CODEX.read(line=line) == [Prose(text="I read the file.\nIt was empty.")]


def test_a_command_that_ran_reports_what_it_was():
    line = completed(
        type="command_execution",
        command="/bin/zsh -lc 'pytest'",
        aggregated_output="1 passed\n",
        exit_code=0,
        status="completed",
    )

    assert CODEX.read(line=line) == [
        Note(label="command_execution", detail="/bin/zsh -lc 'pytest'")
    ]


def test_a_command_that_failed_reports_what_it_said():
    line = completed(
        type="command_execution",
        command="/bin/zsh -lc 'cat nope.txt'",
        aggregated_output="cat: nope.txt: No such file or directory\n",
        exit_code=1,
        status="failed",
    )

    assert CODEX.read(line=line) == [
        Note(label="command_execution", detail="/bin/zsh -lc 'cat nope.txt'"),
        Note(label="failed", detail="cat: nope.txt: No such file or directory\n"),
    ]


def test_a_command_the_reviewer_declined_reads_as_declined():
    line = completed(
        type="command_execution",
        command="/bin/zsh -lc 'rm -rf /'",
        aggregated_output="",
        exit_code=None,
        status="declined",
    )

    assert CODEX.read(line=line) == [
        Note(label="command_execution", detail="/bin/zsh -lc 'rm -rf /'"),
        Note(label="declined", detail=""),
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

    assert CODEX.read(line=line) == [
        Note(label="add", detail="/repo/gamma.txt"),
        Note(label="delete", detail="/repo/alpha.txt"),
    ]


def test_a_web_search_reports_what_it_looked_for():
    line = completed(
        type="web_search",
        query="latest ripgrep release",
        action={"type": "search", "query": "latest ripgrep release"},
    )

    assert CODEX.read(line=line) == [
        Note(label="web_search", detail="latest ripgrep release")
    ]


def test_an_error_the_round_survived_reads_as_an_error_not_a_failure():
    line = completed(type="error", message="Model metadata not found.")

    assert CODEX.read(line=line) == [
        Note(label="error", detail="Model metadata not found.")
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

    assert CODEX.read(line=line) == [
        Note(
            label="usage",
            detail=(
                "621 output, 137 reasoning, 84921 input, "
                "69632 cache read, 0 cache write"
            ),
        )
    ]


def test_a_round_that_failed_closes_with_what_went_wrong():
    line = streamed(type="turn.failed", error={"message": "no such model"})

    assert CODEX.read(line=line) == [Note(label="failed", detail="no such model")]


def test_an_event_the_feed_has_no_line_for_writes_nothing():
    assert CODEX.read(line=streamed(type="turn.started")) == []
    assert (
        CODEX.read(line=streamed(type="error", message="said again as the ending"))
        == []
    )
    assert (
        CODEX.read(line=streamed(type="item.started", item={"type": "web_search"}))
        == []
    )
    assert CODEX.read(line=completed(type="todo_list", items=[])) == []


def test_a_line_that_is_not_json_comes_through_unchanged():
    assert CODEX.read(line="a warning nobody wrapped in JSON\n") == [
        Prose(text="a warning nobody wrapped in JSON\n")
    ]


def test_a_line_of_json_that_is_not_an_event_comes_through_unchanged():
    assert CODEX.read(line='"just a string"') == [Prose(text='"just a string"')]


def test_an_event_shaped_in_a_way_the_parser_cannot_read_comes_through_unchanged():
    line = completed(type="agent_message")

    assert CODEX.read(line=line) == [Prose(text=line)]


def test_an_item_that_is_not_a_mapping_comes_through_unchanged():
    line = streamed(type="item.completed", item=["not", "a", "map"])

    assert CODEX.read(line=line) == [Prose(text=line)]
