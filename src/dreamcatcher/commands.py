"""Run the external commands dreamcatcher shells out to."""

import subprocess
from pathlib import Path
from shutil import which

from dreamcatcher.errors import DreamcatcherError


class CommandError(DreamcatcherError):
    """A command dreamcatcher ran is not there, or it failed."""


def run(program: str, *arguments: str, cwd: Path | None = None) -> str:
    """Return what the command wrote to stdout, reading it as UTF-8.

    Raise CommandError when the program is not on the PATH, naming the program.
    Raise it again when the program exits with a failing status, this time
    naming the command, the status, and everything the program said on stderr.
    A byte that is not UTF-8 comes through as the replacement character, so a
    stray byte in a path or a message never turns into a traceback.

    This looks the program up on the PATH before it runs it, which is also what
    lets a test stand in for it: the lookup takes every extension PATHEXT names,
    while Windows itself only ever adds .exe to a bare name. Windows runs a .cmd
    or .bat through cmd.exe, which reads the arguments again, and Python quotes
    them for a C program rather than for cmd. git and gh are real executables,
    so nothing here meets that. A harness CLI that npm installed is a .cmd, so
    the phase that runs one has to answer for it.
    """
    executable = which(program)
    if executable is None:
        raise CommandError(f"{program} is not on the PATH.")
    finished = subprocess.run(
        [executable, *arguments],
        capture_output=True,
        check=False,
        cwd=cwd,
        encoding="utf-8",
        errors="replace",
    )
    if finished.returncode != 0:
        command = " ".join([program, *arguments])
        said = finished.stderr.strip()
        ending = f": {said}" if said else "."
        raise CommandError(
            f"{command} failed with status {finished.returncode}{ending}"
        )
    return finished.stdout
