import json
import sys
from contextlib import suppress
from threading import Thread
from time import monotonic, sleep
from typing import cast
from unittest.mock import Mock

import psutil
import pytest
from clocks import PINNED
from conftest import (
    FIXTURES,
    HUNK,
    POSTED_BY,
    comment,
    inline_comment,
    review,
    streamed,
)
from fakes import Line, Stream, recorded
from recordings import render_harness_recording

from dreamcatcher.agent_rounds import (
    AGENT_ROUND_RECORD_NAME,
    AgentAssignmentRoundInput,
    AgentRound,
    AgentRoundFinisher,
    AgentRoundHarness,
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundPlan,
    AgentRoundPurpose,
    AgentRoundRecord,
    AgentRoundStartRequest,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    compose_agent_round_ending,
    record_agent_round_interruption,
    start_agent_round,
)
from dreamcatcher.claude import CLAUDE_ADAPTER
from dreamcatcher.config import AgentHarness
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedNote, FeedRenderer
from dreamcatcher.github import (
    ConversationComment,
    InlineReviewComment,
    PullRequestReview,
    PullRequestState,
)
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    AgentWorkKind,
    HarnessAdapter,
    HarnessInvocation,
    HarnessOutput,
)

# A round that listed a directory, read a file that was not there, and sent a
# subagent to count the files. Its golden feed is asserted in test_recordings.
RECORDING = FIXTURES / "claude" / "round.jsonl"

FEED_TIMESTAMP = "2026-08-19T18:41:58Z"

# What the tests here say woke every round they run.
PURPOSE = AgentRoundPurpose.IMPLEMENT

# What every round here asks the harness to do. It holds a percent sign and runs
# over two lines, neither of which a command line could carry to a batch file,
# because the prompt reaches the harness as a file it reads.
PROMPT = "/dream:smith GH9\nfinish 50% of it"

# A harness that leaves a process behind holding the round's own streams, and
# says in the file it is passed which process that is. The streams are handed
# down by name, because Windows passes a child no handle it was not given. The
# process it leaves starts an assignment of its own, so on POSIX it is out of the
# round's group and ending the group cannot reach it, which is the one shape of
# straggler that gets away. Windows keeps it in the round's job, where ending
# the job does reach it.
LEAVES_A_STRAGGLER = (
    "import pathlib, subprocess, sys\n"
    "waiting = [sys.executable, '-c', 'import time; time.sleep(60)']\n"
    "left = subprocess.Popen(\n"
    "    waiting, stdout=sys.stdout, stderr=sys.stderr, start_new_session=True\n"
    ")\n"
    "pathlib.Path(sys.argv[1]).write_text(str(left.pid), encoding='utf-8')\n"
)

# What keeps such a harness running, so a test can stop it mid-round.
AND_WAITS = "left.wait()\n"


def pinned():
    """The clock every round here reads, so a feed line's stamp is known."""
    return PINNED


def ignore_harness_session_identifier(*, identifier: str) -> None:
    """Accept a harness session identifier that a test does not inspect."""


def round_harness(
    *,
    adapter: HarnessAdapter = CLAUDE_ADAPTER,
    invocation: HarnessInvocation | None = None,
    record=ignore_harness_session_identifier,
) -> AgentRoundHarness:
    """Return the harness boundary used by one round test.

    A test that names no invocation runs the stand-in harness on the prompt.
    """
    return AgentRoundHarness(
        adapter=adapter,
        invocation=invocation
        or HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        record_harness_session_identifier=record,
    )


class Unrenderable(HarnessAdapter):
    """An adapter whose events hold what the feed has no way to write."""

    program = "harness"

    def build_first_round(
        self, *, request: AgentRoundLaunchRequest
    ) -> HarnessInvocation:
        return HarnessInvocation(
            program=self.program, arguments=[], prompt=request.prompt
        )

    def build_resumed_round(
        self, *, request: AgentRoundLaunchRequest, harness_session_identifier: str
    ) -> HarnessInvocation:
        return HarnessInvocation(
            program=self.program, arguments=[], prompt=request.prompt
        )

    def build_hand_resume(self, *, harness_session_identifier: str) -> list[str]:
        return [self.program]

    def _read(self, *, harness_event: dict) -> HarnessOutput:
        # A real harness can send a path or a command as something other than
        # text, and the renderer cannot write an event that holds one.
        return HarnessOutput(
            events=[FeedNote(label="read", detail=cast("str", harness_event))]
        )


