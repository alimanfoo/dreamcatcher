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
    IssueConversation,
    describe_issue_conversation_revision,
    find_issue_conversation_harness_session_identifier,
    is_issue_conversation_ready_for_input,
    is_no_reply,
    read_issue_conversation_input,
)
from dreamcatcher.scheduler.models import (
    IssueConversationObservation,
    IssueFactValue,
)
from dreamcatcher.status.rounds import (
    AgentRoundStatus,
    compose_round_duration_description,
    describe_round_outcome,
)


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


# Idle comes last because a conversation at rest asks nothing of the user.
CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER = (
    IssueConversationStatusValue.ROUTING_CONFLICT,
    IssueConversationStatusValue.FAULT,
    IssueConversationStatusValue.WORKING,
    IssueConversationStatusValue.WAITING,
    IssueConversationStatusValue.UNKNOWN,
    IssueConversationStatusValue.IDLE,
)


@dataclass(frozen=True, kw_only=True)
class ConversationSummary:
    """Hold the status, detail and latest output derived for one conversation."""

    value: IssueConversationStatusValue
    detail: str
    latest_output: str | None = None


@dataclass(frozen=True, kw_only=True)
class IssueConversationStatus:
    """Describe an issue conversation's derived summary status.

    A matching issue has a status from the first tick that observes it, but no
    saved conversation until its first round launches.
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
    def stoppable_round_paths(self) -> AgentRoundPaths | None:
        """The live round that can accept a stop request, when one exists."""
        conversation = self.conversation
        if (
            self.value is not IssueConversationStatusValue.WORKING
            or conversation is None
            or find_issue_conversation_harness_session_identifier(
                conversation=conversation
            )
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
                    duration_description=compose_round_duration_description(
                        record=record
                    ),
                    outcome_description=describe_round_outcome(
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


def summarize_observed_conversation(
    *,
    observation: IssueConversationObservation,
    conversation: IssueConversation | None,
) -> ConversationSummary:
    """Return what a matching issue says about its conversation.

    An unknown or conflicting route comes first, then unknown comments, a round
    waiting to be recovered, and comments waiting to be answered.
    """
    routing_conflict = observation.routing_conflict
    if routing_conflict.value is IssueFactValue.UNKNOWN:
        return ConversationSummary(
            value=IssueConversationStatusValue.UNKNOWN,
            detail=routing_conflict.evidence,
        )
    if routing_conflict.value is IssueFactValue.TRUE:
        return ConversationSummary(
            value=IssueConversationStatusValue.ROUTING_CONFLICT,
            detail=routing_conflict.evidence,
        )
    has_comments_to_answer = observation.has_comments_to_answer
    if has_comments_to_answer.value is IssueFactValue.UNKNOWN:
        return ConversationSummary(
            value=IssueConversationStatusValue.UNKNOWN,
            detail=has_comments_to_answer.evidence,
        )
    unfinished_round = describe_unfinished_conversation_round(conversation=conversation)
    if unfinished_round is not None:
        return ConversationSummary(
            value=IssueConversationStatusValue.WAITING, detail=unfinished_round
        )
    if has_comments_to_answer.value is IssueFactValue.TRUE:
        return ConversationSummary(
            value=IssueConversationStatusValue.WAITING,
            detail=has_comments_to_answer.evidence,
        )
    return ConversationSummary(
        value=IssueConversationStatusValue.IDLE,
        detail=_describe_idle_conversation(conversation=conversation),
    )


def describe_unfinished_conversation_round(
    *, conversation: IssueConversation | None
) -> str | None:
    """Describe the conversation's latest round if it errored or was interrupted.

    A round with no ending that no daemon is running was interrupted.
    """
    if conversation is None or not conversation.rounds:
        return None
    if is_issue_conversation_ready_for_input(conversation=conversation):
        return None
    latest = conversation.rounds[-1]
    ending = latest.ending
    if isinstance(ending, ErroredAgentRoundEnding) and ending.reason is not None:
        return f"round {latest.number} errored: {ending.reason}"
    outcome = describe_round_outcome(record=latest, is_running=False)
    return f"round {latest.number} {outcome}"


def _describe_idle_conversation(*, conversation: IssueConversation | None) -> str:
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
