"""Describe the agent rounds of either kind of agent work."""

from dataclasses import dataclass
from datetime import datetime

from dreamcatcher.agent_assignments import AssignmentRoundInput
from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    ErroredAgentRoundEnding,
)
from dreamcatcher.agent_work import AgentWork
from dreamcatcher.documents import read_json_if_exists
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import read_last_feed_line
from dreamcatcher.github import PullRequestState
from dreamcatcher.harness_adapters import AgentWorkKind, HarnessSessionIdentifier
from dreamcatcher.issue_conversations import (
    ConversationRoundInput,
    read_conversation_input,
)
from dreamcatcher.status.findings import describe_signal
from dreamcatcher.words import describe_count, describe_span


@dataclass(frozen=True, kw_only=True)
class AgentRoundRevision:
    """Describe the code revision one agent round investigated."""

    value: str
    description: str


@dataclass(frozen=True, kw_only=True)
class AgentRoundStatus:
    """Describe one agent round for a status view."""

    record: AgentRoundRecord
    trigger_description: str
    duration_description: str
    outcome_description: str
    revision: AgentRoundRevision | None = None


def describe_running_round(
    *,
    record: AgentRoundRecord,
    trigger_description: str,
    paths: AgentRoundPaths,
    at: datetime,
) -> tuple[str, str | None]:
    """Describe a running round and what woke it, and return its latest output."""
    detail = (
        f"round {record.number}, {trigger_description}, "
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
    if isinstance(ending, ErroredAgentRoundEnding):
        detail = f"round {record.number} errored"
        if ending.status is not None:
            detail = f"{detail} (exit {ending.status})"
        if ending.reason is not None:
            detail = f"{detail}: {ending.reason}"
    else:
        outcome = describe_round_outcome(record=record, is_working=False)
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
    """Describe how long a completed, uninterrupted round ran."""
    ending = record.ending
    if ending is None or ending.outcome is AgentRoundOutcome.INTERRUPTED:
        return ""
    return f"ran {describe_span(span=ending.at - record.started)}"


def describe_round_outcome(*, record: AgentRoundRecord, is_working: bool) -> str:
    """Return how the round ended, or what it is doing instead.

    A round that recorded no ending never finished. It is running when a daemon
    is still there to run it, and interrupted once that daemon has gone, since
    a round cannot outlive its daemon. A round that errored for a reason reads as
    errored alone, since its exit status, if it has one, says nothing and its
    reason is too long for a list of rounds.
    """
    if isinstance(record.ending, ErroredAgentRoundEnding):
        if record.ending.reason is not None:
            return str(AgentRoundOutcome.ERRORED)
        return f"errored (exit {record.ending.status})"
    if record.ending is None and not is_working:
        return str(AgentRoundOutcome.INTERRUPTED)
    return str(record.outcome)


def list_round_statuses(*, work: AgentWork, is_working: bool) -> list[AgentRoundStatus]:
    """Return the derived status of every round of the work, in run order.

    A conversation round also names the code revision it investigated, against
    the revision of the conversation round before it.
    """
    statuses: list[AgentRoundStatus] = []
    previous_revision = None
    for record in work.rounds:
        revision = None
        if work.record.kind is AgentWorkKind.CONVERSATION:
            round_input = _read_conversation_input(work=work, number=record.number)
            if round_input is not None:
                revision = _compose_round_revision(
                    previous_revision=previous_revision, revision=round_input.revision
                )
                previous_revision = round_input.revision
        statuses.append(
            AgentRoundStatus(
                record=record,
                trigger_description=describe_round_trigger(
                    work=work, number=record.number
                ),
                duration_description=compose_round_duration_description(record=record),
                outcome_description=describe_round_outcome(
                    record=record,
                    is_working=is_working and record.number == work.rounds[-1].number,
                ),
                revision=revision,
            )
        )
    return statuses


def describe_round_trigger(*, work: AgentWork, number: int) -> str:
    """Describe what woke one round of the work, from the input it was given.

    An assignment round given no input started the assignment. Comments wake
    every conversation round, so one whose input is still to be written, or
    never was, says so without a count.
    """
    if work.record.kind is AgentWorkKind.CONVERSATION:
        conversation_input = _read_conversation_input(work=work, number=number)
        if conversation_input is None:
            return "comments"
        return describe_count(number=len(conversation_input.comments), noun="comment")
    assignment_input = read_json_if_exists(
        model=AssignmentRoundInput,
        path=work.compose_round_paths(number=number).round_input,
    )
    if assignment_input is None:
        return "start"
    if assignment_input.pull_request_state is not PullRequestState.OPEN:
        return assignment_input.pull_request_state.lower()
    words = [describe_signal(signal=signal) for signal in assignment_input.signals]
    if assignment_input.user_posts:
        words.insert(
            0, describe_count(number=len(assignment_input.user_posts), noun="post")
        )
    return ", ".join(words) or "carry on"


def _read_conversation_input(
    *, work: AgentWork, number: int
) -> ConversationRoundInput | None:
    """Return one conversation round's input, or None when it cannot be read."""
    try:
        return read_conversation_input(conversation=work, number=number)
    except ReportableError:
        return None


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
