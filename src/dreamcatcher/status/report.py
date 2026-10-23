"""Read status reports for a dreamcatcher instance."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkEnding,
    read_agent_work,
)
from dreamcatcher.campaigns import CampaignChild
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import read_json_if_exists, read_text
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.lock import is_daemon_lock_held
from dreamcatcher.scheduler.faults import read_scheduler_record
from dreamcatcher.scheduler.models import GlobalCooldown, SchedulerRecord
from dreamcatcher.state import StateDirectory
from dreamcatcher.status.agent_work import (
    AGENT_WORK_STATUS_VALUES_IN_ATTENTION_ORDER,
    AgentWorkStatus,
    AgentWorkStatusReader,
)
from dreamcatcher.status.requests import RequestStatus, describe_request
from dreamcatcher.words import describe_countdown, describe_span

# The guidance that an empty section of each kind gives, naming its labels.
_EMPTY_SECTION_GUIDANCE = {
    AgentWorkKind.ASSIGNMENT: (
        "Assign an issue to yourself and label it with {labels} "
        "to create an assignment."
    ),
    AgentWorkKind.CONVERSATION: (
        "Assign an issue to yourself, label it with {labels} "
        "and post a comment to start a conversation."
    ),
    AgentWorkKind.CAMPAIGN: (
        "Assign a parent issue to yourself and label it with {labels} "
        "to start a campaign."
    ),
}


@dataclass(frozen=True, kw_only=True)
class StatusFact:
    """Hold one labelled fact that a view shows."""

    label: str
    value: str
    is_warning: bool = False


@dataclass(frozen=True, kw_only=True)
class DaemonStatusFact:
    """Describe the labelled daemon state that both status views show."""

    label: str
    state: str
    version: str | None
    process: str | None

    @property
    def value(self) -> str:
        """The daemon state, version and process in display order."""
        return " · ".join(filter(None, (self.state, self.version, self.process)))


@dataclass(frozen=True, kw_only=True)
class AgentWorkStatusSection:
    """Describe one kind of agent work as a status view shows it."""

    heading: str
    empty_message: str | None


@dataclass(frozen=True, kw_only=True)
class CampaignChildStatus:
    """Describe where one child of an active campaign stands.

    The assignment is the newest local assignment at the child's issue, and
    the requests are the child's requests for an assignment that have no open
    work.
    """

    child: CampaignChild
    assignment: AgentWorkStatus | None
    requests: list[RequestStatus]


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
    def preferred_harness(self) -> AgentHarness | None:
        """The preferred harness given to the current or latest `dreamcatcher run`."""
        return None if self.run is None else self.run.preferred_harness

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

    def list_labels(self, *, kind: AgentWorkKind) -> tuple[str, ...]:
        """Return the labels of one kind that the current or latest run routes."""
        return () if self.run is None else self.run.list_labels(kind=kind)

    @property
    def status_fact(self) -> DaemonStatusFact:
        """Whether the daemon runs, with its version and process ID when it does."""
        if not self.is_running:
            return DaemonStatusFact(
                label="daemon", state="not running", version=None, process=None
            )
        version = (
            None
            if self.dreamcatcher_version is None
            else f"dreamcatcher v{self.dreamcatcher_version}"
        )
        process = None if self.pid is None else f"pid {self.pid}"
        return DaemonStatusFact(
            label="daemon", state="running", version=version, process=process
        )


@dataclass(frozen=True, kw_only=True)
class DreamcatcherStatusReport:
    """Describe one dreamcatcher instance from its local state."""

    at: datetime
    repository: str | None
    daemon: DreamcatcherDaemonStatus
    latest_scheduler_tick: datetime | None
    scheduler_failures: tuple[str, ...]
    running_agents: int
    active_global_cooldown: GlobalCooldown | None
    request_statuses: list[RequestStatus]
    work_statuses: list[AgentWorkStatus]

    @property
    def instance_facts(self) -> tuple[StatusFact, ...]:
        """The known instance facts, in the order that a view shows them.

        A global cooldown is a warning.
        """
        daemon = self.daemon
        cooldown = self.active_global_cooldown
        facts = (
            (
                "preferred harness",
                None
                if daemon.preferred_harness is None
                else str(daemon.preferred_harness),
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
        )
        return tuple(
            StatusFact(label=label, value=value, is_warning=is_warning)
            for label, value, is_warning in facts
            if value is not None
        )

    def describe_section(self, *, kind: AgentWorkKind) -> AgentWorkStatusSection | None:
        """Describe one kind's section, shown once the kind is routed or has work.

        The guidance shows only while nothing of the kind is active, and names
        the labels that the current or latest daemon run routes.
        """
        labels = self.daemon.list_labels(kind=kind)
        work_statuses = self._list_work_statuses(kind=kind)
        request_statuses = self.list_request_statuses(kind=kind)
        if not (labels or work_statuses or request_statuses):
            return None
        is_active = bool(
            request_statuses or any(status.is_active for status in work_statuses)
        )
        return AgentWorkStatusSection(
            heading=f"{kind}s",
            empty_message=(
                None
                if is_active or not labels
                else _EMPTY_SECTION_GUIDANCE[kind].format(
                    labels=_describe_route_labels(labels=labels)
                )
            ),
        )

    def list_request_statuses(self, *, kind: AgentWorkKind) -> list[RequestStatus]:
        """Return the requests of one kind with no open work, in the tick's order."""
        return [status for status in self.request_statuses if status.row.kind is kind]

    def list_active_work_statuses(
        self, *, kind: AgentWorkKind
    ) -> list[AgentWorkStatus]:
        """Return the work of one kind that has not ended, in attention order."""
        return sorted(
            (
                status
                for status in self._list_work_statuses(kind=kind)
                if status.is_active
            ),
            key=lambda status: AGENT_WORK_STATUS_VALUES_IN_ATTENTION_ORDER.index(
                status.value
            ),
        )

    def list_ended_work_statuses(self, *, kind: AgentWorkKind) -> list[AgentWorkStatus]:
        """Return the work of one kind that has ended, most recently ended first."""
        return sorted(
            (
                status
                for status in self._list_work_statuses(kind=kind)
                if status.has_ended
            ),
            key=lambda status: cast("AgentWorkEnding", status.work.ending).at,
            reverse=True,
        )

    def list_campaign_child_statuses(
        self, *, campaign: AgentWorkStatus
    ) -> list[CampaignChildStatus]:
        """Return where each of an active campaign's children stands, in order.

        A campaign has none when its status gives it no children, as when its
        children are unknown. Each child's assignment is the newest local
        assignment at the child's issue, so its card shows before the next tick
        records the assignment on the campaign.
        """
        assignments = {
            status.work.record.issue: status
            for status in sorted(
                self._list_work_statuses(kind=AgentWorkKind.ASSIGNMENT),
                key=lambda status: status.work.identifier,
            )
        }
        requests = self.list_request_statuses(kind=AgentWorkKind.ASSIGNMENT)
        return [
            CampaignChildStatus(
                child=child,
                assignment=assignments.get(child.issue),
                requests=[
                    request for request in requests if request.row.issue == child.issue
                ],
            )
            for child in campaign.children or ()
        ]

    def _list_work_statuses(self, *, kind: AgentWorkKind) -> list[AgentWorkStatus]:
        return [
            status for status in self.work_statuses if status.work.record.kind is kind
        ]


