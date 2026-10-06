"""Derive the status of the issues a status report shows."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dreamcatcher.agent_assignments import Assignment, find_open_assignments_by_issue
from dreamcatcher.scheduler.models import (
    IssueObservation,
    ObservedFact,
    SchedulerRecord,
    Truth,
)


class IssueStatusValue(StrEnum):
    """List the reasons a status report shows an observed issue."""

    FAILED_SETUP = "failed setup"
    ROUTING_CONFLICT = "routing conflict"
    BLOCKED = "blocked"
    AVAILABLE = "available"


@dataclass(frozen=True, kw_only=True)
class IssueEvidence:
    """Give one piece of evidence for an issue's status."""

    text: str
    names_issues: bool = False


@dataclass(frozen=True, kw_only=True)
class IssueStatus:
    """Describe why a status report shows an observed issue, with the evidence."""

    observation: IssueObservation
    value: IssueStatusValue
    evidence: tuple[IssueEvidence, ...]

    @property
    def detail(self) -> str:
        """The evidence as one line."""
        return "; ".join(item.text for item in self.evidence)


def _refresh_issue_observations(
    *,
    scheduler_record: SchedulerRecord | None,
    assignments: list[Assignment],
) -> list[IssueObservation]:
    """Return the latest tick's issue observations, claimed here as of now.

    Where this checkout has an assignment for an issue, whether one is open
    decides claimed here. An observation without its own time takes the tick's.
    """
    if scheduler_record is None:
        return []
    assignments_by_issue: dict[int, list[Assignment]] = {}
    for assignment in assignments:
        assignments_by_issue.setdefault(assignment.record.issue, []).append(assignment)
    return [
        _refresh_issue_observation(
            observation=observation,
            assignments=assignments_by_issue.get(observation.issue, []),
            recorded_at=scheduler_record.at,
        )
        for observation in scheduler_record.issue_observations
    ]


def _refresh_issue_observation(
    *,
    observation: IssueObservation,
    assignments: list[Assignment],
    recorded_at: datetime,
) -> IssueObservation:
    open_assignment = find_open_assignments_by_issue(assignments=assignments).get(
        observation.issue
    )
    if open_assignment is not None:
        claimed_here = ObservedFact(
            value=Truth.TRUE,
            evidence="this checkout has an open assignment for it",
        )
    elif assignments:
        claimed_here = ObservedFact(
            value=Truth.FALSE,
            evidence="this checkout has no open assignment for it",
        )
    else:
        claimed_here = observation.claimed_here
    refreshed = observation.model_copy(update={"claimed_here": claimed_here})
    if refreshed.observed_at is None:
        return refreshed.model_copy(update={"observed_at": recorded_at})
    return refreshed


def derive_issue_statuses(
    *, scheduler_record: SchedulerRecord | None, assignments: list[Assignment]
) -> list[IssueStatus]:
    """Return the status of each issue the latest tick observed that a report shows.

    The report shows an issue whose setup failed, or that has a routing
    conflict, is blocked or is available, in the scheduler's order.
    """
    statuses = (
        _derive_issue_status(observation=observation)
        for observation in _refresh_issue_observations(
            scheduler_record=scheduler_record, assignments=assignments
        )
    )
    return [status for status in statuses if status is not None]


def _derive_issue_status(*, observation: IssueObservation) -> IssueStatus | None:
    """Return the status of one observed issue, or None when the report omits it.

    A setup failure or routing conflict comes with any blocked evidence, which
    names the blocking issues.
    """
    evidence = []
    if observation.routing_conflict.value is Truth.TRUE:
        evidence.append(IssueEvidence(text=observation.routing_conflict.evidence))
    if observation.blocked.value is Truth.TRUE:
        evidence.append(
            IssueEvidence(text=observation.blocked.evidence, names_issues=True)
        )
    if observation.setup_failure is not None:
        value = IssueStatusValue.FAILED_SETUP
        evidence.insert(0, IssueEvidence(text=observation.setup_failure))
    elif observation.routing_conflict.value is Truth.TRUE:
        value = IssueStatusValue.ROUTING_CONFLICT
    elif observation.blocked.value is Truth.TRUE:
        value = IssueStatusValue.BLOCKED
    elif observation.availability.value is Truth.TRUE:
        value = IssueStatusValue.AVAILABLE
        evidence.append(IssueEvidence(text=observation.availability.evidence))
    else:
        return None
    return IssueStatus(observation=observation, value=value, evidence=tuple(evidence))
