"""The boundary a harness sits behind.

Everything else in the tool names a harness only to pick its adapter. The
adapter knows what the CLI is called, which flags keep it from stalling, and
what each event of its stream means. Nothing else does.

This module knows one thing about a stream: it carries a JSON event per line.
Both harnesses stream that way. So this module reads a line, and deals with one
that will not parse. The adapter is left what each event means.
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


class Adapter(ABC):
    """One harness, as everything outside its own module sees it.

    The program is the name of the harness's CLI. Asking the adapter for it is
    how anything else reaches the CLI without knowing which harness it is.
    """

    program: ClassVar[str]

    @abstractmethod
    def first_round(self, launch: Launch) -> list[str]:
        """Return the command that runs a session's first round."""

    @abstractmethod
    def resume(self, launch: Launch) -> list[str]:
        """Return the command that resumes the session with launch's prompt."""

    def read(self, line: str) -> list[Event]:
        """Return the feed events one line of the harness's stream carries.

        Not every line is an event. A CLI prints a warning now and then, and an
        event can arrive in a shape the adapter does not expect. Either way the
        line reaches the feed as it came. So the reader sees the raw line
        instead of a tidy one, and this drops nothing.
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
        """Return the feed events one event of the harness's stream carries."""
