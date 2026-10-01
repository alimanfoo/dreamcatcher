"""Start prepared issue-conversation rounds."""

from functools import partial

from dreamcatcher.agent_rounds import (
    AgentRoundPlan,
    AgentRoundStartRequest,
    IssueConversationRoundPurpose,
    start_agent_round,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentRoundLaunchRequest, AgentWorkKind
from dreamcatcher.issue_conversations import (
    IssueConversation,
    post_issue_conversation_answer,
    record_issue_conversation_session_identifier,
)
from dreamcatcher.scheduler.conversations import (
    IssueConversationCandidate,
    _ConversationScheduler,
    _prepare_issue_conversation_round,
    _PreparedIssueConversationRound,
)
from dreamcatcher.scheduler.models import (
    IssueFact,
    IssueFactValue,
    SchedulerRecord,
    combine_scheduler_failures,
)


def launch_issue_conversation_round(
    *,
    scheduler: _ConversationScheduler,
    record: SchedulerRecord,
    candidate: IssueConversationCandidate,
) -> SchedulerRecord:
    """Prepare a conversation's required work and start its next round."""
    try:
        prepared = _prepare_issue_conversation_round(
            state=scheduler.state,
            candidate=candidate,
            requested_harness=scheduler.requested_harness,
        )
        conversation = _start_prepared_conversation_round(
            scheduler=scheduler, prepared=prepared
        )
    except ReportableError as failure:
        return record.model_copy(
            update={
                "hold": combine_scheduler_failures(failures=[record.hold, str(failure)])
            }
        )
    return _record_conversation_comments_delivered(
        record=record,
        issue=conversation.record.issue,
    )


def _start_prepared_conversation_round(
    *, scheduler: _ConversationScheduler, prepared: _PreparedIssueConversationRound
) -> IssueConversation:
    conversation = prepared.conversation
    scheduler.rounds[conversation.identifier] = start_agent_round(
        request=AgentRoundStartRequest(
            harness=conversation.record.harness,
            launch_request=AgentRoundLaunchRequest(
                agent_work_identifier=conversation.identifier,
                model=conversation.record.model,
                effort=conversation.record.effort,
                prompt=prepared.prompt,
                work_kind=AgentWorkKind.CONVERSATION,
            ),
            harness_session_identifier=prepared.harness_session_identifier,
            record_harness_session_identifier=partial(
                record_issue_conversation_session_identifier,
                conversation=conversation,
            ),
            finish_round=partial(
                post_issue_conversation_answer,
                repository=scheduler.repository,
                issue=conversation.record.issue,
            ),
            paths=conversation.compose_round_paths(
                number=conversation.next_round_number
            ),
            plan=AgentRoundPlan(
                purpose=IssueConversationRoundPurpose.DISCUSS,
                is_recovery=prepared.is_recovery,
                input=prepared.round_input,
            ),
        ),
        clock=scheduler.clock,
    )
    return conversation


def _record_conversation_comments_delivered(
    *, record: SchedulerRecord, issue: int
) -> SchedulerRecord:
    no_comments = IssueFact(
        value=IssueFactValue.FALSE,
        evidence="no comments to answer",
    )
    return record.model_copy(
        update={
            "conversation_observations": [
                observation.model_copy(update={"has_comments_to_answer": no_comments})
                if observation.issue == issue
                else observation
                for observation in record.conversation_observations
            ]
        }
    )
