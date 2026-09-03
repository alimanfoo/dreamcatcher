import sys
from pathlib import Path

import pytest
from fakes import Line, Stream

from dreamcatcher.commands import CommandError, locate, run, spawn


def test_a_command_hands_back_what_it_printed(fake):
    probe = fake("probe")
    probe.replies("what it said\n")

    assert run("probe", "--loudly") == "what it said\n"
    assert probe.calls[0].arguments == ["--loudly"]


def test_a_command_runs_where_it_is_told(fake, tmp_path):
    probe = fake("probe")
    probe.replies("")

    run("probe", cwd=tmp_path)

    assert probe.calls[0].directory == tmp_path.resolve()


def test_a_program_on_the_path_is_found(fake):
    fake("probe")

    assert Path(locate("probe")).stem == "probe"


def test_a_program_that_is_not_on_the_path_says_so():
    with pytest.raises(CommandError, match="not on the PATH"):
        locate("dreamcatcher-no-such-program")


def test_a_failure_carries_the_command_and_what_it_said(fake):
    probe = fake("probe")
    probe.fails("probe: nothing doing", status=128)

    with pytest.raises(CommandError) as error:
        run("probe", "--try")

    assert str(error.value) == (
        "probe --try failed with status 128: probe: nothing doing"
    )


def test_a_failure_that_said_nothing_still_names_the_command(fake):
    probe = fake("probe")
    probe.fails("")

    with pytest.raises(CommandError) as error:
        run("probe")

    assert str(error.value) == "probe failed with status 1."


def test_a_command_that_prints_bytes_that_are_not_utf_8_still_reads():
    printing = "import sys; sys.stdout.buffer.write(b'caf\\xe9')"

    assert run(sys.executable, "-c", printing) == "caf\ufffd"


def test_an_argument_a_second_reader_would_act_on_still_arrives_whole(fake):
    probe = fake("probe")
    probe.replies("")

    run("probe", "--prompt", 'say "done" & wait', "-c", "effort=high&low")

    assert probe.calls[0].arguments == [
        "--prompt",
        'say "done" & wait',
        "-c",
        "effort=high&low",
    ]


def test_a_spawned_command_runs_where_it_is_told_and_streams_as_it_goes(fake, tmp_path):
    probe = fake("probe")
    probe.streams([Line("what it said\n"), Line("an aside\n", Stream.ERR)])

    child = spawn("probe", "--loudly", cwd=tmp_path)

    assert child.out.read() == "what it said\n"
    assert child.err.read() == "an aside\n"
    assert child.wait() == 0
    assert probe.calls[0].arguments == ["--loudly"]
    assert probe.calls[0].directory == tmp_path.resolve()


def test_a_spawned_command_finds_its_stdin_already_at_an_end(tmp_path):
    reading = "import sys; sys.stdout.write(f'read {sys.stdin.read()!r}')"

    child = spawn(sys.executable, "-c", reading, cwd=tmp_path)

    assert child.out.read() == "read ''"


def test_a_spawned_child_names_the_process_it_started(tmp_path):
    naming = "import os; print(os.getpid())"

    child = spawn(sys.executable, "-c", naming, cwd=tmp_path)

    assert int(child.out.read()) == child.pid
    assert child.wait() == 0
