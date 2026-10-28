"""Describe the requests that have no open agent work, and why nothing started."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from dreamcatcher.harness_adapters import AgentWorkKind
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
    describe_comments_to_answer,
    describe_conflicting_labels,
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

    Available means that work starts once an agent slot is free. Blocked means
    that an open pull request claims an assignment's issue, or that an open
    issue blocks an assignment's issue or a campaign's parent. Held means that
    someone other than the user applied the label, so the user must remove and
    re-add it. Idle means that a conversation waits for the user's first
    comment. Routing conflict means that the user must remove all but one label
    of the kind.
    """

    AVAILABLE = "available"
    BLOCKED = "blocked"
    HELD = "held"
    IDLE = "idle"
    ROUTING_CONFLICT = "routing conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class RequestReason:
    """Say one thing about why no work has started for a request.

    A reason names the pull requests it refers to as numbers, and the issues
    by references that name another repository where one holds the issue.
    """

    words: str
    issues: Sequence[IssueReference] = ()
    pull_requests: Sequence[int] = ()


@dataclass(frozen=True, kw_only=True)
class RequestStatus:
    """Describe a request that has no open agent work, from the tick's row.

    Every request status has at least one reason, which a view shows as its
    words.
    """

    row: RequestRow
    value: RequestStatusValue
    reasons: Sequence[RequestReason]


def describe_request(*, row: RequestRow) -> RequestStatus:
    """Return the status of a request that the tick found no open work for."""
    value, reasons = _describe_finding(
        finding=cast("_StartFinding", row.finding), kind=row.kind
    )
    return RequestStatus(row=row, value=value, reasons=reasons)


def _describe_finding(
    *, finding: _StartFinding, kind: AgentWorkKind
) -> tuple[RequestStatusValue, tuple[RequestReason, ...]]:
    """Return the status and reasons that what the tick found gives a request."""
    if isinstance(finding, StartTimeFinding):
        return _describe_start_time_answers(finding=finding)
    if isinstance(finding, BlockingIssuesFinding):
        return RequestStatusValue.BLOCKED, (
            _describe_blockers(issues=finding.blocking_issues),
        )
    if isinstance(finding, CampaignFinding):
        return _describe_available()
    if isinstance(finding, IssueCommentsFinding):
        return _describe_comments(finding=finding)
    value, words = _describe_single_reason(finding=finding, kind=kind)
    return value, (RequestReason(words=words),)


def _describe_single_reason(
    *,
    finding: ConflictingLabelsFinding | LabelAppliedByOtherFinding | ReadFailureFinding,
    kind: AgentWorkKind,
) -> tuple[RequestStatusValue, str]:
    """Return the status of a request whose finding gives one reason, and its words."""
    if isinstance(finding, LabelAppliedByOtherFinding):
        return RequestStatusValue.HELD, describe_label_applier(applier=finding.applier)
    if isinstance(finding, ConflictingLabelsFinding):
        return RequestStatusValue.ROUTING_CONFLICT, describe_conflicting_labels(
            kind=kind, labels=finding.labels
        )
    return RequestStatusValue.UNKNOWN, finding.reason


def _describe_start_time_answers(
    *, finding: StartTimeFinding
) -> tuple[RequestStatusValue, tuple[RequestReason, ...]]:
    """Return what claims or blocks an issue, or that nothing does."""
    if finding.is_clear:
        return _describe_available()
    reasons = []
    if finding.linked_pull_requests:
        reasons.append(
            RequestReason(
                words="claimed by",
                pull_requests=tuple(finding.linked_pull_requests),
            )
        )
    if finding.blocking_issues:
        reasons.append(_describe_blockers(issues=finding.blocking_issues))
    return RequestStatusValue.BLOCKED, tuple(reasons)


def _describe_comments(
    *, finding: IssueCommentsFinding
) -> tuple[RequestStatusValue, tuple[RequestReason, ...]]:
    """Return what a conversation request has to answer, or that it waits for it."""
    if finding.new_comments:
        return RequestStatusValue.AVAILABLE, (
            RequestReason(
                words=describe_comments_to_answer(count=finding.new_comments)
            ),
        )
    return RequestStatusValue.IDLE, (RequestReason(words="waiting for a comment"),)


def _describe_blockers(*, issues: Sequence[IssueReference]) -> RequestReason:
    """Return the reason that names the open issues blocking a request's issue."""
    return RequestReason(words="blocked by", issues=tuple(issues))


def _describe_available() -> tuple[RequestStatusValue, tuple[RequestReason, ...]]:
    """Return the status of a request whose work starts once a slot is free."""
    return RequestStatusValue.AVAILABLE, (
        RequestReason(words=str(RequestStatusValue.AVAILABLE)),
    )