@pytest.fixture
def worktree(tmp_path):
    """The directory a round runs in, standing in for an assignment's worktree."""
    made = tmp_path / "worktree"
    made.mkdir()
    return made


@pytest.fixture
def directory(tmp_path):
    """The directory a round writes its own files into."""
    return tmp_path / "rounds" / "1"


@pytest.fixture
def straggler(tmp_path):
    """The file that a harness writes into, naming what it left behind.

    Whatever the file names is killed once the test has run, so nothing a round
    left behind outlives it, and nothing goes on holding a pipe.
    """
    path = tmp_path / "straggler.pid"
    yield path
    with suppress(FileNotFoundError, psutil.NoSuchProcess):
        psutil.Process(int(path.read_text(encoding="utf-8"))).kill()


def written(*, path):
    """Return what the round recorded about itself."""
    return AgentRoundRecord.model_validate_json(path.read_text(encoding="utf-8"))


def compose_round_paths(*, worktree, directory) -> AgentRoundPaths:
    """Name the files of the numbered round at directory."""
    return AgentRoundPaths(
        worktree=worktree,
        rounds_directory=directory.parent,
        number=int(directory.name),
    )


def within(*, seconds, holds):
    """Wait up to seconds for holds to answer true, and say whether it did."""
    deadline = monotonic() + seconds
    while not holds() and monotonic() < deadline:
        sleep(0.05)
    return holds()


def test_a_round_runs_the_command_it_was_given_in_the_worktree(
    fake, worktree, directory
):
    harness = fake(program="harness")
    harness.replies(stdout="")

    AgentRound(
        harness=round_harness(
            invocation=HarnessInvocation(
                program="harness", arguments=["--print"], prompt=PROMPT
            )
        ),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    ).wait()

    assert harness.calls[0].arguments == ["--print"]
    assert harness.calls[0].directory == worktree.resolve()


def test_a_round_gives_the_harness_its_prompt_to_read(fake, worktree, directory):
    harness = fake(program="harness")
    harness.replies(stdout="")

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert harness.calls[0].prompt == PROMPT
    assert running.paths.prompt.read_text(encoding="utf-8") == PROMPT


def test_a_first_round_builds_its_harness_invocation(fake, worktree, directory):
    harness = fake(program="claude")
    harness.replies(stdout="")

    start_agent_round(
        request=AgentRoundStartRequest(
            harness=AgentHarness.CLAUDE,
            launch_request=AgentRoundLaunchRequest(
                agent_work_identifier="GH9-20260819-184158",
                model="opus[1m]",
                effort="xhigh",
                prompt=PROMPT,
            ),
            harness_session_identifier=None,
            record_harness_session_identifier=ignore_harness_session_identifier,
            finish_round=None,
            paths=compose_round_paths(worktree=worktree, directory=directory),
            plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        ),
        clock=pinned,
    ).wait()

    call = harness.calls[0]
    assert call.arguments[-4:] == ["--model", "opus[1m]", "--effort", "xhigh"]
    assert call.prompt == PROMPT
    assert call.directory == worktree.resolve()


