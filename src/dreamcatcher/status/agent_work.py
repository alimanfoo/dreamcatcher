"""Read status facts shared by both kinds of agent work."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from dreamcatcher.agent_assignments import AssignmentRecord
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.issue_conversations import ConversationRecord
from dreamcatcher.scheduler.faults import derive_agent_work_fault
from dreamcatcher.scheduler.models import SchedulerRecord
from dreamcatcher.state import StateDirectory


def compose_hand_resume_command(
    *,
    is_working: bool,
    record: AssignmentRecord | ConversationRecord,
    harness_session_identifier: HarnessSessionIdentifier | None,
) -> list[str] | None:
    """Return the command for resuming an idle harness session by hand."""
    if is_working or harness_session_identifier is None:
        return None
    return HARNESS_ADAPTERS[record.harness].build_hand_resume(
        model=record.model,
        effort=record.effort,
        harness_config=record.harness_config,
        harness_session_identifier=harness_session_identifier,
    )


@dataclass(frozen=True, kw_only=True)
class AgentWorkStatusReader[AgentWorkStatus](ABC):
    """Hold the common facts from which agent-work status is derived."""

    state: StateDirectory
    at: datetime
    is_daemon_running: bool
    scheduler_record: SchedulerRecord | None

    @abstractmethod
    def list_statuses(self) -> list[AgentWorkStatus]:
        """Return this kind's statuses in report order."""

    def is_round_working(self, *, record: AgentRoundRecord) -> bool:
        """Return whether the latest round is still running under a daemon."""
        return record.ending is None and self.is_daemon_running

    def has_fault(
        self,
        *,
        records: list[AgentRoundRecord],
        retry_requested_at: datetime | None,
    ) -> bool:
        """Return whether consecutive errors have exhausted automatic recovery."""
        most_recent_cooldown_ended = (
            None
            if self.scheduler_record is None
            else self.scheduler_record.most_recent_cooldown_ended
        )
        return derive_agent_work_fault(
            rounds=records,
            retry_requested_at=retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )

    def did_round_end_after_latest_tick(
        self,
        *,
        identifier: str,
        record: AgentRoundRecord,
        is_observed: bool,
    ) -> bool:
        """Return whether the latest tick cannot have observed the round ending.

        A tick records its start time, so a later ending is conclusive only when
        that tick launched the round or did not observe the work at all.
        """
        scheduler_record = cast("SchedulerRecord", self.scheduler_record)
        ending = cast(
            "SuccessfulAgentRoundEnding | StoppedAgentRoundEnding",
            record.ending,
        )
        return ending.at > scheduler_record.at and (
            not is_observed
            or identifier in scheduler_record.launched_agent_work_identifiers
        )
