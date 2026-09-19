import json
import sys
from contextlib import suppress
from threading import Thread
from time import monotonic, sleep
from typing import cast

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
)
from fakes import Line, Stream, recorded
from recordings import rendered

from dreamcatcher.agent_rounds import (
    RECORD,
    AgentRound,
    AgentRoundInput,
    AgentRoundOutputReader,
    AgentRoundPaths,
    AgentRoundPlan,
    AgentRoundPurpose,
    AgentRoundRecord,
    ErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    RoundOutcome,
    compose_agent_round_ending,
    record_agent_round_interruption,
)
from dreamcatcher.claude import CLAUDE
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import Note, Renderer
from dreamcatcher.github import (
    ConversationComment,
    InlineReviewComment,
    PullRequestReview,
    PullRequestState,
)
from dreamcatcher.harness_adapters import (
    AgentRoundLaunch,
    HarnessAdapter,
    HarnessInvocation,
    HarnessOutput,
)

# A round that listed a directory, read a file that was not there, and sent a
# subagent to count the files. Its golden feed is asserted in test_recordings.
RECORDING = FIXTURES / "claude" / "round.jsonl"

TIMESTAMP_FORMAT = "2026-08-19T18:41:58Z"

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
    harness_adapter: HarnessAdapter = CLAUDE,
    record=ignore_harness_session_identifier,
) -> AgentRoundOutputReader:
    """Return the harness boundary used by one round test."""
    return AgentRoundOutputReader(
        harness_adapter=harness_adapter,
        record_harness_session_identifier=record,
    )


class Unrenderable(HarnessAdapter):
    """An adapter whose events hold what the feed has no way to write."""

    program = "harness"

    def build_first_round(self, *, launch: AgentRoundLaunch) -> HarnessInvocation:
        return HarnessInvocation(
            program=self.program, arguments=[], prompt=launch.prompt
        )

    def build_resumed_round(
        self, *, launch: AgentRoundLaunch, harness_session_identifier: str
    ) -> HarnessInvocation:
        return HarnessInvocation(
            program=self.program, arguments=[], prompt=launch.prompt
        )

    def build_hand_resume(self, *, harness_session_identifier: str) -> list[str]:
        return [self.program]

    def _read(self, *, streamed: dict) -> HarnessOutput:
        # A real harness can send a path or a command as something other than
        # text, and the renderer cannot write an event that holds one.
        return HarnessOutput(events=[Note(label="read", detail=cast("str", streamed))])


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


def round_paths(*, worktree, directory) -> AgentRoundPaths:
    """Name the files of the numbered round at directory."""
    return AgentRoundPaths(
        worktree=worktree,
        rounds_directory=directory.parent,
        number=int(directory.name),
    )


def within(*, seconds, holds):
    """WaitForSeconds up to seconds for holds to answer true, and say whether it did."""
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
        output_reader=round_harness(),
        invocation=HarnessInvocation(
            program="harness", arguments=["--print"], prompt=PROMPT
        ),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    ).wait()

    assert harness.calls[0].arguments == ["--print"]
    assert harness.calls[0].directory == worktree.resolve()


def test_a_round_gives_the_harness_its_prompt_to_read(fake, worktree, directory):
    harness = fake(program="harness")
    harness.replies(stdout="")

    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert harness.calls[0].prompt == PROMPT
    assert running.paths.prompt.read_text(encoding="utf-8") == PROMPT


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
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(
            purpose=PURPOSE,
            is_recovery=False,
            input=AgentRoundInput(state=PullRequestState.OPEN, posts=posts),
        ),
        clock=pinned,
    )
    running.wait()

    read_back = json.loads(running.paths.inbox.read_text(encoding="utf-8"))
    assert read_back["state"] == "OPEN"
    assert [post["kind"] for post in read_back["posts"]] == [
        "comment",
        "review",
        "inlineComment",
    ]
    assert read_back["posts"][2]["diff_hunk"] == HUNK


def test_the_feed_a_round_writes_is_the_feed_its_stream_renders_as(
    fake, worktree, directory
):
    fake(program="harness").streams(lines=recorded(path=RECORDING))

    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert running.paths.feed.read_text(encoding="utf-8") == rendered(
        adapter=CLAUDE,
        lines=RECORDING.read_text(encoding="utf-8").splitlines(),
        renderer=Renderer(worktree=worktree, clock=pinned),
    )


