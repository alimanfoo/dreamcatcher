"""The boundary a harness sits behind.

Everything else in the tool names a harness only to pick its adapter. The
adapter knows what the CLI is called, which flags keep it from stalling, and
what each event of its stream means. Nothing else does.

This module knows one thing about a stream: it carries a JSON event per line.
Both harnesses stream that way, so this module parses each line, and handles a
line that will not parse. Each adapter says what its own events mean.
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, ClassVar

from pydantic import AfterValidator

from dreamcatcher.commands import refuse_unquotable
from dreamcatcher.feed import Event, Prose


def refuse_invalid_harness_session_identifier(identifier: str, /) -> str:
    """Return an identifier safe and unambiguous on a harness command line."""
    safe_identifier = refuse_unquotable(identifier)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", safe_identifier) is None:
        raise ValueError(
            "must begin with a letter or digit and contain only ASCII letters, "
            "digits, hyphens, or underscores"
        )
    return safe_identifier


HarnessSessionIdentifier = Annotated[
    str, AfterValidator(refuse_invalid_harness_session_identifier)
]


@dataclass(frozen=True, kw_only=True)
class Launch:
    """What one round starts with.

    The dispatch fixes the agent assignment identifier, model, and effort.
    Every round of that assignment runs with them. The prompt is this round's
    own.
    """

    assignment_id: str
    model: str
    effort: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class Invocation:
    """How one round runs: the program to start, its arguments, and its prompt.

    `commands.spawn` takes the program apart from its arguments, and a list
    holding both would have whoever spawns it split the two apart again. So the
    program is named apart from its arguments here as well.

    A harness reads its prompt from stdin rather than from its command line,
    so the three travel together and the adapter is what knows which is which.
    That keeps a prompt off every command line, where cmd.exe would act on a
    percent sign or a line ending in it, and it lets a prompt run to any
    length.
    """

    program: str
    arguments: list[str]
    prompt: str


@dataclass(frozen=True, kw_only=True)
class HarnessOutput:
    """What one line of harness output says to Dreamcatcher."""

    events: list[Event]
    harness_session_identifier: str | None = None


class Adapter(ABC):
    """One harness, as everything outside its own module sees it.

    The program is the name of the harness's CLI. Asking the adapter for it is
    how anything else reaches the CLI without knowing which harness it is.
    """

    program: ClassVar[str]

    @abstractmethod
    def build_first_round(self, *, launch: Launch) -> Invocation:
        """Return how to run an agent assignment's first round."""

    @abstractmethod
    def build_resumed_round(
        self, *, launch: Launch, harness_session_identifier: HarnessSessionIdentifier
    ) -> Invocation:
        """Return how to resume the harness session with launch's prompt."""

    @abstractmethod
    def build_hand_resume(
        self, *, harness_session_identifier: HarnessSessionIdentifier
    ) -> list[str]:
        """Return the command that resumes the harness session interactively.

        It carries no prompt: this invocation is interactive, and whoever ran
        it does the talking.
        """

    def read(self, *, line: str) -> list[Event]:
        """Return the feed events from one line of the harness's stream."""
        return self.read_output(line=line).events

    def read_output(self, *, line: str) -> HarnessOutput:
        """Return what one line of the harness's stream says.

        Not every line is an event. A CLI prints a warning now and then, and an
        event can arrive in a shape the adapter does not expect. In both cases
        the line goes to the feed exactly as it arrived. The reader then sees a
        raw line where a tidy one would normally be, and loses nothing.
        """
        try:
            streamed = json.loads(line)
            return (
                self._read(streamed=streamed)
                if isinstance(streamed, dict)
                else HarnessOutput(events=[Prose(text=line)])
            )
        except Exception:
            return HarnessOutput(events=[Prose(text=line)])

    @abstractmethod
    def _read(self, *, streamed: dict) -> HarnessOutput:
        """Return what one parsed event of this harness's stream says."""
