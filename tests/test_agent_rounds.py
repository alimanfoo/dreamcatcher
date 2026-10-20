import json
import sys
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from typing import cast
from unittest.mock import Mock

import psutil
import pytest
from clocks import PINNED
from conftest import (
    FIXTURES,
    HEAD,
    HUNK,
    POSTED_BY,
    comment,
    gone,
    inline_comment,
    review,
    streamed,
)
from fakes import Line, Stream, recorded
from recordings import render_harness_recording

from dreamcatcher import agent_rounds
from dreamcatcher.agent_assignments import (
    AssignmentRoundInput,
)
from dreamcatcher.agent_rounds import (
    _AGENT_ROUND_RECORD_NAME,
    _STOP_REQUEST_POLL_INTERVAL_SECONDS,
    AgentRound,
    AgentRoundFinisher,
    AgentRoundLaunchError,
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    AgentRoundStartRequest,
    FinishingErroredAgentRoundEnding,
    HarnessErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    LaunchErroredAgentRoundEnding,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
    _AgentRoundHarness,
    _compose_agent_round_ending,
    interpret_agent_round_outcome,
    record_agent_round_interruption,
    record_agent_round_stop,
    request_agent_round_stop,
    start_agent_round,
)
from dreamcatcher.claude import CLAUDE_ADAPTER
from dreamcatcher.config import AgentHarness
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedNote, FeedRenderer
from dreamcatcher.github import (
    InlineReviewComment,
    IssueComment,
    PullRequestReview,
    PullRequestState,
)
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    AgentWorkKind,
    HarnessAdapter,
    HarnessConfigValue,
    HarnessInvocation,
    HarnessOutput,
)

# A round that listed a directory, read a file that was not there, and sent a
# subagent to count the files. Its golden feed is asserted in test_recordings.
RECORDING = FIXTURES / "claude" / "round.jsonl"

FEED_TIMESTAMP = "2026-08-19T18:41:58Z"

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

# A harness that exits cleanly once the file it is passed appears, so a test
# holds it at the point of exiting until the test is ready.
EXITS_WHEN_RELEASED = (
    "import pathlib, sys, time\n"
    "while not pathlib.Path(sys.argv[1]).exists():\n"
    "    time.sleep(0.01)\n"
)


def relay_nothing() -> None:
    """Prepare a round that has no input to relay."""


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
) -> _AgentRoundHarness:
    """Return the harness boundary used by one round test.

    A test that names no invocation runs the stand-in harness on the prompt.
    """
    return _AgentRoundHarness(
        adapter=adapter,
        invocation=invocation
        or HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        record_harness_session_identifier=record,
    )


class Unrenderable(HarnessAdapter):
    """An adapter whose events hold what the feed has no way to write."""

    program = "harness"
    sign_in_check_arguments = ()

    def build_plugin_installation(
        self, *, marketplace: str, plugin: str
    ) -> list[list[str]]:
        return []

    def build_new_session_round(
        self, *, request: AgentRoundLaunchRequest, final_output_path: Path
    ) -> HarnessInvocation:
        return HarnessInvocation(
            program=self.program, arguments=[], prompt=request.prompt
        )

    def build_resumed_round(
        self,
        *,
        request: AgentRoundLaunchRequest,
        harness_session_identifier: str,
        final_output_path: Path,
    ) -> HarnessInvocation:
        return HarnessInvocation(
            program=self.program, arguments=[], prompt=request.prompt
        )

    def build_hand_resume(
        self,
        *,
        model: str,
        effort: str,
        harness_config: Mapping[str, HarnessConfigValue],
        harness_session_identifier: str,
    ) -> list[str]:
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
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(
            invocation=HarnessInvocation(
                program="harness", arguments=["--print"], prompt=PROMPT
            )
        ),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    ).wait()

    assert harness.calls[0].arguments == ["--print"]
    assert harness.calls[0].directory == worktree.resolve()


def test_a_round_gives_the_harness_its_prompt_to_read(fake, worktree, directory):
    harness = fake(program="harness")
    harness.replies(stdout="")

    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )
    running.wait()

    assert harness.calls[0].prompt == PROMPT
    assert running.paths.prompt.read_text(encoding="utf-8") == PROMPT


