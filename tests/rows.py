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


def request_row(
    *,
    issue: int,
    kind: AgentWorkKind = AgentWorkKind.ASSIGNMENT,
    title: str | None = None,
    label: str | None = None,
    agent_work_identifier: str | None = None,
    finding: RequestFinding | None = None,
    started_round: StartedRound | None = None,
) -> RequestRow:
    """Return the row of the request that a label of that kind makes on the issue.

    The title is `Issue <n>` and the label is the kind's usual one unless the
    test gives them.
    """
    return RequestRow(
        issue=issue,
        title=f"Issue {issue}" if title is None else title,
        dispatch_label=(
            label
            if label is not None
            else ASSIGNMENT_LABEL
            if kind is AgentWorkKind.ASSIGNMENT
            else CONVERSATION_LABEL
        ),
        kind=kind,
        agent_work_identifier=agent_work_identifier,
        finding=finding,
        started_round=started_round,
    )
