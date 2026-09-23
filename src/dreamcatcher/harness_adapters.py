"""Define the boundary between Dreamcatcher and each agent harness.

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
from dreamcatcher.feed import FeedEvent, FeedProse


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
class AgentRoundLaunchRequest:
    """Describe the settled agent-work settings and prompt for one round.

    The work owner fixes the identifier, model, and effort. Every round for
    that owner runs with them. The prompt is this round's own.
    """

    agent_work_identifier: str
    model: str
    effort: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class HarnessInvocation:
    """Describe the command and prompt that start one round.

    A harness reads its prompt from stdin rather than from its command line,
    which keeps prompt length and Windows command parsing outside this contract.
    """

    program: str
    arguments: list[str]
    prompt: str


@dataclass(frozen=True, kw_only=True)
class HarnessOutput:
    """Describe the feed events and harness session identifier in one output line."""

    events: list[FeedEvent]
    harness_session_identifier: str | None = None


class HarnessAdapter(ABC):
    """Define how Dreamcatcher invokes and reads one harness.

    The program names the harness CLI. Callers use the adapter without knowing
    any harness-specific arguments or event shapes.
    """

    program: ClassVar[str]

    @abstractmethod
    def build_first_round(
        self, *, request: AgentRoundLaunchRequest
    ) -> HarnessInvocation:
        """Return how to run an agent assignment's first round."""

    @abstractmethod
    def build_resumed_round(
        self,
        *,
        request: AgentRoundLaunchRequest,
        harness_session_identifier: HarnessSessionIdentifier,
    ) -> HarnessInvocation:
        """Return how to resume the harness session with request's prompt."""

    @abstractmethod
    def build_hand_resume(
        self, *, harness_session_identifier: HarnessSessionIdentifier
    ) -> list[str]:
        """Return the command that resumes the harness session interactively.

        It carries no prompt: this invocation is interactive, and whoever ran
        it does the talking.
        """

    def read(self, *, line: str) -> list[FeedEvent]:
        """Return the feed events from one line of the harness's stream."""
        return self.read_output(line=line).events

    def read_output(self, *, line: str) -> HarnessOutput:
        """Return what one line of the harness stream says.

        Not every line is an event. A CLI prints a warning now and then, and an
        event can arrive in a shape the adapter does not expect. In both cases
        the line goes to the feed exactly as it arrived. The reader then sees a
        raw line where a parsed event would normally be, and loses nothing.
        """
        try:
            harness_event = json.loads(line)
            return (
                self._read(harness_event=harness_event)
                if isinstance(harness_event, dict)
                else HarnessOutput(events=[FeedProse(text=line)])
            )
        except Exception:
            return HarnessOutput(events=[FeedProse(text=line)])

    @abstractmethod
    def _read(self, *, harness_event: dict) -> HarnessOutput:
        """Return what one parsed event of this harness's stream says."""
