"""Inspect assignments and prepare the rounds that they require."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import cast

from dreamcatcher.agent_assignments import (
    Assignment,
    AssignmentCreator,
    AssignmentRoundInput,
    find_assignment_harness_session_identifier,
    find_open_assignments_by_issue,
    inspect_incomplete_assignment_setups,
    read_assignments,
    record_assignment_harness_session_identifier,
    record_pull_request_observation,
)
from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundOutcome,
    AgentRoundPlan,
    AgentRoundStartRequest,
    AssignmentRoundPurpose,
    start_agent_round,
)
from dreamcatcher.config import AssignmentRoute
from dreamcatcher.github import (
    PullRequest,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    read_pull_request,
)
from dreamcatcher.harness_adapters import AgentRoundLaunchRequest
from dreamcatcher.prompts import RECOVERY_PROMPT, compose_user_posts_prompt
from dreamcatcher.relay import list_undelivered_user_posts
from dreamcatcher.scheduler.agent_work import AgentWorkScheduler
from dreamcatcher.scheduler.faults import derive_agent_work_fault
from dreamcatcher.scheduler.issues import (
    observe_issues,
    record_missing_assignment_titles,
)
from dreamcatcher.scheduler.models import (
    NO_ROUND_HAS_RUN,
    AgentWorkInspection,
    AgentWorkObservation,
    IssueFact,
    IssueFactValue,
    IssueObservation,
    ObservedIssueDetails,
    SchedulerRecord,
    derive_round_purpose,
)
from dreamcatcher.words import describe_count


@dataclass(frozen=True, kw_only=True)
class NewAssignmentCandidate:
    """Describe an available issue ready for a new assignment."""

    issue: int
    title: str
    route: AssignmentRoute


@dataclass(frozen=True, kw_only=True)
class FirstAssignmentRoundCandidate:
    """Describe an assignment that has not started its first round."""

    assignment: Assignment


@dataclass(frozen=True, kw_only=True)
class AssignmentRoundCandidate:
    """Describe an existing assignment ready for another round."""

    assignment: Assignment
    pull_request: PullRequest
    undelivered_posts: list[UserPost]
    recovery_reason: str | None


type AssignmentCandidate = (
    NewAssignmentCandidate | FirstAssignmentRoundCandidate | AssignmentRoundCandidate
)


@dataclass(frozen=True, kw_only=True)
class AssignmentInspection(
    AgentWorkInspection[AssignmentCandidate, AgentWorkObservation]
):
    """Collect assignment inspection facts and issue observations."""

    issue_observations: list[IssueObservation]


@dataclass(frozen=True, kw_only=True)
class _AssignmentItemInspection:
    candidate: AssignmentCandidate | None
    observation: AgentWorkObservation
    is_fault: bool = False


class AssignmentScheduler(
    AgentWorkScheduler[
        AssignmentCandidate,
        AgentWorkObservation,
        int,
    ]
):
    """Inspect, rank and launch assignment work."""

    def inspect(
        self, *, previous_record: SchedulerRecord | None, at: datetime
    ) -> AssignmentInspection:
        """Inspect all assignment work and return one ranked bundle."""
        assignments = read_assignments(state=self.state)
        issue_result = observe_issues(
            scheduler=self,
            assignments=assignments,
            incomplete_setups=inspect_incomplete_assignment_setups(
                state=self.state,
                repository=self.repository,
            ),
        )
        issue_observations = [
            observation.model_copy(update={"observed_at": at})
            for observation in issue_result.observations
        ]
        record_missing_assignment_titles(
            assignments=assignments,
            observations=issue_observations,
        )
        inspected = self._inspect_assignments(
            assignments=assignments,
            most_recent_cooldown_ended=(
                None
                if previous_record is None
                else previous_record.most_recent_cooldown_ended
            ),
            observed_at=at,
        )
        candidates = [
            item.candidate for item in inspected if item.candidate is not None
        ]
        if issue_result.failure is None:
            candidates.extend(self._compose_new_candidates(issue_observations))
        else:
            candidates = []
        return AssignmentInspection(
            candidates=sorted(candidates, key=self.rank),
            observations=[item.observation for item in inspected],
            fault_count=sum(item.is_fault for item in inspected),
            failure=issue_result.failure,
            issue_observations=issue_observations,
        )

    def rank(self, candidate: AssignmentCandidate, /) -> int:
        """Rank an assignment candidate when `sorted` passes it by position."""
        if isinstance(candidate, FirstAssignmentRoundCandidate):
            return 0
        if isinstance(candidate, NewAssignmentCandidate):
            return 4
        if candidate.recovery_reason is not None:
            return 1
        if derive_round_purpose(pull_request=candidate.pull_request) is (
            AssignmentRoundPurpose.WRAP_UP
        ):
            return 2
        return 3

    def launch(self, *, candidate: AssignmentCandidate, at: datetime) -> AgentRound:
        """Create any new assignment, then start its required round."""
        if isinstance(candidate, NewAssignmentCandidate):
            creator = AssignmentCreator(state=self.state, repository=self.repository)
            assignment = creator.create(
                route=candidate.route,
                requested_harness=self.requested_harness,
                issue=candidate.issue,
                at=at,
            )
            candidate = FirstAssignmentRoundCandidate(assignment=assignment)
        if isinstance(candidate, FirstAssignmentRoundCandidate):
            return self._start_round(
                assignment=candidate.assignment,
                plan=AgentRoundPlan(
                    purpose=AssignmentRoundPurpose.IMPLEMENT,
                    is_recovery=False,
                ),
                next_round_prompt=candidate.assignment.record.prompt,
            )
        purpose = derive_round_purpose(pull_request=candidate.pull_request)
        if (
            candidate.recovery_reason is not None
            and candidate.pull_request.state is PullRequestState.OPEN
        ):
            return self._start_round(
                assignment=candidate.assignment,
                plan=AgentRoundPlan(purpose=purpose, is_recovery=True),
                next_round_prompt=RECOVERY_PROMPT,
            )
        assignment = candidate.assignment
        was_stopped = assignment.rounds[-1].outcome is AgentRoundOutcome.STOPPED
        return self._start_round(
            assignment=assignment,
            plan=AgentRoundPlan(
                purpose=purpose,
                is_recovery=candidate.recovery_reason is not None,
                input=AssignmentRoundInput(
                    pull_request_state=candidate.pull_request.state,
                    user_posts=candidate.undelivered_posts,
                ),
            ),
            next_round_prompt=compose_user_posts_prompt(
                pull_request=candidate.pull_request.number,
                round_input=assignment.compose_round_paths(
                    number=assignment.next_round_number
                ).round_input,
                was_stopped=was_stopped,
            ),
        )

    def _inspect_assignments(
        self,
        *,
        assignments: list[Assignment],
        most_recent_cooldown_ended: datetime | None,
        observed_at: datetime,
    ) -> list[_AssignmentItemInspection]:
        inspected: list[_AssignmentItemInspection] = []
        for assignment in find_open_assignments_by_issue(
            assignments=assignments
        ).values():
            if assignment.rounds and assignment.rounds[-1].ending is None:
                continue
            inspected.append(
                self._inspect_assignment(
                    assignment=assignment,
                    most_recent_cooldown_ended=most_recent_cooldown_ended,
                    observed_at=observed_at,
                )
            )
        return inspected

    def _inspect_assignment(
        self,
        *,
        assignment: Assignment,
        most_recent_cooldown_ended: datetime | None,
        observed_at: datetime,
    ) -> _AssignmentItemInspection:
        if not assignment.rounds:
            candidate = FirstAssignmentRoundCandidate(assignment=assignment)
            return _AssignmentItemInspection(
                candidate=candidate,
                observation=_compose_assignment_observation(
                    assignment=assignment, evidence=NO_ROUND_HAS_RUN
                ),
            )
        if derive_agent_work_fault(
            rounds=assignment.rounds,
            retry_requested_at=assignment.record.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        ):
            return _AssignmentItemInspection(
                candidate=None,
                observation=_compose_assignment_observation(
                    assignment=assignment,
                    evidence="in fault",
                    value=IssueFactValue.FALSE,
                ),
                is_fault=True,
            )
        return self._inspect_pull_request(
            assignment=assignment,
            observed_at=observed_at,
        )

    def _inspect_pull_request(
        self, *, assignment: Assignment, observed_at: datetime
    ) -> _AssignmentItemInspection:
        """Inspect an assignment's pull request and pending user posts."""
        pull_request = read_pull_request(
            repository=self.repository,
            pull_request=assignment.record.pull_request,
        )
        if isinstance(pull_request, UnknownGitHubResponse):
            return _AssignmentItemInspection(
                candidate=None,
                observation=_compose_assignment_observation(
                    assignment=assignment,
                    evidence=f"cannot read its pull request: {pull_request.reason}",
                    value=IssueFactValue.UNKNOWN,
                ),
            )
        record_pull_request_observation(
            assignment=assignment,
            pull_request=pull_request,
            observed_at=observed_at,
        )
        candidate_or_observation = self._inspect_pending_round(
            assignment=assignment,
            pull_request=pull_request,
        )
        if isinstance(candidate_or_observation, AgentWorkObservation):
            return _AssignmentItemInspection(
                candidate=None, observation=candidate_or_observation
            )
        if candidate_or_observation is None:
            return _AssignmentItemInspection(
                candidate=None,
                observation=_compose_assignment_observation(
                    assignment=assignment,
                    evidence="no round required",
                    value=IssueFactValue.FALSE,
                ),
            )
        return _AssignmentItemInspection(
            candidate=candidate_or_observation,
            observation=_compose_assignment_observation(
                assignment=assignment,
                evidence=_describe_assignment_candidate(
                    candidate=candidate_or_observation
                ),
            ),
        )

    def _inspect_pending_round(
        self, *, assignment: Assignment, pull_request: PullRequest
    ) -> AssignmentRoundCandidate | AgentWorkObservation | None:
        recovery_reason = assignment.describe_unfinished_round()
        if recovery_reason is not None and pull_request.state is PullRequestState.OPEN:
            return AssignmentRoundCandidate(
                assignment=assignment,
                pull_request=pull_request,
                undelivered_posts=[],
                recovery_reason=recovery_reason,
            )
        undelivered_posts = list_undelivered_user_posts(
            repository=self.repository,
            pull_request=pull_request.number,
            account=self.account,
            delivery_cursor=assignment.user_post_delivery_cursor,
        )
        if isinstance(undelivered_posts, UnknownGitHubResponse):
            return _compose_assignment_observation(
                assignment=assignment,
                evidence=(
                    f"cannot tell what the user posted: {undelivered_posts.reason}"
                ),
                value=IssueFactValue.UNKNOWN,
            )
        if not undelivered_posts and pull_request.state is PullRequestState.OPEN:
            return None
        return AssignmentRoundCandidate(
            assignment=assignment,
            pull_request=pull_request,
            undelivered_posts=undelivered_posts,
            recovery_reason=recovery_reason,
        )

    def _compose_new_candidates(
        self, observations: list[IssueObservation], /
    ) -> list[NewAssignmentCandidate]:
        return [
            NewAssignmentCandidate(
                issue=observation.issue,
                title=cast("ObservedIssueDetails", observation.details).title,
                route=self.config.assignment_routes[
                    cast("ObservedIssueDetails", observation.details).assignment_labels[
                        0
                    ]
                ],
            )
            for observation in observations
            if observation.availability.value is IssueFactValue.TRUE
        ]

    def _start_round(
        self,
        *,
        assignment: Assignment,
        plan: AgentRoundPlan[AssignmentRoundInput],
        next_round_prompt: str,
    ) -> AgentRound:
        resumption = self.resolve_harness_session(
            agent_work_identifier=assignment.identifier,
            has_rounds=bool(assignment.rounds),
            harness_session_identifier=find_assignment_harness_session_identifier(
                assignment=assignment
            ),
            is_recovery=plan.is_recovery,
            prompt=next_round_prompt,
            replacement_session_prompt=(
                f"{assignment.record.prompt}\n\n{next_round_prompt}"
            ),
        )
        if resumption.identifier is not None:
            record_assignment_harness_session_identifier(
                assignment=assignment,
                identifier=resumption.identifier,
            )
        return start_agent_round(
            request=AgentRoundStartRequest(
                harness=assignment.record.harness,
                launch_request=AgentRoundLaunchRequest(
                    agent_work_identifier=assignment.identifier,
                    model=assignment.record.model,
                    effort=assignment.record.effort,
                    prompt=resumption.prompt,
                ),
                harness_session_identifier=resumption.identifier,
                record_harness_session_identifier=partial(
                    record_assignment_harness_session_identifier,
                    assignment=assignment,
                ),
                finish_round=None,
                paths=assignment.compose_round_paths(
                    number=assignment.next_round_number
                ),
                plan=plan,
            ),
            clock=self.clock,
        )


def _describe_assignment_candidate(*, candidate: AssignmentRoundCandidate) -> str:
    if candidate.recovery_reason is not None:
        latest_round = candidate.assignment.rounds[-1]
        return f"round {latest_round.number} {latest_round.outcome}, to recover"
    if candidate.pull_request.state is not PullRequestState.OPEN:
        return f"the pull request is {candidate.pull_request.state.lower()}"
    return (
        f"{describe_count(number=len(candidate.undelivered_posts), noun='new post')} "
        "to answer"
    )


def _compose_assignment_observation(
    *,
    assignment: Assignment,
    evidence: str,
    value: IssueFactValue = IssueFactValue.TRUE,
) -> AgentWorkObservation:
    return AgentWorkObservation(
        identifier=assignment.identifier,
        issue=assignment.record.issue,
        requires_round=IssueFact(value=value, evidence=evidence),
    )
