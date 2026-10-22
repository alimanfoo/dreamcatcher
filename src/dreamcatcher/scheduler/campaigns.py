"""Inspect campaigns' parents and children and compose the rounds they call for.

The tick inspects campaigns after the assignments, so a campaign observes its
children through what this update already found of their assignments, and reads
none of their pull requests again.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import partial

from dreamcatcher.agent_assignments import (
    ObservedPullRequest,
    read_assignment_pull_request_number,
)
from dreamcatcher.agent_work import AgentWork
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignChildAssignment,
    CampaignChildNotification,
    CampaignRoundInput,
    compare_campaign_children,
    prepare_campaign_round,
    read_delivered_campaign_input,
)
from dreamcatcher.config import DispatchRoute
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    Issue,
    IssueComment,
    SubIssue,
    UnknownGitHubResponse,
    list_sub_issues,
)
from dreamcatcher.prompts import compose_campaign_input_prompt
from dreamcatcher.scheduler.faults import is_last_round_unfinished
from dreamcatcher.scheduler.inspection import (
    Candidate,
    Inspection,
    RoundPlan,
    SchedulingContext,
)
from dreamcatcher.scheduler.issue_work import inspect_open_issue_work, list_new_comments
from dreamcatcher.scheduler.models import (
    CampaignFinding,
    PullRequestFinding,
    ReadFailureFinding,
    RequestFinding,
    RequestRow,
)


@dataclass(frozen=True, kw_only=True)
class AssignmentObservations:
    """Hold what an update found of the assignments, for its campaigns to observe.

    The assignments are the newest at each issue, ended ones included. The
    inspections are the update's inspections of the open assignments and of
    the assignment requests with no open assignment, by issue. A listing
    failure says why some assignment request may have gone uninspected.
    """

    assignments: Mapping[int, AgentWork]
    inspections: Mapping[int, Inspection]
    listing_failure: str | None


def inspect_open_campaign(
    *,
    context: SchedulingContext,
    observations: AssignmentObservations,
    work: AgentWork,
    is_fault: bool,
) -> Inspection:
    """Observe an open campaign's children, then inspect its parent issue.

    The children are observed whether or not the campaign may take a round, so
    the row shows them while the lead is paused or in fault. The parent's
    comments are read unless the campaign may not run.
    """
    children = _observe_children(
        context=context, parent=work.record.issue, observations=observations
    )
    inspection = inspect_open_issue_work(
        context=context,
        work=work,
        is_fault=is_fault,
        inspect_eligible=partial(
            _inspect_lead_input, context=context, work_or_route=work, children=children
        ),
    )
    return _record_children(inspection=inspection, children=children)


def inspect_campaign_request(
    *,
    context: SchedulingContext,
    observations: AssignmentObservations,
    issue: Issue,
    route: DispatchRoute,
    row: RequestRow,
) -> Inspection:
    """Observe the children and read the comments at a request with no open campaign.

    The label on the listed parent is the whole request, so a campaign starts
    whether or not a comment waits. Its first input holds those that do.
    """
    children = _observe_children(
        context=context, parent=issue.number, observations=observations
    )
    inspection = _inspect_lead_input(
        context=context, issue=issue, work_or_route=route, children=children, row=row
    )
    return _record_children(inspection=inspection, children=children)


def _observe_children(
    *, context: SchedulingContext, parent: int, observations: AssignmentObservations
) -> list[CampaignChild] | ReadFailureFinding:
    """Return the parent's children as this update found them, in GitHub's order.

    A child that the update could not observe leaves the picture incomplete,
    so the answer is why, rather than a picture with the child missing. The
    daemon observes work in its own repository alone, so a child in another
    repository is one it cannot observe.
    """
    sub_issues = list_sub_issues(repository=context.repository, issue=parent)
    if isinstance(sub_issues, UnknownGitHubResponse):
        return ReadFailureFinding(reason=sub_issues.reason)
    children: list[CampaignChild] = []
    for sub_issue in sub_issues:
        if sub_issue.repository.casefold() != context.repository.casefold():
            return ReadFailureFinding(
                reason=f"could not observe child {sub_issue.repository}"
                f"#{sub_issue.number}: it is in another repository"
            )
        child = _observe_child(sub_issue=sub_issue, observations=observations)
        if isinstance(child, ReadFailureFinding):
            return child
        children.append(child)
    return children


def _observe_child(
    *, sub_issue: SubIssue, observations: AssignmentObservations
) -> CampaignChild | ReadFailureFinding:
    """Return one child as this update found it, or why the update cannot tell.

    The child's newest assignment and this update's assignment inspection at
    its issue say whether it has a round running or due. A failed listing
    leaves a child with no open assignment unknown, since its request may be
    the one that went uninspected.
    """
    assignment = observations.assignments.get(sub_issue.number)
    inspection = observations.inspections.get(sub_issue.number)
    finding = None if inspection is None else inspection.row.finding
    if isinstance(finding, ReadFailureFinding):
        return ReadFailureFinding(
            reason=f"could not observe child GH{sub_issue.number}: {finding.reason}"
        )
    if observations.listing_failure is not None and not (
        assignment is not None and assignment.is_open
    ):
        return ReadFailureFinding(
            reason=f"could not observe child GH{sub_issue.number}: "
            f"{observations.listing_failure}"
        )
    return CampaignChild(
        issue=sub_issue.number,
        title=sub_issue.title,
        state=sub_issue.state,
        is_settled=not (
            (assignment is not None and assignment.is_round_running)
            or (inspection is not None and inspection.candidate is not None)
        ),
        assignment=(
            None
            if assignment is None
            else _observe_child_assignment(
                assignment=assignment,
                finding=finding,
                is_fault=inspection is not None and inspection.is_counted_fault,
            )
        ),
    )


def _observe_child_assignment(
    *, assignment: AgentWork, finding: RequestFinding | None, is_fault: bool
) -> CampaignChildAssignment:
    """Return where the child's newest assignment stands, given what the update found.

    Only an open assignment's own inspection holds a pull request finding.
    """
    return CampaignChildAssignment(
        identifier=assignment.identifier,
        pull_request=read_assignment_pull_request_number(assignment=assignment),
        observed_pull_request=(
            ObservedPullRequest.model_validate(
                finding.model_dump(include=set(ObservedPullRequest.model_fields))
            )
            if isinstance(finding, PullRequestFinding)
            else None
        ),
        finished_turn=next(
            (
                record.number
                for record in reversed(assignment.rounds)
                if record.ending is not None and not record.is_unfinished
            ),
            None,
        ),
        ending=None if assignment.ending is None else assignment.ending.reason,
        is_fault=is_fault,
    )


def _record_children(
    *, inspection: Inspection, children: list[CampaignChild] | ReadFailureFinding
) -> Inspection:
    """Return the inspection with its row holding the children, when they are known."""
    if isinstance(children, ReadFailureFinding):
        return inspection
    return replace(
        inspection, row=inspection.row.model_copy(update={"children": children})
    )


def _inspect_lead_input(
    *,
    context: SchedulingContext,
    issue: Issue,
    work_or_route: AgentWork | DispatchRoute,
    children: list[CampaignChild] | ReadFailureFinding,
    row: RequestRow,
) -> Inspection:
    """Read the parent's comments and return a candidate when a lead round is due.

    It reads for the open campaign, or for the route of the one that would
    start, and the row is the request's row before the read. Children that the
    update could not observe start no round and leave the comments unread, so
    the lead is never given an incomplete picture. A round is due to start the
    campaign, for new comments, for changes among the children since the
    newest input delivered to the lead, and to give the lead its input again
    after a round that did not finish. Each update compares afresh, so changes
    wait for capacity in the comparison itself. A stopped round took its turn,
    so the lead waits for new input after it.
    """
    if isinstance(children, ReadFailureFinding):
        return Inspection(row=row.model_copy(update={"finding": children}))
    campaign = work_or_route if isinstance(work_or_route, AgentWork) else None
    try:
        previous = (
            None
            if campaign is None
            else read_delivered_campaign_input(campaign=campaign)
        )
    except ReportableError as failure:
        return Inspection(
            row=row.model_copy(
                update={"finding": ReadFailureFinding(reason=str(failure))}
            )
        )
    comments = list_new_comments(
        context=context,
        issue=issue.number,
        cursor=None if previous is None else previous.cursor,
    )
    if isinstance(comments, ReadFailureFinding):
        return Inspection(row=row.model_copy(update={"finding": comments}))
    notifications = (
        []
        if previous is None
        else compare_campaign_children(previous=previous.children, current=children)
    )
    row = row.model_copy(
        update={
            "finding": CampaignFinding(
                new_comments=len(comments), changed_children=len(notifications)
            )
        }
    )
    if not (
        comments
        or notifications
        or campaign is None
        or not campaign.rounds
        or is_last_round_unfinished(rounds=campaign.rounds, is_daemon_running=True)
    ):
        return Inspection(row=row)
    return Inspection(
        row=row,
        candidate=Candidate(
            work_or_route=work_or_route,
            compose_round=partial(
                _compose_campaign_round,
                context=context,
                children=children,
                notifications=notifications,
                comments=comments,
                previous=previous,
            ),
        ),
    )


def _compose_campaign_round(
    *,
    context: SchedulingContext,
    children: list[CampaignChild],
    notifications: list[CampaignChildNotification],
    comments: list[IssueComment],
    previous: CampaignRoundInput | None,
    work: AgentWork,
) -> RoundPlan:
    """Return the plan of a round that gives the lead its input.

    The input offers the lead the assignment routes of this daemon, which may
    differ from the configuration on main. The lead publishes its own
    messages, so the round has no finishing step.
    """
    return RoundPlan(
        prepare_round=partial(
            prepare_campaign_round,
            state=context.state,
            campaign=work,
            children=children,
            notifications=notifications,
            comments=comments,
            previous=previous,
            assignment_routes=context.config.assignment,
        ),
        input_prompt=compose_campaign_input_prompt(
            issue=work.record.issue,
            round_input=work.compose_round_paths(
                number=work.next_round_number
            ).round_input,
        ),
        finish_round=None,
    )
