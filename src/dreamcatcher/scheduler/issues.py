"""Observe issue facts that determine assignment availability."""

from dataclasses import dataclass

from dreamcatcher.agent_assignments import (
    read_pull_request_observation,
)
from dreamcatcher.agent_work import AgentWork, find_open_agent_work_by_issue
from dreamcatcher.github import (
    Issue,
    IssueState,
    UnknownGitHubResponse,
    list_blocking_issues,
    read_issue,
    read_issue_pull_request_context,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.agent_work import AgentWorkScheduler
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueObservation,
    ObservedFact,
    ObservedIssueDetails,
    ReadFailure,
    RequestRow,
    StartTimeFinding,
    Truth,
    observe_claimed_here,
)


@dataclass(frozen=True, kw_only=True)
class _ListedIssueFacts:
    details: ObservedIssueDetails | None
    is_open: ObservedFact
    is_assigned_to_user: ObservedFact
    routing_conflict: ObservedFact


@dataclass(frozen=True, kw_only=True)
class _StartTimeAnswers:
    """Hold the answers to the start-time questions, or why one could not be read."""

    linked_pull_requests: list[int] | UnknownGitHubResponse
    blocking_issues: list[int] | UnknownGitHubResponse


@dataclass(frozen=True, kw_only=True)
class IssueObservationResult:
    """Group issue observations and request rows with any failed listings."""

    observations: list[IssueObservation]
    rows: list[RequestRow]
    failures: list[str]


def observe_issues(
    *,
    scheduler: AgentWorkScheduler,
    assignments: list[AgentWork],
) -> IssueObservationResult:
    """Observe every issue considered for assignment or claimed by this instance.

    Each assignment label on a listed issue with no open assignment is a request
    with a row of its own, in listing order.
    """
    listing = scheduler.list_route_issues(routes=scheduler.config.assignment)
    open_assignments = find_open_agent_work_by_issue(work=assignments)
    issue_responses_by_number: dict[int, Issue | UnknownGitHubResponse] = {
        issue.number: issue for issue in listing.issues
    }
    for issue in open_assignments.keys() - issue_responses_by_number.keys():
        issue_responses_by_number[issue] = read_issue(
            repository=scheduler.repository, issue=issue
        )
    issue_observations: list[IssueObservation] = []
    rows: list[RequestRow] = []
    for issue, issue_response in issue_responses_by_number.items():
        answers = _ask_start_time_questions(
            scheduler=scheduler,
            assignment=open_assignments.get(issue),
            issue=issue,
        )
        issue_observations.append(
            _observe_issue(
                scheduler=scheduler,
                assignments=open_assignments,
                issue=issue,
                issue_response=issue_response,
                answers=answers,
            )
        )
        if isinstance(issue_response, Issue) and issue not in open_assignments:
            rows.extend(
                _compose_request_rows(
                    scheduler=scheduler, issue=issue_response, answers=answers
                )
            )
    return IssueObservationResult(
        observations=sorted(
            issue_observations,
            key=lambda observation: (
                observation.details is None,
                None if observation.details is None else observation.details.created_at,
                observation.issue,
            ),
        ),
        rows=rows,
        failures=listing.failures,
    )


def _ask_start_time_questions(
    *, scheduler: AgentWorkScheduler, assignment: AgentWork | None, issue: int
) -> _StartTimeAnswers:
    """Ask what open pull requests claim the issue and what open issues block it."""
    return _StartTimeAnswers(
        linked_pull_requests=_list_linked_pull_requests(
            scheduler=scheduler, assignment=assignment, issue=issue
        ),
        blocking_issues=_list_open_blockers(
            repository=scheduler.repository, issue=issue
        ),
    )


def _compose_request_rows(
    *, scheduler: AgentWorkScheduler, issue: Issue, answers: _StartTimeAnswers
) -> list[RequestRow]:
    """Return a row for each assignment label on an issue with no open assignment."""
    labels = [
        route.label
        for route in scheduler.config.identify_assignment_routes(
            labels=[label.name for label in issue.labels]
        )
    ]
    finding = _compose_start_finding(labels=labels, answers=answers)
    return [
        RequestRow(
            issue=issue.number,
            title=issue.title,
            dispatch_label=label,
            kind=AgentWorkKind.ASSIGNMENT,
            finding=finding,
        )
        for label in labels
    ]


