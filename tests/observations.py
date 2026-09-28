"""Build issue observations for tests."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from conftest import DISPATCH_LABEL

from dreamcatcher.scheduler import (
    FalseIssueFact,
    IssueConversationObservation,
    IssueFact,
    IssueFactValue,
    IssueObservation,
    TrueIssueFact,
    UnknownIssueFact,
)

OBSERVED_AT = datetime(2026, 8, 19, 18, 41, 58, tzinfo=UTC)


def _observed_issue_fact(
    *, value: IssueFactValue, evidence: str | None, name: str
) -> IssueFact:
    if value is IssueFactValue.TRUE:
        return TrueIssueFact(evidence=evidence or f"{name} is true")
    if value is IssueFactValue.UNKNOWN:
        return UnknownIssueFact(evidence=evidence or f"cannot tell {name}")
    return FalseIssueFact(evidence=evidence)


def observed_issue(
    *,
    issue: int,
    created_at: datetime | None = OBSERVED_AT,
    dispatch_labels: Sequence[str] | None = (DISPATCH_LABEL,),
    values: Mapping[str, IssueFactValue] | None = None,
    evidence: Mapping[str, str] | None = None,
) -> IssueObservation:
    """Return one issue observation with known available defaults."""
    fact_values = {
        "is_open": IssueFactValue.TRUE,
        "is_assigned_to_user": IssueFactValue.TRUE,
        "claimed_here": IssueFactValue.FALSE,
        "claimed_elsewhere": IssueFactValue.FALSE,
        "blocked": IssueFactValue.FALSE,
        "routing_conflict": IssueFactValue.FALSE,
    }
    fact_values.update(values or {})
    fact_evidence = evidence or {}
    return IssueObservation(
        issue=issue,
        created_at=created_at,
        is_open=_observed_issue_fact(
            value=fact_values["is_open"],
            evidence=fact_evidence.get("is_open"),
            name="whether the issue is open",
        ),
        is_assigned_to_user=_observed_issue_fact(
            value=fact_values["is_assigned_to_user"],
            evidence=fact_evidence.get("is_assigned_to_user"),
            name="whether the issue is assigned to the user",
        ),
        dispatch_labels=(None if dispatch_labels is None else list(dispatch_labels)),
        claimed_here=_observed_issue_fact(
            value=fact_values["claimed_here"],
            evidence=fact_evidence.get("claimed_here"),
            name="whether the issue is claimed here",
        ),
        claimed_elsewhere=_observed_issue_fact(
            value=fact_values["claimed_elsewhere"],
            evidence=fact_evidence.get("claimed_elsewhere"),
            name="whether the issue is claimed elsewhere",
        ),
        blocked=_observed_issue_fact(
            value=fact_values["blocked"],
            evidence=fact_evidence.get("blocked"),
            name="whether the issue is blocked",
        ),
        routing_conflict=_observed_issue_fact(
            value=fact_values["routing_conflict"],
            evidence=fact_evidence.get("routing_conflict"),
            name="whether the issue has a routing conflict",
        ),
    )


def observed_conversation(
    *,
    issue: int = 8,
    value: IssueFactValue = IssueFactValue.FALSE,
    evidence: str | None = None,
) -> IssueConversationObservation:
    """Return what a tick found at an eligible conversation issue.

    The title matches the one `records.write_issue_conversation` saves.
    """
    return IssueConversationObservation(
        issue=issue,
        title=f"Issue {issue}",
        has_comments_to_answer=_observed_issue_fact(
            value=value,
            evidence=evidence,
            name="whether comments wait to be answered",
        ),
    )
