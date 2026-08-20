"""Run the external commands dreamcatcher shells out to."""

import subprocess
from pathlib import Path
from shutil import which

from dreamcatcher.errors import DreamcatcherError


class CommandError(DreamcatcherError):
    """A command dreamcatcher ran is not there, or it failed."""


def run(program: str, *arguments: str, cwd: Path | None = None) -> str:
    """Return what the command wrote to stdout, reading it as UTF-8.

    Raise CommandError when the program is not on the PATH, or when it exits
    with a failing status. The message carries the command and everything the
    program said on stderr, so nobody has to guess what went wrong.

    This looks the program up on the PATH before it runs it, which is also what
    lets a test stand in for it. Windows only ever adds .exe to a bare name, so
    a stand-in with any other extension would go unfound.
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
    )
    if finished.returncode != 0:
        command = " ".join([program, *arguments])
        said = finished.stderr.strip()
        ending = f": {said}" if said else "."
        raise CommandError(
            f"{command} failed with status {finished.returncode}{ending}"
        )
    return finished.stdout
