"""Describe the agent rounds of any kind of agent work."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    FinishingErroredAgentRoundEnding,
    HarnessErroredAgentRoundEnding,
    LaunchErroredAgentRoundEnding,
    interpret_agent_round_outcome,
)
from dreamcatcher.agent_work import AgentWork
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignChildChange,
    CampaignChildNotification,
    CampaignRoundInput,
)
from dreamcatcher.documents import read_json_if_exists
from dreamcatcher.feed import read_last_feed_line
from dreamcatcher.github import PullRequestState
from dreamcatcher.harness_adapters import AgentWorkKind, HarnessSessionIdentifier
from dreamcatcher.issue_conversations import ConversationRoundInput
from dreamcatcher.pull_request_work import PullRequestRoundInput
from dreamcatcher.status.findings import describe_changed_children, describe_signal
from dreamcatcher.words import describe_count, describe_span

# What a lead round's trigger calls each change to a sub-issue, apart from a
# change of issue state, which reads as the state that the sub-issue entered.
_CHILD_CHANGE_WORDS = {
    CampaignChildChange.ADDED: "added",
    CampaignChildChange.REMOVED: "removed",
    CampaignChildChange.HANDBACK: "handed back",
    CampaignChildChange.PULL_REQUEST: "pull request changed",
    CampaignChildChange.CHECK_COMPLETION: "checks finished",
    CampaignChildChange.MERGEABLE: "mergeable",
    CampaignChildChange.ENDING: "ended",
    CampaignChildChange.FAULT: "fault",
}


@dataclass(frozen=True, kw_only=True)
class AgentRoundTriggerNotification:
    """Name one sub-issue whose changes woke a lead round, with words for them."""

    issue: int
    changes: str


@dataclass(frozen=True, kw_only=True)
class AgentRoundTrigger:
    """Say what woke one agent round.

    The notifications name the sub-issues whose changes woke a lead round. They
    follow the words for anything else that woke it, which are empty when
    nothing else did.
    """

    words: str
    notifications: Sequence[AgentRoundTriggerNotification] = ()

    def describe(self) -> str:
        """Return what woke the round as one line of plain text."""
        parts = [self.words] if self.words else []
        parts.extend(
            f"#{notification.issue}: {notification.changes}"
            for notification in self.notifications
        )
        return "; ".join(parts)

    def summarize(self) -> str:
        """Return what woke the round in a few words, counting the sub-issues."""
        parts = [self.words] if self.words else []
        if self.notifications:
            parts.append(describe_changed_children(count=len(self.notifications)))
        return ", ".join(parts)


@dataclass(frozen=True, kw_only=True)
class AgentRoundStatus:
    """Describe one agent round for a status view."""

    record: AgentRoundRecord
    trigger: AgentRoundTrigger
    duration_description: str
    outcome: AgentRoundOutcome
    outcome_description: str

    @property
    def listed_outcome_description(self) -> str:
        """Describe the outcome when a round list needs to show it."""
        if self.outcome is AgentRoundOutcome.SUCCESSFUL:
            return ""
        return self.outcome_description


def describe_running_round(
    *,
    record: AgentRoundRecord,
    trigger: AgentRoundTrigger,
    paths: AgentRoundPaths,
    at: datetime,
) -> tuple[str, str | None]:
    """Describe a running round and what woke it, and return its latest output."""
    detail = (
        f"round {record.number}, {trigger.summarize()}, "
        f"running {describe_span(span=at - record.started)}"
    )
    line = read_last_feed_line(path=paths.feed)
    if line is None:
        return f"{detail}, has said nothing yet", None
    since_last_output = describe_span(span=at - line.at)
    return f"{detail}, last output {since_last_output} ago", line.text.strip()


def describe_round_ending(
    *, record: AgentRoundRecord, paths: AgentRoundPaths
) -> tuple[str, str | None]:
    """Describe a round that is no longer running and return its latest output."""
    ending = record.ending
    if isinstance(
        ending,
        LaunchErroredAgentRoundEnding
        | HarnessErroredAgentRoundEnding
        | FinishingErroredAgentRoundEnding,
    ):
        detail = f"round {record.number} errored"
        if ending.status is not None:
            detail = f"{detail} (exit {ending.status})"
        if ending.reason is not None:
            detail = f"{detail}: {ending.reason}"
    else:
        outcome = interpret_agent_round_outcome(record=record, is_daemon_running=False)
        detail = f"round {record.number} {outcome}"
    line = read_last_feed_line(path=paths.feed)
    return detail, None if line is None else line.text.strip()


def find_stoppable_round_paths(
    *,
    is_working: bool,
    harness_session_identifier: HarnessSessionIdentifier | None,
    paths: AgentRoundPaths | None,
) -> AgentRoundPaths | None:
    """Return the live round that can accept a stop request, when one exists."""
    if (
        not is_working
        or harness_session_identifier is None
        or paths is None
        or paths.stop_request.is_file()
    ):
        return None
    return paths


def compose_round_duration_description(*, record: AgentRoundRecord) -> str:
    """Describe how long a round that ended ran, unless it was interrupted."""
    ending = record.ending
    if ending is None or ending.outcome is AgentRoundOutcome.INTERRUPTED:
        return ""
    return f"ran {describe_span(span=ending.at - record.started)}"


def describe_round_outcome(
    *, record: AgentRoundRecord, outcome: AgentRoundOutcome
) -> str:
    """Return the words for the round's outcome.

    A round whose harness failed for no further reason reads with its exit
    status. A round that errored for a reason reads as errored alone, since its
    reason is too long for a list of rounds or a status detail.
    """
    ending = record.ending
    if isinstance(ending, HarnessErroredAgentRoundEnding) and ending.reason is None:
        return f"errored (exit {ending.status})"
    return str(outcome)


def list_round_statuses(*, work: AgentWork, is_working: bool) -> list[AgentRoundStatus]:
    """Return the derived status of every round of the work, in run order."""
    statuses: list[AgentRoundStatus] = []
    for record in work.rounds:
        outcome = interpret_agent_round_outcome(
            record=record,
            is_daemon_running=is_working and record.number == work.rounds[-1].number,
        )
        statuses.append(
            AgentRoundStatus(
                record=record,
                trigger=describe_round_trigger(work=work, number=record.number),
                duration_description=compose_round_duration_description(record=record),
                outcome=outcome,
                outcome_description=describe_round_outcome(
                    record=record, outcome=outcome
                ),
            )
        )
    return statuses


def describe_round_trigger(*, work: AgentWork, number: int) -> AgentRoundTrigger:
    """Describe what woke one round of the work, from the input it was given."""
    if work.record.kind is AgentWorkKind.CAMPAIGN:
        return _describe_campaign_round_trigger(work=work, number=number)
    if work.record.kind is AgentWorkKind.CONVERSATION:
        return AgentRoundTrigger(
            words=_describe_conversation_round_trigger(work=work, number=number)
        )
    return AgentRoundTrigger(
        words=_describe_assignment_round_trigger(work=work, number=number)
    )


def _describe_conversation_round_trigger(*, work: AgentWork, number: int) -> str:
    """Count the comments that woke one conversation round.

    Comments wake every conversation round, so one whose input is still to be
    written, or never was, says so without a count.
    """
    conversation_input = read_json_if_exists(
        model=ConversationRoundInput,
        path=work.compose_round_paths(number=number).round_input,
    )
    if conversation_input is None:
        return "comments"
    return describe_count(number=len(conversation_input.comments), noun="comment")


def _describe_assignment_round_trigger(*, work: AgentWork, number: int) -> str:
    """Say what woke one assignment round."""
    round_input = read_json_if_exists(
        model=PullRequestRoundInput,
        path=work.compose_round_paths(number=number).round_input,
    )
    if round_input is None:
        return "start"
    return _describe_pull_request_trigger(round_input=round_input) or "recover"


def _describe_pull_request_trigger(*, round_input: PullRequestRoundInput) -> str:
    if round_input.pull_request_state is not PullRequestState.OPEN:
        return round_input.pull_request_state.lower()
    words = [describe_signal(signal=signal) for signal in round_input.signals]
    if round_input.user_posts:
        words.insert(0, describe_count(number=len(round_input.user_posts), noun="post"))
    return ", ".join(words)


def _describe_campaign_round_trigger(
    *, work: AgentWork, number: int
) -> AgentRoundTrigger:
    """Describe what woke a lead round, including its sub-issue notifications."""
    campaign_input = read_json_if_exists(
        model=CampaignRoundInput,
        path=work.compose_round_paths(number=number).round_input,
    )
    if number == 1:
        return AgentRoundTrigger(words="start")
    if campaign_input is None:
        return AgentRoundTrigger(words="pull request or sub-issue changes")
    words = _describe_pull_request_trigger(round_input=campaign_input)
    return AgentRoundTrigger(
        words=words or ("" if campaign_input.notifications else "recover"),
        notifications=tuple(
            _describe_notification(
                notification=notification, children=campaign_input.children
            )
            for notification in campaign_input.notifications
        ),
    )


def _describe_notification(
    *, notification: CampaignChildNotification, children: Sequence[CampaignChild]
) -> AgentRoundTriggerNotification:
    """Name the sub-issue of one notification, with words for each of its changes.

    A change of issue state reads as closed or reopened, by the state of the
    sub-issue among the children that the round was given.
    """
    is_closed = any(
        child.is_closed for child in children if child.issue == notification.issue
    )
    words = {
        **_CHILD_CHANGE_WORDS,
        CampaignChildChange.ISSUE_STATE: "closed" if is_closed else "reopened",
    }
    return AgentRoundTriggerNotification(
        issue=notification.issue,
        changes=", ".join(words[change] for change in notification.changes),
    )
