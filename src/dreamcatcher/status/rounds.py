"""Describe agent rounds shared by assignment and conversation status."""

from dataclasses import dataclass

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundRecord,
    ErroredAgentRoundEnding,
)
from dreamcatcher.words import describe_span


@dataclass(frozen=True, kw_only=True)
class AgentRoundStatus:
    """Describe one agent round for a status view."""

    record: AgentRoundRecord
    duration_description: str
    outcome_description: str
    revision: str | None = None
    revision_description: str | None = None


def compose_round_duration_description(*, record: AgentRoundRecord) -> str:
    """Describe how long a completed, uninterrupted round ran."""
    ending = record.ending
    if ending is None or ending.outcome is AgentRoundOutcome.INTERRUPTED:
        return ""
    return f"ran {describe_span(span=ending.at - record.started)}"


def describe_round_outcome(*, record: AgentRoundRecord, is_running: bool) -> str:
    """Return how the round ended, or what it is doing instead.

    A round that recorded no ending never finished. It is running when a daemon
    is still there to run it, and interrupted once that daemon has gone, since
    a round cannot outlive its daemon. A round that errored for a reason, after
    its harness exited cleanly, reads as errored alone, since its exit status
    says nothing and its reason is too long for a list of rounds.
    """
    if isinstance(record.ending, ErroredAgentRoundEnding):
        if record.ending.reason is not None:
            return str(AgentRoundOutcome.ERRORED)
        return f"errored (exit {record.ending.status})"
    if record.ending is None and not is_running:
        return str(AgentRoundOutcome.INTERRUPTED)
    return str(record.outcome)
