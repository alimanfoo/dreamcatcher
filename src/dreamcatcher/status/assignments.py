"""Represent the derived status of agent assignments."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cached_property
from typing import cast

from dreamcatcher.agent_assignments import (
    Assignment,
    find_assignment_harness_session_identifier,
)
from dreamcatcher.agent_rounds import AgentRoundPaths
from dreamcatcher.feed import describe_agent_round_start, read_last_feed_line
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.scheduler.models import (
    AgentWorkObservation,
    IssueFactValue,
    SchedulerRecord,
    derive_round_purpose,
)
from dreamcatcher.status.agent_work import (
    AgentWorkStatusReader,
    compose_hand_resume_command,
)
from dreamcatcher.status.rounds import (
    AgentRoundStatus,
    compose_round_duration_description,
    describe_round_ending,
    describe_round_outcome,
    describe_running_round,
    find_stoppable_round_paths,
)
from dreamcatcher.words import describe_count, describe_span


class AssignmentStatusValue(StrEnum):
    """List the summary statuses of an agent assignment."""

    WORKING = "working"
    WAITING = "waiting"
    NEEDS_USER_FEEDBACK = "needs user feedback"
    FAULT = "fault"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER = (
    AssignmentStatusValue.NEEDS_USER_FEEDBACK,
    AssignmentStatusValue.FAULT,
    AssignmentStatusValue.WORKING,
    AssignmentStatusValue.WAITING,
    AssignmentStatusValue.UNKNOWN,
    AssignmentStatusValue.COMPLETE,
)


@dataclass(frozen=True, kw_only=True)
class AssignmentStatus:
    """Describe an agent assignment's derived summary status."""

    assignment: Assignment
    value: AssignmentStatusValue
    detail: str
    latest_output: str | None
    observed_at: datetime | None

    @property
    def has_ended(self) -> bool:
        """Whether the assignment has ended, so it no longer claims its issue."""
        return self.value is AssignmentStatusValue.COMPLETE

    @property
    def is_over(self) -> bool:
        """Whether nothing more can happen until the user acts."""
        return self.has_ended or self.value is AssignmentStatusValue.FAULT

    @property
    def pull_request_state(self) -> str | None:
        """The latest observed pull-request state in status-report words."""
        observation = self.assignment.record.pull_request_observation
        if observation is None:
            return None
        if observation.is_open:
            return "draft" if observation.is_draft else "ready"
        return observation.state.value.lower()

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
                        self.value is AssignmentStatusValue.WORKING
                        and record.number == assignment.rounds[-1].number
                    ),
                ),
            )
            for record in assignment.rounds
        ]

    @cached_property
    def harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """The recorded or recoverable harness session identifier."""
        return find_assignment_harness_session_identifier(assignment=self.assignment)

    @cached_property
    def hand_resume_command(self) -> list[str] | None:
        """The hand-resume command when nobody is running the session."""
        return compose_hand_resume_command(
            is_working=self.value is AssignmentStatusValue.WORKING,
            harness=self.assignment.record.harness,
            harness_session_identifier=self.harness_session_identifier,
        )

    @cached_property
    def stoppable_round_paths(self) -> AgentRoundPaths | None:
        """The live round that can accept a stop request, when one exists."""
        assignment = self.assignment
        return find_stoppable_round_paths(
            is_working=self.value is AssignmentStatusValue.WORKING,
            harness_session_identifier=(
                self.harness_session_identifier
                if self.value is AssignmentStatusValue.WORKING
                else None
            ),
            paths=(
                None
                if not assignment.rounds
                else assignment.compose_round_paths(number=assignment.rounds[-1].number)
            ),
        )


