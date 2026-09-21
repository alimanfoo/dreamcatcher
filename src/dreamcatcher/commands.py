"""Run external commands and quote Windows batch-file arguments safely."""

import os
import subprocess
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePath
from shutil import which
from typing import IO, cast

from dreamcatcher import teardown
from dreamcatcher.errors import ReportableError

# Windows searches the current directory for a program ahead of the PATH, and
# the daemon's current directory is the watched checkout, so a file named git.exe
# or gh.cmd at that checkout's root would otherwise run in place of the real
# tool. NODEFAULTCURRENTDIRECTORYINEXEPATH takes the current directory back out
# of the search. Microsoft spells the name NoDefaultCurrentDirectoryInExePath,
# and Windows reads a name whatever its case. Windows checks whether the name is
# set and never reads its value. Every child inherits it, and a child that finds
# a program through Windows, through cmd.exe or through Python reads the PATH
# alone as well. macOS and Linux read the PATH alone already, and ignore the
# name.
os.environ["NODEFAULTCURRENTDIRECTORYINEXEPATH"] = "1"

# What npm calls the harness CLIs that it installs on Windows. Windows runs a file
# with one of these endings through cmd.exe, so its command line meets a second
# reader. git and gh are real executables, so neither ever meets that.
WINDOWS_BATCH_SUFFIXES = (".cmd", ".bat")

# What cmd.exe acts on wherever it sits, and what to call each one in a message.
# cmd.exe expands %NAME% on the line that it parses, inside double quotes as well
# as outside, and nothing on a command line escapes a percent sign. It reads a
# newline as the end of a statement, the way pressing Enter would. So quoting
# carries neither, and the tool refuses text holding one rather than let the text
# become something else.
#
# Any percent sign counts, not only a %NAME% pair, because npm's shim pastes
# every argument it was given into a command line of its own, where cmd.exe reads
# it a third time.
#
# A carriage return on its own is refused as the newline is. Reading a file turns
# every line ending into a newline, so this meets one only where a document wrote
# it as an escape, and one line of a prompt is what the author wrote either way.
UNQUOTABLE_CHARACTERS = {
    "%": "a percent sign",
    "\n": "a newline",
    "\r": "a carriage return",
}


class CommandError(ReportableError):
    """Report a failure preparing or running an external command."""


@dataclass(frozen=True, kw_only=True)
class ChildProcess:
    """Represent a running child process with stdout and stderr pipes."""

    out: IO[str]
    err: IO[str]
    process: subprocess.Popen[str]

    @property
    def pid(self) -> int:
        """The process identifier that the operating system assigned."""
        return self.process.pid

    @property
    def is_running(self) -> bool:
        """Whether nobody has collected the child's exit status yet.

        The answer is no once somebody has waited for the child and collected
        the status it ended with. So a child that has ended, and that nobody
        has waited for yet, still reads as running.

        The child can exit after this property returns, so a true result may
        already be stale when the caller acts on it.
        """
        return self.process.returncode is None

    def wait(self) -> int:
        """Wait for the child, end its contained process group, and return its status.

        Processes still contained with the child can outlive it, so its POSIX
        process group or Windows Job Object ends here after the child has gone.
        """
        status = self.process.wait()
        teardown.end_process_tree(pid=self.pid)
        return status

    def kill(self) -> None:
        """End the child's contained process group if it is still running.

        A child that has gone leaves the operating system free to give its pid
        to somebody else, so this leaves it alone. `wait` does signal at that
        point, because there the two statements sit next to each other, while a
        kill can come long afterwards.
        """
        if self.is_running:
            teardown.end_process_tree(pid=self.pid)


def refuse_unquotable(text: str, /) -> str:
    """Return text, or raise ValueError naming every character it cannot carry.

    The message names every character it found, rather than the first, so the
    user can fix every invalid character at once.

    pydantic is what calls this, as the validator behind `QuotableText`, and it
    passes the text positionally, so the parameter is positional-only.
    """
    unquotable_character_names = [
        name for character, name in UNQUOTABLE_CHARACTERS.items() if character in text
    ]
    if unquotable_character_names:
        raise ValueError(
            f"cannot hold {' or '.join(unquotable_character_names)}, because on "
            "Windows cmd.exe acts "
            "on the text rather than passing it to the harness"
        )
    return text


