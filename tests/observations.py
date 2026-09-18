"""Build issue observations for tests."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from conftest import LABEL

from dreamcatcher.scheduler import IssueFact, IssueFactValue, IssueObservation

OBSERVED_AT = datetime(2026, 8, 19, 18, 41, 58, tzinfo=UTC)


def observed_issue(
    *,
    issue: int,
    created_at: datetime | None = OBSERVED_AT,
    dispatch_labels: Sequence[str] | None = (LABEL,),
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
        is_open=IssueFact(
            value=fact_values["is_open"], evidence=fact_evidence.get("is_open")
        ),
        is_assigned_to_user=IssueFact(
            value=fact_values["is_assigned_to_user"],
            evidence=fact_evidence.get("is_assigned_to_user"),
        ),
        dispatch_labels=(None if dispatch_labels is None else list(dispatch_labels)),
        claimed_here=IssueFact(
            value=fact_values["claimed_here"],
            evidence=fact_evidence.get("claimed_here"),
        ),
        claimed_elsewhere=IssueFact(
            value=fact_values["claimed_elsewhere"],
            evidence=fact_evidence.get("claimed_elsewhere"),
        ),
        blocked=IssueFact(
            value=fact_values["blocked"], evidence=fact_evidence.get("blocked")
        ),
        routing_conflict=IssueFact(
            value=fact_values["routing_conflict"],
            evidence=fact_evidence.get("routing_conflict"),
        ),
    )
