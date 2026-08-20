"""Stand-in executables the tests put first on the PATH, in place of a real tool.

A stand-in is a launcher the test writes into a directory it puts first on the
PATH. The launcher hands each call to the replayer in this file, which answers
it as the test scripted it and records what it was passed. Both halves live in
this one file, so the files they pass between them have one shape in one place.

Windows will not run a launcher with no extension, so the launcher is a .cmd
there. `dreamcatcher.commands` finds every program on the PATH before it runs
it, which is what makes a launcher of either kind reachable.
"""

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

UNSCRIPTED = 97


@dataclass(frozen=True)
class Call:
    """One call a stand-in took: what it was passed, and where it ran."""

    arguments: list[str]
    directory: Path


@dataclass(frozen=True)
class Fake:
    """A stand-in for one program.

    The test that installs it says what it answers, and it answers that to every
    call it takes.
    """

    base: Path

    def replies(self, output: str) -> None:
        """Answer output on stdout, and a status of nought."""
        self._answer(output, "", 0)

    def fails(self, said: str, status: int = 1) -> None:
        """Fail with said on stderr, and a failing status."""
        self._answer("", said, status)

    @property
    def calls(self) -> list[Call]:
        """Every call the stand-in took, oldest first."""
        return [
            Call(taken["arguments"], Path(taken["directory"]))
            for taken in _lines(_taken(self.base))
        ]

    def _answer(self, output: str, said: str, status: int) -> None:
        _scripted(self.base).write_text(
            json.dumps({"output": output, "said": said, "status": status}),
            encoding="utf-8",
        )


def install(directory: Path, program: str) -> Fake:
    """Return a stand-in for program, written into directory as a launcher."""
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / program
    _launcher(base)
    return Fake(base)


def replay(base: Path, arguments: list[str]) -> int:
    """Answer one call to the stand-in at base, as its test scripted it."""
    _append(_taken(base), {"arguments": arguments, "directory": str(Path.cwd())})
    scripted = _scripted(base)
    if not scripted.exists():
        sys.stderr.write(f"{base.name} was not scripted, and it was asked.\n")
        return UNSCRIPTED
    answer = json.loads(scripted.read_text(encoding="utf-8"))
    sys.stdout.write(answer["output"])
    sys.stderr.write(answer["said"])
    return int(answer["status"])


def _launcher(base: Path) -> None:
    """Write the launcher that hands a call to replay."""
    replayer = Path(__file__).resolve()
    if os.name == "nt":
        base.with_name(f"{base.name}.cmd").write_text(
            f'@echo off\n"{sys.executable}" "{replayer}" "{base}" %*\n'
            "exit /b %errorlevel%\n",
            encoding="utf-8",
        )
        return
    base.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{replayer}" "{base}" "$@"\n',
        encoding="utf-8",
    )
    base.chmod(base.stat().st_mode | stat.S_IXUSR)


def _scripted(base: Path) -> Path:
    """The file holding what the stand-in was scripted to answer."""
    return base.with_name(f"{base.name}.scripted.json")


def _taken(base: Path) -> Path:
    """The file holding the calls the stand-in took."""
    return base.with_name(f"{base.name}.taken.jsonl")


def _append(path: Path, line: dict) -> None:
    """Add one JSON line to the file at path."""
    with path.open("a", encoding="utf-8") as opened:
        opened.write(json.dumps(line) + "\n")


def _lines(path: Path) -> list[dict]:
    """Return the JSON lines the file at path holds, or none when it is not there."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    sys.exit(replay(Path(sys.argv[1]), sys.argv[2:]))
