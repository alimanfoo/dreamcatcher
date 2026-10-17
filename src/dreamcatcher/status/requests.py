"""Describe the requests that have no open agent work, and why nothing started."""

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    ReadFailure,
    RequestRow,
    StartTimeFinding,
)
from dreamcatcher.words import describe_count

# What the tick finds for a request with no open work: what decides whether work
# may start, or why that read failed.
type _StartFinding = (
    StartTimeFinding | IssueCommentsFinding | ConflictingLabelsFinding | ReadFailure
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
    """Describe a request that has no open agent work, from the tick's row."""

    issue: int
    title: str
    dispatch_label: str
    kind: AgentWorkKind
    value: RequestStatusValue
    reasons: tuple[RequestReason, ...]


def describe_request(*, row: RequestRow) -> RequestStatus:
    """Return the status of a request that the tick found no open work for."""
    value, reasons = _describe_finding(finding=cast("_StartFinding", row.finding))
    return RequestStatus(
        issue=row.issue,
        title=row.title,
        dispatch_label=row.dispatch_label,
        kind=row.kind,
        value=value,
        reasons=reasons,
    )


def _describe_finding(
    *, finding: _StartFinding
) -> tuple[RequestStatusValue, tuple[RequestReason, ...]]:
    """Return the status and reasons that what the tick found gives a request."""
    if isinstance(finding, StartTimeFinding):
        return _describe_start_time_answers(finding=finding)
    if isinstance(finding, IssueCommentsFinding):
        if finding.new_comments:
            comments = describe_count(number=finding.new_comments, noun="comment")
            return RequestStatusValue.AVAILABLE, (
                RequestReason(words=f"{comments} to answer"),
            )
        return RequestStatusValue.IDLE, (RequestReason(words="waiting for a comment"),)
    if isinstance(finding, ConflictingLabelsFinding):
        return RequestStatusValue.ROUTING_CONFLICT, (
            RequestReason(words="conflicting labels " + ", ".join(finding.labels)),
        )
    return RequestStatusValue.UNKNOWN, (
        RequestReason(words=f"cannot tell: {finding.reason}"),
    )


def _describe_start_time_answers(
    *, finding: StartTimeFinding
) -> tuple[RequestStatusValue, tuple[RequestReason, ...]]:
    """Return what claims or blocks an issue, or that nothing does."""
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
    if reasons:
        return RequestStatusValue.BLOCKED, tuple(reasons)
    return RequestStatusValue.AVAILABLE, ()
