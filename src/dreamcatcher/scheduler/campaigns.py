"""Inspect campaigns' parent issues and compose the rounds they call for."""

from functools import partial

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.campaigns import prepare_campaign_round, read_parent_comment_cursor
from dreamcatcher.config import DispatchRoute
from dreamcatcher.github import Issue, IssueComment
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
    ReadFailureFinding,
    RequestRow,
)


def inspect_open_campaign(
    *, context: SchedulingContext, work: AgentWork, is_fault: bool
) -> Inspection:
    """Read an open campaign's parent issue, then its comments unless it may not run."""
    return inspect_open_issue_work(
        context=context,
        work=work,
        is_fault=is_fault,
        inspect_eligible=partial(
            _inspect_lead_input, context=context, work_or_route=work
        ),
    )


def inspect_campaign_request(
    *,
    context: SchedulingContext,
    issue: Issue,
    route: DispatchRoute,
    row: RequestRow,
) -> Inspection:
    """Read the comments at a campaign request with no open campaign.

    The label on the listed parent is the whole request, so a campaign starts
    whether or not a comment waits. Its first input holds those that do.
    """
    return _inspect_lead_input(
        context=context, issue=issue, work_or_route=route, row=row
    )


def _inspect_lead_input(
    *,
    context: SchedulingContext,
    issue: Issue,
    work_or_route: AgentWork | DispatchRoute,
    row: RequestRow,
) -> Inspection:
    """Read the parent's comments and return a candidate when a lead round is due.

    It reads for the open campaign, or for the route of the one that would
    start, and the row is the request's row before the read. A round is due to
    start the campaign, for new comments, and to give the lead its input again
    after a round that did not finish. A stopped round delivered its input, so
    the lead waits for a new comment after it.
    """
    campaign = work_or_route if isinstance(work_or_route, AgentWork) else None
    comments = list_new_comments(
        context=context,
        issue=issue.number,
        read_cursor=(
            None
            if campaign is None
            else partial(read_parent_comment_cursor, campaign=campaign)
        ),
    )
    if isinstance(comments, ReadFailureFinding):
        return Inspection(row=row.model_copy(update={"finding": comments}))
    row = row.model_copy(
        update={"finding": CampaignFinding(new_comments=len(comments))}
    )
    if not (
        comments
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
                _compose_campaign_round, context=context, comments=comments
            ),
        ),
    )


def _compose_campaign_round(
    *, context: SchedulingContext, comments: list[IssueComment], work: AgentWork
) -> RoundPlan:
    """Return the plan of a round that gives the lead its input.

    The lead publishes its own messages, so the round has no finishing step.
    """
    return RoundPlan(
        prepare_round=partial(
            prepare_campaign_round,
            state=context.state,
            campaign=work,
            comments=comments,
        ),
        input_prompt=compose_campaign_input_prompt(
            issue=work.record.issue,
            round_input=work.compose_round_paths(
                number=work.next_round_number
            ).round_input,
        ),
        finish_round=None,
    )
