"""Read-only status reports for a Dreamcatcher instance."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    find_harness_session_identifier,
    read_agent_assignments,
    read_agent_assignments_for_issue,
)
from dreamcatcher.agent_rounds import SuccessfulAgentRoundEnding
from dreamcatcher.clock import now
from dreamcatcher.config import read_config
from dreamcatcher.feed import Line, read_last_feed_line
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.lock import read_daemon_pid
from dreamcatcher.scheduler import (
    NO_ROUND_HAS_RUN,
    AgentAssignmentObservation,
    GlobalCooldown,
    IssueFact,
    IssueFactValue,
    IssueObservation,
    advance_scheduler_record,
    derive_assignment_fault,
    derive_issue_availability,
    read_scheduler_record,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.words import describe_count, describe_span


class AgentAssignmentStatusValue(StrEnum):
    """The summary statuses that one agent assignment can have."""

    WORKING = "working"
    WAITING = "waiting"
    NEEDS_USER_FEEDBACK = "needs user feedback"
    FAULT = "fault"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class IssueStatus:
    """One issue's independent facts and derived availability."""

    issue: int
    created_at: datetime | None
    is_open: IssueFact
    is_assigned_to_user: IssueFact
    dispatch_labels: list[str] | None
    claimed_here: IssueFact
    claimed_elsewhere: IssueFact
    blocked: IssueFact
    routing_conflict: IssueFact
    availability: IssueFact
    observed_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class AgentAssignmentStatus:
    """One agent assignment and its derived summary status."""

    assignment: AgentAssignment
    value: AgentAssignmentStatusValue
    detail: str
    latest_output: str | None
    observed_at: datetime | None
    harness_session_identifier: HarnessSessionIdentifier | None
    harness_resume_command: tuple[str, ...] | None

    @property
    def is_terminal(self) -> bool:
        """Whether no ordinary later round can follow this status."""
        return self.value in (
            AgentAssignmentStatusValue.FAULT,
            AgentAssignmentStatusValue.COMPLETE,
        )


@dataclass(frozen=True, kw_only=True)
class StatusReport:
    """A read-only account of one Dreamcatcher instance."""

    at: datetime
    daemon_pid: int | None
    latest_scheduler_tick: datetime | None
    scheduler_hold: str | None
    max_agent_rounds: int
    running_agent_rounds: int
    active_global_cooldown: GlobalCooldown | None
    issues: list[IssueStatus]
    assignments: list[AgentAssignmentStatus]


def read_status_report(
    *, state: StateDirectory, clock: Callable[[], datetime] = now
) -> StatusReport:
    """Read a status report from the instance's local configuration and state."""
    reading = _StatusReading(state=state, clock=clock)
    assignments = read_agent_assignments(state=state)
    statuses = reading.list_assignment_statuses(assignments=assignments)
    scheduler_record = reading.scheduler_record
    return StatusReport(
        at=reading.at,
        daemon_pid=reading.daemon_pid,
        latest_scheduler_tick=(
            None if scheduler_record is None else scheduler_record.at
        ),
        scheduler_hold=None if scheduler_record is None else scheduler_record.hold,
        max_agent_rounds=read_config(root=state.root).max_agents,
        running_agent_rounds=sum(
            status.value is AgentAssignmentStatusValue.WORKING for status in statuses
        ),
        active_global_cooldown=(
            None if scheduler_record is None else scheduler_record.cooldown
        ),
        issues=reading.list_issue_statuses(assignments=assignments),
        assignments=statuses,
    )


def read_agent_assignment_statuses_for_issue(
    *, state: StateDirectory, issue: int, clock: Callable[[], datetime] = now
) -> list[AgentAssignmentStatus]:
    """Read the statuses at one issue, newest agent assignment first."""
    reading = _StatusReading(state=state, clock=clock)
    return reading.list_assignment_statuses(
        assignments=read_agent_assignments_for_issue(state=state, issue=issue)
    )


