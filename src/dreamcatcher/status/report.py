"""Read status reports for a Dreamcatcher instance."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from dreamcatcher.agent_assignments import (
    Assignment,
    find_open_assignments_by_issue,
    read_assignment,
    read_assignments,
    read_assignments_for_issue,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import read_json, read_text
from dreamcatcher.issue_conversations import (
    read_conversation,
    read_conversations,
)
from dreamcatcher.lock import read_daemon_pid
from dreamcatcher.scheduler.faults import read_scheduler_record
from dreamcatcher.scheduler.models import (
    GlobalCooldown,
    IssueFact,
    IssueFactValue,
    IssueObservation,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status.assignments import (
    AssignmentStatus,
    AssignmentStatusReader,
    AssignmentStatusValue,
)
from dreamcatcher.status.conversations import (
    ConversationStatus,
    ConversationStatusReader,
    ConversationStatusValue,
)


@dataclass(frozen=True, kw_only=True)
class DreamcatcherDaemonStatus:
    """Describe the current daemon process and the run it owns."""

    pid: int | None
    run: DaemonRunRecord | None

    @property
    def is_running(self) -> bool:
        """Whether a daemon is running."""
        return self.pid is not None

    @property
    def agent_harness(self) -> AgentHarness | None:
        """The harness selected for the current or most recent run."""
        return None if self.run is None else self.run.harness

    @property
    def dreamcatcher_version(self) -> str | None:
        """The version used by the current or most recent run."""
        return None if self.run is None else self.run.version

    @property
    def max_agents(self) -> int | None:
        """The agent cap selected for the current or most recent run."""
        return None if self.run is None else self.run.max_agents

    @property
    def interval_seconds(self) -> int | None:
        """The interval selected for the current or most recent run."""
        return None if self.run is None else self.run.interval_seconds


@dataclass(frozen=True, kw_only=True)
class DreamcatcherStatusReport:
    """Describe one Dreamcatcher instance from its local state."""

    at: datetime
    repository: str | None
    daemon: DreamcatcherDaemonStatus
    latest_scheduler_tick: datetime | None
    scheduler_failure_summary: str | None
    running_agents: int
    active_global_cooldown: GlobalCooldown | None
    failed_assignment_setups: list[IssueObservation]
    issue_observations: list[IssueObservation]
    assignment_statuses: list[AssignmentStatus]
    conversation_statuses: list[ConversationStatus]


def read_status_report(
    *, state: StateDirectory, clock: Callable[[], datetime] = read_current_time
) -> DreamcatcherStatusReport:
    """Read a status report from the instance's local state."""
    at, daemon_pid, scheduler_record = _read_status_facts(state=state, clock=clock)
    assignments = read_assignments(state=state)
    assignment_statuses = AssignmentStatusReader(
        state=state,
        at=at,
        is_daemon_running=daemon_pid is not None,
        scheduler_record=scheduler_record,
        assignments=assignments,
    ).list_statuses()
    conversation_statuses = _list_reported_conversation_statuses(
        state=state,
        at=at,
        is_daemon_running=daemon_pid is not None,
        scheduler_record=scheduler_record,
    )
    issue_observations = _refresh_issue_observations(
        scheduler_record=scheduler_record,
        assignments=assignments,
    )
    return DreamcatcherStatusReport(
        at=at,
        repository=read_repository(state=state),
        daemon=_read_dreamcatcher_daemon_status(state=state, daemon_pid=daemon_pid),
        latest_scheduler_tick=(
            None if scheduler_record is None else scheduler_record.at
        ),
        scheduler_failure_summary=(
            None
            if scheduler_record is None or daemon_pid is None
            else "; ".join(scheduler_record.failures) or None
        ),
        running_agents=_count_running_agents(
            assignments=assignment_statuses,
            conversations=conversation_statuses,
        ),
        active_global_cooldown=(
            None if scheduler_record is None else scheduler_record.cooldown
        ),
        failed_assignment_setups=_select_failed_setups(observations=issue_observations),
        issue_observations=_select_issue_observations(observations=issue_observations),
        assignment_statuses=assignment_statuses,
        conversation_statuses=conversation_statuses,
    )


def _read_status_facts(
    *, state: StateDirectory, clock: Callable[[], datetime]
) -> tuple[datetime, int | None, SchedulerRecord | None]:
    at = clock()
    daemon_pid = read_daemon_pid(path=state.lock)
    return at, daemon_pid, read_scheduler_record(state=state, at=at)


def _list_reported_conversation_statuses(
    *,
    state: StateDirectory,
    at: datetime,
    is_daemon_running: bool,
    scheduler_record: SchedulerRecord | None,
) -> list[ConversationStatus]:
    return [
        status
        for status in ConversationStatusReader(
            state=state,
            at=at,
            is_daemon_running=is_daemon_running,
            scheduler_record=scheduler_record,
            conversations=read_conversations(state=state),
        ).list_statuses()
        if status.is_listed
    ]