def test_a_round_keeps_the_harnesss_own_stream_as_it_arrived(fake, worktree, directory):
    fake(program="harness").streams(lines=recorded(path=RECORDING))

    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert running.paths.raw.read_text(encoding="utf-8") == RECORDING.read_text(
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
    paths = round_paths(worktree=worktree, directory=directory)
    recorded = []

    def record(*, identifier: str) -> None:
        recorded.append((identifier, paths.raw.read_text(encoding="utf-8")))

    running = AgentRound(
        output_reader=round_harness(record=record),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
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
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert running.paths.feed.read_text(encoding="utf-8").splitlines() == [
        f"{TIMESTAMP_FORMAT}  first",
        f"{TIMESTAMP_FORMAT}  an aside",
        f"{TIMESTAMP_FORMAT}  second",
    ]
    assert running.paths.raw.read_text(encoding="utf-8") == "first\nsecond\n"


def test_a_line_the_feed_cannot_write_costs_that_line_alone(fake, worktree, directory):
    fake(program="harness").streams(
        lines=[Line(text='{"said": "hello"}\n'), Line(text="plain\n")]
    )

    running = AgentRound(
        output_reader=round_harness(harness_adapter=Unrenderable()),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert running.paths.feed.read_text(encoding="utf-8").splitlines() == [
        f'{TIMESTAMP_FORMAT}  {{"said": "hello"}}',
        f"{TIMESTAMP_FORMAT}  plain",
    ]


def test_a_round_records_its_number_purpose_recovery_and_process(
    fake, worktree, directory
):
    fake(program="harness").streams(
        lines=[Line(text="working\n"), Line(text="still working\n")], delay=5
    )

    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
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
        pid=running.child.pid,
    )
    assert record.outcome is RoundOutcome.RUNNING

    running.stop()


def test_a_round_that_finished_says_how_it_ended(fake, worktree, directory):
    fake(program="harness").streams(lines=[Line(text="giving up\n")], status=2)

    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=True),
        clock=pinned,
    )
    running.wait()

    assert not running.is_alive
    record = written(path=running.paths.record)
    assert record == AgentRoundRecord(
        started=PINNED,
        pid=running.child.pid,
        number=1,
        purpose=PURPOSE,
        is_recovery=True,
        ending=compose_agent_round_ending(at=PINNED, status=2),
    )
    assert record.outcome is RoundOutcome.ERRORED


def test_an_errored_ending_refuses_a_success_status():
    with pytest.raises(ValueError, match="cannot have exit status 0"):
        ErroredAgentRoundEnding(at=PINNED, status=0)


def test_a_round_somebody_stopped_records_interruption(fake, worktree, directory):
    fake(program="harness").streams(
        lines=[Line(text="working\n"), Line(text="still working\n")], delay=5
    )

    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.stop()

    assert not running.is_alive
    assert written(path=running.paths.record).outcome is RoundOutcome.INTERRUPTED


def test_a_round_stopped_after_it_finished_keeps_its_ending(fake, worktree, directory):
    fake(program="harness").streams(lines=[Line(text="done\n")])

    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
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
    assert record.outcome is RoundOutcome.SUCCESSFUL


def test_a_round_that_cannot_write_its_feed_stops_rather_than_stalls(
    fake, worktree, directory
):
    fake(program="harness").streams(
        lines=[Line(text="first\n"), Line(text="second\n")], delay=0.25
    )
    directory.mkdir(parents=True)
    (directory / "feed.txt").mkdir()

    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(program="harness", arguments=[], prompt=PROMPT),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )
    running.wait()

    assert not running.is_alive
    assert written(path=running.paths.record).outcome is RoundOutcome.INTERRUPTED


def test_a_round_that_cannot_write_its_prompt_never_starts(fake, worktree, tmp_path):
    harness = fake(program="harness")
    harness.replies(stdout="")
    occupied = tmp_path / "occupied"
    occupied.write_text("something else is here\n", encoding="utf-8")

    with pytest.raises(ReportableError, match=r"prompt\.txt"):
        AgentRound(
            output_reader=round_harness(),
            invocation=HarnessInvocation(
                program="harness", arguments=[], prompt=PROMPT
            ),
            paths=round_paths(worktree=worktree, directory=occupied / "1"),
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
    (directory / RECORD).mkdir(parents=True)

    with pytest.raises(ReportableError, match=r"round\.json"):
        AgentRound(
            output_reader=round_harness(),
            invocation=HarnessInvocation(
                program="harness", arguments=[], prompt=PROMPT
            ),
            paths=round_paths(worktree=worktree, directory=directory),
            plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
            clock=pinned,
        )


def test_a_round_a_straggler_outlives_still_records_an_ending(
    worktree, directory, straggler
):
    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(
            program=sys.executable,
            arguments=["-c", LEAVES_A_STRAGGLER, str(straggler)],
            prompt=PROMPT,
        ),
        paths=round_paths(worktree=worktree, directory=directory),
        plan=AgentRoundPlan(purpose=PURPOSE, is_recovery=False),
        clock=pinned,
    )

    assert within(seconds=30, holds=lambda: not running.is_alive)
    assert written(path=running.paths.record) == AgentRoundRecord(
        started=PINNED,
        pid=running.child.pid,
        number=1,
        purpose=PURPOSE,
        is_recovery=False,
        ending=compose_agent_round_ending(at=PINNED, status=0),
    )


def test_a_round_a_straggler_outlives_still_stops(worktree, directory, straggler):
    running = AgentRound(
        output_reader=round_harness(),
        invocation=HarnessInvocation(
            program=sys.executable,
            arguments=["-c", LEAVES_A_STRAGGLER + AND_WAITS, str(straggler)],
            prompt=PROMPT,
        ),
        paths=round_paths(worktree=worktree, directory=directory),
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
    assert written(path=running.paths.record).outcome is RoundOutcome.INTERRUPTED


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
