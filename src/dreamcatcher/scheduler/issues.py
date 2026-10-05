"""Observe issue facts that determine assignment availability."""

from dataclasses import dataclass

from dreamcatcher.agent_assignments import (
    Assignment,
    find_open_assignments_by_issue,
)
from dreamcatcher.github import (
    Issue,
    IssueState,
    UnknownGitHubResponse,
    list_blocking_issues,
    read_issue,
    read_issue_pull_request_context,
)
from dreamcatcher.scheduler.agent_work import AgentWorkScheduler
from dreamcatcher.scheduler.models import (
    IssueObservation,
    ObservedFact,
    ObservedIssueDetails,
    Truth,
)


@dataclass(frozen=True, kw_only=True)
class _ListedIssueFacts:
    details: ObservedIssueDetails | None
    is_open: ObservedFact
    is_assigned_to_user: ObservedFact
    routing_conflict: ObservedFact


@dataclass(frozen=True, kw_only=True)
class IssueObservationResult:
    """Group issue observations with any failed listings behind them."""

    observations: list[IssueObservation]
    failures: list[str]


def observe_issues(
    *,
    scheduler: AgentWorkScheduler,
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
                observation.details is None,
                None if observation.details is None else observation.details.created_at,
                observation.issue,
            ),
        ),
        failures=listing.failures,
    )


def _observe_issue(
    *,
    scheduler: AgentWorkScheduler,
    assignments: dict[int, Assignment],
    incomplete_setups: dict[int, str | None],
    issue: int,
    issue_response: Issue | UnknownGitHubResponse,
) -> IssueObservation:
    """Observe the independent scheduling facts for one issue."""
    listed = _observe_listed_issue(scheduler=scheduler, response=issue_response)
    is_claimed_here = issue in assignments
    claimed_here = ObservedFact(
        value=Truth.TRUE if is_claimed_here else Truth.FALSE,
        evidence=(
            "an assignment in this checkout is working on it"
            if is_claimed_here
            else "no assignment in this checkout is working on it"
        ),
    )
    return IssueObservation(
        issue=issue,
        details=listed.details,
        is_open=listed.is_open,
        is_assigned_to_user=listed.is_assigned_to_user,
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
    *, scheduler: AgentWorkScheduler, response: Issue | UnknownGitHubResponse
) -> _ListedIssueFacts:
    if isinstance(response, UnknownGitHubResponse):
        reason = f"cannot read issue: {response.reason}"
        unknown = ObservedFact(value=Truth.UNKNOWN, evidence=reason)
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
        details=ObservedIssueDetails(
            title=response.title,
            created_at=response.created_at,
            assignment_labels=assignment_labels,
        ),
        is_open=ObservedFact(
            value=Truth.TRUE if is_open else Truth.FALSE,
            evidence="issue is open" if is_open else "issue is closed",
        ),
        is_assigned_to_user=ObservedFact(
            value=Truth.TRUE if is_assigned else Truth.FALSE,
            evidence=(
                f"is assigned to {scheduler.account}"
                if is_assigned
                else f"is not assigned to {scheduler.account}"
            ),
        ),
        routing_conflict=_observe_assignment_routing_conflict(labels=assignment_labels),
    )


def _observe_assignment_routing_conflict(*, labels: list[str]) -> ObservedFact:
    if len(labels) <= 1:
        return ObservedFact(
            value=Truth.FALSE,
            evidence="has no routing conflict",
        )
    return ObservedFact(
        value=Truth.TRUE,
        evidence="multiple assignment labels: " + ", ".join(labels),
    )


def _observe_external_claim(
    *,
    scheduler: AgentWorkScheduler,
    assignments: dict[int, Assignment],
    incomplete_setups: dict[int, str | None],
    issue: int,
) -> ObservedFact:
    """Observe whether an open linked pull request claims the issue elsewhere."""
    setup_failure = incomplete_setups.get(issue)
    if issue in incomplete_setups and setup_failure is None:
        return ObservedFact(
            value=Truth.FALSE,
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
        return ObservedFact(
            value=Truth.TRUE,
            evidence=f"a pull request is open on it: {external_pull_requests}",
        )
    if setup_failure is not None:
        return ObservedFact(
            value=Truth.UNKNOWN,
            evidence=setup_failure,
        )
    return ObservedFact(
        value=Truth.FALSE,
        evidence="no pull request outside this checkout claims it",
    )


def _unknown_external_claim(
    *, setup_failure: str | None, response: UnknownGitHubResponse
) -> ObservedFact:
    evidence = setup_failure or (
        "cannot tell whether a pull request claims it: " + response.reason
    )
    return ObservedFact(value=Truth.UNKNOWN, evidence=evidence)


def _observe_blocking_issues(*, repository: str, issue: int) -> ObservedFact:
    """Observe whether an open issue dependency blocks the issue."""
    blocking = list_blocking_issues(repository=repository, issue=issue)
    if isinstance(blocking, UnknownGitHubResponse):
        return ObservedFact(
            value=Truth.UNKNOWN,
            evidence=f"cannot tell what blocks it: {blocking.reason}",
        )
    open_blockers = [
        blocker.number for blocker in blocking if blocker.state is IssueState.OPEN
    ]
    blocker_names = ", ".join(f"GH{number}" for number in open_blockers)
    return (
        ObservedFact(
            value=Truth.TRUE,
            evidence=f"blocked by {blocker_names}",
        )
        if open_blockers
        else ObservedFact(
            value=Truth.FALSE,
            evidence="no open issue blocks it",
        )
    )
