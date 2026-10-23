"""Build the scheduler's request rows for tests."""

from conftest import ASSIGNMENT_LABEL

from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import (
    RequestFinding,
    RequestRow,
    StartedRound,
    StartTimeFinding,
)

# What the start-time questions answer for an issue nothing claims or blocks.
UNCLAIMED = StartTimeFinding(linked_pull_requests=[], blocking_issues=[])

CONVERSATION_LABEL = "dream:conversation"

# The label that a request of each kind carries unless a test gives another.
_USUAL_LABELS = {
    AgentWorkKind.ASSIGNMENT: ASSIGNMENT_LABEL,
    AgentWorkKind.CONVERSATION: CONVERSATION_LABEL,
    AgentWorkKind.CAMPAIGN: "dream:lead",
}


def compose_request_row(
    *,
    issue: int,
    kind: AgentWorkKind = AgentWorkKind.ASSIGNMENT,
    label: str | None = None,
    agent_work_identifier: str | None = None,
    ended_round: int | None = None,
    finding: RequestFinding | None = None,
    started_round: StartedRound | None = None,
) -> RequestRow:
    """Return the row of the request that a label of that kind makes on the issue.

    The title is `Issue <n>`, and the label is the kind's usual one unless the
    test gives it.
    """
    return RequestRow(
        issue=issue,
        title=f"Issue {issue}",
        dispatch_label=_USUAL_LABELS[kind] if label is None else label,
        kind=kind,
        agent_work_identifier=agent_work_identifier,
        ended_round=ended_round,
        finding=finding,
        started_round=started_round,
    )


def compose_conversation_row(
    *,
    finding: RequestFinding | None,
    issue: int = 8,
    title: str | None = None,
    label: str | None = None,
    agent_work_identifier: str | None = None,
    ended_round: int | None = None,
    started_round: StartedRound | None = None,
) -> RequestRow:
    """Return the row of a conversation request at the issue.

    The row names no conversation unless the test gives its identifier. Its
    title is `Issue <n>` unless the test gives another.
    """
    row = compose_request_row(
        issue=issue,
        kind=AgentWorkKind.CONVERSATION,
        label=label,
        agent_work_identifier=agent_work_identifier,
        ended_round=ended_round,
        finding=finding,
        started_round=started_round,
    )
    return row if title is None else row.model_copy(update={"title": title})
