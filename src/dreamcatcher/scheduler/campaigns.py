"""Inspect campaigns' pull requests and children and compose the rounds they call for.

The tick inspects campaigns after the assignments, so a campaign observes its
children through what this tick already found of their assignments, and reads
none of their pull requests again.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial

from dreamcatcher.agent_rounds import AgentRoundFinisher
from dreamcatcher.agent_work import AgentWork, DispatchRequest
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignChildAssignment,
    CampaignChildNotification,
    compare_campaign_children,
    compose_campaign_round_input,
    read_delivered_campaign_input,
)
from dreamcatcher.git import read_worktree_revision
from dreamcatcher.github import (
    Issue,
    PullRequestState,
    SubIssue,
    UnknownGitHubResponse,
    list_sub_issues,
)
from dreamcatcher.prompts import compose_campaign_input_prompt
from dreamcatcher.pull_request_work import (
    ObservedPullRequest,
    PullRequestRoundInput,
    compose_work_branch,
    open_work_pull_request,
    read_work_pull_request_number,
)
from dreamcatcher.scheduler.inspection import (
    Candidate,
    Inspection,
    PreparedRoundInput,
    SchedulingContext,
    compose_open_work_row,
)
from dreamcatcher.scheduler.models import (
    PullRequestFinding,
    ReadFailureFinding,
    RequestFinding,
    RequestRow,
    StartTimeFinding,
)
from dreamcatcher.scheduler.pull_requests import (
    PullRequestActivity,
    PullRequestReader,
    ask_start_time_questions,
    read_pull_request_activity,
)


@dataclass(frozen=True, kw_only=True)
class AssignmentObservations:
    """Hold what a tick found of the assignments, for its campaigns to observe.

    The assignments are the newest at each issue, ended ones included. The
    inspections are the tick's inspections of the open assignments and of
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
    read_campaign_pull_request: PullRequestReader,
    work: AgentWork,
    is_in_fault: bool,
) -> Inspection:
    """Inspect the lead's pull request and observe the parent's sub-issues."""
    children = _observe_children(
        context=context, parent=work.record.issue, observations=observations
    )
    row = compose_open_work_row(work=work, finding=None)
    if not isinstance(children, ReadFailureFinding):
        row = row.model_copy(update={"children": children})
    if is_in_fault:
        return Inspection(row=row, is_counted_fault=True)
    if isinstance(children, ReadFailureFinding):
        return Inspection(row=row.model_copy(update={"finding": children}))
    pull_request = read_work_pull_request_number(work=work)
    if pull_request is None:
        return _offer_lead_round(
            context=context, work_or_request=work, row=row, children=children
        )
    activity = read_pull_request_activity(
        context=context,
        work=work,
        read=read_campaign_pull_request(pull_request=pull_request),
    )
    if isinstance(activity, ReadFailureFinding):
        return Inspection(row=row.model_copy(update={"finding": activity}))
    previous = read_delivered_campaign_input(campaign=work)
    notifications = (
        []
        if previous is None
        else compare_campaign_children(previous=previous.children, current=children)
    )
    finding = activity.finding.model_copy(
        update={"changed_children": len(notifications)}
    )
    row = row.model_copy(update={"finding": finding})
    if not notifications and not activity.is_round_due(work=work):
        return Inspection(row=row)
    return _offer_lead_round(
        context=context,
        work_or_request=work,
        row=row,
        children=children,
        notifications=notifications,
        activity=activity,
    )


def inspect_campaign_request(
    *,
    context: SchedulingContext,
    observations: AssignmentObservations,
    issue: Issue,
    request: DispatchRequest,
    row: RequestRow,
) -> Inspection:
    """Offer an opening round for an available request with known children."""
    answers = ask_start_time_questions(context=context, issue=issue.number)
    row = row.model_copy(update={"finding": answers})
    if not (isinstance(answers, StartTimeFinding) and answers.is_clear):
        return Inspection(row=row)
    children = _observe_children(
        context=context, parent=issue.number, observations=observations
    )
    if isinstance(children, ReadFailureFinding):
        return Inspection(row=row.model_copy(update={"finding": children}))
    return _offer_lead_round(
        context=context,
        work_or_request=request,
        row=row.model_copy(update={"children": children}),
        children=children,
    )


