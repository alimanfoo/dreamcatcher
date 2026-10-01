"""Derive agent-work faults and manage the global cooldown."""

from datetime import datetime

from dreamcatcher.agent_rounds import AgentRoundRecord, ErroredAgentRoundEnding
from dreamcatcher.documents import read_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.issue_conversations import IssueConversation
from dreamcatcher.scheduler.models import (
    GLOBAL_COOLDOWN_DURATION,
    GlobalCooldown,
    IssueConversationObservation,
    IssueFactValue,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory


def derive_agent_work_fault(
    *,
    rounds: list[AgentRoundRecord],
    retry_requested_at: datetime | None,
    most_recent_cooldown_ended: datetime | None,
) -> bool:
    """Derive whether agent work has two current consecutive errors."""
    if len(rounds) < 2:
        return False
    boundaries = [
        boundary
        for boundary in (
            most_recent_cooldown_ended,
            retry_requested_at,
        )
        if boundary is not None
    ]
    most_recent_fault_boundary = max(boundaries, default=None)
    latest_endings = [record.ending for record in rounds[-2:]]
    return all(
        isinstance(ending, ErroredAgentRoundEnding)
        and (
            most_recent_fault_boundary is None
            or ending.at >= most_recent_fault_boundary
        )
        for ending in latest_endings
    )


def _count_observed_conversation_faults(
    *,
    conversations: list[IssueConversation],
    observations: list[IssueConversationObservation],
    most_recent_cooldown_ended: datetime | None,
) -> int:
    """Count faults among conversations this tick keeps in the report."""
    observed_issues = {
        observation.issue
        for observation in observations
        if observation.routing_conflict.value is not IssueFactValue.TRUE
    }
    return sum(
        derive_agent_work_fault(
            rounds=conversation.rounds,
            retry_requested_at=conversation.record.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        for conversation in conversations
        if conversation.record.issue in observed_issues
    )


def read_scheduler_record(
    *, state: StateDirectory, at: datetime
) -> SchedulerRecord | None:
    """Read the scheduler record advanced to the current time."""
    if not state.scheduler_record.exists():
        return None
    try:
        record = read_json(model=SchedulerRecord, path=state.scheduler_record)
    except ReportableError as failure:
        raise InvalidSchedulerRecordError(str(failure)) from failure
    cooldown = record.cooldown
    if cooldown is not None and at >= cooldown.ends:
        return record.model_copy(
            update={
                "hold": None,
                "cooldown": None,
                "most_recent_cooldown_ended": cooldown.ends,
            }
        )
    return record


class InvalidSchedulerRecordError(ReportableError):
    """Report a scheduler record that retrying cannot safely replace."""


def _start_cooldown_if_required(
    *,
    active: GlobalCooldown | None,
    fault_count: int,
    at: datetime,
) -> GlobalCooldown | None:
    """Start a cooldown when two agent work items are currently in fault."""
    if active is not None:
        return active
    if fault_count < 2:
        return None
    return GlobalCooldown(started=at, ends=at + GLOBAL_COOLDOWN_DURATION)
