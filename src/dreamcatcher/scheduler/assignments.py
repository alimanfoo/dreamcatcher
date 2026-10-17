"""Inspect assignments and prepare the rounds that they require."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial

from dreamcatcher.agent_assignments import (
    AssignmentRoundInput,
    PullRequestObservation,
    complete_assignment,
    create_assignment,
    is_final_turn_taken,
    open_assignment_pull_request,
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
from dreamcatcher.scheduler.agent_work import (
    AgentWorkScheduler,
    compose_agent_work_row,
)
from dreamcatcher.scheduler.faults import (
    derive_agent_work_fault,
    is_last_round_unfinished,
)
from dreamcatcher.scheduler.issues import list_assignment_requests
from dreamcatcher.scheduler.models import (
    AgentWorkInspection,
    PullRequestFinding,
    ReadFailure,
    RequestRow,
    SchedulerRecord,
    StartTimeFinding,
)


@dataclass(frozen=True, kw_only=True)
class NewAssignmentCandidate:
    """Describe an available issue ready for a new assignment."""

    issue: int
    title: str
    route: AssignmentRoute


@dataclass(frozen=True, kw_only=True)
class PullRequestOpeningCandidate:
    """Describe an assignment whose next round opens its pull request.

    A round that failed part way through opening it leaves the assignment here,
    and the next round runs the same preparation again.
    """

    assignment: AgentWork


@dataclass(frozen=True, kw_only=True)
class AssignmentRoundCandidate:
    """Describe an existing assignment ready for another round."""

    assignment: AgentWork
    pull_request: PullRequest
    undelivered_posts: list[UserPost]


type AssignmentCandidate = (
    NewAssignmentCandidate | PullRequestOpeningCandidate | AssignmentRoundCandidate
)


@dataclass(frozen=True, kw_only=True)
class _AssignmentItemInspection:
    row: RequestRow
    candidate: AssignmentCandidate | None = None
    is_fault: bool = False


class AssignmentScheduler(AgentWorkScheduler[AssignmentCandidate, int]):
    """Inspect, rank and launch assignment work."""

    def inspect(
        self, *, previous_record: SchedulerRecord | None, at: datetime
    ) -> AgentWorkInspection[AssignmentCandidate]:
        """Inspect all assignment work and return one ranked bundle.

        A failed listing starts no new assignment, but open assignments are
        still inspected, because they are found on disk.
        """
        assignments = read_agent_work_of_kind(
            state=self.state, kind=AgentWorkKind.ASSIGNMENT
        )
        requests = list_assignment_requests(scheduler=self, assignments=assignments)
        inspected = [
            self._inspect_assignment(
                assignment=assignment,
                most_recent_cooldown_ended=(
                    None
                    if previous_record is None
                    else previous_record.most_recent_cooldown_ended
                ),
                observed_at=at,
            )
            for assignment in find_open_agent_work_by_issue(work=assignments).values()
        ]
        candidates = [
            item.candidate for item in inspected if item.candidate is not None
        ]
        if not requests.failures:
            candidates.extend(self._compose_new_candidates(rows=requests.rows))
        return AgentWorkInspection(
            candidates=sorted(candidates, key=self.rank),
            rows=[*(item.row for item in inspected), *requests.rows],
            fault_count=sum(item.is_fault for item in inspected),
            failures=requests.failures,
        )

    def rank(self, candidate: AssignmentCandidate, /) -> int:
        """Rank an assignment candidate when `sorted` passes it by position."""
        return 1 if isinstance(candidate, NewAssignmentCandidate) else 0

    def launch(self, *, candidate: AssignmentCandidate, at: datetime) -> AgentRound:
        """Create any new assignment, then start its required round."""
        if isinstance(candidate, NewAssignmentCandidate):
            assignment = create_assignment(
                state=self.state,
                route=candidate.route,
                preferred_harness=self.preferred_harness,
                issue=candidate.issue,
                title=candidate.title,
                at=at,
            )
            candidate = PullRequestOpeningCandidate(assignment=assignment)
        assignment = candidate.assignment
        if isinstance(candidate, PullRequestOpeningCandidate):
            return self.start_round(
                work=assignment,
                harness_session_identifier=assignment.find_harness_session_identifier(),
                prepare_round=partial(
                    open_assignment_pull_request,
                    state=self.state,
                    repository=self.repository,
                    assignment=assignment,
                    clock=self.clock,
                ),
                input_prompt=None,
                finish_round=None,
            )
        round_input = AssignmentRoundInput(
            pull_request_state=candidate.pull_request.state,
            user_posts=candidate.undelivered_posts,
        )
        return self.start_round(
            work=assignment,
            harness_session_identifier=assignment.find_harness_session_identifier(),
            prepare_round=lambda: round_input,
            input_prompt=compose_assignment_input_prompt(
                pull_request=candidate.pull_request.number,
                round_input=assignment.compose_round_paths(
                    number=assignment.next_round_number
                ).round_input,
            ),
            finish_round=(
                None
                if round_input.pull_request_state is PullRequestState.OPEN
                else partial(
                    complete_assignment, assignment=assignment, clock=self.clock
                )
            ),
        )

    def _inspect_assignment(
        self,
        *,
        assignment: AgentWork,
        most_recent_cooldown_ended: datetime | None,
        observed_at: datetime,
    ) -> _AssignmentItemInspection:
        """Inspect one open assignment, reading its pull request once it has one.

        Nothing is read for an assignment whose round is running or that is in
        fault, since neither can start a round.
        """
        unread = compose_agent_work_row(work=assignment, finding=None)
        if assignment.rounds and assignment.rounds[-1].ending is None:
            return _AssignmentItemInspection(row=unread)
        if derive_agent_work_fault(
            rounds=assignment.rounds,
            retry_requested_at=assignment.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        ):
            return _AssignmentItemInspection(row=unread, is_fault=True)
        observation = read_pull_request_observation(assignment=assignment)
        if observation is None:
            return _AssignmentItemInspection(
                row=unread,
                candidate=PullRequestOpeningCandidate(assignment=assignment),
            )
        return self._inspect_pull_request(
            assignment=assignment,
            observation=observation,
            observed_at=observed_at,
        )

    def _inspect_pull_request(
        self,
        *,
        assignment: AgentWork,
        observation: PullRequestObservation,
        observed_at: datetime,
    ) -> _AssignmentItemInspection:
        """Inspect an assignment's pull request and the user posts past its cursor."""
        pull_request = read_pull_request(
            repository=self.repository, pull_request=observation.number
        )
        if isinstance(pull_request, UnknownGitHubResponse):
            return _AssignmentItemInspection(
                row=compose_agent_work_row(
                    work=assignment, finding=ReadFailure(reason=pull_request.reason)
                )
            )
        record_pull_request_observation(
            assignment=assignment,
            pull_request=pull_request,
            observed_at=observed_at,
        )
        undelivered_posts = list_undelivered_user_posts(
            repository=self.repository,
            pull_request=pull_request.number,
            account=self.account,
            delivery_position=read_user_post_delivery_position(assignment=assignment),
        )
        if isinstance(undelivered_posts, UnknownGitHubResponse):
            return _AssignmentItemInspection(
                row=compose_agent_work_row(
                    work=assignment,
                    finding=ReadFailure(reason=undelivered_posts.reason),
                )
            )
        row = compose_agent_work_row(
            work=assignment,
            finding=PullRequestFinding(
                number=pull_request.number,
                state=pull_request.state,
                is_draft=pull_request.is_draft,
                new_posts=len(undelivered_posts),
            ),
        )
        if not _is_round_due(
            assignment=assignment,
            pull_request=pull_request,
            undelivered_posts=undelivered_posts,
        ):
            return _AssignmentItemInspection(row=row)
        return _AssignmentItemInspection(
            row=row,
            candidate=AssignmentRoundCandidate(
                assignment=assignment,
                pull_request=pull_request,
                undelivered_posts=undelivered_posts,
            ),
        )

    def _compose_new_candidates(
        self, *, rows: list[RequestRow]
    ) -> list[NewAssignmentCandidate]:
        """Return a new assignment for each request that nothing claims or blocks."""
        return [
            NewAssignmentCandidate(
                issue=row.issue,
                title=row.title,
                route=self.config.identify_assignment_routes(
                    labels=[row.dispatch_label]
                )[0],
            )
            for row in rows
            if isinstance(row.finding, StartTimeFinding) and row.finding.is_clear
        ]


def _is_round_due(
    *,
    assignment: AgentWork,
    pull_request: PullRequest,
    undelivered_posts: list[UserPost],
) -> bool:
    """Return whether the assignment needs a round.

    A round is needed for user posts past the cursor, for a merged or closed
    pull request whose final turn has not been taken, or to give again the
    input of a round that did not finish.
    """
    return bool(
        undelivered_posts
        or (
            pull_request.state is not PullRequestState.OPEN
            and not is_final_turn_taken(assignment=assignment)
        )
        or is_last_round_unfinished(rounds=assignment.rounds, is_daemon_running=True)
    )
