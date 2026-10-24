"""Compose Flask-free models for dreamcatcher's web views."""

from collections.abc import Sequence
from datetime import tzinfo

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
    WebCampaignChild,
    WebCampaignChildOverview,
    WebHandResume,
    WebHomeView,
    WebIssueWorkView,
)
from dreamcatcher.words import describe_time


def _compose_hand_resume(
    *, state: StateDirectory, status: AgentWorkStatus
) -> WebHandResume | None:
    """Return the web values for a hand resume, when available."""
    worktree = status.worktree
    command = status.hand_resume_command
    if worktree is None or command is None:
        return None
    return WebHandResume(
        worktree=state.describe_path(path=worktree),
        command=" ".join(command),
    )


def compose_github_repository_url(*, repository: str | None) -> str | None:
    """Return the address of the repository on GitHub, when it is known."""
    if repository is None:
        return None
    return f"https://github.com/{repository}"


def compose_home_view(*, report: DreamcatcherStatusReport) -> WebHomeView:
    """Return the values shown on the home page."""
    daemon = report.daemon
    return WebHomeView(
        repository=report.repository or "repository unknown",
        github_repository_url=compose_github_repository_url(
            repository=report.repository
        ),
        daemon=daemon,
        instance_facts=report.instance_facts,
        scheduler_failures=report.scheduler_failures,
        sections=tuple(
            _compose_section(report=report, kind=kind) for kind in AgentWorkKind
        ),
    )


def _compose_section(
    *, report: DreamcatcherStatusReport, kind: AgentWorkKind
) -> WebAgentWorkSection:
    """Return the home page's section for one kind."""
    section = report.describe_section(kind=kind)
    return WebAgentWorkSection(
        kind=kind,
        heading=section.heading,
        guidance=section.guidance,
        active=tuple(
            _compose_work_card(report=report, status=status)
            for status in report.list_active_work_statuses(kind=kind)
        ),
        requests=tuple(report.list_request_statuses(kind=kind)),
        ended=tuple(
            _compose_work_card(report=report, status=status)
            for status in report.list_ended_work_statuses(kind=kind)
        ),
    )


def _compose_work_card(
    *, report: DreamcatcherStatusReport, status: AgentWorkStatus
) -> WebAgentWorkCard:
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
        is_pull_request_ready_for_review=status.is_pull_request_ready_for_review,
        child_overview=_compose_child_overview(report=report, campaign=status),
        latest_output=status.latest_output,
    )


def _compose_child_overview(
    *, report: DreamcatcherStatusReport, campaign: AgentWorkStatus
) -> WebCampaignChildOverview | None:
    """Return an active campaign's child overview; other work has none."""
    summary = campaign.children_summary
    if summary is None:
        return None
    return WebCampaignChildOverview(
        summary=summary,
        children=tuple(
            WebCampaignChild(
                issue=child_status.child.issue,
                title=child_status.child.title,
                assignment=(
                    None
                    if child_status.assignment is None
                    else _compose_work_card(
                        report=report, status=child_status.assignment
                    )
                ),
                requests=tuple(child_status.requests),
            )
            for child_status in report.list_campaign_child_statuses(campaign=campaign)
        ),
    )


def compose_agent_live_state(
    *,
    state: StateDirectory,
    status: AgentWorkStatus,
    zone: tzinfo | None,
    heading_controls: Sequence[WebAgentWorkControl],
    foot_controls: Sequence[WebAgentWorkControl],
) -> WebAgentLiveState:
    """Return the values of an agent-work page that its tail refreshes."""
    return WebAgentLiveState(
        status=status.value,
        detail=status.detail,
        rounds=_compose_agent_rounds(round_statuses=status.round_statuses, zone=zone),
        heading_controls=heading_controls,
        foot_controls=foot_controls,
        hand_resume=_compose_hand_resume(state=state, status=status),
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
        kind=record.kind,
        repository=repository or "repository unknown",
        github_repository_url=compose_github_repository_url(repository=repository),
        daemon=daemon,
        identifier=assignment.identifier,
        issue=record.issue,
        title=record.title,
        pull_request=status.pull_request,
        pull_request_summary=status.pull_request_summary,
        is_pull_request_ready_for_review=status.is_pull_request_ready_for_review,
        dispatch_label=record.dispatch_label,
        harness=str(record.harness),
        model=record.model,
        effort=record.effort,
        live=live,
        feed_rounds=feed.rounds,
        feed_position=feed.feed_position,
    )


def compose_issue_work_view(
    *,
    state: StateDirectory,
    status: AgentWorkStatus,
    daemon: DreamcatcherDaemonStatus,
    live: WebAgentLiveState,
    zone: tzinfo | None,
) -> WebIssueWorkView:
    """Return the values shown on the page of work whose channel is its issue."""
    work = status.work
    record = work.record
    repository = read_repository(state=state)
    feed = read_agent_feed(work=work, zone=zone, rounds=live.rounds)
    return WebIssueWorkView(
        kind=record.kind,
        repository=repository or "repository unknown",
        github_repository_url=compose_github_repository_url(repository=repository),
        daemon=daemon,
        identifier=work.identifier,
        issue=record.issue,
        title=record.title,
        facts=(
            StatusFact(label="label", value=record.dispatch_label),
            StatusFact(label="harness", value=str(record.harness)),
            StatusFact(
                label="model · effort", value=f"{record.model} · {record.effort}"
            ),
        ),
        live=live,
        feed_rounds=feed.rounds,
        feed_position=feed.feed_position,
    )


def _compose_agent_rounds(
    *, round_statuses: list[AgentRoundStatus], zone: tzinfo | None
) -> tuple[WebAgentRound, ...]:
    """Return the round rows shown for one piece of agent work."""
    return tuple(
        WebAgentRound(
            number=round_status.record.number,
            trigger=round_status.trigger,
            started=describe_time(at=round_status.record.started, zone=zone),
            duration=round_status.duration_description,
            outcome=str(round_status.outcome),
            outcome_description=round_status.listed_outcome_description,
        )
        for round_status in round_statuses
    )
