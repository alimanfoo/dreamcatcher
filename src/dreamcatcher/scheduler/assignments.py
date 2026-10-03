"""Inspect assignments and derive the rounds that they require."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial

from dreamcatcher.agent_assignments import (
    Assignment,
    AssignmentCreator,
    AssignmentRoundInput,
    advance_user_post_delivery_cursor,
    find_harness_session_identifier,
    record_harness_session_identifier,
    record_pull_request_observation,
)
from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundOutcome,
    AgentRoundPlan,
    AgentRoundStartRequest,
    AssignmentRoundPurpose,
    HarnessSessionIdentifierRecorder,
    start_agent_round,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    PullRequest,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    read_pull_request,
)
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    HarnessSessionIdentifier,
)
from dreamcatcher.prompts import RECOVERY_PROMPT, compose_user_posts_prompt
from dreamcatcher.relay import list_undelivered_user_posts
from dreamcatcher.scheduler.agent_work import (
    AgentWorkScheduler,
    LaunchedAgentRoundError,
)
from dreamcatcher.scheduler.faults import derive_agent_work_fault
from dreamcatcher.scheduler.models import (
    NO_ROUND_HAS_RUN,
    AssignmentObservation,
    IssueObservation,
    derive_round_purpose,
)
from dreamcatcher.words import describe_count


@dataclass(frozen=True, kw_only=True)
class RequiredAgentRound:
    """Describe the next round that an assignment requires."""

    assignment: Assignment
    plan: AgentRoundPlan[AssignmentRoundInput]
    reason: str
    prompt: str


@dataclass(frozen=True, kw_only=True)
class FaultedAssignment:
    """Describe an assignment whose errors stop ordinary recovery."""

    assignment: Assignment
    reason: str


type AssignmentInspectionResult = (
    RequiredAgentRound | FaultedAssignment | AssignmentObservation
)


@dataclass(frozen=True, kw_only=True)
class AssignmentInspectionRequest:
    """Hold the current inputs for inspecting one assignment."""

    assignment: Assignment
    most_recent_cooldown_ended: datetime | None
    observed_at: datetime


@dataclass(frozen=True, kw_only=True)
class AssignmentLaunchRequest:
    """Hold the current inputs for launching assignment work."""

    candidate: RequiredAgentRound | IssueObservation
    at: datetime


class AssignmentScheduler(
    AgentWorkScheduler[
        RequiredAgentRound,
        int,
        AssignmentInspectionRequest,
        AssignmentLaunchRequest,
    ]
):
    """Inspect, rank and launch assignment work."""

    def inspect(
        self, *, request: AssignmentInspectionRequest
    ) -> AssignmentInspectionResult | None:
        """Return what one assignment needs after reading external facts."""
        assignment = request.assignment
        if not assignment.rounds:
            return compose_initial_round_requirement(assignment=assignment)
        if assignment.is_complete:
            return None
        if derive_agent_work_fault(
            rounds=assignment.rounds,
            retry_requested_at=assignment.record.retry_requested_at,
            most_recent_cooldown_ended=request.most_recent_cooldown_ended,
        ):
            return FaultedAssignment(
                assignment=assignment,
                reason="two consecutive rounds failed",
            )
        return self._inspect_pull_request(
            assignment=assignment,
            observed_at=request.observed_at,
        )

    def rank(self, candidate: RequiredAgentRound, /) -> int:
        """Rank a required round when `sorted` passes it by position."""
        if not candidate.assignment.rounds:
            return 0
        if candidate.plan.is_recovery:
            return 1
        if candidate.plan.purpose is AssignmentRoundPurpose.WRAP_UP:
            return 2
        return 3

    def launch(self, *, request: AssignmentLaunchRequest) -> AgentRound:
        """Create any new assignment, then start its required round."""
        candidate = request.candidate
        if isinstance(candidate, IssueObservation):
            labels = candidate.assignment_labels or []
            creator = AssignmentCreator(
                state=self.state,
                repository=self.repository,
            )
            assignment = creator.create(
                route=self.config.assignment_routes[labels[0]],
                requested_harness=self.requested_harness,
                issue=candidate.issue,
                at=request.at,
            )
            candidate = compose_initial_round_requirement(assignment=assignment)
        assignment = candidate.assignment
        harness_session_identifier, prompt, is_fresh_recovery = (
            _prepare_assignment_resume(required=candidate)
        )
        if harness_session_identifier is not None:
            record_harness_session_identifier(
                assignment=assignment, identifier=harness_session_identifier
            )
        round_input = candidate.plan.input
        newest_user_post = (
            round_input.user_posts[-1].written_at
            if round_input is not None and round_input.user_posts
            else None
        )
        record_session_identifier = partial(
            record_harness_session_identifier, assignment=assignment
        )
        if is_fresh_recovery and newest_user_post is not None:
            record_session_identifier = partial(
                _record_session_before_advancing_user_post_cursor,
                assignment=assignment,
                newest_user_post=newest_user_post,
            )
        round_ = self._start_round(
            required=candidate,
            prompt=prompt,
            harness_session_identifier=harness_session_identifier,
            record_session_identifier=record_session_identifier,
        )
        if newest_user_post is not None and not is_fresh_recovery:
            try:
                advance_user_post_delivery_cursor(
                    assignment=assignment,
                    newest=newest_user_post,
                )
            except ReportableError as failure:
                raise LaunchedAgentRoundError(
                    agent_round=round_, failure=failure
                ) from failure
        return round_

    def _inspect_pull_request(
        self,
        *,
        assignment: Assignment,
        observed_at: datetime,
    ) -> AssignmentInspectionResult | None:
        """Return what an assignment needs from its pull request and posts."""
        pull_request = read_pull_request(
            repository=self.repository,
            pull_request=assignment.record.pull_request,
        )
        if isinstance(pull_request, UnknownGitHubResponse):
            return compose_assignment_observation(
                assignment=assignment,
                reason=f"cannot read its pull request: {pull_request.reason}",
                is_known=False,
            )
        record_pull_request_observation(
            assignment=assignment,
            pull_request=pull_request,
            observed_at=observed_at,
        )
        recovery_reason = assignment.describe_unfinished_round()
        if recovery_reason is not None and pull_request.state is PullRequestState.OPEN:
            return _compose_recovery_round_requirement(
                assignment=assignment,
                pull_request=pull_request,
                reason=recovery_reason,
            )
        undelivered_posts = list_undelivered_user_posts(
            repository=self.repository,
            pull_request=pull_request.number,
            account=self.account,
            delivery_cursor=assignment.user_post_delivery_cursor,
        )
        if isinstance(undelivered_posts, UnknownGitHubResponse):
            return compose_assignment_observation(
                assignment=assignment,
                reason=f"cannot tell what the user posted: {undelivered_posts.reason}",
                is_known=False,
            )
        if not undelivered_posts and pull_request.state is PullRequestState.OPEN:
            return None
        return _compose_resumed_round_requirement(
            assignment=assignment,
            pull_request=pull_request,
            undelivered_posts=undelivered_posts,
            recovery_reason=recovery_reason,
        )

    def _start_round(
        self,
        *,
        required: RequiredAgentRound,
        prompt: str,
        harness_session_identifier: HarnessSessionIdentifier | None,
        record_session_identifier: HarnessSessionIdentifierRecorder,
    ) -> AgentRound:
        assignment = required.assignment
        return start_agent_round(
            request=AgentRoundStartRequest(
                harness=assignment.record.harness,
                launch_request=AgentRoundLaunchRequest(
                    agent_work_identifier=assignment.identifier,
                    model=assignment.record.model,
                    effort=assignment.record.effort,
                    prompt=prompt,
                ),
                harness_session_identifier=harness_session_identifier,
                record_harness_session_identifier=record_session_identifier,
                finish_round=None,
                paths=assignment.compose_round_paths(
                    number=assignment.next_round_number
                ),
                plan=required.plan,
            ),
            clock=self.clock,
        )


def list_assignment_observations(
    *,
    inspection_results: list[AssignmentInspectionResult],
    required_reason: str | None = None,
) -> list[AssignmentObservation]:
    """Return an agent assignment observation for every inspection result.

    When `required_reason` is given, it replaces the reason of each required
    round. Existing observation and fault reasons remain unchanged.
    """
    return [
        result
        if isinstance(result, AssignmentObservation)
        else compose_assignment_observation(
            assignment=result.assignment,
            reason=(
                required_reason
                if required_reason is not None
                and isinstance(result, RequiredAgentRound)
                else result.reason
            ),
        )
        for result in inspection_results
    ]


def _compose_recovery_round_requirement(
    *, assignment: Assignment, pull_request: PullRequest, reason: str
) -> RequiredAgentRound:
    return RequiredAgentRound(
        assignment=assignment,
        plan=AgentRoundPlan(
            purpose=derive_round_purpose(pull_request=pull_request),
            is_recovery=True,
        ),
        reason=reason,
        prompt=RECOVERY_PROMPT,
    )


def compose_initial_round_requirement(*, assignment: Assignment) -> RequiredAgentRound:
    """Return the first round that a recorded assignment requires."""
    return RequiredAgentRound(
        assignment=assignment,
        plan=AgentRoundPlan(
            purpose=AssignmentRoundPurpose.IMPLEMENT, is_recovery=False
        ),
        reason=NO_ROUND_HAS_RUN,
        prompt=assignment.record.prompt,
    )


def _compose_resumed_round_requirement(
    *,
    assignment: Assignment,
    pull_request: PullRequest,
    undelivered_posts: list[UserPost],
    recovery_reason: str | None,
) -> RequiredAgentRound:
    """Return the round that a pull request and its user posts require."""
    is_open = pull_request.state is PullRequestState.OPEN
    return RequiredAgentRound(
        assignment=assignment,
        plan=AgentRoundPlan(
            purpose=derive_round_purpose(pull_request=pull_request),
            is_recovery=recovery_reason is not None,
            input=AssignmentRoundInput(
                pull_request_state=pull_request.state, user_posts=undelivered_posts
            ),
        ),
        reason=(
            recovery_reason
            or (
                f"{describe_count(number=len(undelivered_posts), noun='new post')} "
                "to answer"
                if is_open
                else f"the pull request is {pull_request.state.lower()}"
            )
        ),
        prompt=compose_user_posts_prompt(
            pull_request=pull_request.number,
            round_input=assignment.compose_round_paths(
                number=assignment.next_round_number
            ).round_input,
            was_stopped=(assignment.rounds[-1].outcome is AgentRoundOutcome.STOPPED),
        ),
    )


def _record_session_before_advancing_user_post_cursor(
    *, assignment: Assignment, newest_user_post: str, identifier: str
) -> None:
    """Record a replacement session before acknowledging its delivered posts."""
    record_harness_session_identifier(assignment=assignment, identifier=identifier)
    advance_user_post_delivery_cursor(assignment=assignment, newest=newest_user_post)


def compose_assignment_observation(
    *,
    assignment: Assignment,
    reason: str,
    is_known: bool = True,
    is_round_required: bool = True,
) -> AssignmentObservation:
    """Return what the scheduler found for one idle assignment."""
    return AssignmentObservation(
        assignment_identifier=assignment.identifier,
        issue=assignment.record.issue,
        reason=reason,
        is_known=is_known,
        is_round_required=is_round_required,
    )


def _prepare_assignment_resume(
    *, required: RequiredAgentRound
) -> tuple[HarnessSessionIdentifier | None, str, bool]:
    assignment = required.assignment
    if not assignment.rounds:
        return None, required.prompt, False
    identifier = find_harness_session_identifier(assignment=assignment)
    if identifier is not None:
        return identifier, required.prompt, False
    if not required.plan.is_recovery:
        raise ReportableError(
            f"Could not resume {assignment.identifier}: its first round did not "
            "report a harness session identifier."
        )
    return None, f"{assignment.record.prompt}\n\n{required.prompt}", True
