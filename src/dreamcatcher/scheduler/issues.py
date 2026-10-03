"""Observe issue facts that determine assignment availability."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from dreamcatcher.agent_assignments import (
    Assignment,
    find_open_assignments_by_issue,
    record_assignment_title,
)
from dreamcatcher.github import (
    Issue,
    IssueState,
    UnknownGitHubResponse,
    list_blocking_issues,
    read_issue,
    read_issue_pull_request_context,
)
from dreamcatcher.scheduler.models import IssueFact, IssueFactValue, IssueObservation

if TYPE_CHECKING:
    from dreamcatcher.scheduler.assignments import AssignmentScheduler


@dataclass(frozen=True, kw_only=True)
class _ListedIssueDetails:
    title: str
    created_at: datetime
    assignment_labels: list[str]


@dataclass(frozen=True, kw_only=True)
class _ListedIssueFacts:
    details: _ListedIssueDetails | None
    is_open: IssueFact
    is_assigned_to_user: IssueFact
    routing_conflict: IssueFact


@dataclass(frozen=True, kw_only=True)
class IssueObservationResult:
    """Group issue observations with any failed listing behind them."""

    observations: list[IssueObservation]
    failure: str | None = None


def observe_issues(
    *,
    scheduler: "AssignmentScheduler",
    assignments: list[Assignment],
    incomplete_setups: dict[int, str | None],
) -> IssueObservationResult:
    """Observe every issue considered for assignment or claimed by this instance."""
    listing = scheduler.list_route_issues(routes=scheduler.config.assignment)
    open_assignments = find_open_assignments_by_issue(assignments=assignments)
    issue_responses_by_number: dict[int, Issue | UnknownGitHubResponse] = {
        issue.number: issue for issue in listing.issues
    }
    local_issue_numbers = open_assignments.keys() | incomplete_setups.keys()
    for issue in local_issue_numbers - issue_responses_by_number.keys():
        issue_responses_by_number[issue] = read_issue(
            repository=scheduler.repository, issue=issue
        )
    issue_observations = [
        _observe_issue(
            scheduler=scheduler,
            assignments=open_assignments,
            incomplete_setups=incomplete_setups,
            issue=issue,
            issue_response=issue_response,
        )
        for issue, issue_response in issue_responses_by_number.items()
    ]
    return IssueObservationResult(
        observations=sorted(
            issue_observations,
            key=lambda observation: (
                observation.created_at is None,
                observation.created_at,
                observation.issue,
            ),
        ),
        failure=listing.failure,
    )


def record_missing_assignment_titles(
    *, assignments: list[Assignment], observations: list[IssueObservation]
) -> None:
    """Record titles first learned after legacy assignments were created."""
    open_assignments = find_open_assignments_by_issue(assignments=assignments)
    for observation in observations:
        assignment = open_assignments.get(observation.issue)
        if assignment is not None and observation.title is not None:
            record_assignment_title(
                assignment=assignment,
                title=observation.title,
            )


def _observe_issue(
    *,
    scheduler: "AssignmentScheduler",
    assignments: dict[int, Assignment],
    incomplete_setups: dict[int, str | None],
    issue: int,
    issue_response: Issue | UnknownGitHubResponse,
) -> IssueObservation:
    """Observe the independent scheduling facts for one issue."""
    listed = _observe_listed_issue(scheduler=scheduler, response=issue_response)
    is_claimed_here = issue in assignments
    claimed_here = IssueFact(
        value=IssueFactValue.TRUE if is_claimed_here else IssueFactValue.FALSE,
        evidence=(
            "an assignment in this checkout is working on it"
            if is_claimed_here
            else "no assignment in this checkout is working on it"
        ),
    )
    return IssueObservation(
        issue=issue,
        title=None if listed.details is None else listed.details.title,
        created_at=None if listed.details is None else listed.details.created_at,
        is_open=listed.is_open,
        is_assigned_to_user=listed.is_assigned_to_user,
        assignment_labels=(
            None if listed.details is None else listed.details.assignment_labels
        ),
        claimed_here=claimed_here,
        claimed_elsewhere=_observe_external_claim(
            scheduler=scheduler,
            assignments=assignments,
            incomplete_setups=incomplete_setups,
            issue=issue,
        ),
        setup_failure=incomplete_setups.get(issue),
        blocked=_observe_blocking_issues(
            repository=scheduler.repository,
            issue=issue,
        ),
        routing_conflict=listed.routing_conflict,
    )


def _observe_listed_issue(
    *, scheduler: "AssignmentScheduler", response: Issue | UnknownGitHubResponse
) -> _ListedIssueFacts:
    if isinstance(response, UnknownGitHubResponse):
        reason = f"cannot read issue: {response.reason}"
        unknown = IssueFact(value=IssueFactValue.UNKNOWN, evidence=reason)
        return _ListedIssueFacts(
            details=None,
            is_open=unknown,
            is_assigned_to_user=unknown,
            routing_conflict=unknown,
        )
    is_open = response.state is IssueState.OPEN
    is_assigned = scheduler.account.casefold() in {
        assignee.login.casefold() for assignee in response.assignees
    }
    assignment_labels = scheduler.config.identify_assignment_labels(
        labels=[label.name for label in response.labels]
    )
    return _ListedIssueFacts(
        details=_ListedIssueDetails(
            title=response.title,
            created_at=response.created_at,
            assignment_labels=assignment_labels,
        ),
        is_open=IssueFact(
            value=IssueFactValue.TRUE if is_open else IssueFactValue.FALSE,
            evidence="issue is open" if is_open else "issue is closed",
        ),
        is_assigned_to_user=IssueFact(
            value=IssueFactValue.TRUE if is_assigned else IssueFactValue.FALSE,
            evidence=(
                f"is assigned to {scheduler.account}"
                if is_assigned
                else f"is not assigned to {scheduler.account}"
            ),
        ),
        routing_conflict=_observe_assignment_routing_conflict(labels=assignment_labels),
    )


def _observe_assignment_routing_conflict(*, labels: list[str]) -> IssueFact:
    if len(labels) <= 1:
        return IssueFact(
            value=IssueFactValue.FALSE,
            evidence="has no routing conflict",
        )
    return IssueFact(
        value=IssueFactValue.TRUE,
        evidence="carries more than one assignment label: " + ", ".join(labels),
    )


def _observe_external_claim(
    *,
    scheduler: "AssignmentScheduler",
    assignments: dict[int, Assignment],
    incomplete_setups: dict[int, str | None],
    issue: int,
) -> IssueFact:
    """Observe whether an open linked pull request claims the issue elsewhere."""
    setup_failure = incomplete_setups.get(issue)
    if issue in incomplete_setups and setup_failure is None:
        return IssueFact(
            value=IssueFactValue.FALSE,
            evidence="no pull request outside this checkout claims it",
        )
    pull_request_context = read_issue_pull_request_context(
        repository=scheduler.repository, issue=issue
    )
    if isinstance(pull_request_context, UnknownGitHubResponse):
        return _unknown_external_claim(
            setup_failure=setup_failure,
            response=pull_request_context,
        )
    assignment = assignments.get(issue)
    owned = None if assignment is None else assignment.record.pull_request
    external = [
        pull_request
        for pull_request in pull_request_context.pull_requests
        if pull_request.number != owned
    ]
    external_pull_requests = ", ".join(
        f"#{pull_request.number}" for pull_request in external
    )
    if external:
        return IssueFact(
            value=IssueFactValue.TRUE,
            evidence=f"a pull request is open on it: {external_pull_requests}",
        )
    if setup_failure is not None:
        return IssueFact(
            value=IssueFactValue.UNKNOWN,
            evidence=setup_failure,
        )
    return IssueFact(
        value=IssueFactValue.FALSE,
        evidence="no pull request outside this checkout claims it",
    )


def _unknown_external_claim(
    *, setup_failure: str | None, response: UnknownGitHubResponse
) -> IssueFact:
    evidence = setup_failure or (
        "cannot tell whether a pull request claims it: " + response.reason
    )
    return IssueFact(value=IssueFactValue.UNKNOWN, evidence=evidence)


def _observe_blocking_issues(*, repository: str, issue: int) -> IssueFact:
    """Observe whether an open issue dependency blocks the issue."""
    blocking = list_blocking_issues(repository=repository, issue=issue)
    if isinstance(blocking, UnknownGitHubResponse):
        return IssueFact(
            value=IssueFactValue.UNKNOWN,
            evidence=f"cannot tell what blocks it: {blocking.reason}",
        )
    open_blockers = [
        blocker.number for blocker in blocking if blocker.state is IssueState.OPEN
    ]
    blocker_names = ", ".join(f"GH{number}" for number in open_blockers)
    return (
        IssueFact(
            value=IssueFactValue.TRUE,
            evidence=f"blocked by {blocker_names}",
        )
        if open_blockers
        else IssueFact(
            value=IssueFactValue.FALSE,
            evidence="no open issue blocks it",
        )
    )
