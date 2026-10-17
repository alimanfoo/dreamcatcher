"""Find the assignment requests that no open assignment answers yet."""

from dataclasses import dataclass

from dreamcatcher.agent_work import AgentWork, find_open_agent_work_by_issue
from dreamcatcher.github import (
    Issue,
    IssueState,
    UnknownGitHubResponse,
    list_blocking_issues,
    read_issue_pull_request_context,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.agent_work import AgentWorkScheduler
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    ReadFailure,
    RequestRow,
    StartTimeFinding,
)


@dataclass(frozen=True, kw_only=True)
class AssignmentRequestListing:
    """Group the rows of assignment requests with no open work and failed listings."""

    rows: list[RequestRow]
    failures: list[str]


def list_assignment_requests(
    *,
    scheduler: AgentWorkScheduler,
    assignments: list[AgentWork],
) -> AssignmentRequestListing:
    """Return a row for each assignment label on each listed issue with no open work.

    The rows keep the listing's order, which is the order in which new
    assignments start. An issue with an open assignment appears through that
    assignment's row, so its labels make no row of their own.
    """
    listing = scheduler.list_route_issues(routes=scheduler.config.assignment)
    open_issues = find_open_agent_work_by_issue(work=assignments).keys()
    return AssignmentRequestListing(
        rows=[
            row
            for issue in listing.issues
            if issue.number not in open_issues
            for row in _compose_request_rows(scheduler=scheduler, issue=issue)
        ],
        failures=listing.failures,
    )


def _compose_request_rows(
    *, scheduler: AgentWorkScheduler, issue: Issue
) -> list[RequestRow]:
    """Return a row for each assignment label on an issue with no open assignment."""
    labels = [
        route.label
        for route in scheduler.config.identify_assignment_routes(
            labels=[label.name for label in issue.labels]
        )
    ]
    finding = _find_what_decides_the_start(
        scheduler=scheduler, issue=issue.number, labels=labels
    )
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


def _find_what_decides_the_start(
    *, scheduler: AgentWorkScheduler, issue: int, labels: list[str]
) -> ConflictingLabelsFinding | ReadFailure | StartTimeFinding:
    """Return what decides whether an assignment may start for these labels.

    Two assignment labels start nothing, so the start-time questions are asked
    only of an issue with one.
    """
    if len(labels) > 1:
        return ConflictingLabelsFinding(labels=labels)
    pull_request_context = read_issue_pull_request_context(
        repository=scheduler.repository, issue=issue
    )
    if isinstance(pull_request_context, UnknownGitHubResponse):
        return ReadFailure(reason=pull_request_context.reason)
    blocking = list_blocking_issues(repository=scheduler.repository, issue=issue)
    if isinstance(blocking, UnknownGitHubResponse):
        return ReadFailure(reason=blocking.reason)
    return StartTimeFinding(
        linked_pull_requests=[
            pull_request.number for pull_request in pull_request_context.pull_requests
        ],
        blocking_issues=[
            blocker.number for blocker in blocking if blocker.state is IssueState.OPEN
        ],
    )