def _observe_children(
    *, context: SchedulingContext, parent: int, observations: AssignmentObservations
) -> list[CampaignChild] | ReadFailureFinding:
    """Return the parent's children as this tick found them, in GitHub's order.

    A child that the tick could not observe leaves the picture incomplete,
    so the answer is why, rather than a picture with the child missing. The
    daemon observes work in its own repository alone, so a child in another
    repository is one it cannot observe.
    """
    sub_issues = list_sub_issues(repository=context.repository, issue=parent)
    if isinstance(sub_issues, UnknownGitHubResponse):
        return ReadFailureFinding(reason=sub_issues.reason)
    children: list[CampaignChild] = []
    for sub_issue in sub_issues:
        if not sub_issue.is_in_repository(repository=context.repository):
            return ReadFailureFinding(
                reason=f"could not observe sub-issue {sub_issue.repository}"
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
    """Return one child as this tick found it, or why the tick cannot tell.

    The child's newest assignment and this tick's assignment inspection at
    its issue say whether it has a round running or due. A failed listing
    leaves a child with no open assignment unknown, since its request may be
    the one that went uninspected.
    """
    assignment = observations.assignments.get(sub_issue.number)
    inspection = observations.inspections.get(sub_issue.number)
    finding = None if inspection is None else inspection.row.finding
    if isinstance(finding, ReadFailureFinding):
        return ReadFailureFinding(
            reason=f"could not observe sub-issue {sub_issue.number}: {finding.reason}"
        )
    if observations.listing_failure is not None and not (
        assignment is not None and assignment.is_open
    ):
        return ReadFailureFinding(
            reason=f"could not observe sub-issue {sub_issue.number}: "
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
                is_in_fault=inspection is not None and inspection.is_counted_fault,
            )
        ),
    )


def _observe_child_assignment(
    *, assignment: AgentWork, finding: RequestFinding | None, is_in_fault: bool
) -> CampaignChildAssignment:
    """Return where the child's newest assignment stands, given what the tick found.

    Only an open assignment's own inspection holds a pull request finding.
    """
    return CampaignChildAssignment(
        identifier=assignment.identifier,
        pull_request=read_work_pull_request_number(work=assignment),
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
        is_in_fault=is_in_fault,
    )


def _offer_lead_round(
    *,
    context: SchedulingContext,
    work_or_request: AgentWork | DispatchRequest,
    row: RequestRow,
    children: Sequence[CampaignChild],
    notifications: Sequence[CampaignChildNotification] = (),
    activity: PullRequestActivity | None = None,
) -> Inspection:
    return Inspection(
        row=row,
        candidate=Candidate(
            work_or_request=work_or_request,
            prepare_round=partial(
                _prepare_campaign_round,
                context=context,
                children=children,
                notifications=notifications,
                activity=activity,
            ),
        ),
    )


def _prepare_campaign_pull_request(
    *, context: SchedulingContext, work: AgentWork, activity: PullRequestActivity | None
) -> tuple[PullRequestRoundInput, bool, AgentRoundFinisher | None]:
    """Freeze the pull request input, readiness and any wrap-up finisher."""
    if activity is None:
        pull_request = open_work_pull_request(
            state=context.state, repository=context.repository, work=work
        )
        return (
            PullRequestRoundInput(
                pull_request=pull_request,
                pull_request_state=PullRequestState.OPEN,
                pull_request_head=read_worktree_revision(worktree=work.worktree),
                signals=[],
                user_posts=[],
            ),
            False,
            None,
        )
    return (
        activity.prepare_round(context=context, work=work),
        activity.finding.is_ready_for_review,
        activity.compose_finisher(context=context, work=work),
    )


def _prepare_campaign_round(
    *,
    context: SchedulingContext,
    children: Sequence[CampaignChild],
    notifications: Sequence[CampaignChildNotification],
    activity: PullRequestActivity | None,
    work: AgentWork,
) -> PreparedRoundInput:
    """Prepare an opening, relay or wrap-up round."""
    pull_request_input, is_ready_for_review, finish_round = (
        _prepare_campaign_pull_request(context=context, work=work, activity=activity)
    )
    return PreparedRoundInput(
        document=compose_campaign_round_input(
            pull_request_input=pull_request_input,
            children=children,
            notifications=notifications,
            assignment_routes=context.config.assignment,
        ),
        prompt=compose_campaign_input_prompt(
            issue=work.record.issue,
            round_input=work.compose_round_paths(
                number=work.next_round_number
            ).round_input,
            finishing_branch=(
                compose_work_branch(identifier=work.identifier)
                if is_ready_for_review
                else None
            ),
            pull_request_signals=pull_request_input.signals,
        ),
        finish_round=finish_round,
    )
