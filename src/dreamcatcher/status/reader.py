"""Derive assignment and conversation status from persisted observations."""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, cast

from dreamcatcher.agent_assignments import (
    Assignment,
    find_open_assignments_by_issue,
)
from dreamcatcher.feed import FeedLine, describe_agent_round_start, read_last_feed_line
from dreamcatcher.issue_conversations import Conversation
from dreamcatcher.lock import read_daemon_pid
from dreamcatcher.scheduler.faults import derive_agent_work_fault, read_scheduler_record
from dreamcatcher.scheduler.models import (
    AgentWorkObservation,
    ConversationObservation,
    IssueFact,
    IssueFactValue,
    IssueObservation,
    SchedulerRecord,
    derive_round_purpose,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status.assignments import (
    AssignmentStatus,
    AssignmentStatusValue,
)
from dreamcatcher.status.conversations import (
    ConversationStatus,
    ConversationStatusValue,
    ConversationSummary,
    describe_unfinished_conversation_round,
    summarize_observed_conversation,
)
from dreamcatcher.words import describe_count, describe_span

if TYPE_CHECKING:
    from dreamcatcher.agent_rounds import (
        StoppedAgentRoundEnding,
        SuccessfulAgentRoundEnding,
    )


class StatusReportReader:
    """Read the local facts required for one status report."""

    def __init__(self, *, state: StateDirectory, clock: Callable[[], datetime]) -> None:
        """Read the daemon and latest complete scheduler record once."""
        self.state = state
        self.at = clock()
        self.daemon_pid = read_daemon_pid(path=state.lock)
        self.scheduler_record: SchedulerRecord | None = read_scheduler_record(
            state=state, at=self.at
        )
        self.assignment_observations: dict[str, AgentWorkObservation] = (
            {}
            if self.scheduler_record is None
            else {
                observation.identifier: observation
                for observation in self.scheduler_record.assignment_observations
            }
        )
        self.conversation_observations: dict[int, ConversationObservation] = (
            {}
            if self.scheduler_record is None
            else {
                observation.issue: observation
                for observation in self.scheduler_record.conversation_observations
            }
        )

    def list_issue_observations(
        self, *, assignments: list[Assignment]
    ) -> list[IssueObservation]:
        """Return refreshed issue observations in scheduler order."""
        if self.scheduler_record is None:
            return []
        assignments_by_issue: dict[int, list[Assignment]] = {}
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
        assignments: list[Assignment],
        recorded_at: datetime,
    ) -> IssueObservation:
        """Refresh one observation's local claim and missing observation time."""
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

    def list_assignment_statuses(
        self, *, assignments: list[Assignment]
    ) -> list[AssignmentStatus]:
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
        self, *, conversations: list[Conversation]
    ) -> list[ConversationStatus]:
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
        self, *, conversation: Conversation
    ) -> ConversationStatus:
        """Derive a saved conversation's summary from its records and latest tick."""
        return self._compose_conversation_status(
            issue=conversation.record.issue,
            title=conversation.record.title,
            conversation=conversation,
            summary=self._summarize_conversation(conversation=conversation),
        )

    def _read_unsaved_conversation_status(
        self, *, observation: ConversationObservation
    ) -> ConversationStatus:
        """Derive the summary of an observed issue with no saved conversation yet."""
        return self._compose_conversation_status(
            issue=observation.issue,
            title=observation.title,
            conversation=None,
            summary=summarize_observed_conversation(
                observation=observation, conversation=None
            ),
        )

    def _summarize_conversation(
        self, *, conversation: Conversation
    ) -> ConversationSummary:
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
            return ConversationSummary(
                value=ConversationStatusValue.UNKNOWN,
                detail="no current scheduler observation",
            )
        observation = self.conversation_observations.get(conversation.record.issue)
        if observation is None:
            return ConversationSummary(
                value=ConversationStatusValue.IDLE,
                detail="issue is not eligible for conversation",
            )
        if (
            observation.routing_conflict.value is not IssueFactValue.FALSE
            or observation.requires_round.value is IssueFactValue.UNKNOWN
        ):
            return summarize_observed_conversation(
                observation=observation,
                conversation=conversation,
            )
        if self._has_conversation_fault(conversation=conversation):
            return ConversationSummary(
                value=ConversationStatusValue.FAULT,
                detail=(
                    describe_unfinished_conversation_round(conversation=conversation)
                    or "two consecutive rounds errored"
                ),
            )
        return summarize_observed_conversation(
            observation=observation, conversation=conversation
        )

    def _has_conversation_fault(self, *, conversation: Conversation) -> bool:
        """Return whether the eligible conversation exhausted its retries."""
        scheduler_record = cast("SchedulerRecord", self.scheduler_record)
        return derive_agent_work_fault(
            rounds=conversation.rounds,
            retry_requested_at=conversation.record.retry_requested_at,
            most_recent_cooldown_ended=scheduler_record.most_recent_cooldown_ended,
        )

    def _summarize_working_conversation(
        self, *, conversation: Conversation
    ) -> ConversationSummary:
        """Describe the conversation's running round and its latest output."""
        latest = conversation.rounds[-1]
        line = read_last_feed_line(
            path=conversation.compose_round_paths(number=latest.number).feed
        )
        since_started = describe_span(span=self.at - latest.started)
        detail = f"round {latest.number}, running {since_started}"
        if line is None:
            return ConversationSummary(
                value=ConversationStatusValue.WORKING,
                detail=f"{detail}, has said nothing yet",
            )
        since_output = describe_span(span=self.at - line.at)
        return ConversationSummary(
            value=ConversationStatusValue.WORKING,
            detail=f"{detail}, last output {since_output} ago",
            latest_output=line.text.strip(),
        )

    def _compose_conversation_status(
        self,
        *,
        issue: int,
        title: str,
        conversation: Conversation | None,
        summary: ConversationSummary,
    ) -> ConversationStatus:
        """Return a summary status from the conversation's current facts.

        The status report lists a conversation while a round runs for it, or
        while the latest tick observed its issue, or when there is no tick yet.
        """
        return ConversationStatus(
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
                summary.value is ConversationStatusValue.WORKING
                or self.scheduler_record is None
                or issue in self.conversation_observations
            ),
        )

    def _read_assignment_status(self, *, assignment: Assignment) -> AssignmentStatus:
        """Derive an assignment's summary from local facts and its observation."""
        local_status = self._read_local_assignment_status(assignment=assignment)
        if local_status is not None:
            return local_status
        observation = self.assignment_observations.get(assignment.identifier)
        ending = cast(
            "SuccessfulAgentRoundEnding | StoppedAgentRoundEnding",
            assignment.rounds[-1].ending,
        )
        if (
            self.scheduler_record is not None
            and ending.at > self.scheduler_record.at
            and (
                observation is None
                or assignment.identifier
                in self.scheduler_record.launched_agent_work_identifiers
            )
        ):
            return self._compose_assignment_status(
                assignment=assignment,
                value=AssignmentStatusValue.WAITING,
                detail=(
                    f"round {assignment.rounds[-1].number} ended, awaiting next update"
                ),
            )
        if observation is None:
            return self._compose_assignment_status(
                assignment=assignment,
                value=AssignmentStatusValue.UNKNOWN,
                detail="no current scheduler observation",
            )
        if observation.requires_round.value is IssueFactValue.UNKNOWN:
            return self._compose_assignment_status(
                assignment=assignment,
                value=AssignmentStatusValue.UNKNOWN,
                detail=observation.requires_round.evidence,
            )
        if observation.requires_round.value is IssueFactValue.FALSE:
            return self._compose_assignment_status(
                assignment=assignment,
                value=AssignmentStatusValue.NEEDS_USER_FEEDBACK,
                detail=self._describe_idle_assignment(assignment=assignment),
            )
        return self._compose_assignment_status(
            assignment=assignment,
            value=AssignmentStatusValue.WAITING,
            detail=self._describe_next_round(assignment=assignment),
        )

    def _read_local_assignment_status(
        self, *, assignment: Assignment
    ) -> AssignmentStatus | None:
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
            return self._compose_assignment_status(
                assignment=assignment,
                value=AssignmentStatusValue.FAULT,
                detail=self._describe_fault_with_feed(
                    assignment=assignment,
                    reason="two consecutive rounds failed",
                ),
            )
        if (
            assignment.rounds and assignment.rounds[-1].ending is None
        ) or assignment.describe_unfinished_round() is not None:
            return self._read_unfinished_assignment_status(assignment=assignment)
        if assignment.is_complete:
            return self._compose_assignment_status(
                assignment=assignment,
                value=AssignmentStatusValue.COMPLETE,
                detail=describe_count(number=len(assignment.rounds), noun="round"),
            )
        if not assignment.rounds:
            return self._compose_assignment_status(
                assignment=assignment,
                value=AssignmentStatusValue.WAITING,
                detail=self._describe_next_round(assignment=assignment),
            )
        return None

    def _read_unfinished_assignment_status(
        self, *, assignment: Assignment
    ) -> AssignmentStatus:
        """Derive the status of an assignment whose latest round did not finish."""
        if self.daemon_pid is not None and assignment.rounds[-1].ending is None:
            detail, latest_output = self._describe_running_assignment(
                assignment=assignment
            )
            return self._compose_assignment_status(
                assignment=assignment,
                value=AssignmentStatusValue.WORKING,
                detail=detail,
                latest_output=latest_output,
            )
        return self._compose_assignment_status(
            assignment=assignment,
            value=AssignmentStatusValue.WAITING,
            detail=self._describe_next_round(assignment=assignment),
        )

    def _compose_assignment_status(
        self,
        *,
        assignment: Assignment,
        value: AssignmentStatusValue,
        detail: str,
        latest_output: str | None = None,
    ) -> AssignmentStatus:
        """Return a summary status from the assignment's current facts."""
        return AssignmentStatus(
            assignment=assignment,
            value=value,
            detail=detail,
            latest_output=latest_output,
            observed_at=(
                None if self.scheduler_record is None else self.scheduler_record.at
            ),
        )

    def _describe_running_assignment(
        self, *, assignment: Assignment
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

    def _describe_idle_assignment(self, *, assignment: Assignment) -> str:
        """Describe how long the assignment has awaited user feedback."""
        line = self._read_last_output(assignment=assignment)
        if line is None:
            return "idle"
        return f"idle {describe_span(span=self.at - line.at)}"

    def _describe_next_round(self, *, assignment: Assignment) -> str:
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
            is_recovery=(
                record.ending is None
                or assignment.describe_unfinished_round() is not None
            ),
        )
        return f"next round, {description}"

    def _read_last_output(self, *, assignment: Assignment) -> FeedLine | None:
        """Read the last complete line from the assignment's latest feed."""
        return read_last_feed_line(
            path=assignment.compose_round_paths(
                number=assignment.rounds[-1].number
            ).feed
        )

    def _describe_fault_with_feed(self, *, assignment: Assignment, reason: str) -> str:
        """Describe a fault with its latest feed output when available."""
        line = self._read_last_output(assignment=assignment)
        if line is not None:
            return line.text.strip()
        feed = assignment.compose_round_paths(number=assignment.rounds[-1].number).feed
        return f"{reason} ({self.state.describe_path(path=feed)})"
