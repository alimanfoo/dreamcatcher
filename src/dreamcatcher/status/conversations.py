"""Represent and summarize the derived status of issue conversations."""

from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
)
from dreamcatcher.agent_work import AgentWork, AgentWorkEnding
from dreamcatcher.documents import read_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.issue_conversations import (
    ConversationRoundInput,
    is_no_reply,
    read_conversation_input,
)
from dreamcatcher.scheduler.faults import is_last_round_unfinished
from dreamcatcher.scheduler.models import (
    ConversationObservation,
    Truth,
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
from dreamcatcher.words import describe_count


class ConversationStatusValue(StrEnum):
    """List the summary statuses of an issue conversation.

    Shared words mean what they mean for an assignment. Routing conflict means
    that the user must remove all but one conversation label before work can
    start. Idle takes the place of needs user feedback, because a conversation
    at rest has posted its answer and asks nothing of the user. Fault takes two
    consecutive errored rounds. Ended means that the conversation's ending is
    recorded.
    """

    ROUTING_CONFLICT = "routing conflict"
    WORKING = "working"
    WAITING = "waiting"
    IDLE = "idle"
    FAULT = "fault"
    UNKNOWN = "unknown"
    ENDED = "ended"


# Idle comes after the others because a conversation at rest asks nothing of the
# user, and ended comes last because nothing more happens to it.
CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER = (
    ConversationStatusValue.ROUTING_CONFLICT,
    ConversationStatusValue.FAULT,
    ConversationStatusValue.WORKING,
    ConversationStatusValue.WAITING,
    ConversationStatusValue.UNKNOWN,
    ConversationStatusValue.IDLE,
    ConversationStatusValue.ENDED,
)


@dataclass(frozen=True, kw_only=True)
class ConversationStatus:
    """Describe an issue conversation's derived summary status."""

    conversation: AgentWork
    value: ConversationStatusValue
    detail: str
    latest_output: str | None
    is_listed: bool

    @property
    def issue(self) -> int:
        """The number of the conversation's issue."""
        return self.conversation.record.issue

    @property
    def title(self) -> str:
        """The title of the conversation's issue when the conversation started."""
        return self.conversation.record.title

    @property
    def ending(self) -> AgentWorkEnding | None:
        """When and why the conversation ended, if it has."""
        return self.conversation.ending

    @property
    def has_ended(self) -> bool:
        """Whether the conversation has ended and no round of it is still running."""
        return self.value is ConversationStatusValue.ENDED

    @property
    def is_active(self) -> bool:
        """Whether the status report lists the conversation as active work."""
        return self.is_listed and not self.has_ended

    @cached_property
    def harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """The recorded or recoverable harness session identifier."""
        return self.conversation.find_harness_session_identifier()

    @cached_property
    def hand_resume_command(self) -> list[str] | None:
        """The hand-resume command when nobody is running the session."""
        return compose_hand_resume_command(
            is_working=self.value is ConversationStatusValue.WORKING,
            record=self.conversation.record,
            harness_session_identifier=self.harness_session_identifier,
        )

    @property
    def faulted_round_number(self) -> int | None:
        """The latest round while the conversation is in fault, else None."""
        if self.value is not ConversationStatusValue.FAULT:
            return None
        return self.conversation.rounds[-1].number

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
                if not conversation.rounds
                else conversation.compose_round_paths(
                    number=conversation.rounds[-1].number
                )
            ),
        )

    @cached_property
    def round_statuses(self) -> list[AgentRoundStatus]:
        """The derived status of every round in conversation order."""
        conversation = self.conversation
        statuses: list[AgentRoundStatus] = []
        previous_revision = None
        for record in conversation.rounds:
            round_input = _read_round_input(
                conversation=conversation, number=record.number
            )
            round_revision = None
            if round_input is not None:
                round_revision = _compose_round_revision(
                    previous_revision=previous_revision, revision=round_input.revision
                )
                previous_revision = round_input.revision
            statuses.append(
                AgentRoundStatus(
                    record=record,
                    trigger_description=_describe_round_trigger(
                        round_input=round_input
                    ),
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

    conversations: list[AgentWork]

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
        """Return the conversations' statuses in issue order."""
        statuses = [
            self.derive(conversation=conversation)
            for conversation in self.conversations
        ]
        return sorted(statuses, key=lambda status: status.issue)

    def derive(
        self,
        *,
        conversation: AgentWork,
    ) -> ConversationStatus:
        """Derive one conversation's status from its records and latest tick."""
        status = self._derive_working(conversation=conversation)
        if status is not None:
            return status
        status = self._derive_ended(conversation=conversation)
        if status is not None:
            return status
        status = self._derive_fault(conversation=conversation)
        if status is not None:
            return status
        status = self._derive_eligibility(conversation=conversation)
        if status is not None:
            return status
        status = self._derive_unfinished(conversation=conversation)
        if status is not None:
            return status
        return self._derive_observation(conversation=conversation)

    def _derive_working(
        self,
        *,
        conversation: AgentWork,
    ) -> ConversationStatus | None:
        if conversation.rounds:
            latest = conversation.rounds[-1]
            if self.is_round_working(record=latest):
                detail, latest_output = describe_running_round(
                    record=latest,
                    trigger_description=_describe_round_trigger(
                        round_input=_read_round_input(
                            conversation=conversation, number=latest.number
                        )
                    ),
                    paths=conversation.compose_round_paths(number=latest.number),
                    at=self.at,
                )
                return self._compose(
                    conversation=conversation,
                    value=ConversationStatusValue.WORKING,
                    detail=detail,
                    latest_output=latest_output,
                )
        return None

    def _derive_ended(
        self,
        *,
        conversation: AgentWork,
    ) -> ConversationStatus | None:
        if conversation.ending is None:
            return None
        return self._compose(
            conversation=conversation,
            value=ConversationStatusValue.ENDED,
            detail=str(conversation.ending.reason),
        )

    def _derive_eligibility(
        self,
        *,
        conversation: AgentWork,
    ) -> ConversationStatus | None:
        ineligibility = self._find_ineligibility(issue=conversation.record.issue)
        if ineligibility is None:
            return None
        value, detail = ineligibility
        return self._compose(
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
        if routing_conflict.value is Truth.UNKNOWN:
            return ConversationStatusValue.UNKNOWN, routing_conflict.evidence
        if routing_conflict.value is Truth.TRUE:
            return ConversationStatusValue.ROUTING_CONFLICT, routing_conflict.evidence
        requires_round = observation.requires_round
        if requires_round.value is Truth.UNKNOWN:
            return ConversationStatusValue.UNKNOWN, requires_round.evidence
        return None

    def _derive_fault(
        self,
        *,
        conversation: AgentWork,
    ) -> ConversationStatus | None:
        if self.has_fault(
            records=conversation.rounds,
            retry_requested_at=conversation.retry_requested_at,
        ):
            latest = conversation.rounds[-1]
            detail, latest_output = describe_round_ending(
                record=latest,
                paths=conversation.compose_round_paths(number=latest.number),
            )
            return self._compose(
                conversation=conversation,
                value=ConversationStatusValue.FAULT,
                detail=detail,
                latest_output=latest_output,
            )
        return None

    def _derive_unfinished(
        self,
        *,
        conversation: AgentWork,
    ) -> ConversationStatus | None:
        if is_last_round_unfinished(
            rounds=conversation.rounds, is_daemon_running=self.is_daemon_running
        ):
            latest = conversation.rounds[-1]
            detail, _ = describe_round_ending(
                record=latest,
                paths=conversation.compose_round_paths(number=latest.number),
            )
            return self._compose(
                conversation=conversation,
                value=ConversationStatusValue.WAITING,
                detail=detail,
            )
        return None

    def _derive_observation(
        self,
        *,
        conversation: AgentWork,
    ) -> ConversationStatus:
        if conversation.rounds:
            latest = conversation.rounds[-1]
            if self.did_round_end_after_latest_tick(
                identifier=conversation.identifier,
                record=latest,
                is_observed=True,
            ):
                return self._compose(
                    conversation=conversation,
                    value=ConversationStatusValue.WAITING,
                    detail=f"round {latest.number} ended, awaiting next update",
                )
        requires_round = self.observations[conversation.record.issue].requires_round
        if requires_round.value is Truth.TRUE:
            return self._compose(
                conversation=conversation,
                value=ConversationStatusValue.WAITING,
                detail=requires_round.evidence,
            )
        return self._compose(
            conversation=conversation,
            value=ConversationStatusValue.IDLE,
            detail=self._describe_idle(conversation=conversation),
        )

    def _compose(
        self,
        *,
        conversation: AgentWork,
        value: ConversationStatusValue,
        detail: str,
        latest_output: str | None = None,
    ) -> ConversationStatus:
        return ConversationStatus(
            conversation=conversation,
            value=value,
            detail=detail,
            latest_output=latest_output,
            is_listed=(
                value is ConversationStatusValue.WORKING
                or self.scheduler_record is None
                or conversation.record.issue in self.observations
            ),
        )

    def _describe_idle(self, *, conversation: AgentWork) -> str:
        if not conversation.rounds:
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


def _read_round_input(
    *, conversation: AgentWork, number: int
) -> ConversationRoundInput | None:
    """Return one round's input, or None when it cannot be read."""
    try:
        return read_conversation_input(conversation=conversation, number=number)
    except ReportableError:
        return None


def _describe_round_trigger(*, round_input: ConversationRoundInput | None) -> str:
    """Describe what woke a conversation round, from the input it was given.

    Comments wake every conversation round, so a round whose input is still to
    be written, or never was, says so without a count.
    """
    if round_input is None:
        return "comments"
    return describe_count(number=len(round_input.comments), noun="comment")


def _compose_round_revision(
    *, previous_revision: str | None, revision: str
) -> AgentRoundRevision:
    """Describe the revision one conversation round investigated."""
    if previous_revision is None:
        description = f"code revision {revision}"
    elif previous_revision == revision:
        description = f"code revision {revision} (unchanged)"
    else:
        description = f"code revision {previous_revision} -> {revision}"
    return AgentRoundRevision(value=revision, description=description)
