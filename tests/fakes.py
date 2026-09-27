"""Stand-in executables the tests put first on the PATH, in place of a real tool.

A stand-in is a launcher the test writes into a directory it puts first on the
PATH. The launcher hands each call to the replayer in this file, which answers
it as the test scripted it and records what it was passed. Both halves live in
this one file, so the files they pass between them have one shape in one place.

Windows will not run a launcher with no extension, so the launcher is a .cmd
there. `dreamcatcher.commands` finds every program on the PATH before it runs
it, which is what makes a launcher of either kind reachable.

Launchers start Python with `-S`, so this replayer stays standard-library-only.
That avoids loading an environment the stand-ins do not use on every call.
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


@dataclass(frozen=True, kw_only=True)
class Line:
    """One line a stand-in writes, and the stream it writes it to.

    A real harness writes most of what it has to say to stdout, and a warning
    or a complaint to stderr as it goes. So a scripted line says which stream
    it belongs to, and the two arrive in the order the script gives them.
    """

    text: str
    stream: Stream = Stream.OUT


@dataclass(frozen=True, kw_only=True)
class Call:
    """One call a stand-in took: what it was passed, where it ran, what it read.

    A harness reads its prompt from stdin, so what the stand-in read there is
    part of the call, and a test can ask for the prompt it was given.
    """

    arguments: list[str]
    directory: Path
    prompt: str


@dataclass(frozen=True, kw_only=True)
class Fake:
    """A stand-in for one program.

    An answer is a list of lines, which covers both kinds of program the tests
    need: a tool that prints its result and exits, and a harness that streams a
    line at a time while it works.

    Every scripting method takes the call it answers, as the words that call's
    arguments open with. A method given none of those words answers every call,
    which is all a test needs of a harness. A test scripts one answer per call
    where one program answers several, as `gh` does, and scripting the same
    call twice leaves the later answer standing.
    """

    base: Path

    def replies(self, *, stdout: str, to: str = "") -> None:
        """Answer this on stdout, with a status of zero."""
        self._answer(lines=[Line(text=stdout)], to=to)

    def fails(self, *, stderr: str, status: int = 1, to: str = "") -> None:
        """Fail with this on stderr, and a failing status."""
        self._answer(lines=[Line(text=stderr, stream=Stream.ERR)], status=status, to=to)

    def streams(
        self, *, lines: list[Line], delay: float = 0, status: int = 0, to: str = ""
    ) -> None:
        """Answer with these lines, one at a time, as a harness does.

        The delay is what leaves a round running long enough to be interrupted.
        """
        self._answer(lines=lines, status=status, delay=delay, to=to)

    @property
    def calls(self) -> list[Call]:
        """Every call the stand-in took, oldest first."""
        return [
            Call(
                arguments=taken["arguments"],
                directory=Path(taken["directory"]),
                prompt=taken["prompt"],
            )
            for taken in _lines(path=_taken(base=self.base))
        ]

    def _answer(
        self, *, lines: list[Line], status: int = 0, delay: float = 0, to: str = ""
    ) -> None:
        _append(
            path=_scripted(base=self.base),
            line={
                "when": to.split(),
                "lines": [asdict(line) for line in lines],
                "status": status,
                "delay": delay,
            },
        )


def recorded(*, path: Path) -> list[Line]:
    """Return the recording at path as the lines a harness streams to stdout."""
    return [
        Line(text=text)
        for text in path.read_text(encoding="utf-8").splitlines(keepends=True)
    ]


def install(*, directory: Path, program: str) -> Fake:
    """Return a stand-in for program, written into directory as a launcher."""
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / program
    _launcher(base=base)
    return Fake(base=base)


def replay(*, base: Path, arguments: list[str]) -> int:
    """Answer one call to the stand-in at base, as its test scripted it."""
    # UTF-8 whatever the console's own code page is, since whoever wrote the
    # prompt wrote it as UTF-8.
    _append(
        path=_taken(base=base),
        line={
            "arguments": arguments,
            "directory": str(Path.cwd()),
            "prompt": sys.stdin.buffer.read().decode("utf-8"),
        },
    )
    answer = _scripted_for(base=base, arguments=arguments)
    if answer is None:
        sys.stderr.write(f"{base.name} was not scripted, and it was asked.\n")
        return UNSCRIPTED
    for line in answer["lines"]:
        written = sys.stdout if line["stream"] == Stream.OUT else sys.stderr
        # UTF-8 whatever the console's own code page is, since the caller reads
        # it as UTF-8. Flushed too, so a reader sees each line as it lands.
        written.buffer.write(line["text"].encode("utf-8"))
        written.buffer.flush()
        sleep(answer["delay"])
    return int(answer["status"])


def _launcher(*, base: Path) -> None:
    """Write the launcher that hands a call to replay."""
    replayer = Path(__file__).resolve()
    if os.name == "nt":
        base.with_name(f"{base.name}.cmd").write_text(
            f'@echo off\n"{sys.executable}" -S "{replayer}" "{base}" %*\n'
            "exit /b %errorlevel%\n",
            encoding="utf-8",
        )
        return
    base.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -S "{replayer}" "{base}" "$@"\n',
        encoding="utf-8",
    )
    base.chmod(base.stat().st_mode | stat.S_IXUSR)


def _scripted(*, base: Path) -> Path:
    """The file holding what the stand-in was scripted to answer, a rule a line."""
    return base.with_name(f"{base.name}.scripted.jsonl")


def _scripted_for(*, base: Path, arguments: list[str]) -> dict | None:
    """Return the rule answering this call, or none when no rule answers it.

    A rule answers a call whose arguments open with the rule's own words, and
    the longest such rule wins. So a test can script a general answer and a
    particular one without minding which it scripts first.

    Between two rules of the same length, the one scripted last wins, so a test
    can script over an answer a fixture already gave.
    """
    answering = [
        rule
        for rule in reversed(_lines(path=_scripted(base=base)))
        if arguments[: len(rule["when"])] == rule["when"]
    ]
    if not answering:
        return None
    return max(answering, key=lambda rule: len(rule["when"]))


def _taken(*, base: Path) -> Path:
    """The file holding the calls the stand-in took."""
    return base.with_name(f"{base.name}.taken.jsonl")


def _append(*, path: Path, line: dict) -> None:
    """Add one JSON line to the file at path."""
    with path.open("a", encoding="utf-8") as opened:
        opened.write(json.dumps(line) + "\n")


def _lines(*, path: Path) -> list[dict]:
    """Return the JSON lines the file at path holds, or none when it is not there."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    sys.exit(replay(base=Path(sys.argv[1]), arguments=sys.argv[2:]))
