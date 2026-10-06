"""Select and refresh the issue observations a status report shows."""

from datetime import datetime

from dreamcatcher.agent_assignments import Assignment, find_open_assignments_by_issue
from dreamcatcher.scheduler.models import (
    IssueObservation,
    ObservedFact,
    SchedulerRecord,
    Truth,
)


def refresh_issue_observations(
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


def select_failed_setups(
    *, observations: list[IssueObservation]
) -> list[IssueObservation]:
    """Return the observations that record a failed assignment setup."""
    return [
        observation
        for observation in observations
        if observation.setup_failure is not None
    ]


def select_issue_observations(
    *, observations: list[IssueObservation]
) -> list[IssueObservation]:
    """Return the available, routing-conflict and blocked observations.

    An observation with a failed setup is left out, since the report shows it
    among the failed setups.
    """
    return [
        observation
        for observation in observations
        if (
            observation.setup_failure is None
            and Truth.TRUE
            in (
                observation.routing_conflict.value,
                observation.availability.value,
                observation.blocked.value,
            )
        )
    ]
