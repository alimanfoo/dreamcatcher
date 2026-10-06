"""Derive the status of the issues a status report shows."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dreamcatcher.agent_assignments import Assignment
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
    """Give one piece of evidence for an issue's status.

    Evidence that names issues, such as "blocked by GH50", lets a view link
    each issue it names.
    """

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

    @property
    def labels(self) -> str:
        """The issue's assignment labels as one line, empty when they are unknown."""
        details = self.observation.details
        return ", ".join([] if details is None else details.assignment_labels)


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
    if any(assignment.is_open for assignment in assignments):
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

    The first that holds of a failed setup, a routing conflict, a blocker and
    availability decides the value. The evidence gives each of the first three
    that holds, or else the availability.
    """
    is_conflicted = observation.routing_conflict.value is Truth.TRUE
    is_blocked = observation.blocked.value is Truth.TRUE
    evidence = []
    if observation.setup_failure is not None:
        evidence.append(IssueEvidence(text=observation.setup_failure))
    if is_conflicted:
        evidence.append(IssueEvidence(text=observation.routing_conflict.evidence))
    if is_blocked:
        evidence.append(
            IssueEvidence(text=observation.blocked.evidence, names_issues=True)
        )
    if observation.setup_failure is not None:
        value = IssueStatusValue.FAILED_SETUP
    elif is_conflicted:
        value = IssueStatusValue.ROUTING_CONFLICT
    elif is_blocked:
        value = IssueStatusValue.BLOCKED
    elif observation.availability.value is Truth.TRUE:
        value = IssueStatusValue.AVAILABLE
        evidence.append(IssueEvidence(text=observation.availability.evidence))
    else:
        return None
    return IssueStatus(observation=observation, value=value, evidence=tuple(evidence))
