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

    assert run(program="harness", arguments=["--print"]) == STREAM
    assert harness.calls[0].arguments == ["--print"]


def test_a_stand_in_harness_streams_at_the_pace_it_was_given(fake, recording):
    fake("harness").streams(recording, delay=0.05)

    started = perf_counter()
    run(program="harness", arguments=[])

    assert perf_counter() - started >= len(recording) * 0.05


def test_a_stand_in_harness_writes_each_line_to_the_stream_it_names(fake):
    fake("harness").streams(
        [
            Line(text="first\n"),
            Line(text="an aside\n", stream=Stream.ERR),
            Line(text="second\n"),
        ]
    )

    assert run(program="harness", arguments=[]) == "first\nsecond\n"


def test_a_stand_in_harness_can_end_as_a_failed_round_does(fake, recording):
    fake("harness").streams(recording, status=2)

    with pytest.raises(CommandError, match="failed with status 2"):
        run(program="harness", arguments=[])


def test_a_stand_in_nobody_scripted_says_so(fake):
    fake("harness")

    with pytest.raises(CommandError, match="was not scripted"):
        run(program="harness", arguments=[])


def test_a_stand_in_answers_each_call_with_the_rule_that_call_opens(fake):
    gh = fake("gh")
    gh.replies("the repository\n", to="repo view")
    gh.replies("the listing\n", to="issue list")

    assert (
        run(program="gh", arguments=["repo", "view", "--json", "nameWithOwner"])
        == "the repository\n"
    )
    assert (
        run(program="gh", arguments=["issue", "list", "--state", "open"])
        == "the listing\n"
    )


def test_a_stand_in_prefers_the_rule_scripted_for_the_particular_call(fake):
    gh = fake("gh")
    gh.replies("anything\n")
    gh.replies("the blockers\n", to="api")

    assert run(program="gh", arguments=["api", "user"]) == "the blockers\n"
    assert run(program="gh", arguments=["repo", "view"]) == "anything\n"


def test_a_call_scripted_twice_answers_with_the_later_of_the_two(fake):
    gh = fake("gh")
    gh.replies("what it knew first\n", to="repo view")
    gh.replies("what it knows now\n", to="repo view")

    assert run(program="gh", arguments=["repo", "view"]) == "what it knows now\n"


def test_a_call_no_rule_answers_says_the_stand_in_was_not_scripted(fake):
    fake("gh").replies("the listing\n", to="issue list")

    with pytest.raises(CommandError, match="was not scripted"):
        run(program="gh", arguments=["repo", "view"])
