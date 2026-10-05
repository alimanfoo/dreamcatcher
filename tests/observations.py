"""Build issue observations for tests."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from conftest import ASSIGNMENT_LABEL

from dreamcatcher.issue_conversations import compose_conversation_identifier
from dreamcatcher.scheduler.models import (
    ConversationObservation,
    IssueObservation,
    ObservedFact,
    ObservedIssueDetails,
    Truth,
)

OBSERVED_AT = datetime(2026, 8, 19, 18, 41, 58, tzinfo=UTC)


def _observed_issue_fact(
    *, value: Truth, evidence: str | None, name: str
) -> ObservedFact:
    if evidence is None:
        evidence = (
            f"cannot tell {name}" if value is Truth.UNKNOWN else f"{name} is {value}"
        )
    return ObservedFact(value=value, evidence=evidence)


def observed_issue(
    *,
    issue: int,
    title: str = "",
    created_at: datetime | None = OBSERVED_AT,
    assignment_labels: Sequence[str] | None = (ASSIGNMENT_LABEL,),
    values: Mapping[str, Truth] | None = None,
    evidence: Mapping[str, str] | None = None,
) -> IssueObservation:
    """Return one issue observation with known available defaults."""
    fact_values = {
        "is_open": Truth.TRUE,
        "is_assigned_to_user": Truth.TRUE,
        "claimed_here": Truth.FALSE,
        "claimed_elsewhere": Truth.FALSE,
        "blocked": Truth.FALSE,
        "routing_conflict": Truth.FALSE,
    }
    fact_values.update(values or {})
    fact_evidence = evidence or {}
    return IssueObservation(
        issue=issue,
        details=(
            None
            if created_at is None or assignment_labels is None
            else ObservedIssueDetails(
                title=title,
                created_at=created_at,
                assignment_labels=list(assignment_labels),
            )
        ),
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
    value: Truth = Truth.FALSE,
    evidence: str | None = None,
    routing_conflict: Truth = Truth.FALSE,
    routing_conflict_evidence: str | None = None,
) -> ConversationObservation:
    """Return what a tick found at a matching conversation issue.

    The title matches the one `records.write_conversation` saves.
    """
    return ConversationObservation(
        identifier=compose_conversation_identifier(issue=issue),
        issue=issue,
        title=f"Issue {issue}",
        requires_round=_observed_issue_fact(
            value=value,
            evidence=evidence,
            name="whether comments wait to be answered",
        ),
        routing_conflict=_observed_issue_fact(
            value=routing_conflict,
            evidence=routing_conflict_evidence,
            name="whether the issue has a conversation routing conflict",
        ),
    )