def test_a_new_session_round_builds_its_harness_invocation(fake, worktree, directory):
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
            prepare_round=relay_nothing,
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
            prepare_round=relay_nothing,
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
        IssueComment.model_validate(comment()),
        PullRequestReview.model_validate(
            review(body="have a look", user={"login": POSTED_BY})
        ),
        InlineReviewComment.model_validate(inline_comment()),
    ]

    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=lambda: AssignmentRoundInput(
            pull_request_state=PullRequestState.OPEN,
            pull_request_head=HEAD,
            signals=[],
            user_posts=posts,
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
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
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
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
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
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(record=record),
        paths=paths,
        prepare_round=relay_nothing,
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
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
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
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(adapter=Unrenderable()),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )
    running.wait()

    assert running.paths.feed.read_text(encoding="utf-8").splitlines() == [
        f'{FEED_TIMESTAMP}  {{"said": "hello"}}',
        f"{FEED_TIMESTAMP}  plain",
    ]


def test_a_round_records_its_number_start_and_process(fake, worktree, directory):
    fake(program="harness").streams(
        lines=[Line(text="working\n"), Line(text="still working\n")], delay=5
    )

    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )

    assert running.is_alive
    record = written(path=running.paths.record)
    assert record == AgentRoundRecord(
        number=1,
        started=PINNED,
        pid=running.harness_process.pid,
    )
    assert record.outcome is AgentRoundOutcome.RUNNING

    running.interrupt()


def test_a_round_that_finished_says_how_it_ended(fake, worktree, directory):
    fake(program="harness").streams(lines=[Line(text="giving up\n")], status=2)

    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )
    running.wait()

    assert not running.is_alive
    record = written(path=running.paths.record)
    assert record == AgentRoundRecord(
        started=PINNED,
        pid=running.harness_process.pid,
        number=1,
        ending=_compose_agent_round_ending(at=PINNED, status=2),
    )
    assert record.outcome is AgentRoundOutcome.ERRORED


def stream_final_result(*, result: str) -> str:
    """Return stdout for a Claude round with one successful result event."""
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
    """Start a conversation round with a finishing step."""
    return start_agent_round(
        request=AgentRoundStartRequest(
            harness=AgentHarness.CLAUDE,
            launch_request=AgentRoundLaunchRequest(
                agent_work_identifier="GH9-20260819-184158-conversation",
                model="opus[1m]",
                effort="xhigh",
                prompt=PROMPT,
                work_kind=AgentWorkKind.CONVERSATION,
            ),
            harness_session_identifier=None,
            record_harness_session_identifier=ignore_harness_session_identifier,
            finish_round=finish_round,
            paths=paths,
            prepare_round=relay_nothing,
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


def test_a_round_discards_final_output_left_by_an_unrecorded_attempt(
    fake, worktree, directory
):
    fake(program="claude").replies(stdout="")
    paths = compose_round_paths(worktree=worktree, directory=directory)
    paths.final_output.parent.mkdir(parents=True)
    paths.final_output.write_bytes(b"stale answer")
    finish_round = Mock()

    start_conversation_round(paths=paths, finish_round=finish_round).wait()

    finish_round.assert_called_once_with(final_output=None)
    assert not paths.final_output.exists()


def test_a_finisher_that_fails_fails_the_round_and_says_why(fake, worktree, directory):
    fake(program="claude").replies(stdout=stream_final_result(result="The answer."))
    paths = compose_round_paths(worktree=worktree, directory=directory)
    finish_round = Mock(side_effect=ReportableError("could not post the answer on GH9"))

    start_conversation_round(paths=paths, finish_round=finish_round).wait()

    assert written(path=paths.record).ending == FinishingErroredAgentRoundEnding(
        at=PINNED, reason="could not post the answer on GH9"
    )
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
    worktree, directory, tmp_path
):
    release = tmp_path / "release"
    paths = compose_round_paths(worktree=worktree, directory=directory)
    finish_round = Mock()
    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158-conversation",
        harness=round_harness(
            invocation=HarnessInvocation(
                program=sys.executable,
                arguments=["-c", EXITS_WHEN_RELEASED, str(release)],
                prompt=PROMPT,
            )
        ),
        paths=paths,
        prepare_round=relay_nothing,
        finish_round=finish_round,
        clock=pinned,
    )

    # The race that `_end_process_tree` records: the harness exits cleanly just
    # as the daemon stops the round.
    running.forced_ending = InterruptedAgentRoundEnding()
    release.touch()
    running.wait()

    assert written(path=paths.record).outcome is AgentRoundOutcome.INTERRUPTED
    finish_round.assert_not_called()