def locate_program(*, program: str) -> str:
    """Return the path to program on the PATH, or raise CommandError."""
    # Windows adds only .exe to a bare name, while a lookup takes every
    # extension PATHEXT names. So looking the program up here, rather than
    # leaving the name to subprocess, is what lets a test stand in for it.
    executable = which(program)
    if executable is None:
        raise CommandError(f"{program} is not on the PATH.")
    return executable


def run_command(
    *, program: str, arguments: Sequence[str], cwd: Path | None = None
) -> str:
    """Return what the command wrote to stdout, reading it as UTF-8."""
    completed_process = subprocess.run(
        _build_subprocess_command(program=program, arguments=arguments),
        capture_output=True,
        check=False,
        cwd=cwd,
        encoding="utf-8",
        # A stray byte that is not UTF-8, in a path or a message, comes through
        # as the replacement character rather than as a traceback.
        errors="replace",
    )
    if completed_process.returncode != 0:
        command = " ".join([program, *arguments])
        stderr = completed_process.stderr.strip()
        failure_suffix = f": {stderr}" if stderr else "."
        raise CommandError(
            f"{command} failed with status {completed_process.returncode}"
            f"{failure_suffix}"
        )
    return completed_process.stdout


def spawn_command(
    *,
    program: str,
    arguments: Sequence[str],
    cwd: Path,
    stdin: Path | None = None,
) -> ChildProcess:
    """Start the program in cwd and return it with UTF-8 output pipes.

    A harness reads its prompt from stdin, so the caller names the file holding
    it and the child reads that file. A pipe would have the daemon writing the
    prompt while the child read it, and a prompt longer than the pipe's own
    buffer would stall them both.

    A child named no file finds its stdin already at an end, so a harness
    waiting for the rest of a prompt waits no longer than that.
    """
    with ExitStack() as opening:
        stdin_stream = (
            opening.enter_context(_open_for_reading(path=stdin))
            if stdin is not None
            else subprocess.DEVNULL
        )
        process = subprocess.Popen(
            _build_subprocess_command(program=program, arguments=arguments),
            cwd=cwd,
            stdin=stdin_stream,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            # A stray byte that is not UTF-8, in a path or a message, comes
            # through as the replacement character rather than as a traceback.
            errors="replace",
            start_new_session=teardown.SHOULD_START_NEW_PROCESS_SESSION,
        )
    teardown.contain_process_tree(pid=process.pid)
    # This asked for both pipes above, so both are there. subprocess types them
    # for every caller, including the ones that asked for neither.
    return ChildProcess(
        out=cast("IO[str]", process.stdout),
        err=cast("IO[str]", process.stderr),
        process=process,
    )


def _open_for_reading(*, path: Path) -> IO[bytes]:
    """Return the file at path, open for a child to read, or raise CommandError.

    The bytes reach the child unchanged, which preserves the prompt's line
    endings.
    """
    try:
        return path.open("rb")
    except OSError as error:
        raise CommandError(f"cannot read {path}: {error}.") from error


def _build_subprocess_command(
    *, program: str, arguments: Sequence[str]
) -> list[str] | str:
    """Return the command in the form that subprocess requires.

    Most programs receive a list that subprocess quotes. Windows passes batch
    files through cmd.exe, so they receive a string quoted for both readers.
    """
    executable = locate_program(program=program)
    if (
        PurePath(executable).suffix.lower() in WINDOWS_BATCH_SUFFIXES
    ):  # pragma: no cover
        return " ".join(
            _quote_windows_argument(part=part) for part in (executable, *arguments)
        )
    return [executable, *arguments]


def _quote_windows_argument(*, part: str) -> str:
    """Return the part quoted so cmd.exe and then the program read it whole.

    The quotes are always there, so a character that cmd.exe acts on — an
    ampersand, a pipe, a bracket — sits inside them, where cmd.exe passes it
    through instead. A quote in the part itself is doubled, which is how the
    program's own reader takes it back as the one quote it was.

    A backslash means something to that reader only where a quote follows it,
    and there two of them stand for one. So a run of them before a quote is
    doubled, and the quote that closes the part counts as a quote. Left alone, a
    part ending in a backslash would escape its own closing quote, and every
    part after it would land inside the quotes of the part before.
    """
    quoted = ['"']
    backslashes = 0
    for character in part:
        if character == "\\":
            backslashes += 1
        elif character == '"':
            quoted.append("\\" * backslashes)
            backslashes = 0
        else:
            backslashes = 0
        quoted.append('""' if character == '"' else character)
    quoted.append("\\" * backslashes)
    quoted.append('"')
    return "".join(quoted)
