"""Read status reports for a Dreamcatcher instance."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    find_open_agent_assignments_by_issue,
    read_agent_assignments,
    read_agent_assignments_for_issue,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import read_dreamcatcher_config
from dreamcatcher.documents import read_text
from dreamcatcher.feed import FeedLine, read_last_feed_line
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
    """List the summary statuses of an agent assignment."""

    WORKING = "working"
    WAITING = "waiting"
    NEEDS_USER_FEEDBACK = "needs user feedback"
    FAULT = "fault"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class AgentAssignmentStatus:
    """Describe an agent assignment's derived summary status."""

    assignment: AgentAssignment
    value: AgentAssignmentStatusValue
    detail: str
    latest_output: str | None
    observed_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class DreamcatcherStatusReport:
    """Describe one Dreamcatcher instance from its local state."""

    at: datetime
    repository: str | None
    daemon_pid: int | None
    latest_scheduler_tick: datetime | None
    scheduler_hold: str | None
    max_agent_rounds: int
    running_agent_rounds: int
    active_global_cooldown: GlobalCooldown | None
    issue_observations: list[IssueObservation]
    assignment_statuses: list[AgentAssignmentStatus]


def read_status_report(
    *, state: StateDirectory, clock: Callable[[], datetime] = read_current_time
) -> DreamcatcherStatusReport:
    """Read a status report from the instance's local configuration and state."""
    reader = _StatusReportReader(state=state, clock=clock)
    assignments = read_agent_assignments(state=state)
    assignment_statuses = reader.list_assignment_statuses(assignments=assignments)
    scheduler_record = reader.scheduler_record
    return DreamcatcherStatusReport(
        at=reader.at,
        repository=_read_repository(state=state),
        daemon_pid=reader.daemon_pid,
        latest_scheduler_tick=(
            None if scheduler_record is None else scheduler_record.at
        ),
        scheduler_hold=(
            None
            if scheduler_record is None or reader.daemon_pid is None
            else scheduler_record.hold
        ),
        max_agent_rounds=read_dreamcatcher_config(root=state.root).max_agents,
        running_agent_rounds=sum(
            status.value is AgentAssignmentStatusValue.WORKING
            for status in assignment_statuses
        ),
        active_global_cooldown=(
            None if scheduler_record is None else scheduler_record.cooldown
        ),
        issue_observations=reader.list_available_issues(assignments=assignments),
        assignment_statuses=assignment_statuses,
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
    reader = _StatusReportReader(state=state, clock=clock)
    return reader.list_assignment_statuses(
        assignments=read_agent_assignments_for_issue(state=state, issue=issue)
    )


class _StatusReportReader:
    """Read the local facts required for one status report."""

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
                observation.assignment_identifier: observation
                for observation in self.scheduler_record.assignment_observations
            }
        )

    def list_available_issues(
        self, *, assignments: list[AgentAssignment]
    ) -> list[IssueObservation]:
        """Return available issue observations in scheduler order."""
        if self.scheduler_record is None:
            return []
        assignments_by_issue: dict[int, list[AgentAssignment]] = {}
        for assignment in assignments:
            assignments_by_issue.setdefault(assignment.record.issue, []).append(
                assignment
            )
        available_issues = []
        for observation in self.scheduler_record.issue_observations:
            refreshed_observation = self._refresh_issue_observation(
                observation=observation,
                assignments=assignments_by_issue.get(observation.issue, []),
                recorded_at=self.scheduler_record.at,
            )
            if refreshed_observation.availability.value is IssueFactValue.TRUE:
                available_issues.append(refreshed_observation)
        return available_issues

    def _refresh_issue_observation(
        self,
        *,
        observation: IssueObservation,
        assignments: list[AgentAssignment],
        recorded_at: datetime,
    ) -> IssueObservation:
        """Refresh one observation's local claim and missing observation time."""
        open_assignment = find_open_agent_assignments_by_issue(
            assignments=assignments
        ).get(observation.issue)
        if open_assignment is not None:
            claimed_here = IssueFact(value=IssueFactValue.TRUE)
        elif assignments:
            claimed_here = IssueFact(value=IssueFactValue.FALSE)
        else:
            claimed_here = observation.claimed_here
        refreshed = observation.model_copy(update={"claimed_here": claimed_here})
        if refreshed.observed_at is None:
            return refreshed.model_copy(update={"observed_at": recorded_at})
        return refreshed

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
        """Derive an assignment's summary from local facts and its observation."""
        local_status = self._read_local_assignment_status(assignment=assignment)
        if local_status is not None:
            return local_status
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
                detail=self._describe_idle_assignment(assignment=assignment),
            )
        return self._compose_agent_assignment_status(
            assignment=assignment,
            value=AgentAssignmentStatusValue.WAITING,
            detail=observation.reason,
        )

    def _read_local_assignment_status(
        self, *, assignment: AgentAssignment
    ) -> AgentAssignmentStatus | None:
        """Derive a status when local facts determine it completely."""
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
                detail=self._describe_fault_with_feed(
                    assignment=assignment,
                    reason="two consecutive rounds failed",
                ),
            )
        unfinished_round = assignment.describe_unfinished_round()
        if unfinished_round is not None:
            if self.daemon_pid is not None and assignment.rounds[-1].ending is None:
                detail, latest_output = self._describe_running_assignment(
                    assignment=assignment
                )
                return self._compose_agent_assignment_status(
                    assignment=assignment,
                    value=AgentAssignmentStatusValue.WORKING,
                    detail=detail,
                    latest_output=latest_output,
                )
            return self._compose_agent_assignment_status(
                assignment=assignment,
                value=AgentAssignmentStatusValue.WAITING,
                detail=unfinished_round,
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

    def _describe_running_assignment(
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

    def _describe_idle_assignment(self, *, assignment: AgentAssignment) -> str:
        """Describe how long the assignment has awaited user feedback."""
        line = self._read_last_output(assignment=assignment)
        if line is None:
            return "idle"
        return f"idle {describe_span(span=self.at - line.at)}"

    def _read_last_output(self, *, assignment: AgentAssignment) -> FeedLine | None:
        """Read the last complete line from the assignment's latest feed."""
        return read_last_feed_line(
            path=assignment.compose_round_paths(
                number=assignment.rounds[-1].number
            ).feed
        )

    def _describe_fault_with_feed(
        self, *, assignment: AgentAssignment, reason: str
    ) -> str:
        """Describe a fault and the feed that holds its latest output."""
        feed = assignment.compose_round_paths(number=assignment.rounds[-1].number).feed
        return f"{reason} ({self.state.describe_path(path=feed)})"
