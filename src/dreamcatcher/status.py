"""Read status reports for a Dreamcatcher instance."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import dreamcatcher.assignment_status as assignment_status
import dreamcatcher.conversation_status as conversation_status
from dreamcatcher.agent_assignments import (
    read_agent_assignment,
    read_agent_assignments,
    read_agent_assignments_for_issue,
)
from dreamcatcher.assignment_status import (
    AgentAssignmentStatus as AgentAssignmentStatus,
)
from dreamcatcher.assignment_status import (
    AgentAssignmentStatusValue as AgentAssignmentStatusValue,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness
from dreamcatcher.conversation_status import (
    IssueConversationStatus as IssueConversationStatus,
)
from dreamcatcher.conversation_status import (
    IssueConversationStatusValue as IssueConversationStatusValue,
)
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import read_json, read_text
from dreamcatcher.issue_conversations import (
    read_issue_conversation,
    read_issue_conversations,
)
from dreamcatcher.lock import read_daemon_pid
from dreamcatcher.scheduler import GlobalCooldown, IssueFactValue, IssueObservation
from dreamcatcher.state import StateDirectory
from dreamcatcher.status_reader import StatusReportReader
from dreamcatcher.status_rounds import AgentRoundStatus as AgentRoundStatus

ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER = (
    assignment_status.ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER
)
STATUSES_THAT_END_A_VIEW = assignment_status.STATUSES_THAT_END_A_VIEW
CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER = (
    conversation_status.CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER
)


@dataclass(frozen=True, kw_only=True)
class DreamcatcherStatusReport:
    """Describe one Dreamcatcher instance from its local state."""

    at: datetime
    repository: str | None
    daemon_pid: int | None
    agent_harness: AgentHarness | None
    dreamcatcher_version: str | None
    latest_scheduler_tick: datetime | None
    scheduler_interval_seconds: int | None
    scheduler_hold: str | None
    max_agents: int | None
    running_agents: int
    active_global_cooldown: GlobalCooldown | None
    failed_assignment_setups: list[IssueObservation]
    available_issues: list[IssueObservation]
    blocked_issues: list[IssueObservation]
    assignment_statuses: list[AgentAssignmentStatus]
    conversation_statuses: list[IssueConversationStatus]


@dataclass(frozen=True, kw_only=True)
class DreamcatcherDaemonStatus:
    """Describe the current daemon process and the run it owns."""

    pid: int | None
    agent_harness: AgentHarness | None
    dreamcatcher_version: str | None
    max_agents: int | None
    interval_seconds: int | None


def read_status_report(
    *, state: StateDirectory, clock: Callable[[], datetime] = read_current_time
) -> DreamcatcherStatusReport:
    """Read a status report from the instance's local state."""
    reader = StatusReportReader(state=state, clock=clock)
    assignments = read_agent_assignments(state=state)
    assignment_statuses = reader.list_assignment_statuses(assignments=assignments)
    conversation_statuses = [
        status
        for status in reader.list_conversation_statuses(
            conversations=read_issue_conversations(state=state)
        )
        if status.is_listed
    ]
    issue_observations = reader.list_issue_observations(assignments=assignments)
    scheduler_record = reader.scheduler_record
    daemon = _read_dreamcatcher_daemon_status(
        state=state,
        daemon_pid=reader.daemon_pid,
    )
    return DreamcatcherStatusReport(
        at=reader.at,
        repository=read_repository(state=state),
        daemon_pid=daemon.pid,
        agent_harness=daemon.agent_harness,
        dreamcatcher_version=daemon.dreamcatcher_version,
        latest_scheduler_tick=(
            None if scheduler_record is None else scheduler_record.at
        ),
        scheduler_interval_seconds=daemon.interval_seconds,
        scheduler_hold=(
            None
            if scheduler_record is None or reader.daemon_pid is None
            else scheduler_record.hold
        ),
        max_agents=daemon.max_agents,
        running_agents=_count_running_agents(
            assignments=assignment_statuses,
            conversations=conversation_statuses,
        ),
        active_global_cooldown=(
            None if scheduler_record is None else scheduler_record.cooldown
        ),
        failed_assignment_setups=_select_failed_setups(observations=issue_observations),
        available_issues=_select_available_issues(observations=issue_observations),
        blocked_issues=_select_blocked_issues(observations=issue_observations),
        assignment_statuses=assignment_statuses,
        conversation_statuses=conversation_statuses,
    )


def _count_running_agents(
    *,
    assignments: list[AgentAssignmentStatus],
    conversations: list[IssueConversationStatus],
) -> int:
    return sum(
        status.value is AgentAssignmentStatusValue.WORKING for status in assignments
    ) + sum(
        status.value is IssueConversationStatusValue.WORKING for status in conversations
    )


def _select_failed_setups(
    *, observations: list[IssueObservation]
) -> list[IssueObservation]:
    return [
        observation
        for observation in observations
        if observation.setup_failure is not None
    ]


def _select_available_issues(
    *, observations: list[IssueObservation]
) -> list[IssueObservation]:
    return [
        observation
        for observation in observations
        if observation.availability.value is IssueFactValue.TRUE
    ]


def _select_blocked_issues(
    *, observations: list[IssueObservation]
) -> list[IssueObservation]:
    return [
        observation
        for observation in observations
        if observation.blocked.value is IssueFactValue.TRUE
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
        agent_harness=None if daemon_run is None else daemon_run.harness,
        dreamcatcher_version=None if daemon_run is None else daemon_run.version,
        max_agents=None if daemon_run is None else daemon_run.max_agents,
        interval_seconds=None if daemon_run is None else daemon_run.interval_seconds,
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


def read_agent_assignment_statuses_for_issue(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime] = read_current_time,
) -> list[AgentAssignmentStatus]:
    """Read the statuses at one issue, newest agent assignment first."""
    reader = StatusReportReader(state=state, clock=clock)
    return reader.list_assignment_statuses(
        assignments=read_agent_assignments_for_issue(state=state, issue=issue)
    )


def read_agent_assignment_status(
    *,
    state: StateDirectory,
    identifier: str,
    clock: Callable[[], datetime] = read_current_time,
) -> AgentAssignmentStatus | None:
    """Read one agent assignment's status by its exact identifier."""
    assignment = read_agent_assignment(state=state, identifier=identifier)
    if assignment is None:
        return None
    reader = StatusReportReader(state=state, clock=clock)
    return reader.list_assignment_statuses(assignments=[assignment])[0]


def read_issue_conversation_status(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime] = read_current_time,
) -> IssueConversationStatus | None:
    """Read one issue conversation's status by its issue number.

    An issue has a conversation once it has a saved conversation or the latest
    tick observed it through a configured conversation route.
    """
    conversation = read_issue_conversation(state=state, issue=issue)
    reader = StatusReportReader(state=state, clock=clock)
    statuses = reader.list_conversation_statuses(
        conversations=[] if conversation is None else [conversation]
    )
    return next((status for status in statuses if status.issue == issue), None)