def _describe_route_labels(*, labels: tuple[str, ...]) -> str:
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} or {labels[-1]}"


def read_status_report(
    *, state: StateDirectory, clock: Callable[[], datetime] = read_current_time
) -> DreamcatcherStatusReport:
    """Read a status report from local state alone."""
    daemon = read_dreamcatcher_daemon_status(state=state)
    reader = _create_status_reader(state=state, daemon=daemon, clock=clock)
    scheduler_record = reader.scheduler_record
    work_statuses = [
        reader.derive(work=work)
        for work in _sort_by_issue_newest_first(work=read_agent_work(state=state))
    ]
    request_statuses = (
        []
        if scheduler_record is None
        else [
            describe_request(row=row)
            for row in scheduler_record.rows
            if row.agent_work_identifier is None
        ]
    )
    return DreamcatcherStatusReport(
        at=reader.at,
        repository=read_repository(state=state),
        daemon=daemon,
        latest_scheduler_tick=(
            None if scheduler_record is None else scheduler_record.at
        ),
        scheduler_failures=(
            ()
            if scheduler_record is None or not daemon.is_running
            else tuple(scheduler_record.failures)
        ),
        running_agents=sum(status.is_working for status in work_statuses),
        active_global_cooldown=(
            None if scheduler_record is None else scheduler_record.cooldown
        ),
        request_statuses=request_statuses,
        work_statuses=work_statuses,
    )


def _read_status_facts(
    *, state: StateDirectory, clock: Callable[[], datetime]
) -> tuple[datetime, SchedulerRecord | None]:
    at = clock()
    return at, read_scheduler_record(state=state, at=at)


def _sort_by_issue_newest_first(*, work: list[AgentWork]) -> list[AgentWork]:
    """Return the work in ascending issue order, the newest at each issue first."""
    newest_first = sorted(work, key=lambda item: item.identifier, reverse=True)
    return sorted(newest_first, key=lambda item: item.record.issue)


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


def read_agent_work_status(
    *,
    state: StateDirectory,
    work: AgentWork,
    daemon: DreamcatcherDaemonStatus,
    clock: Callable[[], datetime] = read_current_time,
) -> AgentWorkStatus:
    """Read the status of one piece of agent work, of any kind.

    The caller reads the daemon status, so a view that also shows it shows the
    same answer that its round statuses came from.
    """
    reader = _create_status_reader(state=state, daemon=daemon, clock=clock)
    return reader.derive(work=work)


def _create_status_reader(
    *,
    state: StateDirectory,
    daemon: DreamcatcherDaemonStatus,
    clock: Callable[[], datetime],
) -> AgentWorkStatusReader:
    at, scheduler_record = _read_status_facts(state=state, clock=clock)
    return AgentWorkStatusReader(
        state=state,
        at=at,
        is_daemon_running=daemon.is_running,
        scheduler_record=scheduler_record,
    )
