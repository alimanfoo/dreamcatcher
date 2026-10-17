"""Compose Flask-free models for dreamcatcher's web views."""

from datetime import tzinfo
from pathlib import Path

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentRoundStatus,
    AssignmentStatus,
    ConversationStatus,
    DreamcatcherDaemonStatus,
    DreamcatcherStatusReport,
    StatusFact,
    read_repository,
)
from dreamcatcher.web.feed import read_agent_feed
from dreamcatcher.web.models import (
    WebAgentLiveState,
    WebAgentRound,
    WebAgentWorkControl,
    WebAssignmentCard,
    WebAssignmentView,
    WebConversationCard,
    WebConversationView,
    WebHandResume,
    WebHomeView,
)
from dreamcatcher.words import describe_time


def _compose_hand_resume(
    *,
    state: StateDirectory,
    worktree: Path | None,
    command: list[str] | None,
) -> WebHandResume | None:
    """Return the web values for a manual session resume, when available."""
    if worktree is None or command is None:
        return None
    return WebHandResume(
        worktree=state.describe_path(path=worktree),
        command=" ".join(command),
    )


def _compose_github_repository_url(*, repository: str | None) -> str | None:
    if repository is None:
        return None
    return f"https://github.com/{repository}"


def compose_home_view(*, report: DreamcatcherStatusReport) -> WebHomeView:
    """Return the values shown on the home page."""
    daemon = report.daemon
    return WebHomeView(
        repository=report.repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(
            repository=report.repository
        ),
        daemon=daemon,
        instance_facts=report.instance_facts,
        assignment_section=report.assignment_section,
        conversation_section=report.conversation_section,
        active_conversations=tuple(
            _compose_conversation_card(status=status)
            for status in report.active_conversation_statuses
        ),
        ended_conversations=tuple(
            _compose_conversation_card(status=status)
            for status in report.ended_conversation_statuses
        ),
        active_assignments=tuple(
            _compose_assignment_card(status=status)
            for status in report.active_assignment_statuses
        ),
        ended_assignments=tuple(
            _compose_assignment_card(status=status)
            for status in report.ended_assignment_statuses
        ),
        assignment_requests=tuple(
            report.list_request_statuses(kind=AgentWorkKind.ASSIGNMENT)
        ),
        conversation_requests=tuple(
            report.list_request_statuses(kind=AgentWorkKind.CONVERSATION)
        ),
    )


def _compose_assignment_card(*, status: AssignmentStatus) -> WebAssignmentCard:
    assignment = status.assignment
    return WebAssignmentCard(
        identifier=assignment.identifier,
        issue=assignment.record.issue,
        title=assignment.record.title,
        status=status.value,
        detail=status.detail,
        dispatch_label=assignment.record.dispatch_label,
        harness=str(assignment.record.harness),
        model=assignment.record.model,
        effort=assignment.record.effort,
        pull_request=status.pull_request,
        pull_request_state=status.pull_request_state,
        latest_output=status.latest_output,
    )


def _compose_conversation_card(*, status: ConversationStatus) -> WebConversationCard:
    """Return the values shown for one issue conversation on the home page."""
    conversation = status.conversation
    return WebConversationCard(
        identifier=conversation.identifier,
        issue=status.issue,
        title=status.title,
        status=status.value,
        detail=status.detail,
        settings=" · ".join(
            [
                str(conversation.record.harness),
                conversation.record.model,
                conversation.record.effort,
            ]
        ),
        latest_output=status.latest_output,
    )


def compose_agent_live_state(
    *,
    state: StateDirectory,
    status: AssignmentStatus | ConversationStatus,
    worktree: Path | None,
    zone: tzinfo | None,
    heading_controls: tuple[WebAgentWorkControl, ...],
    foot_controls: tuple[WebAgentWorkControl, ...],
) -> WebAgentLiveState:
    """Return the values of an agent page that its tail refreshes."""
    return WebAgentLiveState(
        status=status.value,
        detail=status.detail,
        rounds=_compose_agent_rounds(round_statuses=status.round_statuses, zone=zone),
        heading_controls=heading_controls,
        foot_controls=foot_controls,
        hand_resume=_compose_hand_resume(
            state=state, worktree=worktree, command=status.hand_resume_command
        ),
    )


def compose_assignment_view(
    *,
    state: StateDirectory,
    status: AssignmentStatus,
    daemon: DreamcatcherDaemonStatus,
    live: WebAgentLiveState,
    zone: tzinfo | None,
) -> WebAssignmentView:
    """Return the values shown on one assignment page."""
    assignment = status.assignment
    record = assignment.record
    repository = read_repository(state=state)
    feed = read_agent_feed(owner=assignment, zone=zone, rounds=live.rounds)
    return WebAssignmentView(
        repository=repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(repository=repository),
        daemon=daemon,
        identifier=assignment.identifier,
        issue=record.issue,
        title=record.title,
        pull_request=status.pull_request,
        pull_request_state=status.pull_request_state,
        dispatch_label=record.dispatch_label,
        harness=str(record.harness),
        model=record.model,
        effort=record.effort,
        live=live,
        feed_rounds=feed.rounds,
        feed_cursor=feed.cursor,
    )


def compose_conversation_view(
    *,
    state: StateDirectory,
    conversation: AgentWork,
    status: ConversationStatus,
    daemon: DreamcatcherDaemonStatus,
    live: WebAgentLiveState,
    zone: tzinfo | None,
) -> WebConversationView:
    """Return the values shown on one issue-conversation page."""
    repository = read_repository(state=state)
    feed = read_agent_feed(owner=conversation, zone=zone, rounds=live.rounds)
    return WebConversationView(
        repository=repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(repository=repository),
        daemon=daemon,
        identifier=conversation.identifier,
        issue=status.issue,
        title=status.title,
        facts=_compose_conversation_facts(conversation=conversation),
        live=live,
        feed_rounds=feed.rounds,
        feed_cursor=feed.cursor,
    )


def _compose_conversation_facts(*, conversation: AgentWork) -> tuple[StatusFact, ...]:
    """Return the settings that a conversation settled at its first round."""
    record = conversation.record
    return (
        StatusFact(label="label", value=record.dispatch_label),
        StatusFact(label="harness", value=str(record.harness)),
        StatusFact(label="model", value=f"{record.model} · {record.effort}"),
    )


def _compose_agent_rounds(
    *, round_statuses: list[AgentRoundStatus], zone: tzinfo | None
) -> tuple[WebAgentRound, ...]:
    """Return the round rows shown for one piece of agent work."""
    return tuple(
        WebAgentRound(
            number=round_status.record.number,
            trigger=round_status.trigger_description,
            started=describe_time(at=round_status.record.started, zone=zone),
            duration=round_status.duration_description,
            outcome=str(round_status.record.outcome),
            outcome_description=round_status.outcome_description,
            revision=round_status.revision,
        )
        for round_status in round_statuses
    )
