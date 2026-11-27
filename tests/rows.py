"""Build the scheduler's request rows for tests."""

from collections.abc import Sequence

from conftest import ASSIGNMENT_LABEL, HEAD

from dreamcatcher.github import (
    CheckResult,
    IssueState,
    PullRequestMergeState,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import (
    CampaignChild,
    PullRequestFinding,
    RequestFinding,
    RequestRow,
    StartedRound,
    StartTimeFinding,
)

# What the start-time questions answer for an issue nothing claims or blocks.
UNCLAIMED = StartTimeFinding(linked_pull_requests=[], blocking_issues=[])

CAMPAIGN_PULL_REQUEST = 90

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
            "issue_state": IssueState.OPEN if agent_work_identifier is None else None,
        }
    )


def compose_campaign_finding(
    *,
    new_posts: int = 0,
    changed_children: int = 0,
    number: int = CAMPAIGN_PULL_REQUEST,
) -> PullRequestFinding:
    """Return the finding of a draft campaign pull request with passing checks."""
    return PullRequestFinding(
        number=number,
        state=PullRequestState.OPEN,
        is_draft=True,
        merge_state=PullRequestMergeState.CLEAN,
        head=HEAD,
        check_result=CheckResult.PASSING,
        has_running_checks=False,
        new_posts=new_posts,
        new_pull_request_signals=[],
        is_check_failure_withheld=False,
        is_wrap_up_due=False,
        changed_children=changed_children,
    )