@pytest.mark.parametrize(
    ("ending", "kind"),
    [
        pytest.param(
            {"status": None, "reason": "could not fetch main"},
            LaunchErroredAgentRoundEnding,
            id="launch",
        ),
        pytest.param(
            {"status": 2, "reason": None}, HarnessErroredAgentRoundEnding, id="harness"
        ),
        pytest.param(
            {"status": -9, "reason": None},
            HarnessErroredAgentRoundEnding,
            id="harness-signalled",
        ),
        pytest.param(
            {"status": 2, "reason": "git push failed"},
            HarnessErroredAgentRoundEnding,
            id="harness-with-reason",
        ),
        pytest.param(
            {"status": 0, "reason": "could not post the answer on GH9"},
            FinishingErroredAgentRoundEnding,
            id="finishing",
        ),
    ],
)
def test_a_saved_errored_ending_reads_as_its_kind_and_writes_back_unchanged(
    ending, kind
):
    saved = {
        "number": 1,
        "started": "2026-08-19T18:41:58Z",
        "pid": None,
        "ending": {"outcome": "errored", "at": "2026-08-19T18:42:58Z", **ending},
    }

    record = AgentRoundRecord.model_validate_json(json.dumps(saved))

    assert type(record.ending) is kind
    assert json.loads(record.model_dump_json()) == saved


@pytest.mark.parametrize("status", [None, 0])
def test_a_saved_errored_ending_refuses_a_missing_reason_without_a_failed_exit(
    status,
):
    saved = {
        "number": 1,
        "started": "2026-08-19T18:41:58Z",
        "ending": {
            "outcome": "errored",
            "at": "2026-08-19T18:42:58Z",
            "status": status,
        },
    }

    with pytest.raises(ValueError, match="reason"):
        AgentRoundRecord.model_validate_json(json.dumps(saved))


@pytest.mark.parametrize(
    "kind", [LaunchErroredAgentRoundEnding, FinishingErroredAgentRoundEnding]
)
def test_a_launch_or_finishing_failure_refuses_a_missing_reason(kind):
    with pytest.raises(ValueError, match="reason"):
        kind(at=PINNED)


def test_a_harness_failure_refuses_a_clean_exit_status():
    with pytest.raises(ValueError, match="nonzero exit status"):
        HarnessErroredAgentRoundEnding(at=PINNED, status=0)


def test_a_successful_ending_refuses_a_time_without_a_zone():
    with pytest.raises(ValueError, match="timezone info"):
        _compose_agent_round_ending(at=datetime(2026, 8, 19, 18, 41, 58), status=0)


@pytest.mark.parametrize("is_daemon_running", [True, False])
@pytest.mark.parametrize(
    "ending",
    [
        SuccessfulAgentRoundEnding(at=PINNED),
        HarnessErroredAgentRoundEnding(at=PINNED, status=2),
        InterruptedAgentRoundEnding(),
        StoppedAgentRoundEnding(at=PINNED),
    ],
)
def test_a_recorded_ending_keeps_its_outcome(ending, is_daemon_running):
    record = AgentRoundRecord(number=1, started=PINNED, ending=ending)

    assert (
        interpret_agent_round_outcome(
            record=record, is_daemon_running=is_daemon_running
        )
        is ending.outcome
    )


@pytest.mark.parametrize(
    ("is_daemon_running", "outcome"),
    [
        (True, AgentRoundOutcome.RUNNING),
        (False, AgentRoundOutcome.INTERRUPTED),
    ],
)
def test_a_round_with_no_ending_runs_only_while_a_daemon_runs_it(
    is_daemon_running, outcome
):
    record = AgentRoundRecord(number=1, started=PINNED)

    assert (
        interpret_agent_round_outcome(
            record=record, is_daemon_running=is_daemon_running
        )
        is outcome
    )
    assert record.outcome is AgentRoundOutcome.RUNNING


def test_interrupting_a_round_records_interruption(fake, worktree, directory):
    fake(program="harness").streams(
        lines=[Line(text="working\n"), Line(text="still working\n")], delay=5
    )

    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )
    running.interrupt()

    assert not running.is_alive
    assert written(path=running.paths.record).outcome is AgentRoundOutcome.INTERRUPTED


def test_daemon_shutdown_honours_a_pending_stop_request(fake, worktree, directory):
    fake(program="harness").streams(
        lines=[Line(text="working\n"), Line(text="still working\n")], delay=5
    )
    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )
    request_agent_round_stop(paths=running.paths)

    running.end_for_daemon_shutdown()

    assert written(path=running.paths.record).outcome is AgentRoundOutcome.STOPPED


