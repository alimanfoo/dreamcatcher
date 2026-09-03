from time import perf_counter

import pytest
from fakes import Line, Stream, recorded

from dreamcatcher.commands import CommandError, run

# A stream a harness could have written, non-ASCII included, so a stand-in that
# guessed the console's own encoding would come back wrong.
STREAM = '{"type":"assistant","text":"café"}\n{"type":"result"}\n'


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "stream.jsonl"
    path.write_text(STREAM, encoding="utf-8")
    return recorded(path)


def test_a_stand_in_harness_replays_the_recording_it_was_given(fake, recording):
    harness = fake("harness")
    harness.streams(recording)

    assert run("harness", "--print") == STREAM
    assert harness.calls[0].arguments == ["--print"]


def test_a_stand_in_harness_streams_at_the_pace_it_was_given(fake, recording):
    fake("harness").streams(recording, delay=0.05)

    started = perf_counter()
    run("harness")

    assert perf_counter() - started >= len(recording) * 0.05


def test_a_stand_in_harness_writes_each_line_to_the_stream_it_names(fake):
    fake("harness").streams(
        [Line("first\n"), Line("an aside\n", Stream.ERR), Line("second\n")]
    )

    assert run("harness") == "first\nsecond\n"


def test_a_stand_in_harness_can_end_as_a_failed_round_does(fake, recording):
    fake("harness").streams(recording, status=2)

    with pytest.raises(CommandError, match="failed with status 2"):
        run("harness")


def test_a_stand_in_nobody_scripted_says_so(fake):
    fake("harness")

    with pytest.raises(CommandError, match="was not scripted"):
        run("harness")
