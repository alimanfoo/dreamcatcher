"""Run the external commands dreamcatcher shells out to."""

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePath
from shutil import which
from typing import IO, cast

from dreamcatcher import teardown
from dreamcatcher.errors import ReportableError

# What npm calls the harness CLIs that it installs on Windows. Windows runs a file
# with one of these endings through cmd.exe, so its command line meets a second
# reader. git and gh are real executables, so neither ever meets that.
BATCH_ENDINGS = (".cmd", ".bat")


class CommandError(ReportableError):
    """A command dreamcatcher ran is not there, or it failed."""


@dataclass(frozen=True)
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

    def wait(self) -> int:
        """Wait for the child to end, and return the status that it ended with."""
        status = self.process.wait()
        teardown.release(self.pid)
        return status

    def kill(self) -> None:
        """End the child, and everything that the child started, outright.

        A child already waited for has gone, and the operating system is free
        to give its pid to somebody else, so this leaves it alone.
        """
        if self.process.returncode is None:
            teardown.kill(self.pid)


def locate(program: str) -> str:
    """Return the path to program on the PATH, or raise CommandError."""
    # Windows adds only .exe to a bare name, while a lookup takes every
    # extension PATHEXT names. So looking the program up here, rather than
    # leaving the name to subprocess, is what lets a test stand in for it.
    executable = which(program)
    if executable is None:
        raise CommandError(f"{program} is not on the PATH.")
    return executable


def run(program: str, *arguments: str, cwd: Path | None = None) -> str:
    """Return what the command wrote to stdout, reading it as UTF-8."""
    finished = subprocess.run(
        _build(program, arguments),
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


def spawn(program: str, *arguments: str, cwd: Path) -> Child:
    """Start the program in cwd and hand it back while it runs.

    The daemon watches a round while it runs rather than waiting for it to
    finish, so this returns the running child, with each of its two streams on
    a pipe of its own and its output read as UTF-8.

    The child gets no stdin. Codex reads stdin for more of its prompt and waits
    for the end of it, so a pipe that the daemon held open would stall the round
    for ever, even with the whole prompt already in an argument.
    """
    started = subprocess.Popen(
        _build(program, arguments),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        # A stray byte that is not UTF-8, in a path or a message, comes through
        # as the replacement character rather than as a traceback.
        errors="replace",
        start_new_session=teardown.OWN_SESSION,
    )
    teardown.contain(started.pid)
    # This asked for both pipes above, so both are there. subprocess types them
    # for every caller, including the ones that asked for neither.
    return Child(
        cast("IO[str]", started.stdout), cast("IO[str]", started.stderr), started
    )


def _build(program: str, arguments: tuple[str, ...]) -> list[str] | str:
    """Return the command as subprocess has to be given it.

    A list, which subprocess quotes for the program's own reader. A batch file
    is the exception. Windows hands one to cmd.exe, which reads the line again
    under its own rules, and subprocess quotes for the second reader alone. So
    a batch file gets a line that this builds for both readers.
    """
    executable = locate(program)
    if PurePath(executable).suffix.lower() in BATCH_ENDINGS:  # pragma: no cover
        return " ".join(_quote(part) for part in (executable, *arguments))
    return [executable, *arguments]


def _quote(part: str) -> str:
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