def test_the_daemon_stopping_a_finished_round_keeps_its_ending(
    fake, worktree, directory
):
    fake(program="harness").streams(lines=[Line(text="done\n")])

    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )
    running.wait()

    # The daemon stops every round it holds as it goes down, and one of them
    # can be a round that finished a moment before.
    running.end_for_daemon_shutdown()

    assert running.forced_ending is None
    record = written(path=running.paths.record)
    assert record.ending == _compose_agent_round_ending(at=PINNED, status=0)
    assert record.outcome is AgentRoundOutcome.SUCCESSFUL


def test_a_stop_request_stops_the_round_and_records_why(fake, worktree, directory):
    fake(program="harness").streams(
        lines=[Line(text="working\n"), Line(text="still working\n")], delay=5
    )
    paths = compose_round_paths(worktree=worktree, directory=directory)
    polls: list[float] = []

    def request_stop_on_the_second_poll(seconds: float, /) -> bool:
        """Let the first poll find nothing, and the second find the request."""
        polls.append(seconds)
        if len(polls) == 2:
            request_agent_round_stop(paths=paths)
        return False

    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=paths,
        prepare_round=relay_nothing,
        clock=pinned,
        wait_for_round_end=request_stop_on_the_second_poll,
    )
    running.wait()

    assert polls == [_STOP_REQUEST_POLL_INTERVAL_SECONDS] * 2
    assert running.paths.stop_request.read_text(encoding="utf-8") == ""
    assert not running.is_alive
    assert not running._stop_request_watcher.is_alive()
    assert written(path=running.paths.record).ending == StoppedAgentRoundEnding(
        at=PINNED
    )


def test_a_stop_requested_while_the_round_prepared_stops_it_at_once(
    fake, worktree, directory
):
    fake(program="harness").streams(lines=[Line(text="working\n")], delay=5)
    paths = compose_round_paths(worktree=worktree, directory=directory)
    polls: list[float] = []

    def request_stop() -> None:
        request_agent_round_stop(paths=paths)

    def count_poll(seconds: float, /) -> bool:
        polls.append(seconds)
        return False

    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=paths,
        prepare_round=request_stop,
        clock=pinned,
        wait_for_round_end=count_poll,
    )
    running.wait()

    assert polls == []
    assert written(path=paths.record).ending == StoppedAgentRoundEnding(at=PINNED)


def test_the_first_reason_for_ending_a_round_wins(fake, worktree, directory):
    fake(program="harness").streams(
        lines=[Line(text="working\n"), Line(text="still working\n")], delay=5
    )
    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )

    running._end_process_tree(ending=StoppedAgentRoundEnding(at=PINNED))
    running._end_process_tree(ending=InterruptedAgentRoundEnding())
    running.wait()

    assert written(path=running.paths.record).outcome is AgentRoundOutcome.STOPPED


def test_a_round_that_cannot_write_its_feed_stops_rather_than_stalls(
    fake, worktree, directory
):
    fake(program="harness").streams(
        lines=[Line(text="first\n"), Line(text="second\n")], delay=0.25
    )
    directory.mkdir(parents=True)
    (directory / "feed.txt").mkdir()

    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )
    running.wait()

    assert not running.is_alive
    assert written(path=running.paths.record).outcome is AgentRoundOutcome.INTERRUPTED


def test_a_round_that_cannot_write_its_prompt_errors_without_a_process(
    fake, worktree, directory
):
    harness = fake(program="harness")
    harness.replies(stdout="")
    paths = compose_round_paths(worktree=worktree, directory=directory)
    paths.prompt.mkdir(parents=True)

    with pytest.raises(
        ReportableError, match=r"^GH9-20260819-184158 round 1 errored: .*prompt\.txt"
    ):
        AgentRound(
            agent_work_identifier="GH9-20260819-184158",
            harness=round_harness(
                invocation=HarnessInvocation(
                    program="harness", arguments=[], prompt=PROMPT
                )
            ),
            paths=paths,
            prepare_round=relay_nothing,
            clock=pinned,
        )

    record = written(path=paths.record)
    assert record.pid is None
    assert isinstance(record.ending, LaunchErroredAgentRoundEnding)
    assert "prompt.txt" in record.ending.reason
    assert harness.calls == []


