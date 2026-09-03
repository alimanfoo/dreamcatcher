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
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from time import sleep

UNSCRIPTED = 97


class Stream(StrEnum):
    """One of the two streams a stand-in can write a line to."""

    OUT = "stdout"
    ERR = "stderr"


@dataclass(frozen=True)
class Line:
    """One line a stand-in writes, and the stream it writes it to.

    A real harness writes most of what it has to say to stdout, and a warning
    or a complaint to stderr as it goes. So a scripted line says which stream
    it belongs to, and the two arrive in the order the script gives them.
    """

    text: str
    stream: Stream = Stream.OUT


@dataclass(frozen=True)
class Call:
    """One call a stand-in took: what it was passed, and where it ran."""

    arguments: list[str]
    directory: Path


@dataclass(frozen=True)
class Fake:
    """A stand-in for one program.

    A test scripts the answer once, and the stand-in gives that answer to every
    call. An answer is a list of lines, which covers both kinds of program the
    tests need: a tool that prints its result and exits, and a harness that
    streams a line at a time while it works.
    """

    base: Path

    def replies(self, stdout: str) -> None:
        """Answer this on stdout, with a status of zero."""
        self._answer([Line(stdout)])

    def fails(self, stderr: str, status: int = 1) -> None:
        """Fail with this on stderr, and a failing status."""
        self._answer([Line(stderr, Stream.ERR)], status=status)

    def streams(self, lines: list[Line], delay: float = 0, status: int = 0) -> None:
        """Answer with these lines, one at a time, as a harness does.

        The delay is what leaves a round running long enough to be interrupted.
        """
        self._answer(lines, status=status, delay=delay)

    @property
    def calls(self) -> list[Call]:
        """Every call the stand-in took, oldest first."""
        return [
            Call(taken["arguments"], Path(taken["directory"]))
            for taken in _lines(_taken(self.base))
        ]

    def _answer(self, lines: list[Line], status: int = 0, delay: float = 0) -> None:
        _scripted(self.base).write_text(
            json.dumps(
                {
                    "lines": [asdict(line) for line in lines],
                    "status": status,
                    "delay": delay,
                }
            ),
            encoding="utf-8",
        )


def recorded(path: Path) -> list[Line]:
    """Return the recording at path as the lines a harness streams to stdout."""
    return [
        Line(text)
        for text in path.read_text(encoding="utf-8").splitlines(keepends=True)
    ]


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
    for line in answer["lines"]:
        written = sys.stdout if line["stream"] == Stream.OUT else sys.stderr
        # UTF-8 whatever the console's own code page is, since the caller reads
        # it as UTF-8. Flushed too, so a reader sees each line as it lands.
        written.buffer.write(line["text"].encode("utf-8"))
        written.buffer.flush()
        sleep(answer["delay"])
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
