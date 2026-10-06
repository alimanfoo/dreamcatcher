"""Derive the assignment issue status of each issue that assignment routes list."""

from dataclasses import dataclass
from enum import StrEnum

from dreamcatcher.agent_assignments import Assignment, find_open_assignments_by_issue
from dreamcatcher.scheduler.models import (
    IssueObservation,
    SchedulerRecord,
    Truth,
    observe_claimed_here,
)


class AssignmentIssueStatusValue(StrEnum):
    """List the reasons a status report shows an issue that assignment routes list."""

    FAILED_ASSIGNMENT_SETUP = "failed assignment setup"
    ASSIGNMENT_ROUTING_CONFLICT = "assignment routing conflict"
    BLOCKED = "blocked"
    AVAILABLE = "available"


@dataclass(frozen=True, kw_only=True)
class AssignmentIssueEvidence:
    """Give one piece of evidence for an assignment issue status.

    Evidence that names issues, such as "blocked by GH50", lets a view link
    each issue it names.
    """

    text: str
    names_issues: bool = False


@dataclass(frozen=True, kw_only=True)
class AssignmentIssueStatus:
    """Describe why a status report shows an issue that assignment routes list."""

    observation: IssueObservation
    value: AssignmentIssueStatusValue
    evidence: tuple[AssignmentIssueEvidence, ...]

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

    An observation without its own time takes the tick's.
    """
    if scheduler_record is None:
        return []
    open_assignment_issues = find_open_assignments_by_issue(
        assignments=assignments
    ).keys()
    return [
        observation.model_copy(
            update={
                "claimed_here": observe_claimed_here(
                    issue=observation.issue,
                    open_assignment_issues=open_assignment_issues,
                ),
                "observed_at": observation.observed_at or scheduler_record.at,
            }
        )
        for observation in scheduler_record.issue_observations
    ]


def derive_assignment_issue_statuses(
    *, scheduler_record: SchedulerRecord | None, assignments: list[Assignment]
) -> list[AssignmentIssueStatus]:
    """Return the status of each issue the latest tick observed that a report shows.

    The report shows an issue whose assignment setup failed, or that has an
    assignment routing conflict, is blocked or is available, in the scheduler's
    order.
    """
    statuses = (
        _derive_assignment_issue_status(observation=observation)
        for observation in _refresh_issue_observations(
            scheduler_record=scheduler_record, assignments=assignments
        )
    )
    return [status for status in statuses if status is not None]


def _derive_assignment_issue_status(
    *, observation: IssueObservation
) -> AssignmentIssueStatus | None:
    """Return the status of one observed issue, or None when the report omits it.

    The first that holds of a failed assignment setup, an assignment routing
    conflict, a blocker and availability decides the value. The evidence gives
    each of the first three that holds, or else the availability.
    """
    is_conflicted = observation.routing_conflict.value is Truth.TRUE
    is_blocked = observation.blocked.value is Truth.TRUE
    evidence = []
    if observation.setup_failure is not None:
        evidence.append(AssignmentIssueEvidence(text=observation.setup_failure))
    if is_conflicted:
        evidence.append(
            AssignmentIssueEvidence(text=observation.routing_conflict.evidence)
        )
    if is_blocked:
        evidence.append(
            AssignmentIssueEvidence(
                text=observation.blocked.evidence, names_issues=True
            )
        )
    if observation.setup_failure is not None:
        value = AssignmentIssueStatusValue.FAILED_ASSIGNMENT_SETUP
    elif is_conflicted:
        value = AssignmentIssueStatusValue.ASSIGNMENT_ROUTING_CONFLICT
    elif is_blocked:
        value = AssignmentIssueStatusValue.BLOCKED
    elif observation.availability.value is Truth.TRUE:
        value = AssignmentIssueStatusValue.AVAILABLE
        evidence.append(AssignmentIssueEvidence(text=observation.availability.evidence))
    else:
        return None
    return AssignmentIssueStatus(
        observation=observation, value=value, evidence=tuple(evidence)
    )
