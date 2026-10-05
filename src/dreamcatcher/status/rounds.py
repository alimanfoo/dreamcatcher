"""Describe agent rounds shared by assignment and conversation status."""

from dataclasses import dataclass
from datetime import datetime

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    ErroredAgentRoundEnding,
)
from dreamcatcher.feed import describe_agent_round_start, read_last_feed_line
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.words import describe_span


@dataclass(frozen=True, kw_only=True)
class AgentRoundRevision:
    """Describe the code revision one agent round investigated."""

    value: str
    description: str


@dataclass(frozen=True, kw_only=True)
class AgentRoundStatus:
    """Describe one agent round for a status view."""

    record: AgentRoundRecord
    duration_description: str
    outcome_description: str
    revision: AgentRoundRevision | None = None


def describe_running_round(
    *, record: AgentRoundRecord, paths: AgentRoundPaths, at: datetime
) -> tuple[str, str | None]:
    """Describe a running round and return its latest output."""
    purpose = describe_agent_round_start(
        purpose=record.purpose, is_recovery=record.is_recovery
    )
    detail = (
        f"round {record.number}, {purpose}, "
        f"running {describe_span(span=at - record.started)}"
    )
    line = read_last_feed_line(path=paths.feed)
    if line is None:
        return f"{detail}, has said nothing yet", None
    since_last_output = describe_span(span=at - line.at)
    return f"{detail}, last output {since_last_output} ago", line.text.strip()


def describe_round_ending(
    *, record: AgentRoundRecord, paths: AgentRoundPaths
) -> tuple[str, str | None]:
    """Describe a round that is no longer running and return its latest output."""
    ending = record.ending
    if isinstance(ending, ErroredAgentRoundEnding):
        detail = f"round {record.number} errored (exit {ending.status})"
        if ending.reason is not None:
            detail = f"{detail}: {ending.reason}"
    else:
        outcome = describe_round_outcome(record=record, is_working=False)
        detail = f"round {record.number} {outcome}"
    line = read_last_feed_line(path=paths.feed)
    return detail, None if line is None else line.text.strip()


def find_stoppable_round_paths(
    *,
    is_working: bool,
    harness_session_identifier: HarnessSessionIdentifier | None,
    paths: AgentRoundPaths | None,
) -> AgentRoundPaths | None:
    """Return the live round that can accept a stop request, when one exists."""
    if (
        not is_working
        or harness_session_identifier is None
        or paths is None
        or paths.stop_request.is_file()
    ):
        return None
    return paths


def compose_round_duration_description(*, record: AgentRoundRecord) -> str:
    """Describe how long a completed, uninterrupted round ran."""
    ending = record.ending
    if ending is None or ending.outcome is AgentRoundOutcome.INTERRUPTED:
        return ""
    return f"ran {describe_span(span=ending.at - record.started)}"


def describe_round_outcome(*, record: AgentRoundRecord, is_working: bool) -> str:
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
    if record.ending is None and not is_working:
        return str(AgentRoundOutcome.INTERRUPTED)
    return str(record.outcome)