def _compose_start_finding(
    *, labels: list[str], answers: _StartTimeAnswers
) -> ConflictingLabelsFinding | ReadFailure | StartTimeFinding:
    """Return what decides whether an assignment may start for these labels."""
    if len(labels) > 1:
        return ConflictingLabelsFinding(labels=labels)
    if isinstance(answers.linked_pull_requests, UnknownGitHubResponse):
        return ReadFailure(reason=answers.linked_pull_requests.reason)
    if isinstance(answers.blocking_issues, UnknownGitHubResponse):
        return ReadFailure(reason=answers.blocking_issues.reason)
    return StartTimeFinding(
        linked_pull_requests=answers.linked_pull_requests,
        blocking_issues=answers.blocking_issues,
    )


def _observe_issue(
    *,
    scheduler: AgentWorkScheduler,
    assignments: dict[int, AgentWork],
    issue: int,
    issue_response: Issue | UnknownGitHubResponse,
    answers: _StartTimeAnswers,
) -> IssueObservation:
    """Observe the independent scheduling facts for one issue."""
    listed = _observe_listed_issue(scheduler=scheduler, response=issue_response)
    return IssueObservation(
        issue=issue,
        details=listed.details,
        is_open=listed.is_open,
        is_assigned_to_user=listed.is_assigned_to_user,
        claimed_here=observe_claimed_here(
            issue=issue, open_assignment_issues=assignments.keys()
        ),
        claimed_elsewhere=_observe_external_claim(
            linked_pull_requests=answers.linked_pull_requests
        ),
        blocked=_observe_blocking_issues(blocking_issues=answers.blocking_issues),
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
    routes = scheduler.config.identify_assignment_routes(
        labels=[label.name for label in response.labels]
    )
    assignment_labels = [route.label for route in routes]
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


def _list_linked_pull_requests(
    *,
    scheduler: AgentWorkScheduler,
    assignment: AgentWork | None,
    issue: int,
) -> list[int] | UnknownGitHubResponse:
    """Return the open linked pull requests that claim the issue from elsewhere.

    The open assignment's own pull request, once a round has opened it, is no
    claim from elsewhere.
    """
    pull_request_context = read_issue_pull_request_context(
        repository=scheduler.repository, issue=issue
    )
    if isinstance(pull_request_context, UnknownGitHubResponse):
        return pull_request_context
    observation = (
        None
        if assignment is None
        else read_pull_request_observation(assignment=assignment)
    )
    owned = None if observation is None else observation.number
    return [
        pull_request.number
        for pull_request in pull_request_context.pull_requests
        if pull_request.number != owned
    ]


def _list_open_blockers(
    *, repository: str, issue: int
) -> list[int] | UnknownGitHubResponse:
    """Return the open issues whose dependency blocks the issue."""
    blocking = list_blocking_issues(repository=repository, issue=issue)
    if isinstance(blocking, UnknownGitHubResponse):
        return blocking
    return [blocker.number for blocker in blocking if blocker.state is IssueState.OPEN]


def _observe_external_claim(
    *, linked_pull_requests: list[int] | UnknownGitHubResponse
) -> ObservedFact:
    """Observe whether an open linked pull request claims the issue elsewhere."""
    if isinstance(linked_pull_requests, UnknownGitHubResponse):
        return ObservedFact(
            value=Truth.UNKNOWN,
            evidence=(
                "cannot tell whether a pull request claims it: "
                + linked_pull_requests.reason
            ),
        )
    if linked_pull_requests:
        external_pull_requests = ", ".join(
            f"#{number}" for number in linked_pull_requests
        )
        return ObservedFact(
            value=Truth.TRUE,
            evidence=f"a pull request is open on it: {external_pull_requests}",
        )
    return ObservedFact(
        value=Truth.FALSE,
        evidence="no pull request outside this checkout claims it",
    )


def _observe_blocking_issues(
    *, blocking_issues: list[int] | UnknownGitHubResponse
) -> ObservedFact:
    """Observe whether an open issue dependency blocks the issue."""
    if isinstance(blocking_issues, UnknownGitHubResponse):
        return ObservedFact(
            value=Truth.UNKNOWN,
            evidence=f"cannot tell what blocks it: {blocking_issues.reason}",
        )
    blocker_names = ", ".join(f"GH{number}" for number in blocking_issues)
    return (
        ObservedFact(
            value=Truth.TRUE,
            evidence=f"blocked by {blocker_names}",
        )
        if blocking_issues
        else ObservedFact(
            value=Truth.FALSE,
            evidence="no open issue blocks it",
        )
    )
