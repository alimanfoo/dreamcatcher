import sys
from pathlib import Path

import pytest
from fakes import Line, Stream, install

from dreamcatcher.commands import CommandError, _quote, locate, run, spawn


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


# Only Windows searches the current directory for a program, so only Windows
# shows what taking that directory out of the search is worth. This test sits
# here even so, where every platform runs it.
def test_a_program_in_the_current_directory_alone_is_not_found(tmp_path, monkeypatch):
    install(tmp_path, "probe")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(CommandError, match="not on the PATH"):
        locate("probe")


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
    assert child.wait() == 0


# The quoting is Windows's answer, and only Windows shows what it is worth. So
# these read it here, where every platform runs them.
def test_a_quoted_part_hides_what_a_second_reader_would_act_on():
    assert _quote("effort=high&low") == '"effort=high&low"'


def test_a_quote_in_a_part_is_doubled():
    assert _quote('say "done"') == '"say ""done"""'


def test_a_part_ending_in_a_backslash_does_not_escape_its_closing_quote():
    assert _quote("C:\\repo\\") == '"C:\\repo\\\\"'


def test_a_backslash_before_a_quote_is_doubled_so_the_quote_still_counts():
    assert _quote('C:\\repo\\"done"') == '"C:\\repo\\\\""done"""'