def test_a_resumed_round_builds_its_harness_invocation(fake, worktree, directory):
    harness = fake(program="claude")
    harness.replies(stdout="")

    start_agent_round(
        request=AgentRoundStartRequest(
            harness=AgentHarness.CLAUDE,
            launch_request=AgentRoundLaunchRequest(
                agent_work_identifier="GH9-20260819-184158",
                model="opus[1m]",
                effort="xhigh",
                prompt=PROMPT,
            ),
            harness_session_identifier="abc-123",
            record_harness_session_identifier=ignore_harness_session_identifier,
            finish_round=None,
            paths=compose_round_paths(worktree=worktree, directory=directory),
            plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=True),
        ),
        clock=pinned,
    ).wait()

    call = harness.calls[0]
    assert call.arguments[-2:] == ["--resume", "abc-123"]
    assert "opus[1m]" not in call.arguments
    assert "xhigh" not in call.arguments
    assert call.prompt == PROMPT
    assert call.directory == worktree.resolve()


def test_a_round_writes_the_pull_request_state_and_user_posts_it_was_given(
    fake, worktree, directory
):
    harness = fake(program="harness")
    harness.replies(stdout="")
    posts = [
        ConversationComment.model_validate(comment()),
        PullRequestReview.model_validate(
            review(body="have a look", user={"login": POSTED_BY})
        ),
        InlineReviewComment.model_validate(inline_comment()),
    ]

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(
            purpose=PURPOSE,
            is_recovery=False,
            input=AgentAssignmentRoundInput(
                pull_request_state=PullRequestState.OPEN, user_posts=posts
            ),
        ),
        clock=pinned,
    )
    running.wait()

    read_back = json.loads(running.paths.round_input.read_text(encoding="utf-8"))
    assert read_back["pull_request_state"] == "OPEN"
    assert [post["kind"] for post in read_back["user_posts"]] == [
        "comment",
        "review",
        "inlineComment",
    ]
    assert read_back["user_posts"][1]["verdict"] == "COMMENTED"
    assert "state" not in read_back["user_posts"][1]
    assert read_back["user_posts"][2]["diff_hunk"] == HUNK


def test_the_feed_a_round_writes_is_the_feed_its_stream_renders_as(
    fake, worktree, directory
):
    fake(program="harness").streams(lines=recorded(path=RECORDING))

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert running.paths.feed.read_text(encoding="utf-8") == render_harness_recording(
        adapter=CLAUDE_ADAPTER,
        lines=RECORDING.read_text(encoding="utf-8").splitlines(),
        renderer=FeedRenderer(worktree=worktree, clock=pinned),
    )


def test_a_round_keeps_the_harnesss_own_stream_as_it_arrived(fake, worktree, directory):
    fake(program="harness").streams(lines=recorded(path=RECORDING))

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert running.paths.raw_output.read_text(encoding="utf-8") == RECORDING.read_text(
        encoding="utf-8"
    )


