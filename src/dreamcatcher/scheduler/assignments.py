"""Inspect assignments' pull requests and compose the rounds they call for."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from functools import cache, partial

from dreamcatcher.agent_work import AgentWork, AgentWorkEndReason, DispatchRequest
from dreamcatcher.github import (
    Issue,
    PullRequest,
    PullRequestSignal,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    read_issue,
    read_issue_parent,
    read_pull_request,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.prompts import compose_assignment_input_prompt
from dreamcatcher.pull_request_work import (
    complete_pull_request_work,
    compose_work_branch,
    open_work_pull_request,
    prepare_assignment_round_input,
    read_work_pull_request_number,
)
from dreamcatcher.scheduler.faults import is_last_round_unfinished
from dreamcatcher.scheduler.inspection import (
    Candidate,
    Inspection,
    RequestInspector,
    RoundPlan,
    SchedulingContext,
    compose_open_work_row,
)
from dreamcatcher.scheduler.models import (
    CampaignPullRequestUnavailableFinding,
    IssueReference,
    ReadFailureFinding,
    RequestRow,
    StartTimeFinding,
)
from dreamcatcher.scheduler.pull_requests import (
    ask_start_time_questions,
    read_pull_request_activity,
)


def inspect_open_assignment(
    *, context: SchedulingContext, work: AgentWork, is_in_fault: bool
) -> Inspection:
    """Inspect an open assignment, reading its pull request once it has one.

    An assignment in fault reads nothing. One whose pull request no round has
    opened yet calls for the round that opens it.
    """
    unread = compose_open_work_row(work=work, finding=None)
    if is_in_fault:
        return Inspection(row=unread, is_counted_fault=True)
    pull_request = read_work_pull_request_number(work=work)
    if pull_request is None:
        return Inspection(
            row=unread,
            candidate=Candidate(
                work_or_request=work,
                compose_round=partial(_compose_opening_round, context=context),
            ),
        )
    return _inspect_pull_request(context=context, work=work, pull_request=pull_request)


def _inspect_pull_request(
    *, context: SchedulingContext, work: AgentWork, pull_request: int
) -> Inspection:
    activity = read_pull_request_activity(
        context=context, work=work, pull_request=pull_request
    )
    if isinstance(activity, ReadFailureFinding):
        return Inspection(row=compose_open_work_row(work=work, finding=activity))
    row = compose_open_work_row(work=work, finding=activity.finding)
    if not activity.is_round_due(work=work):
        return Inspection(row=row)
    return Inspection(
        row=row,
        candidate=Candidate(
            work_or_request=work,
            compose_round=partial(
                _compose_relay_round,
                context=context,
                pull_request=activity.pull_request,
                posts=activity.posts,
                pull_request_signals=activity.finding.new_pull_request_signals,
            ),
        ),
    )


def create_assignment_request_inspector(
    *, context: SchedulingContext, all_work: Sequence[AgentWork]
) -> RequestInspector:
    """Inspect new assignments using the campaign history and reads of one tick."""
    campaigns = {
        work.record.issue: work
        for work in sorted(
            (work for work in all_work if work.record.kind is AgentWorkKind.CAMPAIGN),
            key=lambda work: (
                work.record.label_applied_at or datetime.min.replace(tzinfo=UTC),
                work.identifier,
            ),
        )
    }
    find_campaign_base = cache(
        partial(_find_campaign_base, context=context, campaigns=campaigns)
    )

    def inspect_assignment_request(
        *,
        issue: Issue,
        request: DispatchRequest,
        row: RequestRow,
    ) -> Inspection:
        answers = ask_start_time_questions(context=context, issue=issue.number)
        if not (isinstance(answers, StartTimeFinding) and answers.is_clear):
            return Inspection(row=row.model_copy(update={"finding": answers}))

        parent = read_issue_parent(repository=context.repository, issue=issue.number)
        if isinstance(parent, UnknownGitHubResponse):
            base = ReadFailureFinding(reason=parent.reason)
        elif parent is not None and parent.is_in_repository(
            repository=context.repository
        ):
            base = find_campaign_base(parent=parent.number)
        else:
            base = None
        if isinstance(
            base, (CampaignPullRequestUnavailableFinding, ReadFailureFinding)
        ):
            return Inspection(row=row.model_copy(update={"finding": base}))
        return Inspection(
            row=row.model_copy(update={"finding": answers}),
            candidate=Candidate(
                work_or_request=replace(request, base_branch=base),
                compose_round=partial(_compose_opening_round, context=context),
            ),
        )

    return inspect_assignment_request


def _find_campaign_base(
    *,
    context: SchedulingContext,
    campaigns: dict[int, AgentWork],
    parent: int,
) -> str | CampaignPullRequestUnavailableFinding | ReadFailureFinding | None:
    campaign = campaigns.get(parent)
    if campaign is None:
        if not context.config.campaign:
            return None
        issue = read_issue(repository=context.repository, issue=parent)
        if isinstance(issue, UnknownGitHubResponse):
            return ReadFailureFinding(reason=issue.reason)
        if not context.config.identify_routes(
            kind=AgentWorkKind.CAMPAIGN, labels=[label.name for label in issue.labels]
        ):
            return None
    elif (
        campaign.ending is None
        or campaign.ending.reason is AgentWorkEndReason.CANCELLED
    ) and ((number := read_work_pull_request_number(work=campaign)) is not None):
        pull_request = read_pull_request(
            repository=context.repository, pull_request=number
        )
        if isinstance(pull_request, UnknownGitHubResponse):
            return ReadFailureFinding(reason=pull_request.reason)
        if pull_request.state is PullRequestState.OPEN:
            return compose_work_branch(identifier=campaign.identifier)
    return CampaignPullRequestUnavailableFinding(parent=IssueReference(number=parent))


def _compose_opening_round(*, context: SchedulingContext, work: AgentWork) -> RoundPlan:
    """Return the plan of a round whose preparation opens the pull request.

    The round has no input, so its prompt is the agent's instructions alone.
    """
    return RoundPlan(
        prepare_round=partial(
            open_work_pull_request,
            state=context.state,
            repository=context.repository,
            assignment=work,
        ),
        input_prompt=None,
        finish_round=None,
    )


def _compose_relay_round(
    *,
    context: SchedulingContext,
    pull_request: PullRequest,
    posts: Sequence[UserPost],
    pull_request_signals: Sequence[PullRequestSignal],
    work: AgentWork,
) -> RoundPlan:
    """Return the plan of a round given the pull request, its signals and posts.

    A round given a merged or closed pull request is the wrap-up round, and it
    records that the assignment completed as it finishes.
    """
    return RoundPlan(
        prepare_round=partial(
            prepare_assignment_round_input,
            repository=context.repository,
            assignment=work,
            pull_request=pull_request,
            signals=pull_request_signals,
            posts=posts,
        ),
        input_prompt=compose_assignment_input_prompt(
            pull_request=pull_request.number,
            round_input=work.compose_round_paths(
                number=work.next_round_number
            ).round_input,
            pull_request_signals=pull_request_signals,
            is_previous_round_unfinished=is_last_round_unfinished(
                rounds=work.rounds, is_daemon_running=True
            ),
        ),
        finish_round=(
            None
            if pull_request.state is PullRequestState.OPEN
            else partial(
                complete_pull_request_work, assignment=work, clock=context.clock
            )
        ),
    )
