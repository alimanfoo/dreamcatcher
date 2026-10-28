"""Describe the requests that have no open agent work, and why nothing started."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from dreamcatcher.github import IssueState
from dreamcatcher.scheduler.models import (
    BlockingIssuesFinding,
    CampaignFinding,
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    LabelAppliedByOtherFinding,
    ReadFailureFinding,
    RequestRow,
    StartTimeFinding,
)
from dreamcatcher.status.findings import (
    IssueFact,
    describe_comments_to_answer,
    describe_hold,
    describe_issue_state,
)

# What the tick finds for a request with no open work: what decides whether work
# may start, or why that read failed.
type _StartFinding = (
    StartTimeFinding
    | BlockingIssuesFinding
    | IssueCommentsFinding
    | CampaignFinding
    | ConflictingLabelsFinding
    | LabelAppliedByOtherFinding
    | ReadFailureFinding
)


class RequestStatusValue(StrEnum):
    """List the summary statuses of a request that has no open agent work.

    Available means that work starts once an agent slot is free. Held means
    that the scheduler holds the request back for what GitHub says of its
    issue: an open issue blocks it, a linked open pull request claims it,
    someone other than the user applied its label, or it carries a second
    label of its kind. Idle means that a conversation waits for the user's first
    comment. Unknown means that a read that decides whether work may start
    failed.
    """

    AVAILABLE = "available"
    HELD = "held"
    IDLE = "idle"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class RequestStatus:
    """Describe a request that has no open agent work, from the tick's row.

    The issue's facts are what GitHub says that qualifies the issue's state,
    and the detail is what _dreamcatcher_ found or what the user has to do.
    """

    row: RequestRow
    value: RequestStatusValue
    issue_facts: Sequence[IssueFact]
    detail: str | None

    @property
    def issue_state(self) -> str:
        """The state of the request's issue in words.

        The tick finds requests only on the open issues that it lists.
        """
        return describe_issue_state(state=IssueState.OPEN)


def describe_request(*, row: RequestRow) -> RequestStatus:
    """Return the status of a request that the tick found no open work for."""
    finding = cast("_StartFinding", row.finding)
    if isinstance(finding, ReadFailureFinding):
        return RequestStatus(
            row=row,
            value=RequestStatusValue.UNKNOWN,
            issue_facts=(),
            detail=finding.reason,
        )
    if isinstance(finding, IssueCommentsFinding):
        return _describe_comments(row=row, finding=finding)
    if isinstance(finding, LabelAppliedByOtherFinding | ConflictingLabelsFinding):
        fact, advice = describe_hold(finding=finding, kind=row.kind)
        return RequestStatus(
            row=row,
            value=RequestStatusValue.HELD,
            issue_facts=(fact,),
            detail=advice,
        )
    facts = _list_holding_facts(finding=finding)
    return RequestStatus(
        row=row,
        value=RequestStatusValue.HELD if facts else RequestStatusValue.AVAILABLE,
        issue_facts=facts,
        detail=None,
    )


def _list_holding_facts(
    *, finding: StartTimeFinding | BlockingIssuesFinding | CampaignFinding
) -> tuple[IssueFact, ...]:
    """Return the open issues that block a request's issue, then the pull requests.

    The pull requests are the open ones that claim an assignment request's
    issue.
    """
    facts = []
    if not isinstance(finding, CampaignFinding) and finding.blocking_issues:
        facts.append(
            IssueFact(words="blocked by", issues=tuple(finding.blocking_issues))
        )
    if isinstance(finding, StartTimeFinding) and finding.linked_pull_requests:
        facts.append(
            IssueFact(
                words="linked to", pull_requests=tuple(finding.linked_pull_requests)
            )
        )
    return tuple(facts)


def _describe_comments(
    *, row: RequestRow, finding: IssueCommentsFinding
) -> RequestStatus:
    """Return what a conversation request has to answer, or that it waits for it."""
    if finding.new_comments:
        return RequestStatus(
            row=row,
            value=RequestStatusValue.AVAILABLE,
            issue_facts=(),
            detail=describe_comments_to_answer(count=finding.new_comments),
        )
    return RequestStatus(
        row=row,
        value=RequestStatusValue.IDLE,
        issue_facts=(),
        detail="waiting for a comment",
    )
