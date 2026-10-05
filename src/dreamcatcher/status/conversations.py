"""Represent and summarize the derived status of issue conversations."""

from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
)
from dreamcatcher.documents import read_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.issue_conversations import (
    Conversation,
    describe_conversation_revision,
    is_conversation_ready_for_input,
    is_no_reply,
    read_conversation_input,
)
from dreamcatcher.scheduler.models import (
    ConversationObservation,
    IssueFactValue,
)
from dreamcatcher.status.agent_work import (
    AgentWorkStatusReader,
    compose_hand_resume_command,
)
from dreamcatcher.status.rounds import (
    AgentRoundRevision,
    AgentRoundStatus,
    compose_round_duration_description,
    describe_round_ending,
    describe_round_outcome,
    describe_running_round,
    find_stoppable_round_paths,
)


class ConversationStatusValue(StrEnum):
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


# Idle comes last because a conversation at rest asks nothing of the user.
CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER = (
    ConversationStatusValue.ROUTING_CONFLICT,
    ConversationStatusValue.FAULT,
    ConversationStatusValue.WORKING,
    ConversationStatusValue.WAITING,
    ConversationStatusValue.UNKNOWN,
    ConversationStatusValue.IDLE,
)


@dataclass(frozen=True, kw_only=True)
class ConversationStatus:
    """Describe an issue conversation's derived summary status.

    A matching issue has a status from the first tick that observes it, but no
    saved conversation until its first round launches.
    """

    issue: int
    title: str
    conversation: Conversation | None
    value: ConversationStatusValue
    detail: str
    latest_output: str | None
    is_listed: bool

    @property
    def is_over(self) -> bool:
        """Whether the work has ended or is stuck, so a live view stops following it.

        A faulted or conflicted conversation waits for the user to act, and one
        that the status report no longer lists waits for its issue to be eligible
        again.
        """
        return (
            self.value
            in {
                ConversationStatusValue.FAULT,
                ConversationStatusValue.ROUTING_CONFLICT,
            }
            or not self.is_listed
        )

    @cached_property
    def harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """The recorded or recoverable harness session identifier."""
        conversation = self.conversation
        if conversation is None:
            return None
        return conversation.find_harness_session_identifier()

    @cached_property
    def hand_resume_command(self) -> list[str] | None:
        """The hand-resume command when nobody is running the session."""
        conversation = self.conversation
        if conversation is None:
            return None
        return compose_hand_resume_command(
            is_working=self.value is ConversationStatusValue.WORKING,
            record=conversation.record,
            harness_session_identifier=self.harness_session_identifier,
        )

    @property
    def faulted_round_number(self) -> int | None:
        """The latest round while the conversation is in fault, else None."""
        conversation = self.conversation
        if conversation is None or self.value is not ConversationStatusValue.FAULT:
            return None
        return conversation.rounds[-1].number

    @cached_property
    def stoppable_round_paths(self) -> AgentRoundPaths | None:
        """The live round that can accept a stop request, when one exists."""
        conversation = self.conversation
        harness_session_identifier = (
            None
            if self.value is not ConversationStatusValue.WORKING
            else self.harness_session_identifier
        )
        return find_stoppable_round_paths(
            is_working=self.value is ConversationStatusValue.WORKING,
            harness_session_identifier=harness_session_identifier,
            paths=(
                None
                if conversation is None or not conversation.rounds
                else conversation.compose_round_paths(
                    number=conversation.rounds[-1].number
                )
            ),
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
            round_revision = None
            try:
                round_input = read_conversation_input(
                    conversation=conversation,
                    number=record.number,
                )
                revision = round_input.revision
                round_revision = AgentRoundRevision(
                    value=revision,
                    description=describe_conversation_revision(
                        previous_revision=previous_revision,
                        revision=revision,
                    ),
                )
                previous_revision = revision
            except ReportableError:
                pass
            statuses.append(
                AgentRoundStatus(
                    record=record,
                    duration_description=compose_round_duration_description(
                        record=record
                    ),
                    outcome_description=describe_round_outcome(
                        record=record,
                        is_working=(
                            self.value is ConversationStatusValue.WORKING
                            and record.number == conversation.rounds[-1].number
                        ),
                    ),
                    revision=round_revision,
                )
            )
        return statuses


@dataclass(frozen=True, kw_only=True)
class ConversationStatusReader(AgentWorkStatusReader[ConversationStatus]):
    """Derive conversation statuses from local state and the latest tick."""

    conversations: list[Conversation]

    @cached_property
    def observations(self) -> dict[int, ConversationObservation]:
        """The latest conversation observations, keyed by issue number."""
        if self.scheduler_record is None:
            return {}
        return {
            observation.issue: observation
            for observation in self.scheduler_record.conversation_observations
        }

    def list_statuses(self) -> list[ConversationStatus]:
        """Return saved and observed conversation statuses in issue order."""
        saved_issues = {
            conversation.record.issue for conversation in self.conversations
        }
        statuses = [
            self.derive(
                issue=conversation.record.issue,
                title=conversation.record.title,
                conversation=conversation,
            )
            for conversation in self.conversations
        ]
        statuses.extend(
            self.derive(
                issue=observation.issue,
                title=observation.title,
                conversation=None,
            )
            for observation in self.observations.values()
            if observation.issue not in saved_issues
        )
        return sorted(statuses, key=lambda status: status.issue)

    def derive(
        self,
        *,
        issue: int,
        title: str,
        conversation: Conversation | None,
    ) -> ConversationStatus:
        """Derive one conversation's status from its records and latest tick."""
        status = self._derive_working(
            issue=issue, title=title, conversation=conversation
        )
        if status is not None:
            return status
        status = self._derive_fault(issue=issue, title=title, conversation=conversation)
        if status is not None:
            return status
        status = self._derive_eligibility(
            issue=issue, title=title, conversation=conversation
        )
        if status is not None:
            return status
        status = self._derive_unfinished(
            issue=issue, title=title, conversation=conversation
        )
        if status is not None:
            return status
        return self._derive_observation(
            issue=issue, title=title, conversation=conversation
        )

    def _derive_working(
        self,
        *,
        issue: int,
        title: str,
        conversation: Conversation | None,
    ) -> ConversationStatus | None:
        if conversation is not None and conversation.rounds:
            latest = conversation.rounds[-1]
            if self.is_round_working(record=latest):
                detail, latest_output = describe_running_round(
                    record=latest,
                    paths=conversation.compose_round_paths(number=latest.number),
                    at=self.at,
                )
                return self._compose(
                    issue=issue,
                    title=title,
                    conversation=conversation,
                    value=ConversationStatusValue.WORKING,
                    detail=detail,
                    latest_output=latest_output,
                )
        return None

    def _derive_eligibility(
        self,
        *,
        issue: int,
        title: str,
        conversation: Conversation | None,
    ) -> ConversationStatus | None:
        ineligibility = self._find_ineligibility(issue=issue)
        if ineligibility is None:
            return None
        value, detail = ineligibility
        return self._compose(
            issue=issue,
            title=title,
            conversation=conversation,
            value=value,
            detail=detail,
        )

    def _find_ineligibility(
        self, *, issue: int
    ) -> tuple[ConversationStatusValue, str] | None:
        """Return the status and detail of an issue the latest tick cannot run."""
        if self.scheduler_record is None:
            return ConversationStatusValue.UNKNOWN, "no current scheduler observation"
        observation = self.observations.get(issue)
        if observation is None:
            return (
                ConversationStatusValue.IDLE,
                "issue is not eligible for conversation",
            )
        routing_conflict = observation.routing_conflict
        if routing_conflict.value is IssueFactValue.UNKNOWN:
            return ConversationStatusValue.UNKNOWN, routing_conflict.evidence
        if routing_conflict.value is IssueFactValue.TRUE:
            return ConversationStatusValue.ROUTING_CONFLICT, routing_conflict.evidence
        requires_round = observation.requires_round
        if requires_round.value is IssueFactValue.UNKNOWN:
            return ConversationStatusValue.UNKNOWN, requires_round.evidence
        return None

    def _derive_fault(
        self,
        *,
        issue: int,
        title: str,
        conversation: Conversation | None,
    ) -> ConversationStatus | None:
        if conversation is not None and self.has_fault(
            records=conversation.rounds,
            retry_requested_at=conversation.retry_requested_at,
        ):
            latest = conversation.rounds[-1]
            detail, latest_output = describe_round_ending(
                record=latest,
                paths=conversation.compose_round_paths(number=latest.number),
            )
            return self._compose(
                issue=issue,
                title=title,
                conversation=conversation,
                value=ConversationStatusValue.FAULT,
                detail=detail,
                latest_output=latest_output,
            )
        return None

    def _derive_unfinished(
        self,
        *,
        issue: int,
        title: str,
        conversation: Conversation | None,
    ) -> ConversationStatus | None:
        if conversation is not None and not is_conversation_ready_for_input(
            conversation=conversation
        ):
            latest = conversation.rounds[-1]
            detail, _ = describe_round_ending(
                record=latest,
                paths=conversation.compose_round_paths(number=latest.number),
            )
            return self._compose(
                issue=issue,
                title=title,
                conversation=conversation,
                value=ConversationStatusValue.WAITING,
                detail=detail,
            )
        return None

    def _derive_observation(
        self,
        *,
        issue: int,
        title: str,
        conversation: Conversation | None,
    ) -> ConversationStatus:
        if conversation is not None and conversation.rounds:
            latest = conversation.rounds[-1]
            if self.did_round_end_after_latest_tick(
                identifier=conversation.identifier,
                record=latest,
                is_observed=True,
            ):
                return self._compose(
                    issue=issue,
                    title=title,
                    conversation=conversation,
                    value=ConversationStatusValue.WAITING,
                    detail=f"round {latest.number} ended, awaiting next update",
                )
        requires_round = self.observations[issue].requires_round
        if requires_round.value is IssueFactValue.TRUE:
            return self._compose(
                issue=issue,
                title=title,
                conversation=conversation,
                value=ConversationStatusValue.WAITING,
                detail=requires_round.evidence,
            )
        return self._compose(
            issue=issue,
            title=title,
            conversation=conversation,
            value=ConversationStatusValue.IDLE,
            detail=self._describe_idle(conversation=conversation),
        )

    def _compose(
        self,
        *,
        issue: int,
        title: str,
        conversation: Conversation | None,
        value: ConversationStatusValue,
        detail: str,
        latest_output: str | None = None,
    ) -> ConversationStatus:
        return ConversationStatus(
            issue=issue,
            title=title,
            conversation=conversation,
            value=value,
            detail=detail,
            latest_output=latest_output,
            is_listed=(
                value is ConversationStatusValue.WORKING
                or self.scheduler_record is None
                or issue in self.observations
            ),
        )

    def _describe_idle(self, *, conversation: Conversation | None) -> str:
        if conversation is None or not conversation.rounds:
            return "no comments yet"
        latest = conversation.rounds[-1]
        duration = compose_round_duration_description(record=latest)
        if latest.outcome is AgentRoundOutcome.STOPPED:
            return f"round {latest.number}, stopped, {duration}"
        final_output = read_text(
            path=conversation.compose_round_paths(number=latest.number).final_output
        )
        answer = (
            "no reply needed" if is_no_reply(final_output=final_output) else "answered"
        )
        return f"round {latest.number}, {answer}, {duration}"