def test_a_round_records_the_harness_session_after_its_raw_event_lands(
    fake, worktree, directory
):
    line = (
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "model": "claude-opus-5",
                "session_id": "abc-123",
            }
        )
        + "\n"
    )
    fake(program="harness").streams(lines=[Line(text=line)])
    paths = compose_round_paths(worktree=worktree, directory=directory)
    recorded = []

    def record(*, identifier: str) -> None:
        recorded.append((identifier, paths.raw_output.read_text(encoding="utf-8")))

    running = AgentRound(
        harness=round_harness(record=record),
        paths=paths,
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert recorded == [("abc-123", line)]


def test_what_the_harness_says_on_stderr_lands_where_it_happened(
    fake, worktree, directory
):
    fake(program="harness").streams(
        lines=[
            Line(text="first\n"),
            Line(text="an aside\n", stream=Stream.ERR),
            Line(text="second\n"),
        ],
        # The two streams reach the round on threads of their own, so the space
        # between the lines is what puts them in a known order.
        delay=0.25,
    )

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert running.paths.feed.read_text(encoding="utf-8").splitlines() == [
        f"{FEED_TIMESTAMP}  first",
        f"{FEED_TIMESTAMP}  an aside",
        f"{FEED_TIMESTAMP}  second",
    ]
    assert running.paths.raw_output.read_text(encoding="utf-8") == "first\nsecond\n"


def test_a_line_the_feed_cannot_write_costs_that_line_alone(fake, worktree, directory):
    fake(program="harness").streams(
        lines=[Line(text='{"said": "hello"}\n'), Line(text="plain\n")]
    )

    running = AgentRound(
        harness=round_harness(adapter=Unrenderable()),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert running.paths.feed.read_text(encoding="utf-8").splitlines() == [
        f'{FEED_TIMESTAMP}  {{"said": "hello"}}',
        f"{FEED_TIMESTAMP}  plain",
    ]


def test_a_round_records_its_number_purpose_recovery_and_process(
    fake, worktree, directory
):
    fake(program="harness").streams(
        lines=[Line(text="working\n"), Line(text="still working\n")], delay=5
    )

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )

    assert running.is_alive
    record = written(path=running.paths.record)
    assert record == AgentRoundRecord(
        number=1,
        purpose=PURPOSE,
        is_recovery=False,
        started=PINNED,
        pid=running.harness_process.pid,
    )
    assert record.outcome is AgentRoundOutcome.RUNNING

    running.stop()


def test_a_round_that_finished_says_how_it_ended(fake, worktree, directory):
    fake(program="harness").streams(lines=[Line(text="giving up\n")], status=2)

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=True),
        clock=pinned,
    )
    running.wait()

    assert not running.is_alive
    record = written(path=running.paths.record)
    assert record == AgentRoundRecord(
        started=PINNED,
        pid=running.harness_process.pid,
        number=1,
        purpose=PURPOSE,
        is_recovery=True,
        ending=compose_agent_round_ending(at=PINNED, status=2),
    )
    assert record.outcome is AgentRoundOutcome.ERRORED


