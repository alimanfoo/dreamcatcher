"""Read status reports for a Dreamcatcher instance."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cached_property
from typing import cast

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    find_harness_session_identifier,
    find_open_agent_assignments_by_issue,
    read_agent_assignment,
    read_agent_assignments,
    read_agent_assignments_for_issue,
)
from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundRecord,
    ErroredAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import read_json, read_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import (
    FeedLine,
    describe_agent_round_start,
    read_last_feed_line,
)
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.issue_conversations import (
    IssueConversation,
    describe_issue_conversation_revision,
    is_no_reply,
    read_issue_conversation,
    read_issue_conversation_input,
    read_issue_conversations,
)
from dreamcatcher.lock import read_daemon_pid
from dreamcatcher.scheduler import (
    AgentAssignmentObservation,
    GlobalCooldown,
    IssueConversationObservation,
    IssueFact,
    IssueFactValue,
    IssueObservation,
    derive_agent_work_fault,
    derive_round_purpose,
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


class IssueConversationStatusValue(StrEnum):
    """List the summary statuses of an issue conversation.

    Shared words mean what they mean for an assignment. Routing conflict means
    that the user must remove all but one conversation label before work can
    start. Idle takes the place of needs user feedback, because a conversation
    at rest has posted its answer and asks nothing of the user. Fault takes two
    consecutive errored rounds.
    """

    ROUTING_CONFLICT = "routing conflict"
    WORKING = "working"
    WAITING = "waiting"
    IDLE = "idle"
    FAULT = "fault"
    UNKNOWN = "unknown"


ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER = (
    AgentAssignmentStatusValue.NEEDS_USER_FEEDBACK,
    AgentAssignmentStatusValue.FAULT,
    AgentAssignmentStatusValue.WORKING,
    AgentAssignmentStatusValue.WAITING,
    AgentAssignmentStatusValue.UNKNOWN,
    AgentAssignmentStatusValue.COMPLETE,
)

# Idle comes last because a conversation at rest asks nothing of the user.
CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER = (
    IssueConversationStatusValue.ROUTING_CONFLICT,
    IssueConversationStatusValue.FAULT,
    IssueConversationStatusValue.WORKING,
    IssueConversationStatusValue.WAITING,
    IssueConversationStatusValue.UNKNOWN,
    IssueConversationStatusValue.IDLE,
)

STATUSES_THAT_END_A_VIEW = (
    AgentAssignmentStatusValue.FAULT,
    AgentAssignmentStatusValue.COMPLETE,
)


@dataclass(frozen=True, kw_only=True)
class AgentRoundStatus:
    """Describe one agent round for a status view."""

    record: AgentRoundRecord
    duration_description: str
    outcome_description: str
    revision: str | None = None
    revision_description: str | None = None


@dataclass(frozen=True, kw_only=True)
class _ConversationSummary:
    """Hold the status, detail and latest output derived for one conversation."""

    value: IssueConversationStatusValue
    detail: str
    latest_output: str | None = None


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
                duration_description=_compose_round_duration_description(record=record),
                outcome_description=_describe_round_outcome(
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


@dataclass(frozen=True, kw_only=True)
class IssueConversationStatus:
    """Describe an issue conversation's derived summary status.

    An eligible issue has a conversation from the first tick that observes it,
    but no saved conversation until its first round launches.
    """

    issue: int
    title: str
    conversation: IssueConversation | None
    value: IssueConversationStatusValue
    detail: str
    latest_output: str | None
    observed_at: datetime | None
    is_listed: bool

    @property
    def is_over(self) -> bool:
        """Whether nothing more can happen until the user acts.

        A faulted or conflicted conversation waits for the user to act, and one
        that the status report no longer lists waits for its issue to be eligible
        again.
        """
        return (
            self.value
            in {
                IssueConversationStatusValue.FAULT,
                IssueConversationStatusValue.ROUTING_CONFLICT,
            }
            or not self.is_listed
        )

    @cached_property
    def round_statuses(self) -> list[AgentRoundStatus]:
        """The derived status of every round in conversation order."""
        conversation = self.conversation
        if conversation is None:
            return []
        statuses: list[AgentRoundStatus] = []
        previous_revision = None
        for record in conversation.rounds:
            revision = None
            revision_description = None
            try:
                round_input = read_issue_conversation_input(
                    conversation=conversation,
                    number=record.number,
                )
                revision = round_input.revision
                revision_description = describe_issue_conversation_revision(
                    previous_revision=previous_revision,
                    revision=revision,
                )
                previous_revision = revision
            except ReportableError:
                pass
            statuses.append(
                AgentRoundStatus(
                    record=record,
                    duration_description=_compose_round_duration_description(
                        record=record
                    ),
                    outcome_description=_describe_round_outcome(
                        record=record,
                        is_running=(
                            self.value is IssueConversationStatusValue.WORKING
                            and record.number == conversation.rounds[-1].number
                        ),
                    ),
                    revision=revision,
                    revision_description=revision_description,
                )
            )
        return statuses


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
    reader = _StatusReportReader(state=state, clock=clock)
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
        running_agents=sum(
            status.value is AgentAssignmentStatusValue.WORKING
            for status in assignment_statuses
        )
        + sum(
            status.value is IssueConversationStatusValue.WORKING
            for status in conversation_statuses
        ),
        active_global_cooldown=(
            None if scheduler_record is None else scheduler_record.cooldown
        ),
        failed_assignment_setups=[
            observation
            for observation in issue_observations
            if observation.setup_failure is not None
        ],
        available_issues=[
            observation
            for observation in issue_observations
            if observation.availability.value is IssueFactValue.TRUE
        ],
        blocked_issues=[
            observation
            for observation in issue_observations
            if observation.blocked.value is IssueFactValue.TRUE
        ],
        assignment_statuses=assignment_statuses,
        conversation_statuses=conversation_statuses,
    )


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
    reader = _StatusReportReader(state=state, clock=clock)
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
    reader = _StatusReportReader(state=state, clock=clock)
    return reader.list_assignment_statuses(assignments=[assignment])[0]


def read_issue_conversation_status(
    *,
    state: StateDirectory,
    issue: int,
    clock: Callable[[], datetime] = read_current_time,
) -> IssueConversationStatus | None:
    """Read one issue conversation's status by its issue number.

    An issue has a conversation once it has a saved conversation or the latest
    tick observed it as eligible.
    """
    conversation = read_issue_conversation(state=state, issue=issue)
    reader = _StatusReportReader(state=state, clock=clock)
    statuses = reader.list_conversation_statuses(
        conversations=[] if conversation is None else [conversation]
    )
    return next((status for status in statuses if status.issue == issue), None)


def _summarize_observed_conversation(
    *,
    observation: IssueConversationObservation,
    conversation: IssueConversation | None,
) -> _ConversationSummary:
    """Return what an eligible issue says about its conversation.

    An unknown or conflicting route comes first, then unknown comments, a round
    waiting to be recovered, and comments waiting to be answered.
    """
    routing_conflict = observation.routing_conflict
    if routing_conflict.value is IssueFactValue.UNKNOWN:
        return _ConversationSummary(
            value=IssueConversationStatusValue.UNKNOWN,
            detail=routing_conflict.evidence,
        )
    if routing_conflict.value is IssueFactValue.TRUE:
        return _ConversationSummary(
            value=IssueConversationStatusValue.ROUTING_CONFLICT,
            detail=routing_conflict.evidence,
        )
    has_comments_to_answer = observation.has_comments_to_answer
    if has_comments_to_answer.value is IssueFactValue.UNKNOWN:
        return _ConversationSummary(
            value=IssueConversationStatusValue.UNKNOWN,
            detail=has_comments_to_answer.evidence,
        )
    unfinished_round = _describe_unfinished_conversation_round(
        conversation=conversation
    )
    if unfinished_round is not None:
        return _ConversationSummary(
            value=IssueConversationStatusValue.WAITING, detail=unfinished_round
        )
    if has_comments_to_answer.value is IssueFactValue.TRUE:
        return _ConversationSummary(
            value=IssueConversationStatusValue.WAITING,
            detail=has_comments_to_answer.evidence,
        )
    return _ConversationSummary(
        value=IssueConversationStatusValue.IDLE,
        detail=_describe_idle_conversation(conversation=conversation),
    )


def _describe_unfinished_conversation_round(
    *, conversation: IssueConversation | None
) -> str | None:
    """Describe the conversation's latest round if it errored or was interrupted.

    A round with no ending that no daemon is running was interrupted.
    """
    if conversation is None or not conversation.rounds:
        return None
    latest = conversation.rounds[-1]
    if latest.outcome is AgentRoundOutcome.SUCCESSFUL:
        return None
    ending = latest.ending
    if isinstance(ending, ErroredAgentRoundEnding) and ending.reason is not None:
        return f"round {latest.number} errored: {ending.reason}"
    outcome = _describe_round_outcome(record=latest, is_running=False)
    return f"round {latest.number} {outcome}"


def _describe_idle_conversation(*, conversation: IssueConversation | None) -> str:
    """Describe a conversation that has answered every comment it was given.

    Its latest round succeeded, so that round's final output was saved.
    """
    if conversation is None or not conversation.rounds:
        return "no comments yet"
    latest = conversation.rounds[-1]
    final_output = read_text(
        path=conversation.compose_round_paths(number=latest.number).final_output
    )
    answer = "no reply needed" if is_no_reply(final_output=final_output) else "answered"
    duration = _compose_round_duration_description(record=latest)
    return f"round {latest.number}, {answer}, {duration}"


def _compose_round_duration_description(*, record: AgentRoundRecord) -> str:
    ending = record.ending
    if ending is None or ending.outcome is AgentRoundOutcome.INTERRUPTED:
        return ""
    return f"ran {describe_span(span=ending.at - record.started)}"


def _describe_round_outcome(*, record: AgentRoundRecord, is_running: bool) -> str:
    """Return how the round ended, or what it is doing instead.

    A round that recorded no ending never finished. It is running when a daemon
    is still there to run it, and interrupted once that daemon has gone, since
    a round cannot outlive its daemon. A round that errored for a reason, after
    its harness exited cleanly, reads as errored alone, since its exit status
    says nothing and its reason is too long for a list of rounds.
    """
    if isinstance(record.ending, ErroredAgentRoundEnding):
        if record.ending.reason is not None:
            return str(AgentRoundOutcome.ERRORED)
        return f"errored (exit {record.ending.status})"
    if record.ending is None and not is_running:
        return str(AgentRoundOutcome.INTERRUPTED)
    return str(record.outcome)


class _StatusReportReader:
    """Read the local facts required for one status report."""

    def __init__(self, *, state: StateDirectory, clock: Callable[[], datetime]) -> None:
        """Read the daemon and latest complete scheduler record once."""
        self.state = state
        self.at = clock()
        self.daemon_pid = read_daemon_pid(path=state.lock)
        self.scheduler_record = read_scheduler_record(state=state, at=self.at)
        self.assignment_observations: dict[str, AgentAssignmentObservation] = (
            {}
            if self.scheduler_record is None
            else {
                observation.assignment_identifier: observation
                for observation in self.scheduler_record.assignment_observations
            }
        )
        self.conversation_observations: dict[int, IssueConversationObservation] = (
            {}
            if self.scheduler_record is None
            else {
                observation.issue: observation
                for observation in self.scheduler_record.conversation_observations
            }
        )

    def list_issue_observations(
        self, *, assignments: list[AgentAssignment]
    ) -> list[IssueObservation]:
        """Return refreshed issue observations in scheduler order."""
        if self.scheduler_record is None:
            return []
        assignments_by_issue: dict[int, list[AgentAssignment]] = {}
        for assignment in assignments:
            assignments_by_issue.setdefault(assignment.record.issue, []).append(
                assignment
            )
        return [
            self._refresh_issue_observation(
                observation=observation,
                assignments=assignments_by_issue.get(observation.issue, []),
                recorded_at=self.scheduler_record.at,
            )
            for observation in self.scheduler_record.issue_observations
        ]

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

    def list_assignment_statuses(
        self, *, assignments: list[AgentAssignment]
    ) -> list[AgentAssignmentStatus]:
        """Return statuses in ascending issue order, newest at each issue first."""
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

    def list_conversation_statuses(
        self, *, conversations: list[IssueConversation]
    ) -> list[IssueConversationStatus]:
        """Return issue conversation statuses in ascending issue order.

        Every saved conversation has a status, and so does every issue that the
        latest tick observed but that has no saved conversation yet.
        """
        saved_issues = {conversation.record.issue for conversation in conversations}
        statuses = [
            self._read_conversation_status(conversation=conversation)
            for conversation in conversations
        ]
        statuses.extend(
            self._read_unsaved_conversation_status(observation=observation)
            for observation in self.conversation_observations.values()
            if observation.issue not in saved_issues
        )
        return sorted(statuses, key=lambda status: status.issue)

    def _read_conversation_status(
        self, *, conversation: IssueConversation
    ) -> IssueConversationStatus:
        """Derive a saved conversation's summary from its records and latest tick."""
        return self._compose_issue_conversation_status(
            issue=conversation.record.issue,
            title=conversation.record.title,
            conversation=conversation,
            summary=self._summarize_conversation(conversation=conversation),
        )

    def _read_unsaved_conversation_status(
        self, *, observation: IssueConversationObservation
    ) -> IssueConversationStatus:
        """Derive the summary of an observed issue with no saved conversation yet."""
        return self._compose_issue_conversation_status(
            issue=observation.issue,
            title=observation.title,
            conversation=None,
            summary=_summarize_observed_conversation(
                observation=observation, conversation=None
            ),
        )

    def _summarize_conversation(
        self, *, conversation: IssueConversation
    ) -> _ConversationSummary:
        """Return what a saved conversation's records and latest tick say.

        A running round comes first. The latest tick then establishes whether
        the issue is eligible; only an eligible conversation can be in fault or
        waiting for work.
        """
        if (
            conversation.rounds
            and conversation.rounds[-1].ending is None
            and self.daemon_pid is not None
        ):
            return self._summarize_working_conversation(conversation=conversation)
        if self.scheduler_record is None:
            return _ConversationSummary(
                value=IssueConversationStatusValue.UNKNOWN,
                detail="no current scheduler observation",
            )
        observation = self.conversation_observations.get(conversation.record.issue)
        if observation is None:
            return _ConversationSummary(
                value=IssueConversationStatusValue.IDLE,
                detail="issue is not eligible for conversation",
            )
        if (
            observation.routing_conflict.value is not IssueFactValue.FALSE
            or observation.has_comments_to_answer.value is IssueFactValue.UNKNOWN
        ):
            return _summarize_observed_conversation(
                observation=observation,
                conversation=conversation,
            )
        if derive_agent_work_fault(
            rounds=conversation.rounds,
            retry_requested_at=conversation.record.retry_requested_at,
            most_recent_cooldown_ended=(
                self.scheduler_record.most_recent_cooldown_ended
            ),
        ):
            return _ConversationSummary(
                value=IssueConversationStatusValue.FAULT,
                detail=(
                    _describe_unfinished_conversation_round(conversation=conversation)
                    or "two consecutive rounds errored"
                ),
            )
        return _summarize_observed_conversation(
            observation=observation, conversation=conversation
        )

    def _summarize_working_conversation(
        self, *, conversation: IssueConversation
    ) -> _ConversationSummary:
        """Describe the conversation's running round and its latest output."""
        latest = conversation.rounds[-1]
        line = read_last_feed_line(
            path=conversation.compose_round_paths(number=latest.number).feed
        )
        since_started = describe_span(span=self.at - latest.started)
        detail = f"round {latest.number}, running {since_started}"
        if line is None:
            return _ConversationSummary(
                value=IssueConversationStatusValue.WORKING,
                detail=f"{detail}, has said nothing yet",
            )
        since_output = describe_span(span=self.at - line.at)
        return _ConversationSummary(
            value=IssueConversationStatusValue.WORKING,
            detail=f"{detail}, last output {since_output} ago",
            latest_output=line.text.strip(),
        )

    def _compose_issue_conversation_status(
        self,
        *,
        issue: int,
        title: str,
        conversation: IssueConversation | None,
        summary: _ConversationSummary,
    ) -> IssueConversationStatus:
        """Return a summary status from the conversation's current facts.

        The status report lists a conversation while a round runs for it, or
        while the latest tick observed its issue, or when there is no tick yet.
        """
        return IssueConversationStatus(
            issue=issue,
            title=title,
            conversation=conversation,
            value=summary.value,
            detail=summary.detail,
            latest_output=summary.latest_output,
            observed_at=(
                None if self.scheduler_record is None else self.scheduler_record.at
            ),
            is_listed=(
                summary.value is IssueConversationStatusValue.WORKING
                or self.scheduler_record is None
                or issue in self.conversation_observations
            ),
        )

    def _read_assignment_status(
        self, *, assignment: AgentAssignment
    ) -> AgentAssignmentStatus:
        """Derive an assignment's summary from local facts and its observation."""
        local_status = self._read_local_assignment_status(assignment=assignment)
        if local_status is not None:
            return local_status
        observation = self.assignment_observations.get(assignment.identifier)
        if observation is None:
            ending = cast("SuccessfulAgentRoundEnding", assignment.rounds[-1].ending)
            if (
                self.scheduler_record is not None
                and ending.at > self.scheduler_record.at
            ):
                return self._compose_agent_assignment_status(
                    assignment=assignment,
                    value=AgentAssignmentStatusValue.WAITING,
                    detail=(
                        f"round {assignment.rounds[-1].number} ended, "
                        "awaiting next update"
                    ),
                )
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
            detail=self._describe_next_round(assignment=assignment),
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
        if derive_agent_work_fault(
            rounds=assignment.rounds,
            retry_requested_at=assignment.record.retry_requested_at,
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
                detail=self._describe_next_round(assignment=assignment),
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
                detail=self._describe_next_round(assignment=assignment),
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
        record = assignment.rounds[-1]
        since_started = describe_span(span=self.at - record.started)
        purpose = describe_agent_round_start(
            purpose=record.purpose, is_recovery=record.is_recovery
        )
        detail = f"round {record.number}, {purpose}, running {since_started}"
        line = self._read_last_output(assignment=assignment)
        if line is None:
            return f"{detail}, has said nothing yet", None
        since_last_output = describe_span(span=self.at - line.at)
        return (
            f"{detail}, last output {since_last_output} ago",
            line.text.strip(),
        )

    def _describe_idle_assignment(self, *, assignment: AgentAssignment) -> str:
        """Describe how long the assignment has awaited user feedback."""
        line = self._read_last_output(assignment=assignment)
        if line is None:
            return "idle"
        return f"idle {describe_span(span=self.at - line.at)}"

    def _describe_next_round(self, *, assignment: AgentAssignment) -> str:
        """Describe the work the assignment requires next."""
        if not assignment.rounds:
            return "next round, implement"
        record = assignment.rounds[-1]
        pull_request = assignment.record.pull_request_observation
        purpose = (
            record.purpose
            if pull_request is None
            else derive_round_purpose(pull_request=pull_request)
        )
        description = describe_agent_round_start(
            purpose=purpose,
            is_recovery=assignment.describe_unfinished_round() is not None,
        )
        return f"next round, {description}"

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