def test_a_round_whose_preparation_fails_errors_with_its_reason(
    fake, worktree, directory
):
    harness = fake(program="harness")
    harness.replies(stdout="")
    paths = compose_round_paths(worktree=worktree, directory=directory)

    def refuse_to_prepare() -> None:
        raise ReportableError("git push failed with status 1: hook refused")

    with pytest.raises(
        AgentRoundLaunchError,
        match=r"^GH9-20260819-184158 round 1 errored: git push failed",
    ) as raised:
        AgentRound(
            agent_work_identifier="GH9-20260819-184158",
            harness=round_harness(),
            paths=paths,
            prepare_round=refuse_to_prepare,
            clock=pinned,
        )

    assert raised.value.agent_work_identifier == "GH9-20260819-184158"
    assert raised.value.round_number == 1
    assert raised.value.reason == "git push failed with status 1: hook refused"
    assert written(path=paths.record) == AgentRoundRecord(
        number=1,
        started=PINNED,
        ending=LaunchErroredAgentRoundEnding(
            at=PINNED, reason="git push failed with status 1: hook refused"
        ),
    )
    assert not paths.prompt.exists()
    assert not paths.round_input.exists()
    assert harness.calls == []


def test_a_round_whose_harness_cannot_be_contained_errors_without_a_process(
    fake, worktree, directory, monkeypatch
):
    fake(program="harness").streams(lines=[Line(text="working\n")], delay=5)
    paths = compose_round_paths(worktree=worktree, directory=directory)

    def refuse(*, pid: int) -> None:
        raise OSError("Access is denied")

    monkeypatch.setattr("dreamcatcher.commands.teardown.contain_process_tree", refuse)

    with pytest.raises(AgentRoundLaunchError, match="Access is denied"):
        AgentRound(
            agent_work_identifier="GH9-20260819-184158",
            harness=round_harness(),
            paths=paths,
            prepare_round=relay_nothing,
            clock=pinned,
        )

    record = written(path=paths.record)
    assert record.pid is None
    assert isinstance(record.ending, LaunchErroredAgentRoundEnding)
    assert record.ending.reason.endswith("Access is denied.")


def test_a_round_whose_process_cannot_be_recorded_does_not_run_on(
    fake, worktree, directory, monkeypatch
):
    fake(program="harness").streams(lines=[Line(text="working\n")], delay=5)
    paths = compose_round_paths(worktree=worktree, directory=directory)
    spawned = []
    write_json = agent_rounds.write_json

    def refuse_a_record_with_a_process(*, document, path):
        if isinstance(document, AgentRoundRecord) and document.pid is not None:
            spawned.append(document.pid)
            raise ReportableError(f"cannot write {path}")
        write_json(document=document, path=path)

    monkeypatch.setattr(
        "dreamcatcher.agent_rounds.write_json", refuse_a_record_with_a_process
    )

    with pytest.raises(ReportableError, match=r"round\.json"):
        AgentRound(
            agent_work_identifier="GH9-20260819-184158",
            harness=round_harness(
                invocation=HarnessInvocation(
                    program="harness", arguments=[], prompt=PROMPT
                )
            ),
            paths=paths,
            prepare_round=relay_nothing,
            clock=pinned,
        )

    assert spawned
    assert within(seconds=30, holds=lambda: gone(pid=spawned[0]))
    assert written(path=paths.record).pid is None


def test_a_round_whose_process_cannot_be_recorded_ends_without_an_exit_status(
    fake, worktree, directory, monkeypatch
):
    fake(program="harness").streams(lines=[Line(text="working\n")], delay=5)
    paths = compose_round_paths(worktree=worktree, directory=directory)
    refused = []
    write_json = agent_rounds.write_json

    def refuse_the_first_record_with_a_process(*, document, path):
        if (
            isinstance(document, AgentRoundRecord)
            and document.pid is not None
            and not refused
        ):
            refused.append(document.pid)
            raise ReportableError(f"cannot write {path}")
        write_json(document=document, path=path)

    monkeypatch.setattr(
        "dreamcatcher.agent_rounds.write_json", refuse_the_first_record_with_a_process
    )

    with pytest.raises(AgentRoundLaunchError, match=r"cannot write .*round\.json"):
        AgentRound(
            agent_work_identifier="GH9-20260819-184158",
            harness=round_harness(
                invocation=HarnessInvocation(
                    program="harness", arguments=[], prompt=PROMPT
                )
            ),
            paths=paths,
            prepare_round=relay_nothing,
            clock=pinned,
        )

    ending = written(path=paths.record).ending
    assert refused
    assert isinstance(ending, LaunchErroredAgentRoundEnding)
    assert ending.reason.startswith("cannot write ")
    assert ending.status is None