def stream_final_result(*, result: str) -> str:
    """Return the stdout of a Claude round that ends with one final result."""
    final_result = streamed(
        type="result",
        subtype="success",
        is_error=False,
        result=result,
        total_cost_usd=0.0,
        usage={
            "output_tokens": 1,
            "input_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    )
    return f"{final_result}\n"


def start_conversation_round(
    *, paths: AgentRoundPaths, finish_round: AgentRoundFinisher | None
) -> AgentRound:
    """Start a conversation round that its owner may finish."""
    return start_agent_round(
        request=AgentRoundStartRequest(
            harness=AgentHarness.CLAUDE,
            launch_request=AgentRoundLaunchRequest(
                agent_work_identifier="conversation-GH9",
                model="opus[1m]",
                effort="xhigh",
                prompt=PROMPT,
                work_kind=AgentWorkKind.CONVERSATION,
            ),
            harness_session_identifier=None,
            record_harness_session_identifier=ignore_harness_session_identifier,
            finish_round=finish_round,
            paths=paths,
            plan=AgentRoundPlan(purpose=AgentRoundPurpose.DISCUSS, is_recovery=False),
        ),
        clock=pinned,
    )


def test_a_round_keeps_the_final_output_its_harness_reports(fake, worktree, directory):
    fake(program="claude").replies(stdout=stream_final_result(result="The answer.\n"))
    paths = compose_round_paths(worktree=worktree, directory=directory)

    start_conversation_round(paths=paths, finish_round=None).wait()

    assert paths.final_output.read_text(encoding="utf-8") == "The answer.\n"
    assert written(path=paths.record).outcome is AgentRoundOutcome.SUCCESSFUL


def test_a_round_is_finished_with_its_final_output_before_it_ends(
    fake, worktree, directory
):
    fake(program="claude").replies(stdout=stream_final_result(result="The answer.\n"))
    paths = compose_round_paths(worktree=worktree, directory=directory)
    finished: list[tuple[str | None, AgentRoundOutcome]] = []

    def finish_round(*, final_output: str | None) -> None:
        finished.append((final_output, written(path=paths.record).outcome))

    start_conversation_round(paths=paths, finish_round=finish_round).wait()

    assert finished == [("The answer.\n", AgentRoundOutcome.RUNNING)]
    assert written(path=paths.record).outcome is AgentRoundOutcome.SUCCESSFUL


def test_a_round_whose_harness_reported_no_final_output_is_finished_without_one(
    fake, worktree, directory
):
    fake(program="claude").replies(stdout="")
    paths = compose_round_paths(worktree=worktree, directory=directory)
    finish_round = Mock()

    start_conversation_round(paths=paths, finish_round=finish_round).wait()

    finish_round.assert_called_once_with(final_output=None)
    assert written(path=paths.record).outcome is AgentRoundOutcome.SUCCESSFUL


def test_a_finisher_that_fails_fails_the_round_and_says_why(fake, worktree, directory):
    fake(program="claude").replies(stdout=stream_final_result(result="The answer."))
    paths = compose_round_paths(worktree=worktree, directory=directory)
    finish_round = Mock(side_effect=ReportableError("could not post the answer on GH9"))

    start_conversation_round(paths=paths, finish_round=finish_round).wait()

    assert written(path=paths.record).outcome is AgentRoundOutcome.ERRORED
    assert "[failed] could not post the answer on GH9" in paths.feed.read_text(
        encoding="utf-8"
    )


def test_a_round_whose_harness_failed_is_not_finished(fake, worktree, directory):
    fake(program="claude").streams(
        lines=[Line(text=stream_final_result(result="The answer."))], status=2
    )
    paths = compose_round_paths(worktree=worktree, directory=directory)
    finish_round = Mock()

    start_conversation_round(paths=paths, finish_round=finish_round).wait()

    assert written(path=paths.record).outcome is AgentRoundOutcome.ERRORED
    finish_round.assert_not_called()


def test_a_round_interrupted_as_its_harness_succeeds_is_not_finished(
    fake, worktree, directory
):
    fake(program="claude").streams(
        lines=[Line(text=stream_final_result(result="The answer."))], delay=1
    )
    paths = compose_round_paths(worktree=worktree, directory=directory)
    finish_round = Mock()

    running = start_conversation_round(paths=paths, finish_round=finish_round)
    # The race that `_interrupt` records: the harness exits cleanly just as
    # somebody stops the round.
    running.is_interrupted = True
    running.wait()

    assert written(path=paths.record).outcome is AgentRoundOutcome.INTERRUPTED
    finish_round.assert_not_called()


def test_an_errored_ending_refuses_a_success_status():
    with pytest.raises(ValueError, match="cannot have exit status 0"):
        ErroredAgentRoundEnding(at=PINNED, status=0)


def test_a_round_somebody_stopped_records_interruption(fake, worktree, directory):
    fake(program="harness").streams(
        lines=[Line(text="working\n"), Line(text="still working\n")], delay=5
    )

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.stop()

    assert not running.is_alive
    assert written(path=running.paths.record).outcome is AgentRoundOutcome.INTERRUPTED


def test_a_round_stopped_after_it_finished_keeps_its_ending(fake, worktree, directory):
    fake(program="harness").streams(lines=[Line(text="done\n")])

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    # The daemon stops every round it holds as it goes down, and one of them
    # can be a round that finished a moment before.
    running.stop()

    assert not running.is_interrupted
    record = written(path=running.paths.record)
    assert record.ending == compose_agent_round_ending(at=PINNED, status=0)
    assert record.outcome is AgentRoundOutcome.SUCCESSFUL


def test_a_round_that_cannot_write_its_feed_stops_rather_than_stalls(
    fake, worktree, directory
):
    fake(program="harness").streams(
        lines=[Line(text="first\n"), Line(text="second\n")], delay=0.25
    )
    directory.mkdir(parents=True)
    (directory / "feed.txt").mkdir()

    running = AgentRound(
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert not running.is_alive
    assert written(path=running.paths.record).outcome is AgentRoundOutcome.INTERRUPTED


def test_a_round_that_cannot_write_its_prompt_never_starts(fake, worktree, tmp_path):
    harness = fake(program="harness")
    harness.replies(stdout="")
    occupied = tmp_path / "occupied"
    occupied.write_text("something else is here\n", encoding="utf-8")

    with pytest.raises(ReportableError, match=r"prompt\.txt"):
        AgentRound(
            harness=round_harness(
                invocation=HarnessInvocation(
                    program="harness", arguments=[], prompt=PROMPT
                )
            ),
            paths=compose_round_paths(worktree=worktree, directory=occupied / "1"),
            plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
            clock=pinned,
        )

    assert harness.calls == []


def test_a_round_that_cannot_record_its_start_does_not_run_on(
    fake, worktree, directory
):
    fake(program="harness").streams(lines=[Line(text="working\n")], delay=5)
    # A directory where the record goes, so the prompt lands and the record
    # cannot, which is what leaves a child running with nothing to find it by.
    (directory / AGENT_ROUND_RECORD_NAME).mkdir(parents=True)

    with pytest.raises(ReportableError, match=r"round\.json"):
        AgentRound(
            harness=round_harness(
                invocation=HarnessInvocation(
                    program="harness", arguments=[], prompt=PROMPT
                )
            ),
            paths=compose_round_paths(worktree=worktree, directory=directory),
            plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
            clock=pinned,
        )


def test_a_round_a_straggler_outlives_still_records_an_ending(
    worktree, directory, straggler
):
    running = AgentRound(
        harness=round_harness(
            invocation=HarnessInvocation(
                program=sys.executable,
                arguments=["-c", LEAVES_A_STRAGGLER, str(straggler)],
                prompt=PROMPT,
            )
        ),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )

    assert within(seconds=30, holds=lambda: not running.is_alive)
    assert written(path=running.paths.record) == AgentRoundRecord(
        started=PINNED,
        pid=running.harness_process.pid,
        number=1,
        purpose=PURPOSE,
        is_recovery=False,
        ending=compose_agent_round_ending(at=PINNED, status=0),
    )


def test_a_finished_round_a_straggler_outlives_still_records_an_ending(
    monkeypatch, worktree, directory, straggler
):
    monkeypatch.setattr(
        "dreamcatcher.agent_rounds.FINAL_OUTPUT_CAPTURE_TIMEOUT_SECONDS", 0.01
    )
    paths = compose_round_paths(worktree=worktree, directory=directory)
    finish_round = Mock()
    running = AgentRound(
        harness=round_harness(
            invocation=HarnessInvocation(
                program=sys.executable,
                arguments=["-c", LEAVES_A_STRAGGLER, str(straggler)],
                prompt=PROMPT,
            ),
        ),
        paths=paths,
        plan=AgentRoundPlan(purpose=AgentRoundPurpose.DISCUSS, is_recovery=False),
        finish_round=finish_round,
        clock=pinned,
    )

    assert within(seconds=30, holds=lambda: not running.is_alive)
    assert written(path=paths.record).outcome is AgentRoundOutcome.SUCCESSFUL
    finish_round.assert_called_once_with(final_output=None)


def test_a_round_a_straggler_outlives_still_stops(worktree, directory, straggler):
    running = AgentRound(
        harness=round_harness(
            invocation=HarnessInvocation(
                program=sys.executable,
                arguments=["-c", LEAVES_A_STRAGGLER + AND_WAITS, str(straggler)],
                prompt=PROMPT,
            )
        ),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    assert within(seconds=30, holds=straggler.exists)

    # On its own thread, because a stop that waited on the straggler would
    # hang the suite rather than fail this test.
    stopping = Thread(target=running.stop, daemon=True)
    stopping.start()
    stopping.join(30)

    assert not stopping.is_alive()
    assert not running.is_alive
    assert written(path=running.paths.record).outcome is AgentRoundOutcome.INTERRUPTED


def test_recording_interruption_again_keeps_a_terminal_record(tmp_path):
    record = AgentRoundRecord(
        number=1,
        purpose=PURPOSE,
        started=PINNED,
        pid=1,
        ending=InterruptedAgentRoundEnding(),
    )
    path = tmp_path / "round.json"

    reconciled = record_agent_round_interruption(record=record, path=path)

    assert reconciled is record
    assert not path.exists()
