"""Compose Flask-free models for dreamcatcher's web views."""

from datetime import tzinfo
from pathlib import Path

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentRoundStatus,
    AgentWorkStatus,
    DreamcatcherDaemonStatus,
    DreamcatcherStatusReport,
    StatusFact,
    read_repository,
)
from dreamcatcher.web.feed import read_agent_feed
from dreamcatcher.web.models import (
    WebAgentLiveState,
    WebAgentRound,
    WebAgentWorkCard,
    WebAgentWorkControl,
    WebAgentWorkSection,
    WebAssignmentView,
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
    """Return the web values for a hand resume, when available."""
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
        scheduler_failures=report.scheduler_failures,
        sections=tuple(
            section
            for kind in AgentWorkKind
            if (section := _compose_section(report=report, kind=kind)) is not None
        ),
    )


def _compose_section(
    *, report: DreamcatcherStatusReport, kind: AgentWorkKind
) -> WebAgentWorkSection | None:
    """Return the home page's section for one kind, when the report shows one."""
    section = report.describe_section(kind=kind)
    if section is None:
        return None
    return WebAgentWorkSection(
        kind=kind,
        heading=section.heading,
        empty_message=section.empty_message,
        active=tuple(
            _compose_work_card(status=status)
            for status in report.list_active_work_statuses(kind=kind)
        ),
        requests=tuple(report.list_request_statuses(kind=kind)),
        ended=tuple(
            _compose_work_card(status=status)
            for status in report.list_ended_work_statuses(kind=kind)
        ),
    )


def _compose_work_card(*, status: AgentWorkStatus) -> WebAgentWorkCard:
    """Return the values shown for one piece of agent work on the home page."""
    work = status.work
    record = work.record
    return WebAgentWorkCard(
        identifier=work.identifier,
        kind=record.kind,
        issue=record.issue,
        title=record.title,
        status=status.value,
        detail=status.detail,
        dispatch_label=record.dispatch_label,
        harness=str(record.harness),
        model=record.model,
        effort=record.effort,
        pull_request=status.pull_request,
        pull_request_summary=status.pull_request_summary,
        latest_output=status.latest_output,
    )


def compose_agent_live_state(
    *,
    state: StateDirectory,
    status: AgentWorkStatus,
    worktree: Path | None,
    zone: tzinfo | None,
    heading_controls: tuple[WebAgentWorkControl, ...],
    foot_controls: tuple[WebAgentWorkControl, ...],
) -> WebAgentLiveState:
    """Return the values of an agent-work page that its tail refreshes."""
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
    status: AgentWorkStatus,
    daemon: DreamcatcherDaemonStatus,
    live: WebAgentLiveState,
    zone: tzinfo | None,
) -> WebAssignmentView:
    """Return the values shown on one assignment page."""
    assignment = status.work
    record = assignment.record
    repository = read_repository(state=state)
    feed = read_agent_feed(work=assignment, zone=zone, rounds=live.rounds)
    return WebAssignmentView(
        repository=repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(repository=repository),
        daemon=daemon,
        identifier=assignment.identifier,
        issue=record.issue,
        title=record.title,
        pull_request=status.pull_request,
        pull_request_summary=status.pull_request_summary,
        dispatch_label=record.dispatch_label,
        harness=str(record.harness),
        model=record.model,
        effort=record.effort,
        live=live,
        feed_rounds=feed.rounds,
        feed_cursor=feed.feed_cursor,
    )


def compose_conversation_view(
    *,
    state: StateDirectory,
    status: AgentWorkStatus,
    daemon: DreamcatcherDaemonStatus,
    live: WebAgentLiveState,
    zone: tzinfo | None,
) -> WebConversationView:
    """Return the values shown on one issue-conversation page."""
    conversation = status.work
    repository = read_repository(state=state)
    feed = read_agent_feed(work=conversation, zone=zone, rounds=live.rounds)
    return WebConversationView(
        repository=repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(repository=repository),
        daemon=daemon,
        identifier=conversation.identifier,
        issue=conversation.record.issue,
        title=conversation.record.title,
        facts=_compose_conversation_facts(conversation=conversation),
        live=live,
        feed_rounds=feed.rounds,
        feed_cursor=feed.feed_cursor,
    )


def _compose_conversation_facts(*, conversation: AgentWork) -> tuple[StatusFact, ...]:
    """Return the settings that a conversation's work record holds."""
    record = conversation.record
    return (
        StatusFact(label="label", value=record.dispatch_label),
        StatusFact(label="harness", value=str(record.harness)),
        StatusFact(label="model · effort", value=f"{record.model} · {record.effort}"),
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
            outcome=str(round_status.outcome),
            outcome_description=round_status.outcome_description,
            revision=round_status.revision,
        )
        for round_status in round_statuses
    )