def test_a_round_that_cannot_record_its_start_prepares_and_spawns_nothing(
    fake, worktree, directory
):
    harness = fake(program="harness")
    harness.replies(stdout="")
    # A directory where the record goes, so the round cannot begin.
    (directory / _AGENT_ROUND_RECORD_NAME).mkdir(parents=True)
    paths = compose_round_paths(worktree=worktree, directory=directory)

    with pytest.raises(ReportableError, match=r"round\.json"):
        AgentRound(
            agent_work_identifier="GH9-20260819-184158",
            harness=round_harness(
                invocation=HarnessInvocation(
                    program="harness", arguments=[], prompt=PROMPT
                )
            ),
            paths=paths,
            prepare_round=relay_nothing,
            clock=pinned,
        )

    assert not paths.prompt.exists()
    assert harness.calls == []


def test_a_round_a_straggler_outlives_still_records_an_ending(
    worktree, directory, straggler
):
    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(
            invocation=HarnessInvocation(
                program=sys.executable,
                arguments=["-c", LEAVES_A_STRAGGLER, str(straggler)],
                prompt=PROMPT,
            )
        ),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )

    assert within(seconds=30, holds=lambda: not running.is_alive)
    assert written(path=running.paths.record) == AgentRoundRecord(
        started=PINNED,
        pid=running.harness_process.pid,
        number=1,
        ending=_compose_agent_round_ending(at=PINNED, status=0),
    )


def test_a_finished_round_a_straggler_outlives_still_records_an_ending(
    monkeypatch, worktree, directory, straggler
):
    monkeypatch.setattr(
        "dreamcatcher.agent_rounds._FINAL_OUTPUT_CAPTURE_TIMEOUT_SECONDS", 0.01
    )
    paths = compose_round_paths(worktree=worktree, directory=directory)
    finish_round = Mock()
    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(
            invocation=HarnessInvocation(
                program=sys.executable,
                arguments=["-c", LEAVES_A_STRAGGLER, str(straggler)],
                prompt=PROMPT,
            ),
        ),
        paths=paths,
        prepare_round=relay_nothing,
        finish_round=finish_round,
        clock=pinned,
    )

    assert within(seconds=30, holds=lambda: not running.is_alive)
    assert written(path=paths.record).outcome is AgentRoundOutcome.SUCCESSFUL
    finish_round.assert_called_once_with(final_output=None)


def test_a_round_a_straggler_outlives_still_stops(worktree, directory, straggler):
    running = AgentRound(
        agent_work_identifier="GH9-20260819-184158",
        harness=round_harness(
            invocation=HarnessInvocation(
                program=sys.executable,
                arguments=["-c", LEAVES_A_STRAGGLER + AND_WAITS, str(straggler)],
                prompt=PROMPT,
            )
        ),
        paths=compose_round_paths(worktree=worktree, directory=directory),
        prepare_round=relay_nothing,
        clock=pinned,
    )
    assert within(seconds=30, holds=straggler.exists)

    # On its own thread, because a stop that waited on the straggler would
    # hang the suite rather than fail this test.
    stopping = Thread(target=running.interrupt, daemon=True)
    stopping.start()
    stopping.join(30)

    assert not stopping.is_alive()
    assert not running.is_alive
    assert written(path=running.paths.record).outcome is AgentRoundOutcome.INTERRUPTED


def test_recording_interruption_again_keeps_a_terminal_record(tmp_path):
    record = AgentRoundRecord(
        number=1,
        started=PINNED,
        pid=1,
        ending=InterruptedAgentRoundEnding(),
    )
    path = tmp_path / "round.json"

    reconciled = record_agent_round_interruption(record=record, path=path)

    assert reconciled is record
    assert not path.exists()


def test_recording_a_stop_again_keeps_a_terminal_record(tmp_path):
    record = AgentRoundRecord(
        number=1,
        started=PINNED,
        pid=1,
        ending=StoppedAgentRoundEnding(at=PINNED),
    )
    path = tmp_path / "round.json"

    reconciled = record_agent_round_stop(record=record, path=path, at=PINNED)

    assert reconciled is record
    assert not path.exists()
