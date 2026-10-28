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
    IssueReference,
    LabelAppliedByOtherFinding,
    ReadFailureFinding,
    RequestRow,
    StartTimeFinding,
)
from dreamcatcher.status.findings import (
    REAPPLY_LABEL_ADVICE,
    describe_comments_to_answer,
    describe_conflicting_label_advice,
    describe_conflicting_labels,
    describe_issue_state,
    describe_label_applier,
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
class IssueFact:
    """Say one thing that GitHub holds about a request's issue.

    A fact names the pull requests it refers to as numbers, and the issues
    by references that name another repository where one holds the issue.
    """

    words: str
    issues: Sequence[IssueReference] = ()
    pull_requests: Sequence[int] = ()


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
    if isinstance(finding, LabelAppliedByOtherFinding):
        return RequestStatus(
            row=row,
            value=RequestStatusValue.HELD,
            issue_facts=(
                IssueFact(words=describe_label_applier(applier=finding.applier)),
            ),
            detail=REAPPLY_LABEL_ADVICE,
        )
    if isinstance(finding, ConflictingLabelsFinding):
        return RequestStatus(
            row=row,
            value=RequestStatusValue.HELD,
            issue_facts=(IssueFact(words=describe_conflicting_labels(kind=row.kind)),),
            detail=describe_conflicting_label_advice(labels=finding.labels),
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
