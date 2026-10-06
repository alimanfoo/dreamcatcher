"""Read status reports for a dreamcatcher instance."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from dreamcatcher.agent_assignments import (
    read_assignment,
    read_assignments,
    read_assignments_for_issue,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import read_json_if_exists, read_text
from dreamcatcher.issue_conversations import (
    read_conversation,
    read_conversations,
)
from dreamcatcher.lock import is_daemon_lock_held
from dreamcatcher.scheduler.faults import read_scheduler_record
from dreamcatcher.scheduler.models import (
    GlobalCooldown,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status.assignments import (
    ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
    AssignmentStatus,
    AssignmentStatusReader,
    AssignmentStatusValue,
)
from dreamcatcher.status.conversations import (
    CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER,
    ConversationStatus,
    ConversationStatusReader,
    ConversationStatusValue,
)
from dreamcatcher.status.issues import (
    IssueStatus,
    IssueStatusValue,
    derive_issue_statuses,
)
from dreamcatcher.words import describe_countdown, describe_span


@dataclass(frozen=True, kw_only=True)
class DreamcatcherDaemonStatus:
    """Describe whether a daemon is running, and the current or latest daemon run."""

    is_running: bool
    run: DaemonRunRecord | None

    @property
    def pid(self) -> int | None:
        """The running daemon's process ID, from the latest daemon run record.

        A daemon writes its daemon run record just after it takes the lock, so for
        that moment a starting daemon reports the previous daemon run's record.
        """
        return None if not self.is_running or self.run is None else self.run.pid

    @property
    def agent_harness(self) -> AgentHarness | None:
        """The preferred harness given to the current or latest `dreamcatcher run`."""
        return None if self.run is None else self.run.harness

    @property
    def dreamcatcher_version(self) -> str | None:
        """The version used by the current or latest daemon run."""
        return None if self.run is None else self.run.version

    @property
    def max_agents(self) -> int | None:
        """The agent capacity selected for the current or latest daemon run."""
        return None if self.run is None else self.run.max_agents

    @property
    def interval_seconds(self) -> int | None:
        """The interval selected for the current or latest daemon run."""
        return None if self.run is None else self.run.interval_seconds

    @property
    def summary(self) -> str:
        """The daemon's state in words, such as "running dreamcatcher v5.1.0 as pid 7".

        The views put the word "daemon" before it.
        """
        if not self.is_running:
            return "not running"
        version = (
            None
            if self.dreamcatcher_version is None
            else f"dreamcatcher v{self.dreamcatcher_version}"
        )
        pid = None if self.pid is None else f"as pid {self.pid}"
        return " ".join(filter(None, ("running", version, pid)))


@dataclass(frozen=True, kw_only=True)
class StatusFact:
    """Hold one labelled fact, worded as a status view shows it."""

    label: str
    value: str
    is_warning: bool = False


@dataclass(frozen=True, kw_only=True)
class DreamcatcherStatusReport:
    """Describe one dreamcatcher instance from its local state."""

    at: datetime
    repository: str | None
    daemon: DreamcatcherDaemonStatus
    latest_scheduler_tick: datetime | None
    scheduler_failure_summary: str | None
    running_agents: int
    active_global_cooldown: GlobalCooldown | None
    failed_assignment_setups: list[IssueStatus]
    issue_statuses: list[IssueStatus]
    assignment_statuses: list[AssignmentStatus]
    conversation_statuses: list[ConversationStatus]

    @property
    def instance_facts(self) -> tuple[StatusFact, ...]:
        """The instance's facts that are known, in the order a view shows them.

        A global cooldown and scheduler failures are warnings.
        """
        daemon = self.daemon
        cooldown = self.active_global_cooldown
        facts = (
            (
                "preferred harness",
                None if daemon.agent_harness is None else str(daemon.agent_harness),
                False,
            ),
            (
                "next update in",
                None
                if not daemon.is_running
                else describe_countdown(
                    at=self.at,
                    since=self.latest_scheduler_tick,
                    span_seconds=daemon.interval_seconds,
                ),
                False,
            ),
            (
                "agent capacity",
                None
                if daemon.max_agents is None
                else f"{self.running_agents} of {daemon.max_agents} working",
                False,
            ),
            (
                "global cooldown",
                None
                if cooldown is None
                else f"ends in {describe_span(span=cooldown.ends - self.at)}",
                True,
            ),
            ("scheduler failures", self.scheduler_failure_summary, True),
        )
        return tuple(
            StatusFact(label=label, value=value, is_warning=is_warning)
            for label, value, is_warning in facts
            if value is not None
        )

    @property
    def active_assignment_statuses(self) -> list[AssignmentStatus]:
        """The assignments that have not ended, in attention order."""
        return sorted(
            (status for status in self.assignment_statuses if not status.has_ended),
            key=lambda status: ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER.index(
                status.value
            ),
        )

    @property
    def ended_assignment_statuses(self) -> list[AssignmentStatus]:
        """The assignments that have ended, most recently ended first."""
        return sorted(
            (status for status in self.assignment_statuses if status.has_ended),
            key=lambda status: cast("datetime", status.assignment.ended_at),
            reverse=True,
        )


def read_status_report(
    *, state: StateDirectory, clock: Callable[[], datetime] = read_current_time
) -> DreamcatcherStatusReport:
    """Read a status report from the instance's local state."""
    daemon = read_dreamcatcher_daemon_status(state=state)
    at, scheduler_record = _read_status_facts(state=state, clock=clock)
    assignments = read_assignments(state=state)
    assignment_statuses = AssignmentStatusReader(
        state=state,
        at=at,
        is_daemon_running=daemon.is_running,
        scheduler_record=scheduler_record,
        assignments=assignments,
    ).list_statuses()
    conversation_statuses = _list_reported_conversation_statuses(
        state=state,
        at=at,
        is_daemon_running=daemon.is_running,
        scheduler_record=scheduler_record,
    )
    issue_statuses = derive_issue_statuses(
        scheduler_record=scheduler_record, assignments=assignments
    )
    return DreamcatcherStatusReport(
        at=at,
        repository=read_repository(state=state),
        daemon=daemon,
        latest_scheduler_tick=(
            None if scheduler_record is None else scheduler_record.at
        ),
        scheduler_failure_summary=(
            None
            if scheduler_record is None or not daemon.is_running
            else "; ".join(scheduler_record.failures) or None
        ),
        running_agents=_count_running_agents(
            assignments=assignment_statuses,
            conversations=conversation_statuses,
        ),
        active_global_cooldown=(
            None if scheduler_record is None else scheduler_record.cooldown
        ),
        failed_assignment_setups=[
            status
            for status in issue_statuses
            if status.value is IssueStatusValue.FAILED_SETUP
        ],
        issue_statuses=[
            status
            for status in issue_statuses
            if status.value is not IssueStatusValue.FAILED_SETUP
        ],
        assignment_statuses=assignment_statuses,
        conversation_statuses=conversation_statuses,
    )


