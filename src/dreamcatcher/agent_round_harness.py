"""Adapt one harness invocation to the agent-round lifecycle."""

from dataclasses import dataclass
from typing import Protocol

from dreamcatcher.harness_adapters import (
    HarnessAdapter,
    HarnessInvocation,
    HarnessOutput,
)


class HarnessSessionIdentifierRecorder(Protocol):
    """Record the harness session identifier that an agent round observes."""

    def __call__(self, *, identifier: str) -> None:
        """Record the identifier."""


class AgentRoundFinisher(Protocol):
    """Finish a round whose harness exited successfully, before the round ends.

    Raising a `ReportableError` fails the round, and the round notes why in its
    feed.
    """

    def __call__(self, *, final_output: str | None) -> None:
        """Finish the round with the final output its harness reported, if any."""


@dataclass(frozen=True, kw_only=True)
class AgentRoundHarness:
    """The harness command that a round runs, and the reader of its output."""

    adapter: HarnessAdapter
    invocation: HarnessInvocation
    record_harness_session_identifier: HarnessSessionIdentifierRecorder

    def read(self, *, line: str) -> HarnessOutput:
        """Record the harness session that one line reports, and return the line."""
        output = self.adapter.read_output(line=line)
        identifier = output.harness_session_identifier
        if identifier is not None:
            self.record_harness_session_identifier(identifier=identifier)
        return output
