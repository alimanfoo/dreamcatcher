"""Build the scheduler's request rows for tests."""

from collections.abc import Sequence

from conftest import ASSIGNMENT_LABEL

from dreamcatcher.github import IssueState
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import (
    CampaignChild,
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
    AgentWorkKind.CAMPAIGN: "dream:big",
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
    test gives it. The row holds the issue as open, as the tick read it.
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
        issue_state=IssueState.OPEN,
    )


def compose_open_assignment_row(
    *,
    issue: int,
    agent_work_identifier: str,
    ended_round: int | None = None,
    finding: RequestFinding | None = None,
    started_round: StartedRound | None = None,
) -> RequestRow:
    """Return the row of an open assignment, whose issue the tick does not read."""
    return compose_request_row(
        issue=issue,
        agent_work_identifier=agent_work_identifier,
        ended_round=ended_round,
        finding=finding,
        started_round=started_round,
    ).model_copy(update={"issue_state": None})


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


def compose_campaign_row(
    *,
    issue: int,
    finding: RequestFinding | None,
    label: str | None = None,
    agent_work_identifier: str | None = None,
    ended_round: int | None = None,
    started_round: StartedRound | None = None,
    children: Sequence[CampaignChild] | None = None,
) -> RequestRow:
    """Return the row of a campaign request at the parent issue.

    The title is `Parent <n>`. The row names no campaign unless the test gives
    its identifier, and its children are unknown unless the test gives them.
    """
    return compose_request_row(
        issue=issue,
        kind=AgentWorkKind.CAMPAIGN,
        label=label,
        agent_work_identifier=agent_work_identifier,
        ended_round=ended_round,
        finding=finding,
        started_round=started_round,
    ).model_copy(
        update={
            "title": f"Parent {issue}",
            "children": None if children is None else list(children),
        }
    )