@dataclass(frozen=True, kw_only=True)
class AssignmentStatusReader(AgentWorkStatusReader[AssignmentStatus]):
    """Derive assignment statuses from local state and the latest tick."""

    assignments: list[Assignment]

    @cached_property
    def observations(self) -> dict[str, AgentWorkObservation]:
        """The latest assignment observations, keyed by assignment identifier."""
        scheduler_record = cast("SchedulerRecord", self.scheduler_record)
        return {
            observation.identifier: observation
            for observation in scheduler_record.assignment_observations
        }

    def list_statuses(self) -> list[AssignmentStatus]:
        """Return statuses in ascending issue order, newest at each issue first."""
        newest_first = sorted(
            self.assignments,
            key=lambda assignment: assignment.identifier,
            reverse=True,
        )
        ordered = sorted(
            newest_first,
            key=lambda assignment: assignment.record.issue,
        )
        return [self.derive(assignment=assignment) for assignment in ordered]

    def derive(self, *, assignment: Assignment) -> AssignmentStatus:
        """Derive one assignment's status from its records and latest tick."""
        status = self._derive_working(assignment=assignment)
        if status is not None:
            return status
        status = self._derive_ended(assignment=assignment)
        if status is not None:
            return status
        status = self._derive_unfinished(assignment=assignment)
        if status is not None:
            return status
        status = self._derive_unobserved(assignment=assignment)
        if status is not None:
            return status
        return self._derive_observation(assignment=assignment)

    def _derive_working(self, *, assignment: Assignment) -> AssignmentStatus | None:
        if assignment.rounds:
            latest = assignment.rounds[-1]
            if self.is_round_working(record=latest):
                detail, latest_output = describe_running_round(
                    record=latest,
                    paths=assignment.compose_round_paths(number=latest.number),
                    at=self.at,
                )
                return self._compose(
                    assignment=assignment,
                    value=AssignmentStatusValue.WORKING,
                    detail=detail,
                    latest_output=latest_output,
                )
        return None

    def _derive_ended(self, *, assignment: Assignment) -> AssignmentStatus | None:
        if assignment.is_complete:
            return self._compose(
                assignment=assignment,
                value=AssignmentStatusValue.COMPLETE,
                detail=describe_count(number=len(assignment.rounds), noun="round"),
            )
        return None

    def _derive_unfinished(self, *, assignment: Assignment) -> AssignmentStatus | None:
        if self.has_fault(
            records=assignment.rounds,
            retry_requested_at=assignment.record.retry_requested_at,
        ):
            latest = assignment.rounds[-1]
            detail, latest_output = describe_round_ending(
                record=latest,
                paths=assignment.compose_round_paths(number=latest.number),
            )
            return self._compose(
                assignment=assignment,
                value=AssignmentStatusValue.FAULT,
                detail=detail,
                latest_output=latest_output,
            )
        if assignment.rounds and (
            assignment.rounds[-1].ending is None
            or assignment.describe_unfinished_round() is not None
        ):
            latest = assignment.rounds[-1]
            detail, _ = describe_round_ending(
                record=latest,
                paths=assignment.compose_round_paths(number=latest.number),
            )
            return self._compose(
                assignment=assignment,
                value=AssignmentStatusValue.WAITING,
                detail=detail,
            )
        return None

    def _derive_unobserved(self, *, assignment: Assignment) -> AssignmentStatus | None:
        """Derive the status of an assignment that no tick could have observed."""
        if not assignment.rounds:
            return self._compose(
                assignment=assignment,
                value=AssignmentStatusValue.WAITING,
                detail="next round, implement",
            )
        if self.scheduler_record is None:
            return self._compose(
                assignment=assignment,
                value=AssignmentStatusValue.UNKNOWN,
                detail="no current scheduler observation",
            )
        return None

    def _derive_observation(self, *, assignment: Assignment) -> AssignmentStatus:
        observation = self.observations.get(assignment.identifier)
        latest = assignment.rounds[-1]
        if self.did_round_end_after_latest_tick(
            identifier=assignment.identifier,
            record=latest,
            is_observed=observation is not None,
        ):
            return self._compose(
                assignment=assignment,
                value=AssignmentStatusValue.WAITING,
                detail=f"round {latest.number} ended, awaiting next update",
            )
        if observation is None:
            return self._compose(
                assignment=assignment,
                value=AssignmentStatusValue.UNKNOWN,
                detail="no current scheduler observation",
            )
        if observation.requires_round.value is IssueFactValue.UNKNOWN:
            return self._compose(
                assignment=assignment,
                value=AssignmentStatusValue.UNKNOWN,
                detail=observation.requires_round.evidence,
            )
        if observation.requires_round.value is IssueFactValue.TRUE:
            return self._compose(
                assignment=assignment,
                value=AssignmentStatusValue.WAITING,
                detail=self._describe_next_round(assignment=assignment),
            )
        return self._compose(
            assignment=assignment,
            value=AssignmentStatusValue.NEEDS_USER_FEEDBACK,
            detail=self._describe_idle(assignment=assignment),
        )

    def _compose(
        self,
        *,
        assignment: Assignment,
        value: AssignmentStatusValue,
        detail: str,
        latest_output: str | None = None,
    ) -> AssignmentStatus:
        return AssignmentStatus(
            assignment=assignment,
            value=value,
            detail=detail,
            latest_output=latest_output,
            observed_at=self.observed_at,
        )

    def _describe_idle(self, *, assignment: Assignment) -> str:
        line = read_last_feed_line(
            path=assignment.compose_round_paths(
                number=assignment.rounds[-1].number
            ).feed
        )
        if line is None:
            return "idle"
        return f"idle {describe_span(span=self.at - line.at)}"

    def _describe_next_round(self, *, assignment: Assignment) -> str:
        record = assignment.rounds[-1]
        pull_request = assignment.record.pull_request_observation
        purpose = (
            record.purpose
            if pull_request is None
            else derive_round_purpose(pull_request=pull_request)
        )
        description = describe_agent_round_start(
            purpose=purpose,
            is_recovery=(
                record.ending is None
                or assignment.describe_unfinished_round() is not None
            ),
        )
        return f"next round, {description}"
