"""The boundary a harness sits behind.

Everything else in the tool names a harness only to pick its adapter. The
adapter knows what the CLI is called, which flags keep it from stalling, and
what each event of its stream means. Nothing else does.

This module knows one thing about a stream: it carries a JSON event per line.
Both harnesses stream that way, so this module parses each line, and handles a
line that will not parse. Each adapter says what its own events mean.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from dreamcatcher.feed import Event, Prose


@dataclass(frozen=True)
class Launch:
    """What one round starts with.

    The dispatch fixes the session's name, its model, and its effort. Every
    round of that session runs with them. The prompt is this round's own.
    """

    session: str
    model: str
    effort: str
    prompt: str


@dataclass(frozen=True)
class Invocation:
    """How one round runs: the command to start, and the prompt it reads.

    A harness reads its prompt from stdin rather than from its command line,
    so the two travel together and the adapter is what knows which is which.
    That keeps a prompt off every command line, where cmd.exe would act on a
    percent sign or a line ending in it, and it lets a prompt run to any
    length.
    """

    command: list[str]
    prompt: str


class Adapter(ABC):
    """One harness, as everything outside its own module sees it.

    The program is the name of the harness's CLI. Asking the adapter for it is
    how anything else reaches the CLI without knowing which harness it is.
    """

    program: ClassVar[str]

    @abstractmethod
    def build_first_round(self, launch: Launch) -> Invocation:
        """Return how to run a session's first round."""

    @abstractmethod
    def build_resumed_round(self, launch: Launch) -> Invocation:
        """Return how to resume the session with launch's prompt."""

    def read(self, line: str) -> list[Event]:
        """Return the feed events from one line of the harness's stream.

        Not every line is an event. A CLI prints a warning now and then, and an
        event can arrive in a shape the adapter does not expect. In both cases
        the line goes to the feed exactly as it arrived. The reader then sees a
        raw line where a tidy one would normally be, and loses nothing.
        """
        try:
            streamed = json.loads(line)
            return (
                self._events(streamed) if isinstance(streamed, dict) else [Prose(line)]
            )
        except Exception:
            return [Prose(line)]

    @abstractmethod
    def _events(self, streamed: dict) -> list[Event]:
        """Return the feed events one event of this harness's stream turns into."""
