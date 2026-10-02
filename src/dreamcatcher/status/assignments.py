"""Represent the derived status of agent assignments."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cached_property

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    find_harness_session_identifier,
)
from dreamcatcher.agent_rounds import AgentRoundPaths
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.status.rounds import (
    AgentRoundStatus,
    compose_round_duration_description,
    describe_round_outcome,
)


class AgentAssignmentStatusValue(StrEnum):
    """List the summary statuses of an agent assignment."""

    WORKING = "working"
    WAITING = "waiting"
    NEEDS_USER_FEEDBACK = "needs user feedback"
    FAULT = "fault"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER = (
    AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK,
    AgentAssignmentStatusValue.FAULT,
    AgentAssignmentStatusValue.WORKING,
    AgentAssignmentStatusValue.WAITING,
    AgentAssignmentStatusValue.UNKNOWN,
    AgentAssignmentStatusValue.COMPLETE,
)

STATUSES_THAT_END_A_VIEW = (
    AgentAssignmentStatusValue.FAULT,
    AgentAssignmentStatusValue.COMPLETE,
)


@dataclass(frozen=True, kw_only=True)
class AgentAssignmentStatus:
    """Describe an agent assignment's derived summary status."""

    assignment: AgentAssignment
    value: AgentAssignmentStatusValue
    detail: str
    latest_output: str | None
    observed_at: datetime | None

    @cached_property
    def round_statuses(self) -> list[AgentRoundStatus]:
        """The derived status of every round in assignment order."""
        assignment = self.assignment
        return [
            AgentRoundStatus(
                record=record,
                duration_description=compose_round_duration_description(record=record),
                outcome_description=describe_round_outcome(
                    record=record,
                    is_running=(
                        self.value is AgentAssignmentStatusValue.WORKING
                        and record.number == assignment.rounds[-1].number
                    ),
                ),
            )
            for record in assignment.rounds
        ]

    @cached_property
    def harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """The recorded or recoverable harness session identifier."""
        return find_harness_session_identifier(assignment=self.assignment)

    @cached_property
    def hand_resume_command(self) -> list[str] | None:
        """The hand-resume command when nobody is running the session."""
        harness_session_identifier = self.harness_session_identifier
        if (
            self.value is AgentAssignmentStatusValue.WORKING
            or harness_session_identifier is None
        ):
            return None
        harness_adapter = HARNESS_ADAPTERS[self.assignment.record.harness]
        return harness_adapter.build_hand_resume(
            harness_session_identifier=harness_session_identifier
        )

    @cached_property
    def stoppable_round_paths(self) -> AgentRoundPaths | None:
        """The live round that can accept a stop request, when one exists."""
        if (
            self.value is not AgentAssignmentStatusValue.WORKING
            or self.harness_session_identifier is None
        ):
            return None
        assignment = self.assignment
        paths = assignment.compose_round_paths(number=assignment.rounds[-1].number)
        return None if paths.stop_request.is_file() else paths
