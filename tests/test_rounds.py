import sys
from contextlib import suppress
from threading import Thread
from time import monotonic, sleep
from typing import cast

import psutil
import pytest
from clocks import PINNED
from conftest import FIXTURES
from fakes import Line, Stream, recorded
from recordings import rendered

from dreamcatcher.adapters import Adapter, Launch
from dreamcatcher.claude import CLAUDE
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import Event, Note, Renderer
from dreamcatcher.rounds import Ending, Round, RoundRecord, Workspace

# A round that listed a directory, read a file that was not there, and sent a
# subagent to count the files. Its golden feed is asserted in test_recordings.
RECORDING = FIXTURES / "claude" / "round.jsonl"

STAMP = "2026-08-19T18:41:58Z"

# What the tests here say woke every round they run.
CAUSE = "dispatched"

# A harness that leaves a process behind holding the round's own streams, and
# says in the file it is passed which process that is. The streams are handed
# down by name, because Windows passes a child no handle it was not given. The
# process it leaves starts a session of its own, so on POSIX it is out of the
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


class Unrenderable(Adapter):
    """An adapter whose events hold what the feed has no way to write."""

    program = "harness"

    def first_round(self, launch: Launch) -> list[str]:
        return [self.program]

    def resume(self, launch: Launch) -> list[str]:
        return [self.program]

    def _events(self, streamed: dict) -> list[Event]:
        # A real harness can send a path or a command as something other than
        # text, and the renderer cannot write an event that holds one.
        return [Note("read", cast("str", streamed))]


@pytest.fixture
def worktree(tmp_path):
    """The directory a round runs in, standing in for a session's worktree."""
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


def written(path):
    """Return what the round recorded about itself."""
    return RoundRecord.model_validate_json(path.read_text(encoding="utf-8"))


def within(seconds, holds):
    """Wait up to seconds for holds to answer true, and say whether it did."""
    deadline = monotonic() + seconds
    while not holds() and monotonic() < deadline:
        sleep(0.05)
    return holds()


def test_a_round_runs_the_command_it_was_given_in_the_worktree(
    fake, worktree, directory
):
    harness = fake("harness")
    harness.replies("")

    Round(
        CLAUDE,
        ["harness", "--print"],
        Workspace(worktree, directory),
        CAUSE,
        clock=pinned,
    ).wait()

    assert harness.calls[0].arguments == ["--print"]
    assert harness.calls[0].directory == worktree.resolve()


def test_the_feed_a_round_writes_is_the_feed_its_stream_renders_as(
    fake, worktree, directory
):
    fake("harness").streams(recorded(RECORDING))

    running = Round(
        CLAUDE, ["harness"], Workspace(worktree, directory), CAUSE, clock=pinned
    )
    running.wait()

    assert running.feed.read_text(encoding="utf-8") == rendered(
        CLAUDE,
        RECORDING.read_text(encoding="utf-8").splitlines(),
        Renderer(worktree, clock=pinned),
    )


def test_a_round_keeps_the_harnesss_own_stream_as_it_arrived(fake, worktree, directory):
    fake("harness").streams(recorded(RECORDING))

    running = Round(
        CLAUDE, ["harness"], Workspace(worktree, directory), CAUSE, clock=pinned
    )
    running.wait()

    assert running.raw.read_text(encoding="utf-8") == RECORDING.read_text(
        encoding="utf-8"
    )


def test_what_the_harness_says_on_stderr_lands_where_it_happened(
    fake, worktree, directory
):
    fake("harness").streams(
        [Line("first\n"), Line("an aside\n", Stream.ERR), Line("second\n")],
        # The two streams reach the round on threads of their own, so the space
        # between the lines is what puts them in a known order.
        delay=0.25,
    )

    running = Round(
        CLAUDE, ["harness"], Workspace(worktree, directory), CAUSE, clock=pinned
    )
    running.wait()

    assert running.feed.read_text(encoding="utf-8").splitlines() == [
        f"{STAMP}  first",
        f"{STAMP}  an aside",
        f"{STAMP}  second",
    ]
    assert running.raw.read_text(encoding="utf-8") == "first\nsecond\n"


