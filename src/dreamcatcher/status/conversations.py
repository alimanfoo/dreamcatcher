"""Represent and summarize the derived status of issue conversations."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cached_property

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    ErroredAgentRoundEnding,
)
from dreamcatcher.documents import read_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.issue_conversations import (
    Conversation,
    describe_conversation_revision,
    find_conversation_harness_session_identifier,
    is_conversation_ready_for_input,
    is_no_reply,
    read_conversation_input,
)
from dreamcatcher.scheduler.models import (
    ConversationObservation,
    IssueFactValue,
)
from dreamcatcher.status.rounds import (
    AgentRoundRevision,
    AgentRoundStatus,
    compose_round_duration_description,
    describe_round_outcome,
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
class ConversationSummary:
    """Hold the status, detail and latest output derived for one conversation."""

    value: ConversationStatusValue
    detail: str
    latest_output: str | None = None


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
                ConversationStatusValue.FAULT,
                ConversationStatusValue.ROUTING_CONFLICT,
            }
            or not self.is_listed
        )

    @cached_property
    def stoppable_round_paths(self) -> AgentRoundPaths | None:
        """The live round that can accept a stop request, when one exists."""
        conversation = self.conversation
        if (
            self.value is not ConversationStatusValue.WORKING
            or conversation is None
            or find_conversation_harness_session_identifier(conversation=conversation)
            is None
        ):
            return None
        paths = conversation.compose_round_paths(number=conversation.rounds[-1].number)
        return None if paths.stop_request.is_file() else paths

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
                        is_running=(
                            self.value is ConversationStatusValue.WORKING
                            and record.number == conversation.rounds[-1].number
                        ),
                    ),
                    revision=round_revision,
                )
            )
        return statuses


def summarize_observed_conversation(
    *,
    observation: ConversationObservation,
    conversation: Conversation | None,
) -> ConversationSummary:
    """Return what a matching issue says about its conversation.

    An unknown or conflicting route comes first, then unknown comments, a round
    waiting to be recovered, and comments waiting to be answered.
    """
    routing_conflict = observation.routing_conflict
    if routing_conflict.value is IssueFactValue.UNKNOWN:
        return ConversationSummary(
            value=ConversationStatusValue.UNKNOWN,
            detail=routing_conflict.evidence,
        )
    if routing_conflict.value is IssueFactValue.TRUE:
        return ConversationSummary(
            value=ConversationStatusValue.ROUTING_CONFLICT,
            detail=routing_conflict.evidence,
        )
    requires_round = observation.requires_round
    if requires_round.value is IssueFactValue.UNKNOWN:
        return ConversationSummary(
            value=ConversationStatusValue.UNKNOWN,
            detail=requires_round.evidence,
        )
    unfinished_round = describe_unfinished_conversation_round(conversation=conversation)
    if unfinished_round is not None:
        return ConversationSummary(
            value=ConversationStatusValue.WAITING, detail=unfinished_round
        )
    if requires_round.value is IssueFactValue.TRUE:
        return ConversationSummary(
            value=ConversationStatusValue.WAITING,
            detail=requires_round.evidence,
        )
    return ConversationSummary(
        value=ConversationStatusValue.IDLE,
        detail=_describe_idle_conversation(conversation=conversation),
    )


def describe_unfinished_conversation_round(
    *, conversation: Conversation | None
) -> str | None:
    """Describe the conversation's latest round if it errored or was interrupted.

    A round with no ending that no daemon is running was interrupted.
    """
    if conversation is None or not conversation.rounds:
        return None
    if is_conversation_ready_for_input(conversation=conversation):
        return None
    latest = conversation.rounds[-1]
    ending = latest.ending
    if isinstance(ending, ErroredAgentRoundEnding) and ending.reason is not None:
        return f"round {latest.number} errored: {ending.reason}"
    outcome = describe_round_outcome(record=latest, is_running=False)
    return f"round {latest.number} {outcome}"


def _describe_idle_conversation(*, conversation: Conversation | None) -> str:
    """Describe a conversation that has answered every comment it was given.

    Its latest round either answered the comments or stopped for new direction.
    """
    if conversation is None or not conversation.rounds:
        return "no comments yet"
    latest = conversation.rounds[-1]
    duration = compose_round_duration_description(record=latest)
    if latest.outcome is AgentRoundOutcome.STOPPED:
        return f"round {latest.number}, stopped, {duration}"
    final_output = read_text(
        path=conversation.compose_round_paths(number=latest.number).final_output
    )
    answer = "no reply needed" if is_no_reply(final_output=final_output) else "answered"
    return f"round {latest.number}, {answer}, {duration}"