class _StatusReading:
    """The local facts read together for one status report."""

    def __init__(self, *, state: StateDirectory, clock: Callable[[], datetime]) -> None:
        """Read the daemon and latest complete scheduler record once."""
        self.state = state
        self.at = clock()
        self.daemon_pid = read_daemon_pid(path=state.lock)
        self.scheduler_record = advance_scheduler_record(
            previous=read_scheduler_record(state=state),
            at=self.at,
        )
        self.assignment_observations: dict[str, AgentAssignmentObservation] = (
            {}
            if self.scheduler_record is None
            else {
                observation.assignment: observation
                for observation in self.scheduler_record.assignment_observations
            }
        )

    def list_issue_statuses(
        self, *, assignments: list[AgentAssignment]
    ) -> list[IssueStatus]:
        """Return observed issues plus any open local assignment not observed."""
        by_issue: dict[int, list[AgentAssignment]] = {}
        for assignment in assignments:
            by_issue.setdefault(assignment.record.issue, []).append(assignment)
        observations = (
            []
            if self.scheduler_record is None
            else self.scheduler_record.issue_observations
        )
        statuses = [
            self._compose_issue_status(
                observation=observation,
                assignments=by_issue.get(observation.issue, []),
            )
            for observation in observations
        ]
        observed_issues = {status.issue for status in statuses}
        for issue, issue_assignments in sorted(by_issue.items()):
            if issue not in observed_issues and any(
                not assignment.is_complete for assignment in issue_assignments
            ):
                statuses.append(self._compose_unobserved_issue_status(issue=issue))
        return statuses

    def _compose_issue_status(
        self,
        *,
        observation: IssueObservation,
        assignments: list[AgentAssignment],
    ) -> IssueStatus:
        """Return one observed issue with its current local claim and availability."""
        if any(not assignment.is_complete for assignment in assignments):
            claimed_here = IssueFact(value=IssueFactValue.TRUE)
        elif assignments:
            claimed_here = IssueFact(value=IssueFactValue.FALSE)
        else:
            claimed_here = observation.claimed_here
        current = observation.model_copy(update={"claimed_here": claimed_here})
        return _issue_status_from_observation(
            observation=current,
            observed_at=(
                None if self.scheduler_record is None else self.scheduler_record.at
            ),
        )

    def _compose_unobserved_issue_status(self, *, issue: int) -> IssueStatus:
        """Return an open local assignment's issue with unknown external facts."""
        unknown = IssueFact(
            value=IssueFactValue.UNKNOWN,
            evidence="no scheduler observation yet",
        )
        observation = IssueObservation(
            issue=issue,
            is_open=unknown,
            is_assigned_to_user=unknown,
            dispatch_labels=None,
            claimed_here=IssueFact(value=IssueFactValue.TRUE),
            claimed_elsewhere=unknown,
            blocked=unknown,
            routing_conflict=unknown,
        )
        return _issue_status_from_observation(
            observation=observation,
            observed_at=None,
        )

    def list_assignment_statuses(
        self, *, assignments: list[AgentAssignment]
    ) -> list[AgentAssignmentStatus]:
        """Return agent assignments by issue, newest at each issue first."""
        newest_first = sorted(
            assignments,
            key=lambda assignment: assignment.identifier,
            reverse=True,
        )
        ordered = sorted(
            newest_first,
            key=lambda assignment: assignment.record.issue,
        )
        return [
            self._read_assignment_status(assignment=assignment)
            for assignment in ordered
        ]

    def _read_assignment_status(
        self, *, assignment: AgentAssignment
    ) -> AgentAssignmentStatus:
        """Derive one assignment's summary from local facts and its last observation."""
        observed_at = (
            None if self.scheduler_record is None else self.scheduler_record.at
        )
        local = self._read_local_assignment_status(
            assignment=assignment,
            observed_at=observed_at,
        )
        if local is not None:
            return local
        if self._has_no_current_external_observation(assignment=assignment):
            return self._status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.UNKNOWN,
                detail="no current scheduler observation",
                observed_at=observed_at,
            )
        observation = self.assignment_observations.get(assignment.identifier)
        if observation is None:
            return self._status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK,
                detail=self._describe_idle(assignment=assignment),
                observed_at=observed_at,
            )
        return self._status(
            assignment=assignment,
            value=(
                AgentAssignmentStatusValue.WAITING
                if observation.is_known
                else AgentAssignmentStatusValue.UNKNOWN
            ),
            detail=observation.reason,
            observed_at=observed_at,
        )

    def _read_local_assignment_status(
        self,
        *,
        assignment: AgentAssignment,
        observed_at: datetime | None,
    ) -> AgentAssignmentStatus | None:
        """Derive a status from local facts alone, when they settle it."""
        most_recent_cooldown_ended = (
            None
            if self.scheduler_record is None
            else self.scheduler_record.most_recent_cooldown_ended
        )
        if derive_assignment_fault(
            assignment=assignment,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        ):
            return self._status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.FAULT,
                detail=self._point_at_feed(
                    assignment=assignment,
                    reason="two consecutive rounds failed",
                ),
                observed_at=observed_at,
            )
        unfinished = assignment.describe_unfinished_round()
        if unfinished is not None:
            if self.daemon_pid is not None and assignment.rounds[-1].ending is None:
                detail, latest_output = self._describe_running(assignment=assignment)
                return self._status(
                    assignment=assignment,
                    value=AgentAssignmentStatusValue.WORKING,
                    detail=detail,
                    latest_output=latest_output,
                    observed_at=observed_at,
                )
            return self._status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.WAITING,
                detail=unfinished,
                observed_at=observed_at,
            )
        if assignment.is_complete:
            return self._status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.COMPLETE,
                detail=describe_count(number=len(assignment.rounds), noun="round"),
                observed_at=observed_at,
            )
        if not assignment.rounds:
            return self._status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.WAITING,
                detail=NO_ROUND_HAS_RUN,
                observed_at=observed_at,
            )
        return None

    def _has_no_current_external_observation(
        self, *, assignment: AgentAssignment
    ) -> bool:
        """Return whether no tick has observed the assignment's latest ending."""
        if self.scheduler_record is None:
            return True
        ending = assignment.rounds[-1].ending
        return (
            isinstance(ending, SuccessfulAgentRoundEnding)
            and ending.at > self.scheduler_record.at
        )

    def _status(
        self,
        *,
        assignment: AgentAssignment,
        value: AgentAssignmentStatusValue,
        detail: str,
        observed_at: datetime | None,
        latest_output: str | None = None,
    ) -> AgentAssignmentStatus:
        """Return a status with the assignment's harness session identity."""
        harness_adapter = HARNESS_ADAPTERS[assignment.record.harness]
        harness_session_identifier = find_harness_session_identifier(
            assignment=assignment,
            harness_adapter=harness_adapter,
        )
        harness_resume_command = (
            None
            if value is AgentAssignmentStatusValue.WORKING
            or harness_session_identifier is None
            else tuple(
                harness_adapter.build_hand_resume(
                    harness_session_identifier=harness_session_identifier
                )
            )
        )
        return AgentAssignmentStatus(
            assignment=assignment,
            value=value,
            detail=detail,
            latest_output=latest_output,
            observed_at=observed_at,
            harness_session_identifier=harness_session_identifier,
            harness_resume_command=harness_resume_command,
        )

    def _describe_running(
        self, *, assignment: AgentAssignment
    ) -> tuple[str, str | None]:
        """Describe the live round and return its latest feed output."""
        since_started = describe_span(span=self.at - assignment.rounds[-1].started)
        line = self._read_last_output(assignment=assignment)
        if line is None:
            return f"running {since_started}, has said nothing yet", None
        since_last_output = describe_span(span=self.at - line.at)
        return (
            f"running {since_started}, last output {since_last_output} ago",
            line.text.strip(),
        )

    def _describe_idle(self, *, assignment: AgentAssignment) -> str:
        """Describe how long the assignment has awaited user feedback."""
        line = self._read_last_output(assignment=assignment)
        if line is None:
            return "idle"
        return f"idle {describe_span(span=self.at - line.at)}"

    def _read_last_output(self, *, assignment: AgentAssignment) -> Line | None:
        """Read the last complete line from the assignment's latest feed."""
        return read_last_feed_line(
            path=assignment.round_paths(number=assignment.rounds[-1].number).feed
        )

    def _point_at_feed(self, *, assignment: AgentAssignment, reason: str) -> str:
        """Describe a fault and the feed that holds its latest output."""
        feed = assignment.round_paths(number=assignment.rounds[-1].number).feed
        return f"{reason} ({self.state.describe_path(path=feed)})"


def _issue_status_from_observation(
    *, observation: IssueObservation, observed_at: datetime | None
) -> IssueStatus:
    """Build an issue status from an observation and its observation time."""
    return IssueStatus(
        issue=observation.issue,
        created_at=observation.created_at,
        is_open=observation.is_open,
        is_assigned_to_user=observation.is_assigned_to_user,
        dispatch_labels=observation.dispatch_labels,
        claimed_here=observation.claimed_here,
        claimed_elsewhere=observation.claimed_elsewhere,
        blocked=observation.blocked,
        routing_conflict=observation.routing_conflict,
        availability=derive_issue_availability(observation=observation),
        observed_at=observed_at,
    )
