"""Run the external commands dreamcatcher shells out to.

Windows runs a .cmd or .bat through cmd.exe, which reads the arguments again,
and Python quotes them for a C program rather than for cmd. git and gh are real
executables, so nothing here meets that. A harness CLI that npm installed is a
.cmd, so the phase that runs one has to answer for it.
"""

import subprocess
from pathlib import Path
from shutil import which

from dreamcatcher.errors import DreamcatcherError


class CommandError(DreamcatcherError):
    """A command dreamcatcher ran is not there, or it failed."""


def locate(program: str) -> str:
    """Return the path to program on the PATH, or raise CommandError."""
    # Looking the program up, rather than leaving the name to subprocess, is
    # what lets a test stand in for it: the lookup takes every extension PATHEXT
    # names, while Windows itself only ever adds .exe to a bare name.
    executable = which(program)
    if executable is None:
        raise CommandError(f"{program} is not on the PATH.")
    return executable


def run(program: str, *arguments: str, cwd: Path | None = None) -> str:
    """Return what the command wrote to stdout, reading it as UTF-8."""
    finished = subprocess.run(
        [locate(program), *arguments],
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
