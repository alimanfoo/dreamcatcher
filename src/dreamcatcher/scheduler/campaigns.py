"""Inspect campaigns' parent issues and compose the rounds they call for."""

from functools import partial

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.campaigns import prepare_campaign_round, read_delivered_campaign_input
from dreamcatcher.config import DispatchRoute
from dreamcatcher.github import Issue
from dreamcatcher.prompts import compose_campaign_input_prompt
from dreamcatcher.scheduler.inspection import (
    Candidate,
    Inspection,
    RoundPlan,
    SchedulingContext,
)
from dreamcatcher.scheduler.issue_work import inspect_open_issue_work
from dreamcatcher.scheduler.models import CampaignFinding, RequestRow


def inspect_open_campaign(
    *, context: SchedulingContext, work: AgentWork, is_fault: bool
) -> Inspection:
    """Read an open campaign's parent issue, then whether the lead has input due."""
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
    """Start a campaign at a request with no open campaign.

    The label on the listed parent is the whole request, so nothing more is read.
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
    """Return a candidate while no round has delivered the lead its input.

    It inspects the open campaign, or the route of the one that would start, and
    the row is the request's row before the inspection. A round that did not
    finish delivered nothing, so its campaign is due a round again.
    """
    row = row.model_copy(update={"finding": CampaignFinding()})
    if (
        isinstance(work_or_route, AgentWork)
        and read_delivered_campaign_input(campaign=work_or_route) is not None
    ):
        return Inspection(row=row)
    return Inspection(
        row=row,
        candidate=Candidate(
            work_or_route=work_or_route,
            compose_round=partial(_compose_campaign_round, context=context),
        ),
    )


def _compose_campaign_round(
    *, context: SchedulingContext, work: AgentWork
) -> RoundPlan:
    """Return the plan of a round that gives the lead its input.

    The lead publishes its own messages, so the round has no finishing step.
    """
    return RoundPlan(
        prepare_round=partial(
            prepare_campaign_round, state=context.state, campaign=work
        ),
        input_prompt=compose_campaign_input_prompt(
            issue=work.record.issue,
            round_input=work.compose_round_paths(
                number=work.next_round_number
            ).round_input,
        ),
        finish_round=None,
    )
