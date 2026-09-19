"""Read-only status reports for a Dreamcatcher instance."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    read_agent_assignments,
    read_agent_assignments_for_issue,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import read_dreamcatcher_config
from dreamcatcher.documents import read_text
from dreamcatcher.feed import Line, read_last_feed_line
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
class AgentAssignmentStatus:
    """One agent assignment and its derived summary status."""

    assignment: AgentAssignment
    value: AgentAssignmentStatusValue
    detail: str
    latest_output: str | None
    observed_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class StatusReport:
    """A read-only account of one Dreamcatcher instance."""

    at: datetime
    repository: str | None
    daemon_pid: int | None
    latest_scheduler_tick: datetime | None
    scheduler_hold: str | None
    max_agent_rounds: int
    running_agent_rounds: int
    active_global_cooldown: GlobalCooldown | None
    issues: list[IssueObservation]
    assignments: list[AgentAssignmentStatus]


def read_status_report(
    *, state: StateDirectory, clock: Callable[[], datetime] = read_current_time
) -> StatusReport:
    """Read a status report from the instance's local configuration and state."""
    reading = _StatusReading(state=state, clock=clock)
    assignments = read_agent_assignments(state=state)
    statuses = reading.list_assignment_statuses(assignments=assignments)
    scheduler_record = reading.scheduler_record
    return StatusReport(
        at=reading.at,
        repository=_read_repository(state=state),
        daemon_pid=reading.daemon_pid,
        latest_scheduler_tick=(
            None if scheduler_record is None else scheduler_record.at
        ),
        scheduler_hold=(
            None
            if scheduler_record is None or reading.daemon_pid is None
            else scheduler_record.hold
        ),
        max_agent_rounds=read_dreamcatcher_config(root=state.root).max_agents,
        running_agent_rounds=sum(
            status.value is AgentAssignmentStatusValue.WORKING for status in statuses
        ),
        active_global_cooldown=(
            None if scheduler_record is None else scheduler_record.cooldown
        ),
        issues=reading.list_available_issues(assignments=assignments),
        assignments=statuses,
    )


def _read_repository(*, state: StateDirectory) -> str | None:
    """Read the repository name after a daemon has recorded it."""
    if not state.repository.exists():
        return None
    return read_text(path=state.repository).strip()


def read_agent_assignment_statuses_for_issue(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime] = read_current_time,
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

    def list_available_issues(
        self, *, assignments: list[AgentAssignment]
    ) -> list[IssueObservation]:
        """Return available issue observations in scheduler order."""
        if self.scheduler_record is None:
            return []
        by_issue: dict[int, list[AgentAssignment]] = {}
        for assignment in assignments:
            by_issue.setdefault(assignment.record.issue, []).append(assignment)
        available = []
        for observation in self.scheduler_record.issue_observations:
            current = self._refresh_issue_observation(
                observation=observation,
                assignments=by_issue.get(observation.issue, []),
                recorded_at=self.scheduler_record.at,
            )
            if current.availability.value is IssueFactValue.TRUE:
                available.append(current)
        return available

    def _refresh_issue_observation(
        self,
        *,
        observation: IssueObservation,
        assignments: list[AgentAssignment],
        recorded_at: datetime,
    ) -> IssueObservation:
        """Refresh one observation's local claim and missing observation time."""
        if any(not assignment.is_complete for assignment in assignments):
            claimed_here = IssueFact(value=IssueFactValue.TRUE)
        elif assignments:
            claimed_here = IssueFact(value=IssueFactValue.FALSE)
        else:
            claimed_here = observation.claimed_here
        current = observation.model_copy(update={"claimed_here": claimed_here})
        if current.observed_at is None:
            return current.model_copy(update={"observed_at": recorded_at})
        return current

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
        local = self._read_local_assignment_status(assignment=assignment)
        if local is not None:
            return local
        observation = self.assignment_observations.get(assignment.identifier)
        if observation is None:
            return self._compose_agent_assignment_status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.UNKNOWN,
                detail="no current scheduler observation",
            )
        if not observation.is_known:
            return self._compose_agent_assignment_status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.UNKNOWN,
                detail=observation.reason,
            )
        if not observation.is_round_required:
            return self._compose_agent_assignment_status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK,
                detail=self._describe_idle(assignment=assignment),
            )
        return self._compose_agent_assignment_status(
            assignment=assignment,
            value=AgentAssignmentStatusValue.WAITING,
            detail=observation.reason,
        )

    def _read_local_assignment_status(
        self, *, assignment: AgentAssignment
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
            return self._compose_agent_assignment_status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.FAULT,
                detail=self._point_at_feed(
                    assignment=assignment,
                    reason="two consecutive rounds failed",
                ),
            )
        unfinished = assignment.describe_unfinished_round()
        if unfinished is not None:
            if self.daemon_pid is not None and assignment.rounds[-1].ending is None:
                detail, latest_output = self._describe_running(assignment=assignment)
                return self._compose_agent_assignment_status(
                    assignment=assignment,
                    value=AgentAssignmentStatusValue.WORKING,
                    detail=detail,
                    latest_output=latest_output,
                )
            return self._compose_agent_assignment_status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.WAITING,
                detail=unfinished,
            )
        if assignment.is_complete:
            return self._compose_agent_assignment_status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.COMPLETE,
                detail=describe_count(number=len(assignment.rounds), noun="round"),
            )
        if not assignment.rounds:
            return self._compose_agent_assignment_status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.WAITING,
                detail=NO_ROUND_HAS_RUN,
            )
        return None

    def _compose_agent_assignment_status(
        self,
        *,
        assignment: AgentAssignment,
        value: AgentAssignmentStatusValue,
        detail: str,
        latest_output: str | None = None,
    ) -> AgentAssignmentStatus:
        """Return a summary status from the assignment's current facts."""
        return AgentAssignmentStatus(
            assignment=assignment,
            value=value,
            detail=detail,
            latest_output=latest_output,
            observed_at=(
                None if self.scheduler_record is None else self.scheduler_record.at
            ),
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
