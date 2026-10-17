"""Inspect assignments and prepare the rounds that they require."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import cast

from dreamcatcher.agent_assignments import (
    AssignmentCreator,
    AssignmentRoundInput,
    complete_assignment,
    inspect_incomplete_assignment_setups,
    is_final_turn_taken,
    read_pull_request_observation,
    read_user_post_delivery_position,
    record_pull_request_observation,
)
from dreamcatcher.agent_rounds import AgentRound
from dreamcatcher.agent_work import (
    AgentWork,
    find_open_agent_work_by_issue,
    read_agent_work_of_kind,
)
from dreamcatcher.config import AssignmentRoute
from dreamcatcher.github import (
    PullRequest,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    read_pull_request,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.prompts import compose_assignment_input_prompt
from dreamcatcher.relay import list_undelivered_user_posts
from dreamcatcher.scheduler.agent_work import AgentWorkScheduler
from dreamcatcher.scheduler.faults import (
    derive_agent_work_fault,
    is_last_round_unfinished,
)
from dreamcatcher.scheduler.issues import observe_issues
from dreamcatcher.scheduler.models import (
    NO_ROUND_HAS_RUN,
    AgentWorkInspection,
    AgentWorkObservation,
    IssueObservation,
    ObservedFact,
    ObservedIssueDetails,
    SchedulerRecord,
    Truth,
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

    assignment: AgentWork


@dataclass(frozen=True, kw_only=True)
class AssignmentRoundCandidate:
    """Describe an existing assignment ready for another round."""

    assignment: AgentWork
    pull_request: PullRequest
    undelivered_posts: list[UserPost]


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
        assignments = read_agent_work_of_kind(
            state=self.state, kind=AgentWorkKind.ASSIGNMENT
        )
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
        if not issue_result.failures:
            candidates.extend(self._compose_new_candidates(issue_observations))
        return AssignmentInspection(
            candidates=sorted(candidates, key=self.rank),
            observations=[item.observation for item in inspected],
            fault_count=sum(item.is_fault for item in inspected),
            failures=issue_result.failures,
            issue_observations=issue_observations,
        )

    def rank(self, candidate: AssignmentCandidate, /) -> int:
        """Rank an assignment candidate when `sorted` passes it by position."""
        if isinstance(candidate, FirstAssignmentRoundCandidate):
            return 0
        return 1 if isinstance(candidate, NewAssignmentCandidate) else 0

    def launch(self, *, candidate: AssignmentCandidate, at: datetime) -> AgentRound:
        """Create any new assignment, then start its required round."""
        if isinstance(candidate, NewAssignmentCandidate):
            creator = AssignmentCreator(state=self.state, repository=self.repository)
            assignment = creator.create(
                route=candidate.route,
                preferred_harness=self.preferred_harness,
                issue=candidate.issue,
                at=at,
            )
            candidate = FirstAssignmentRoundCandidate(assignment=assignment)
        if isinstance(candidate, FirstAssignmentRoundCandidate):
            return self._start_round(
                assignment=candidate.assignment, round_input=None, input_prompt=None
            )
        assignment = candidate.assignment
        return self._start_round(
            assignment=assignment,
            round_input=AssignmentRoundInput(
                pull_request_state=candidate.pull_request.state,
                user_posts=candidate.undelivered_posts,
            ),
            input_prompt=compose_assignment_input_prompt(
                pull_request=candidate.pull_request.number,
                round_input=assignment.compose_round_paths(
                    number=assignment.next_round_number
                ).round_input,
            ),
        )

    def _inspect_assignments(
        self,
        *,
        assignments: list[AgentWork],
        most_recent_cooldown_ended: datetime | None,
        observed_at: datetime,
    ) -> list[_AssignmentItemInspection]:
        inspected: list[_AssignmentItemInspection] = []
        for assignment in find_open_agent_work_by_issue(work=assignments).values():
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
        assignment: AgentWork,
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
            retry_requested_at=assignment.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        ):
            return _AssignmentItemInspection(
                candidate=None,
                observation=_compose_assignment_observation(
                    assignment=assignment,
                    evidence="in fault",
                    value=Truth.FALSE,
                ),
                is_fault=True,
            )
        return self._inspect_pull_request(
            assignment=assignment,
            observed_at=observed_at,
        )

    def _inspect_pull_request(
        self, *, assignment: AgentWork, observed_at: datetime
    ) -> _AssignmentItemInspection:
        """Inspect an assignment's pull request and pending user posts."""
        pull_request = read_pull_request(
            repository=self.repository,
            pull_request=read_pull_request_observation(assignment=assignment).number,
        )
        if isinstance(pull_request, UnknownGitHubResponse):
            return _AssignmentItemInspection(
                candidate=None,
                observation=_compose_assignment_observation(
                    assignment=assignment,
                    evidence=f"cannot read its pull request: {pull_request.reason}",
                    value=Truth.UNKNOWN,
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
                    value=Truth.FALSE,
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
        self, *, assignment: AgentWork, pull_request: PullRequest
    ) -> AssignmentRoundCandidate | AgentWorkObservation | None:
        """Return the round the assignment needs, if any.

        A round is needed for user posts past the cursor, for a merged or closed
        pull request whose final turn has not been taken, or to give again the
        input of a round that did not finish.
        """
        undelivered_posts = list_undelivered_user_posts(
            repository=self.repository,
            pull_request=pull_request.number,
            account=self.account,
            delivery_position=read_user_post_delivery_position(assignment=assignment),
        )
        if isinstance(undelivered_posts, UnknownGitHubResponse):
            return _compose_assignment_observation(
                assignment=assignment,
                evidence=(
                    f"cannot tell what the user posted: {undelivered_posts.reason}"
                ),
                value=Truth.UNKNOWN,
            )
        if not (
            undelivered_posts
            or (
                pull_request.state is not PullRequestState.OPEN
                and not is_final_turn_taken(assignment=assignment)
            )
            or is_last_round_unfinished(
                rounds=assignment.rounds, is_daemon_running=True
            )
        ):
            return None
        return AssignmentRoundCandidate(
            assignment=assignment,
            pull_request=pull_request,
            undelivered_posts=undelivered_posts,
        )

    def _compose_new_candidates(
        self, observations: list[IssueObservation], /
    ) -> list[NewAssignmentCandidate]:
        return [
            NewAssignmentCandidate(
                issue=observation.issue,
                title=cast("ObservedIssueDetails", observation.details).title,
                route=self.config.identify_assignment_routes(
                    labels=cast(
                        "ObservedIssueDetails", observation.details
                    ).assignment_labels
                )[0],
            )
            for observation in observations
            if observation.availability.value is Truth.TRUE
        ]

    def _start_round(
        self,
        *,
        assignment: AgentWork,
        round_input: AssignmentRoundInput | None,
        input_prompt: str | None,
    ) -> AgentRound:
        return self.start_round(
            work=assignment,
            harness_session_identifier=assignment.find_harness_session_identifier(),
            prepare_round=lambda: round_input,
            input_prompt=input_prompt,
            finish_round=(
                None
                if round_input is None
                or round_input.pull_request_state is PullRequestState.OPEN
                else partial(
                    complete_assignment, assignment=assignment, clock=self.clock
                )
            ),
        )


def _describe_assignment_candidate(*, candidate: AssignmentRoundCandidate) -> str:
    if candidate.pull_request.state is not PullRequestState.OPEN:
        return f"the pull request is {candidate.pull_request.state.lower()}"
    if candidate.undelivered_posts:
        posts = describe_count(number=len(candidate.undelivered_posts), noun="new post")
        return f"{posts} to answer"
    latest_round = candidate.assignment.rounds[-1]
    return f"round {latest_round.number} {latest_round.outcome}, to try again"


def _compose_assignment_observation(
    *,
    assignment: AgentWork,
    evidence: str,
    value: Truth = Truth.TRUE,
) -> AgentWorkObservation:
    return AgentWorkObservation(
        identifier=assignment.identifier,
        issue=assignment.record.issue,
        requires_round=ObservedFact(value=value, evidence=evidence),
    )
