"""Run the external commands dreamcatcher shells out to.

This module also owns what the tool knows about cmd.exe, the second reader that
a command line meets on Windows, since a command line has to survive it.
"""

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
BATCH_ENDINGS = (".cmd", ".bat")

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
UNQUOTABLE = {
    "%": "a percent sign",
    "\n": "a newline",
    "\r": "a carriage return",
}


class CommandError(ReportableError):
    """A command dreamcatcher ran is not there, or it failed."""


@dataclass(frozen=True, kw_only=True)
class Child:
    """A program running as a child process, with both its streams on pipes.

    subprocess gives a child only the streams that the caller asked it for, so
    reading one means asking first whether it is there. This child always has
    both, so whoever reads them never has to ask.
    """

    out: IO[str]
    err: IO[str]
    process: subprocess.Popen[str]

    @property
    def pid(self) -> int:
        """The process id the operating system gave the child."""
        return self.process.pid

    @property
    def is_running(self) -> bool:
        """Whether the child is still running.

        The answer is no once somebody has waited for the child and collected
        the status it ended with. So a child that has ended, and that nobody
        has waited for yet, still reads as running.

        A caller acts on the answer a moment after asking for it, and the
        child can end in that moment, so an answer of yes can already be out
        of date.
        """
        return self.process.returncode is None

    def wait(self) -> int:
        """Wait for the child to end, and return the status that it ended with.

        Whatever the child started can outlive it, so the child's whole tree is
        ended here too, once the child itself has gone.
        """
        status = self.process.wait()
        teardown.end(pid=self.pid)
        return status

    def kill(self) -> None:
        """End the child, and everything that the child started, outright.

        A child that has gone leaves the operating system free to give its pid
        to somebody else, so this leaves it alone. `wait` does signal at that
        point, because there the two statements sit next to each other, while a
        kill can come long afterwards.
        """
        if self.is_running:
            teardown.end(pid=self.pid)


def refuse_unquotable(text: str, /) -> str:
    """Return text, or raise ValueError naming every character it cannot carry.

    Whoever reads text in from outside calls this, so the message can name where
    the text came from. A ValueError is what pydantic turns into that message.

    The message names every character it found, rather than the first, so the
    repo's owner fixes a setting once instead of once for each.

    pydantic is what calls this, as the validator behind `QuotableText`, and it
    passes the text positionally, so the parameter is positional-only.
    """
    found = [name for character, name in UNQUOTABLE.items() if character in text]
    if found:
        raise ValueError(
            f"cannot hold {' or '.join(found)}, because on Windows cmd.exe acts "
            "on the text rather than passing it to the harness"
        )
    return text


def locate(*, program: str) -> str:
    """Return the path to program on the PATH, or raise CommandError."""
    # Windows adds only .exe to a bare name, while a lookup takes every
    # extension PATHEXT names. So looking the program up here, rather than
    # leaving the name to subprocess, is what lets a test stand in for it.
    executable = which(program)
    if executable is None:
        raise CommandError(f"{program} is not on the PATH.")
    return executable


def run(*, program: str, arguments: Sequence[str], cwd: Path | None = None) -> str:
    """Return what the command wrote to stdout, reading it as UTF-8."""
    finished = subprocess.run(
        _build(program=program, arguments=arguments),
        capture_output=True,
        check=False,
        cwd=cwd,
        encoding="utf-8",
        # A stray byte that is not UTF-8, in a path or a message, comes through
        # as the replacement character rather than as a traceback.
        errors="replace",
    )
    if finished.returncode != 0:
        command = " ".join([program, *arguments])
        stderr = finished.stderr.strip()
        ending = f": {stderr}" if stderr else "."
        raise CommandError(
            f"{command} failed with status {finished.returncode}{ending}"
        )
    return finished.stdout


def spawn(
    *,
    program: str,
    arguments: Sequence[str],
    cwd: Path,
    stdin: Path | None = None,
) -> Child:
    """Start the program in cwd and hand it back while it runs.

    The daemon watches a round while it runs rather than waiting for it to
    finish, so this returns the running child, with each of its two streams on
    a pipe of its own and its output read as UTF-8.

    A harness reads its prompt from stdin, so the caller names the file holding
    it and the child reads that file. A pipe would have the daemon writing the
    prompt while the child read it, and a prompt longer than the pipe's own
    buffer would stall them both. So a file, rather than a pipe.

    A child named no file finds its stdin already at an end, so a harness
    waiting for the rest of a prompt waits no longer than that.
    """
    with ExitStack() as opening:
        reading = (
            opening.enter_context(_open_for_reading(path=stdin))
            if stdin is not None
            else subprocess.DEVNULL
        )
        started = subprocess.Popen(
            _build(program=program, arguments=arguments),
            cwd=cwd,
            stdin=reading,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            # A stray byte that is not UTF-8, in a path or a message, comes
            # through as the replacement character rather than as a traceback.
            errors="replace",
            start_new_session=teardown.OWN_SESSION,
        )
    teardown.contain(pid=started.pid)
    # This asked for both pipes above, so both are there. subprocess types them
    # for every caller, including the ones that asked for neither.
    return Child(
        out=cast("IO[str]", started.stdout),
        err=cast("IO[str]", started.stderr),
        process=started,
    )


def _open_for_reading(*, path: Path) -> IO[bytes]:
    """Return the file at path, open for a child to read, or raise CommandError.

    A file the tool cannot open is not a bug in the tool, and the user can act
    on it, so it reads as a message. The bytes go to the child as they are,
    which is what keeps a prompt's own line endings.
    """
    try:
        return path.open("rb")
    except OSError as error:
        raise CommandError(f"cannot read {path}: {error}.") from error


def _build(*, program: str, arguments: Sequence[str]) -> list[str] | str:
    """Return the command as subprocess has to be given it.

    A list, which subprocess quotes for the program's own reader. A batch file
    is the exception. Windows hands one to cmd.exe, which reads the line again
    under its own rules, and subprocess quotes for the second reader alone. So
    a batch file gets a line that this builds for both readers.
    """
    executable = locate(program=program)
    if PurePath(executable).suffix.lower() in BATCH_ENDINGS:  # pragma: no cover
        return " ".join(_quote(part=part) for part in (executable, *arguments))
    return [executable, *arguments]


def _quote(*, part: str) -> str:
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
