"""Run the external commands dreamcatcher shells out to."""

import subprocess
from pathlib import Path, PurePath
from shutil import which

from dreamcatcher.errors import ReportableError

# What npm calls the harness CLIs it installs on Windows. Windows runs a file
# with one of these endings through cmd.exe, so its command line meets a second
# reader. git and gh are real executables, so neither ever meets that.
BATCH_ENDINGS = (".cmd", ".bat")


class CommandError(ReportableError):
    """A command dreamcatcher ran is not there, or it failed."""


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
        _built(program, arguments),
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


def _built(program: str, arguments: tuple[str, ...]) -> list[str] | str:
    """Return the command as subprocess has to be given it.

    A list, which subprocess quotes for the program's own reader. A batch file
    is the exception. Windows hands one to cmd.exe, which reads the line again
    under its own rules, and subprocess quotes for the second reader alone. So
    a batch file gets a line this builds for both readers.
    """
    executable = locate(program)
    if PurePath(executable).suffix.lower() in BATCH_ENDINGS:  # pragma: no cover
        return " ".join(_quoted(part) for part in (executable, *arguments))
    return [executable, *arguments]


def _quoted(part: str) -> str:  # pragma: no cover
    """Return the part quoted so cmd.exe and then the program read it whole.

    The quotes are always there, so a character cmd.exe acts on — an ampersand,
    a pipe, a bracket — sits inside them, where cmd.exe passes it through
    instead. A quote in the part itself is doubled, which is how the program's
    own reader takes it back as the one quote it was.
    """
    doubled = part.replace('"', '""')
    return f'"{doubled}"'