def _read_status_facts(
    *, state: StateDirectory, clock: Callable[[], datetime]
) -> tuple[datetime, SchedulerRecord | None]:
    at = clock()
    return at, read_scheduler_record(state=state, at=at)


def _list_reported_conversation_statuses(
    *,
    state: StateDirectory,
    at: datetime,
    is_daemon_running: bool,
    scheduler_record: SchedulerRecord | None,
) -> list[ConversationStatus]:
    """Return the listed conversations in attention order."""
    return sorted(
        (
            status
            for status in ConversationStatusReader(
                state=state,
                at=at,
                is_daemon_running=is_daemon_running,
                scheduler_record=scheduler_record,
                conversations=read_conversations(state=state),
            ).list_statuses()
            if status.is_listed
        ),
        key=lambda status: CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER.index(
            status.value
        ),
    )


def _count_running_agents(
    *,
    assignments: list[AssignmentStatus],
    conversations: list[ConversationStatus],
) -> int:
    return sum(
        status.value is AssignmentStatusValue.WORKING for status in assignments
    ) + sum(status.value is ConversationStatusValue.WORKING for status in conversations)


def read_repository(*, state: StateDirectory) -> str | None:
    """Read the repository name after a daemon has recorded it."""
    if not state.repository.exists():
        return None
    return read_text(path=state.repository).strip()


def read_dreamcatcher_daemon_status(
    *, state: StateDirectory
) -> DreamcatcherDaemonStatus:
    """Read whether a daemon is running, and the current or latest daemon run."""
    return DreamcatcherDaemonStatus(
        is_running=is_daemon_lock_held(path=state.lock),
        run=read_json_if_exists(model=DaemonRunRecord, path=state.daemon_run_record),
    )


def read_assignment_statuses_for_issue(
    *,
    state: StateDirectory,
    issue: int,
    daemon: DreamcatcherDaemonStatus,
    clock: Callable[[], datetime] = read_current_time,
) -> list[AssignmentStatus]:
    """Read the statuses at one issue, newest agent assignment first.

    The caller reads the daemon status, so a view that also shows it shows the
    same answer that its round statuses came from.
    """
    at, scheduler_record = _read_status_facts(state=state, clock=clock)
    return AssignmentStatusReader(
        state=state,
        at=at,
        is_daemon_running=daemon.is_running,
        scheduler_record=scheduler_record,
        assignments=read_assignments_for_issue(state=state, issue=issue),
    ).list_statuses()


def read_assignment_status(
    *,
    state: StateDirectory,
    identifier: str,
    daemon: DreamcatcherDaemonStatus,
    clock: Callable[[], datetime] = read_current_time,
) -> AssignmentStatus | None:
    """Read one agent assignment's status by its exact identifier.

    The caller reads the daemon status, so a view that also shows it shows the
    same answer that its round statuses came from.
    """
    assignment = read_assignment(state=state, identifier=identifier)
    if assignment is None:
        return None
    at, scheduler_record = _read_status_facts(state=state, clock=clock)
    return AssignmentStatusReader(
        state=state,
        at=at,
        is_daemon_running=daemon.is_running,
        scheduler_record=scheduler_record,
        assignments=[assignment],
    ).derive(assignment=assignment)


def read_conversation_status(
    *,
    state: StateDirectory,
    issue: int,
    daemon: DreamcatcherDaemonStatus,
    clock: Callable[[], datetime] = read_current_time,
) -> ConversationStatus | None:
    """Read one issue conversation's status by its issue number.

    An issue has a conversation once it has a saved conversation or the latest
    tick observed it through a configured conversation route. The caller reads
    the daemon status, so a view that also shows it shows the same answer that
    its round statuses came from.
    """
    conversation = read_conversation(state=state, issue=issue)
    at, scheduler_record = _read_status_facts(state=state, clock=clock)
    statuses = ConversationStatusReader(
        state=state,
        at=at,
        is_daemon_running=daemon.is_running,
        scheduler_record=scheduler_record,
        conversations=[] if conversation is None else [conversation],
    ).list_statuses()
    return next((status for status in statuses if status.issue == issue), None)
