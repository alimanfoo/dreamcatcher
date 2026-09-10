import sys
from pathlib import Path

import pytest
from fakes import Line, Stream, install

from dreamcatcher.commands import (
    CommandError,
    _quote,
    locate,
    refuse_unquotable,
    run,
    spawn,
)


def test_a_command_hands_back_what_it_printed(fake):
    probe = fake(program="probe")
    probe.replies(stdout="what it said\n")

    assert run(program="probe", arguments=["--loudly"]) == "what it said\n"
    assert probe.calls[0].arguments == ["--loudly"]


def test_a_command_runs_where_it_is_told(fake, tmp_path):
    probe = fake(program="probe")
    probe.replies(stdout="")

    run(program="probe", arguments=[], cwd=tmp_path)

    assert probe.calls[0].directory == tmp_path.resolve()


def test_a_program_on_the_path_is_found(fake):
    fake(program="probe")

    assert Path(locate(program="probe")).stem == "probe"


# Only Windows searches the current directory for a program, so only Windows
# shows what taking that directory out of the search is worth. This test sits
# here even so, where every platform runs it.
def test_a_program_in_the_current_directory_alone_is_not_found(tmp_path, monkeypatch):
    install(directory=tmp_path, program="probe")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(CommandError, match="not on the PATH"):
        locate(program="probe")


def test_a_program_that_is_not_on_the_path_says_so():
    with pytest.raises(CommandError, match="not on the PATH"):
        locate(program="dreamcatcher-no-such-program")


def test_a_failure_carries_the_command_and_what_it_said(fake):
    probe = fake(program="probe")
    probe.fails(stderr="probe: nothing doing", status=128)

    with pytest.raises(CommandError) as error:
        run(program="probe", arguments=["--try"])

    assert str(error.value) == (
        "probe --try failed with status 128: probe: nothing doing"
    )


def test_a_failure_that_said_nothing_still_names_the_command(fake):
    probe = fake(program="probe")
    probe.fails(stderr="")

    with pytest.raises(CommandError) as error:
        run(program="probe", arguments=[])

    assert str(error.value) == "probe failed with status 1."


def test_a_command_that_prints_bytes_that_are_not_utf_8_still_reads():
    printing = "import sys; sys.stdout.buffer.write(b'caf\\xe9')"

    assert run(program=sys.executable, arguments=["-c", printing]) == "caf\ufffd"


def test_an_argument_a_second_reader_would_act_on_still_arrives_whole(fake):
    probe = fake(program="probe")
    probe.replies(stdout="")

    run(
        program="probe",
        arguments=["--prompt", 'say "done" & wait', "-c", "effort=high&low"],
    )

    assert probe.calls[0].arguments == [
        "--prompt",
        'say "done" & wait',
        "-c",
        "effort=high&low",
    ]


def test_a_spawned_command_runs_where_it_is_told_and_streams_as_it_goes(fake, tmp_path):
    probe = fake(program="probe")
    probe.streams(
        lines=[Line(text="what it said\n"), Line(text="an aside\n", stream=Stream.ERR)]
    )

    child = spawn(program="probe", arguments=["--loudly"], cwd=tmp_path)

    assert child.out.read() == "what it said\n"
    assert child.err.read() == "an aside\n"
    assert child.wait() == 0
    assert probe.calls[0].arguments == ["--loudly"]
    assert probe.calls[0].directory == tmp_path.resolve()


def test_a_spawned_command_reads_the_file_it_was_given_as_its_stdin(tmp_path):
    reading = "import sys; sys.stdout.write(f'read {sys.stdin.read()!r}')"
    holds = tmp_path / "prompt.txt"
    holds.write_bytes(b"do this\nthen 50% more")

    child = spawn(
        program=sys.executable, arguments=["-c", reading], cwd=tmp_path, stdin=holds
    )

    assert child.out.read() == "read 'do this\\nthen 50% more'"
    assert child.wait() == 0


def test_a_prompt_the_child_cannot_be_given_says_so(tmp_path):
    with pytest.raises(CommandError, match="cannot read"):
        spawn(
            program=sys.executable,
            arguments=["-c", "pass"],
            cwd=tmp_path,
            stdin=tmp_path / "gone.txt",
        )


def test_a_spawned_command_finds_its_stdin_already_at_an_end(tmp_path):
    reading = "import sys; sys.stdout.write(f'read {sys.stdin.read()!r}')"

    child = spawn(program=sys.executable, arguments=["-c", reading], cwd=tmp_path)

    assert child.out.read() == "read ''"
    assert child.wait() == 0


# The quoting and the refusal beside it are Windows's answer, and only Windows
# shows what either is worth. The tests that follow read both anyway, so they run
# on every platform.
def test_a_quoted_part_hides_what_a_second_reader_would_act_on():
    assert _quote(part="effort=high&low") == '"effort=high&low"'


def test_a_quote_in_a_part_is_doubled():
    assert _quote(part='say "done"') == '"say ""done"""'


def test_a_part_ending_in_a_backslash_does_not_escape_its_closing_quote():
    assert _quote(part="C:\\repo\\") == '"C:\\repo\\\\"'


def test_a_backslash_before_a_quote_is_doubled_so_the_quote_still_counts():
    assert _quote(part='C:\\repo\\"done"') == '"C:\\repo\\\\""done"""'


# One percent sign is enough, with nothing to close it, because npm's shim reads
# every argument again on a command line of its own.
def test_text_holding_a_percent_sign_is_refused():
    with pytest.raises(ValueError, match="cannot hold a percent sign"):
        refuse_unquotable("finish 50% of it")


def test_text_holding_a_newline_is_refused():
    with pytest.raises(ValueError, match="cannot hold a newline"):
        refuse_unquotable("do this\nthen that")


def test_text_holding_a_carriage_return_is_refused():
    with pytest.raises(ValueError, match="cannot hold a carriage return"):
        refuse_unquotable("do this\rthen that")


def test_text_holding_more_than_one_of_them_names_every_one():
    with pytest.raises(ValueError, match="cannot hold a percent sign or a newline"):
        refuse_unquotable("finish 50% of it\nthen stop")


def test_text_the_quoting_carries_comes_back_as_it_was():
    assert refuse_unquotable('say "done" & wait') == 'say "done" & wait'
