"""Describe the requests that have no open agent work, and why nothing started."""

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    ReadFailureFinding,
    RequestRow,
    StartTimeFinding,
)
from dreamcatcher.status.findings import (
    describe_comments_to_answer,
    describe_conflicting_labels,
    describe_read_failure,
)

# What the tick finds for a request with no open work: what decides whether work
# may start, or why that read failed.
type _StartFinding = (
    StartTimeFinding
    | IssueCommentsFinding
    | ConflictingLabelsFinding
    | ReadFailureFinding
)


class RequestStatusValue(StrEnum):
    """List the summary statuses of a request that has no open agent work.

    Available means that work starts once an agent slot is free. Blocked means
    that an open pull request claims the issue or an open issue blocks it. Idle
    means that a conversation waits for the user's first comment. Routing
    conflict means that the user must remove all but one label of the kind.
    """

    AVAILABLE = "available"
    BLOCKED = "blocked"
    IDLE = "idle"
    ROUTING_CONFLICT = "routing conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class RequestReason:
    """Say one thing that holds a request back, with the numbers that it names."""

    words: str
    issues: tuple[int, ...] = ()
    pull_requests: tuple[int, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RequestStatus:
    """Describe a request that has no open agent work, from the tick's row.

    Every request status has at least one reason, which a view shows as its
    words.
    """

    row: RequestRow
    value: RequestStatusValue
    reasons: tuple[RequestReason, ...]


def describe_request(*, row: RequestRow) -> RequestStatus:
    """Return the status of a request that the tick found no open work for."""
    value, reasons = _describe_finding(finding=cast("_StartFinding", row.finding))
    return RequestStatus(row=row, value=value, reasons=reasons)


def _describe_finding(
    *, finding: _StartFinding
) -> tuple[RequestStatusValue, tuple[RequestReason, ...]]:
    """Return the status and reasons that what the tick found gives a request."""
    if isinstance(finding, StartTimeFinding):
        return _describe_start_time_answers(finding=finding)
    if isinstance(finding, IssueCommentsFinding):
        if finding.new_comments:
            return RequestStatusValue.AVAILABLE, (
                RequestReason(
                    words=describe_comments_to_answer(count=finding.new_comments)
                ),
            )
        return RequestStatusValue.IDLE, (RequestReason(words="waiting for a comment"),)
    if isinstance(finding, ConflictingLabelsFinding):
        return RequestStatusValue.ROUTING_CONFLICT, (
            RequestReason(words=describe_conflicting_labels(labels=finding.labels)),
        )
    return RequestStatusValue.UNKNOWN, (
        RequestReason(words=describe_read_failure(reason=finding.reason)),
    )


def _describe_start_time_answers(
    *, finding: StartTimeFinding
) -> tuple[RequestStatusValue, tuple[RequestReason, ...]]:
    """Return what claims or blocks an issue, or that nothing does."""
    if finding.is_clear:
        return RequestStatusValue.AVAILABLE, (
            RequestReason(words=str(RequestStatusValue.AVAILABLE)),
        )
    reasons = []
    if finding.linked_pull_requests:
        reasons.append(
            RequestReason(
                words="claimed by",
                pull_requests=tuple(finding.linked_pull_requests),
            )
        )
    if finding.blocking_issues:
        reasons.append(
            RequestReason(words="blocked by", issues=tuple(finding.blocking_issues))
        )
    return RequestStatusValue.BLOCKED, tuple(reasons)
