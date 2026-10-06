"""Compose Flask-free models for dreamcatcher's web views."""

import re
from datetime import tzinfo
from pathlib import Path

from dreamcatcher.issue_conversations import Conversation
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentRoundStatus,
    AssignmentStatus,
    ConversationStatus,
    DreamcatcherDaemonStatus,
    DreamcatcherStatusReport,
    IssueStatus,
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
    WebFact,
    WebHandResume,
    WebHomeView,
    WebIssueRow,
)
from dreamcatcher.words import describe_countdown, describe_time

_ISSUE_REFERENCE_PATTERN = re.compile(r"(?<!\w)(?:GH|#)(\d+)\b(?!-)")


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


def compose_home_view(
    *, report: DreamcatcherStatusReport, zone: tzinfo | None
) -> WebHomeView:
    """Return the values shown on the home page."""
    daemon = report.daemon
    cooldown_end = (
        None
        if report.active_global_cooldown is None
        else describe_time(at=report.active_global_cooldown.ends, zone=zone)
    )
    return WebHomeView(
        repository=report.repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(
            repository=report.repository
        ),
        daemon_state="running" if daemon.is_running else "not-running",
        daemon_summary=daemon.summary,
        instance_facts=_compose_instance_facts(report=report),
        cooldown_message=(
            None if cooldown_end is None else f"Global cooldown ends {cooldown_end}"
        ),
        conversations=tuple(
            _compose_conversation_card(status=status)
            for status in report.conversation_statuses
        ),
        active_assignments=tuple(
            _compose_assignment_card(status=status)
            for status in report.active_assignment_statuses
        ),
        ended_assignments=tuple(
            _compose_assignment_card(status=status)
            for status in report.ended_assignment_statuses
        ),
        failed_setups=tuple(
            _compose_issue_row(status=setup)
            for setup in report.failed_assignment_setups
        ),
        issues=tuple(
            _compose_issue_row(status=issue) for issue in report.issue_statuses
        ),
    )


def _compose_assignment_card(*, status: AssignmentStatus) -> WebAssignmentCard:
    assignment = status.assignment
    return WebAssignmentCard(
        identifier=assignment.identifier,
        issue=assignment.record.issue,
        title=assignment.record.title,
        status=str(status.value),
        detail=status.detail,
        dispatch_label=assignment.record.dispatch_label,
        harness=str(assignment.record.harness),
        model=assignment.record.model,
        effort=assignment.record.effort,
        pull_request=assignment.record.pull_request,
        pull_request_state=status.pull_request_state,
        latest_output=status.latest_output,
    )


def _compose_conversation_card(*, status: ConversationStatus) -> WebConversationCard:
    """Return the values shown for one issue conversation on the home page.

    A conversation settles its settings when its first round launches.
    """
    conversation = status.conversation
    return WebConversationCard(
        issue=status.issue,
        title=status.title,
        status=str(status.value),
        detail=status.detail,
        settings=(
            None
            if conversation is None
            else " · ".join(
                [
                    str(conversation.record.harness),
                    conversation.record.model,
                    conversation.record.effort,
                ]
            )
        ),
        latest_output=status.latest_output,
    )


def compose_agent_live_state(
    *,
    state: StateDirectory,
    status: AssignmentStatus | ConversationStatus,
    worktree: Path | None,
    zone: tzinfo | None,
    controls: tuple[WebAgentWorkControl, ...],
) -> WebAgentLiveState:
    """Return the values of an agent page that its tail refreshes."""
    return WebAgentLiveState(
        status=str(status.value),
        detail=status.detail,
        rounds=_compose_agent_rounds(round_statuses=status.round_statuses, zone=zone),
        controls=controls,
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
        daemon_state="running" if daemon.is_running else "not-running",
        daemon_summary=daemon.summary,
        identifier=assignment.identifier,
        issue=record.issue,
        title=record.title,
        pull_request=record.pull_request,
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
    status: ConversationStatus,
    daemon: DreamcatcherDaemonStatus,
    live: WebAgentLiveState,
    zone: tzinfo | None,
) -> WebConversationView:
    """Return the values shown on one issue-conversation page."""
    conversation = status.conversation
    repository = read_repository(state=state)
    feed = read_agent_feed(owner=conversation, zone=zone, rounds=live.rounds)
    return WebConversationView(
        repository=repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(repository=repository),
        daemon_state="running" if daemon.is_running else "not-running",
        daemon_summary=daemon.summary,
        issue=status.issue,
        title=status.title,
        facts=(
            ()
            if conversation is None
            else _compose_conversation_facts(conversation=conversation)
        ),
        live=live,
        feed_rounds=feed.rounds,
        feed_cursor=feed.cursor,
    )


def _compose_conversation_facts(*, conversation: Conversation) -> tuple[WebFact, ...]:
    """Return the settings that a conversation settled at its first round."""
    record = conversation.record
    return (
        WebFact(label="label", value=record.dispatch_label),
        WebFact(label="harness", value=str(record.harness)),
        WebFact(label="model", value=f"{record.model} · {record.effort}"),
    )


def _compose_agent_rounds(
    *, round_statuses: list[AgentRoundStatus], zone: tzinfo | None
) -> tuple[WebAgentRound, ...]:
    """Return the round rows shown for one piece of agent work."""
    return tuple(
        WebAgentRound(
            number=round_status.record.number,
            purpose=round_status.purpose_description,
            started=describe_time(at=round_status.record.started, zone=zone),
            duration=round_status.duration_description,
            outcome=str(round_status.record.outcome),
            outcome_description=round_status.outcome_description,
            revision=round_status.revision,
        )
        for round_status in round_statuses
    )


def _compose_issue_row(*, status: IssueStatus) -> WebIssueRow:
    details = status.observation.details
    return WebIssueRow(
        issue=status.observation.issue,
        title=None if details is None else details.title,
        labels=", ".join([] if details is None else details.assignment_labels),
        status=str(status.value),
        evidence=_compose_issue_evidence(status=status),
    )


def _compose_issue_evidence(*, status: IssueStatus) -> tuple[str | int, ...]:
    """Return the evidence as text, with each issue it names as a number."""
    parts: list[str | int] = []
    for item in status.evidence:
        if parts:
            parts.append("; ")
        if item.names_issues:
            parts.extend(_compose_issue_references(evidence=item.text))
        else:
            parts.append(item.text)
    return tuple(parts)


def _compose_issue_references(*, evidence: str) -> tuple[str | int, ...]:
    return tuple(
        int(part) if index % 2 else part
        for index, part in enumerate(_ISSUE_REFERENCE_PATTERN.split(evidence))
        if part
    )


def _compose_instance_facts(*, report: DreamcatcherStatusReport) -> tuple[WebFact, ...]:
    daemon = report.daemon
    values: tuple[tuple[str, str | None, bool], ...] = (
        (
            "preferred harness",
            None if daemon.agent_harness is None else str(daemon.agent_harness),
            False,
        ),
        (
            "next update in",
            (
                None
                if not daemon.is_running
                else describe_countdown(
                    at=report.at,
                    since=report.latest_scheduler_tick,
                    span_seconds=daemon.interval_seconds,
                )
            ),
            False,
        ),
        (
            "agent capacity",
            (
                None
                if daemon.max_agents is None
                else f"{report.running_agents} of {daemon.max_agents} working"
            ),
            False,
        ),
        (
            "scheduler failures",
            report.scheduler_failure_summary,
            report.scheduler_failure_summary is not None,
        ),
    )
    return tuple(
        WebFact(label=label, value=value, is_warning=is_warning)
        for label, value, is_warning in values
        if value is not None
    )