def _refresh_issue_observations(
    *,
    scheduler_record: SchedulerRecord | None,
    assignments: list[Assignment],
) -> list[IssueObservation]:
    if scheduler_record is None:
        return []
    assignments_by_issue: dict[int, list[Assignment]] = {}
    for assignment in assignments:
        assignments_by_issue.setdefault(assignment.record.issue, []).append(assignment)
    return [
        _refresh_issue_observation(
            observation=observation,
            assignments=assignments_by_issue.get(observation.issue, []),
            recorded_at=scheduler_record.at,
        )
        for observation in scheduler_record.issue_observations
    ]


def _refresh_issue_observation(
    *,
    observation: IssueObservation,
    assignments: list[Assignment],
    recorded_at: datetime,
) -> IssueObservation:
    open_assignment = find_open_assignments_by_issue(assignments=assignments).get(
        observation.issue
    )
    if open_assignment is not None:
        claimed_here = IssueFact(
            value=IssueFactValue.TRUE,
            evidence="an assignment in this checkout is working on it",
        )
    elif assignments:
        claimed_here = IssueFact(
            value=IssueFactValue.FALSE,
            evidence="no assignment in this checkout is working on it",
        )
    else:
        claimed_here = observation.claimed_here
    refreshed = observation.model_copy(update={"claimed_here": claimed_here})
    if refreshed.observed_at is None:
        return refreshed.model_copy(update={"observed_at": recorded_at})
    return refreshed


def _count_running_agents(
    *,
    assignments: list[AssignmentStatus],
    conversations: list[ConversationStatus],
) -> int:
    return sum(
        status.value is AssignmentStatusValue.WORKING for status in assignments
    ) + sum(status.value is ConversationStatusValue.WORKING for status in conversations)


def _select_failed_setups(
    *, observations: list[IssueObservation]
) -> list[IssueObservation]:
    return [
        observation
        for observation in observations
        if observation.setup_failure is not None
    ]


def _select_issue_observations(
    *, observations: list[IssueObservation]
) -> list[IssueObservation]:
    return [
        observation
        for observation in observations
        if (
            observation.setup_failure is None
            and IssueFactValue.TRUE
            in (
                observation.routing_conflict.value,
                observation.availability.value,
                observation.blocked.value,
            )
        )
    ]


def read_repository(*, state: StateDirectory) -> str | None:
    """Read the repository name after a daemon has recorded it."""
    if not state.repository.exists():
        return None
    return read_text(path=state.repository).strip()


def read_dreamcatcher_daemon_status(
    *, state: StateDirectory
) -> DreamcatcherDaemonStatus:
    """Read the current daemon process and the run it owns."""
    return _read_dreamcatcher_daemon_status(
        state=state,
        daemon_pid=read_daemon_pid(path=state.lock),
    )


def _read_dreamcatcher_daemon_status(
    *, state: StateDirectory, daemon_pid: int | None
) -> DreamcatcherDaemonStatus:
    daemon_run = _read_daemon_run_record(state=state, daemon_pid=daemon_pid)
    return DreamcatcherDaemonStatus(
        pid=daemon_pid,
        run=daemon_run,
    )


def _read_daemon_run_record(
    *, state: StateDirectory, daemon_pid: int | None
) -> DaemonRunRecord | None:
    """Read one coherent set of facts about the current or most recent run."""
    if not state.daemon_run_record.exists():
        return None
    record = read_json(model=DaemonRunRecord, path=state.daemon_run_record)
    if daemon_pid is not None and record.pid != daemon_pid:
        return None
    return record


def read_assignment_statuses_for_issue(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime] = read_current_time,
) -> list[AssignmentStatus]:
    """Read the statuses at one issue, newest agent assignment first."""
    at, daemon_pid, scheduler_record = _read_status_facts(state=state, clock=clock)
    return AssignmentStatusReader(
        state=state,
        at=at,
        is_daemon_running=daemon_pid is not None,
        scheduler_record=scheduler_record,
        assignments=read_assignments_for_issue(state=state, issue=issue),
    ).list_statuses()


def read_assignment_status(
    *,
    state: StateDirectory,
    identifier: str,
    clock: Callable[[], datetime] = read_current_time,
) -> AssignmentStatus | None:
    """Read one agent assignment's status by its exact identifier."""
    assignment = read_assignment(state=state, identifier=identifier)
    if assignment is None:
        return None
    at, daemon_pid, scheduler_record = _read_status_facts(state=state, clock=clock)
    return AssignmentStatusReader(
        state=state,
        at=at,
        is_daemon_running=daemon_pid is not None,
        scheduler_record=scheduler_record,
        assignments=[assignment],
    ).derive(assignment=assignment)


def read_conversation_status(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime] = read_current_time,
) -> ConversationStatus | None:
    """Read one issue conversation's status by its issue number.

    An issue has a conversation once it has a saved conversation or the latest
    tick observed it through a configured conversation route.
    """
    conversation = read_conversation(state=state, issue=issue)
    at, daemon_pid, scheduler_record = _read_status_facts(state=state, clock=clock)
    statuses = ConversationStatusReader(
        state=state,
        at=at,
        is_daemon_running=daemon_pid is not None,
        scheduler_record=scheduler_record,
        conversations=[] if conversation is None else [conversation],
    ).list_statuses()
    return next((status for status in statuses if status.issue == issue), None)
