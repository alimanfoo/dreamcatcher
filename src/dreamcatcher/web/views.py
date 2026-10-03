"""Compose Flask-free models for Dreamcatcher's web views."""

import re
from datetime import datetime, tzinfo
from typing import TYPE_CHECKING, cast

from dreamcatcher.issue_conversations import Conversation
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER,
    CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER,
    AgentRoundRevision,
    AgentRoundStatus,
    AssignmentStatus,
    AssignmentStatusValue,
    ConversationStatus,
    DreamcatcherStatusReport,
    IssueFactValue,
    IssueObservation,
    read_dreamcatcher_daemon_status,
    read_repository,
)
from dreamcatcher.web.feed import read_agent_feed
from dreamcatcher.web.models import (
    WebAgentRound,
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

if TYPE_CHECKING:
    from dreamcatcher.agent_rounds import SuccessfulAgentRoundEnding

_ISSUE_REFERENCE_PATTERN = re.compile(r"(?<!\w)(?:GH|#)(\d+)\b(?!-)")
_GIT_REVISION_PATTERN = re.compile(r"\b[0-9a-f]{40}\b")


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
    active_assignments, complete_assignments = _compose_assignment_cards(report=report)
    return WebHomeView(
        repository=report.repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(
            repository=report.repository
        ),
        daemon_state="stopped" if daemon.pid is None else "running",
        daemon_summary=_describe_daemon(
            daemon_pid=daemon.pid,
            dreamcatcher_version=daemon.dreamcatcher_version,
        ),
        instance_facts=_compose_instance_facts(report=report),
        cooldown_message=(
            None if cooldown_end is None else f"Global cooldown ends {cooldown_end}"
        ),
        conversations=_compose_conversation_cards(report=report),
        active_assignments=active_assignments,
        complete_assignments=complete_assignments,
        failed_setups=tuple(report.failed_assignment_setups),
        available_issues=tuple(
            _compose_issue_row(observation=issue) for issue in report.available_issues
        ),
        blocked_issues=tuple(
            _compose_issue_row(observation=issue) for issue in report.blocked_issues
        ),
    )


def _compose_assignment_cards(
    *, report: DreamcatcherStatusReport
) -> tuple[tuple[WebAssignmentCard, ...], tuple[WebAssignmentCard, ...]]:
    active_statuses = sorted(
        (
            status
            for status in report.assignment_statuses
            if status.value is not AssignmentStatusValue.COMPLETE
        ),
        key=lambda status: ASSIGNMENT_STATUS_VALUES_IN_ATTENTION_ORDER.index(
            status.value
        ),
    )
    complete_statuses = sorted(
        (
            status
            for status in report.assignment_statuses
            if status.value is AssignmentStatusValue.COMPLETE
        ),
        key=_read_assignment_completion_time,
        reverse=True,
    )
    complete_assignments = tuple(
        _compose_assignment_card(status=status) for status in complete_statuses
    )
    active_assignments = tuple(
        _compose_assignment_card(status=status) for status in active_statuses
    )
    return active_assignments, complete_assignments


def _compose_conversation_cards(
    *, report: DreamcatcherStatusReport
) -> tuple[WebConversationCard, ...]:
    return tuple(
        _compose_conversation_card(status=status)
        for status in sorted(
            report.conversation_statuses,
            key=lambda status: CONVERSATION_STATUS_VALUES_IN_ATTENTION_ORDER.index(
                status.value
            ),
        )
    )


def _read_assignment_completion_time(status: AssignmentStatus, /) -> datetime:
    """Return the completion time for sorted, which passes items by position.

    The caller selects complete statuses, whose final round has a successful
    ending.
    """
    ending = cast(
        "SuccessfulAgentRoundEnding",
        status.assignment.rounds[-1].ending,
    )
    return ending.at


def _compose_assignment_card(*, status: AssignmentStatus) -> WebAssignmentCard:
    assignment = status.assignment
    return WebAssignmentCard(
        identifier=assignment.identifier,
        issue=assignment.record.issue,
        title=assignment.record.title,
        status=str(status.value),
        status_label=str(status.value),
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


def compose_assignment_view(
    *,
    state: StateDirectory,
    status: AssignmentStatus,
    zone: tzinfo | None,
    stop_url: str | None = None,
) -> WebAssignmentView:
    """Return the values shown on one assignment page."""
    assignment = status.assignment
    record = assignment.record
    repository = read_repository(state=state)
    daemon = read_dreamcatcher_daemon_status(state=state)
    hand_resume_command = status.hand_resume_command
    feed = read_agent_feed(owner=assignment, zone=zone)
    return WebAssignmentView(
        repository=repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(repository=repository),
        daemon_state="stopped" if daemon.pid is None else "running",
        daemon_summary=_describe_daemon(
            daemon_pid=daemon.pid,
            dreamcatcher_version=daemon.dreamcatcher_version,
        ),
        identifier=assignment.identifier,
        issue=record.issue,
        title=record.title,
        status=str(status.value),
        status_label=str(status.value),
        detail=status.detail,
        pull_request=record.pull_request,
        pull_request_state=status.pull_request_state,
        dispatch_label=record.dispatch_label,
        harness=str(record.harness),
        model=record.model,
        effort=record.effort,
        rounds=compose_agent_rounds(round_statuses=status.round_statuses, zone=zone),
        stop_url=stop_url,
        hand_resume=(
            None
            if hand_resume_command is None
            else WebHandResume(
                worktree=state.describe_path(path=record.worktree),
                command=" ".join(hand_resume_command),
            )
        ),
        feed_rounds=feed.rounds,
        feed_cursor=feed.cursor,
    )


def compose_conversation_view(
    *,
    state: StateDirectory,
    status: ConversationStatus,
    zone: tzinfo | None,
    stop_url: str | None = None,
) -> WebConversationView:
    """Return the values shown on one issue-conversation page."""
    conversation = status.conversation
    repository = read_repository(state=state)
    daemon = read_dreamcatcher_daemon_status(state=state)
    rounds = compose_agent_rounds(round_statuses=status.round_statuses, zone=zone)
    feed = read_agent_feed(owner=conversation, zone=zone, rounds=rounds)
    return WebConversationView(
        repository=repository or "repository unknown",
        github_repository_url=_compose_github_repository_url(repository=repository),
        daemon_state="stopped" if daemon.pid is None else "running",
        daemon_summary=_describe_daemon(
            daemon_pid=daemon.pid,
            dreamcatcher_version=daemon.dreamcatcher_version,
        ),
        issue=status.issue,
        title=status.title,
        status=str(status.value),
        detail=status.detail,
        facts=(
            ()
            if conversation is None
            else _compose_conversation_facts(conversation=conversation)
        ),
        rounds=rounds,
        stop_url=stop_url,
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


def compose_agent_rounds(
    *, round_statuses: list[AgentRoundStatus], zone: tzinfo | None
) -> tuple[WebAgentRound, ...]:
    """Return the round rows shown for one piece of agent work."""
    return tuple(
        WebAgentRound(
            number=round_status.record.number,
            purpose=str(round_status.record.purpose),
            is_recovery=round_status.record.is_recovery,
            started=describe_time(at=round_status.record.started, zone=zone),
            duration=round_status.duration_description,
            outcome=str(round_status.record.outcome),
            outcome_description=round_status.outcome_description,
            revision=_compose_web_round_revision(revision=round_status.revision),
        )
        for round_status in round_statuses
    )


def _compose_web_round_revision(
    *, revision: AgentRoundRevision | None
) -> AgentRoundRevision | None:
    if revision is None:
        return None
    return AgentRoundRevision(
        value=_shorten_git_revisions(text=revision.value),
        description=_shorten_git_revisions(text=revision.description),
    )


def _shorten_git_revisions(*, text: str) -> str:
    return _GIT_REVISION_PATTERN.sub(lambda match: match.group()[:7], text)


def _compose_issue_row(*, observation: IssueObservation) -> WebIssueRow:
    if observation.blocked.value is IssueFactValue.TRUE:
        status = "blocked"
        evidence = _compose_issue_evidence(evidence=observation.blocked.evidence)
    else:
        status = "available"
        evidence = ()
    details = observation.details
    return WebIssueRow(
        issue=observation.issue,
        title=None if details is None else details.title,
        labels=", ".join([] if details is None else details.assignment_labels),
        status=status,
        evidence=evidence,
    )


def _compose_issue_evidence(*, evidence: str) -> tuple[str | int, ...]:
    return tuple(
        int(part) if index % 2 else part
        for index, part in enumerate(_ISSUE_REFERENCE_PATTERN.split(evidence))
        if part
    )


def _describe_daemon(
    *, daemon_pid: int | None, dreamcatcher_version: str | None
) -> str:
    if daemon_pid is None:
        return "daemon stopped"
    version = (
        ""
        if dreamcatcher_version is None
        else f"dreamcatcher v{dreamcatcher_version} · "
    )
    return f"daemon running · {version}pid {daemon_pid}"


def _compose_instance_facts(*, report: DreamcatcherStatusReport) -> tuple[WebFact, ...]:
    daemon = report.daemon
    scheduler_hold = report.scheduler_hold
    if scheduler_hold is not None and scheduler_hold.startswith("at cap:"):
        scheduler_hold = None
    values: tuple[tuple[str, str | None, bool], ...] = (
        (
            "harness",
            None if daemon.agent_harness is None else str(daemon.agent_harness),
            False,
        ),
        (
            "next update in",
            (
                None
                if daemon.pid is None
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
        ("scheduler hold", scheduler_hold, scheduler_hold is not None),
    )
    return tuple(
        WebFact(label=label, value=value, is_warning=is_warning)
        for label, value, is_warning in values
        if value is not None
    )