def test_a_line_the_feed_cannot_write_costs_that_line_alone(fake, worktree, directory):
    fake("harness").streams([Line('{"said": "hello"}\n'), Line("plain\n")])

    running = Round(
        Unrenderable(), ["harness"], Workspace(worktree, directory), CAUSE, clock=pinned
    )
    running.wait()

    assert running.feed.read_text(encoding="utf-8").splitlines() == [
        f'{STAMP}  {{"said": "hello"}}',
        f"{STAMP}  plain",
    ]


def test_a_round_says_when_it_started_what_caused_it_and_what_process_it_is(
    fake, worktree, directory
):
    fake("harness").streams([Line("working\n"), Line("still working\n")], delay=5)

    running = Round(
        CLAUDE, ["harness"], Workspace(worktree, directory), CAUSE, clock=pinned
    )

    assert running.is_alive
    assert written(running.record) == RoundRecord(
        started=PINNED, pid=running.child.pid, cause=CAUSE
    )

    running.stop()


def test_a_round_that_finished_says_how_it_ended(fake, worktree, directory):
    fake("harness").streams([Line("giving up\n")], status=2)

    running = Round(
        CLAUDE, ["harness"], Workspace(worktree, directory), CAUSE, clock=pinned
    )
    running.wait()

    assert not running.is_alive
    assert written(running.record) == RoundRecord(
        started=PINNED,
        pid=running.child.pid,
        cause=CAUSE,
        ending=Ending(at=PINNED, status=2),
    )


def test_a_round_somebody_stopped_says_no_ending(fake, worktree, directory):
    fake("harness").streams([Line("working\n"), Line("still working\n")], delay=5)

    running = Round(
        CLAUDE, ["harness"], Workspace(worktree, directory), CAUSE, clock=pinned
    )
    running.stop()

    assert not running.is_alive
    assert written(running.record).ending is None


def test_a_round_that_cannot_write_its_feed_stops_rather_than_stalls(
    fake, worktree, directory
):
    fake("harness").streams([Line("first\n"), Line("second\n")], delay=0.25)
    directory.mkdir(parents=True)
    (directory / "feed.txt").mkdir()

    running = Round(
        CLAUDE, ["harness"], Workspace(worktree, directory), CAUSE, clock=pinned
    )
    running.wait()

    assert not running.is_alive
    assert written(running.record).ending is None


def test_a_round_that_cannot_record_its_start_does_not_run_on(fake, worktree, tmp_path):
    fake("harness").streams([Line("working\n")], delay=5)
    occupied = tmp_path / "occupied"
    occupied.write_text("something else is here\n", encoding="utf-8")

    with pytest.raises(ReportableError, match="cannot write"):
        Round(
            CLAUDE,
            ["harness"],
            Workspace(worktree, occupied / "1"),
            CAUSE,
            clock=pinned,
        )


def test_a_round_a_straggler_outlives_still_records_an_ending(
    worktree, directory, straggler
):
    running = Round(
        CLAUDE,
        [sys.executable, "-c", LEAVES_A_STRAGGLER, str(straggler)],
        Workspace(worktree, directory),
        CAUSE,
        clock=pinned,
    )

    assert within(30, lambda: not running.is_alive)
    assert written(running.record) == RoundRecord(
        started=PINNED,
        pid=running.child.pid,
        cause=CAUSE,
        ending=Ending(at=PINNED, status=0),
    )


def test_a_round_a_straggler_outlives_still_stops(worktree, directory, straggler):
    running = Round(
        CLAUDE,
        [sys.executable, "-c", LEAVES_A_STRAGGLER + AND_WAITS, str(straggler)],
        Workspace(worktree, directory),
        CAUSE,
        clock=pinned,
    )
    assert within(30, straggler.exists)

    # On its own thread, because a stop that waited on the straggler would
    # hang the suite rather than fail this test.
    stopping = Thread(target=running.stop, daemon=True)
    stopping.start()
    stopping.join(30)

    assert not stopping.is_alive()
    assert not running.is_alive
    assert written(running.record).ending is None
