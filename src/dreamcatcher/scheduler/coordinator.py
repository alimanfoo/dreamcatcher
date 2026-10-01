"""Alternate between ready assignment and conversation work."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    AgentAssignmentCreator,
    find_open_agent_assignments_by_issue,
    inspect_incomplete_assignment_setups,
    read_agent_assignments,
)
from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundOutcome,
)
from dreamcatcher.config import AgentHarness, DreamcatcherConfig
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import (
    read_issue_conversations,
)
from dreamcatcher.scheduler.assignments import (
    AgentAssignmentInspectionResult,
    FaultedAgentAssignment,
    RequiredAgentRound,
    compose_assignment_observation,
    compose_initial_round_requirement,
    inspect_agent_assignment,
    launch_required_round,
    list_assignment_observations,
    prioritize_required_rounds,
)
from dreamcatcher.scheduler.conversation_launch import (
    launch_issue_conversation_round,
)
from dreamcatcher.scheduler.conversations import (
    IssueConversationCandidate,
    IssueConversationCandidateResult,
    IssueConversationRecoveryCandidate,
    list_issue_conversation_candidates,
)
from dreamcatcher.scheduler.faults import (
    _count_observed_conversation_faults,
    _start_cooldown_if_required,
    read_scheduler_record,
)
from dreamcatcher.scheduler.issues import (
    _record_missing_assignment_titles,
    observe_issues,
)
from dreamcatcher.scheduler.models import (
    DEFAULT_MAX_AGENTS,
    IssueFactValue,
    IssueObservation,
    SchedulerRecord,
    combine_scheduler_failures,
)
from dreamcatcher.state import StateDirectory


def _list_available_issues(*, record: SchedulerRecord) -> list[IssueObservation]:
    """Return the issues that the scheduler observed as available, in order."""
    return [
        observation
        for observation in record.issue_observations
        if observation.availability.value is IssueFactValue.TRUE
    ]


type _AssignmentCandidate = RequiredAgentRound | IssueObservation


def _list_ready_assignment_candidates(
    *,
    record: SchedulerRecord,
    inspection_results: list[AgentAssignmentInspectionResult],
    failure: str | None,
) -> list[_AssignmentCandidate]:
    """Return assignment candidates when their shared issue read succeeded."""
    if failure is not None:
        return []
    required_rounds = prioritize_required_rounds(
        required_rounds=[
            result
            for result in inspection_results
            if isinstance(result, RequiredAgentRound)
        ]
    )
    return [*required_rounds, *_list_available_issues(record=record)]


def _list_ready_conversation_candidates(
    *, result: IssueConversationCandidateResult
) -> list[IssueConversationCandidate]:
    """Return safe candidates, retaining saved recovery across a failed read."""
    if result.failure is None:
        return list(result.candidates)
    return [
        candidate
        for candidate in result.candidates
        if isinstance(candidate, IssueConversationRecoveryCandidate)
    ]


@dataclass(kw_only=True)
class _ReadyAgentWork:
    assignments: list[_AssignmentCandidate]
    conversations: list[IssueConversationCandidate]

    @property
    def is_assignment_ready(self) -> bool:
        """Whether an assignment round or issue can start."""
        return bool(self.assignments)

    @property
    def is_conversation_ready(self) -> bool:
        """Whether a conversation round can start."""
        return bool(self.conversations)


def _choose_next_work_kind(
    *,
    candidates: _ReadyAgentWork,
    last_selected_work_kind: AgentWorkKind | None,
) -> AgentWorkKind | None:
    if candidates.is_assignment_ready and candidates.is_conversation_ready:
        if last_selected_work_kind is AgentWorkKind.ASSIGNMENT:
            return AgentWorkKind.CONVERSATION
        return AgentWorkKind.ASSIGNMENT
    if candidates.is_assignment_ready:
        return AgentWorkKind.ASSIGNMENT
    if candidates.is_conversation_ready:
        return AgentWorkKind.CONVERSATION
    return None


@dataclass(kw_only=True)
class AgentWorkScheduler:
    """Choose and start the work for one Dreamcatcher instance."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    requested_harness: AgentHarness
    clock: Callable[[], datetime]
    rounds: dict[str, AgentRound]
    max_agents: int = DEFAULT_MAX_AGENTS
    _last_selected_work_kind: AgentWorkKind | None = field(
        default=None, init=False, repr=False
    )

    def tick(self, *, at: datetime) -> SchedulerRecord:
        """Inspect current work and fill every free agent slot.

        A round that has ended is forgotten first, so the cap counts what is
        running now. A failure reaches the daemon, which reports it before the
        next tick tries again.

        Every tick observes relevant issues so that status stays current while
        open work runs or waits for capacity. A failed read prevents launches
        in the workflow that depends on it without holding the other workflow.

        A global cooldown prevents every launch but does not prevent reads, so
        assignment and conversation observations remain current while the
        cooldown is active.
        """
        previous_record = read_scheduler_record(state=self.state, at=at)
        cooldown = None if previous_record is None else previous_record.cooldown
        most_recent_cooldown_ended = (
            None
            if previous_record is None
            else previous_record.most_recent_cooldown_ended
        )
        ended_agent_work_identifiers = [
            agent_work_identifier
            for agent_work_identifier, running in self.rounds.items()
            if not running.is_alive
        ]
        for agent_work_identifier in ended_agent_work_identifiers:
            del self.rounds[agent_work_identifier]
        assignments = read_agent_assignments(state=self.state)
        conversations = read_issue_conversations(state=self.state)
        issue_observation_result = observe_issues(
            repository=self.repository,
            account=self.account,
            config=self.config,
            assignments=assignments,
            incomplete_setups=inspect_incomplete_assignment_setups(
                state=self.state, repository=self.repository
            ),
        )
        assignment_failure = (
            None
            if issue_observation_result.failure is None
            else f"could not refresh issues: {issue_observation_result.failure}"
        )
        issue_observations = [
            observation.model_copy(update={"observed_at": at})
            for observation in issue_observation_result.observations
        ]
        _record_missing_assignment_titles(
            assignments=assignments,
            observations=issue_observations,
        )
        inspection_results = self._inspect_assignments(
            assignments=assignments,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
            observed_at=at,
        )
        conversation_candidates = list_issue_conversation_candidates(
            scheduler=self,
            conversations=conversations,
            previous_observations=(
                []
                if previous_record is None
                else previous_record.conversation_observations
            ),
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        conversation_fault_count = _count_observed_conversation_faults(
            conversations=conversations,
            observations=conversation_candidates.observations,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        cooldown = _start_cooldown_if_required(
            active=cooldown,
            fault_count=(
                sum(
                    isinstance(result, FaultedAgentAssignment)
                    for result in inspection_results
                )
                + conversation_fault_count
            ),
            at=at,
        )
        scheduler_failure = combine_scheduler_failures(
            failures=[assignment_failure, conversation_candidates.failure]
        )
        assignment_observations = list_assignment_observations(
            inspection_results=inspection_results
        )
        record = SchedulerRecord(
            at=at,
            cooldown=cooldown,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
            issue_observations=issue_observations,
            assignment_observations=assignment_observations,
            conversation_observations=conversation_candidates.observations,
        )
        if cooldown is not None:
            hold_reason = "global cooldown"
            if scheduler_failure is not None:
                hold_reason = f"{hold_reason}; {scheduler_failure}"
            return record.model_copy(update={"hold": hold_reason})
        if len(self.rounds) >= self.max_agents:
            capacity_reason = (
                f"at cap: {len(self.rounds)} of {self.max_agents} agents running"
            )
            hold_reason = (
                capacity_reason
                if scheduler_failure is None
                else f"{capacity_reason}; {scheduler_failure}"
            )
            return record.model_copy(
                update={
                    "hold": hold_reason,
                    "assignment_observations": list_assignment_observations(
                        inspection_results=inspection_results,
                        required_reason=capacity_reason,
                    ),
                }
            )
        return self._launch_available_work(
            record=record,
            inspection_results=inspection_results,
            conversation_candidates=conversation_candidates,
            assignment_failure=assignment_failure,
            scheduler_failure=scheduler_failure,
        )

    def _launch_available_work(
        self,
        *,
        record: SchedulerRecord,
        inspection_results: list[AgentAssignmentInspectionResult],
        conversation_candidates: IssueConversationCandidateResult,
        assignment_failure: str | None,
        scheduler_failure: str | None,
    ) -> SchedulerRecord:
        """Fill free capacity while alternating between ready work kinds."""
        launched_identifiers: list[str] = []
        if scheduler_failure is not None:
            record = record.model_copy(update={"hold": scheduler_failure})
        candidates = _ReadyAgentWork(
            assignments=_list_ready_assignment_candidates(
                record=record,
                inspection_results=inspection_results,
                failure=assignment_failure,
            ),
            conversations=_list_ready_conversation_candidates(
                result=conversation_candidates
            ),
        )
        record, inspection_results, launched_identifiers = (
            self._launch_ready_candidates(
                record=record,
                candidates=candidates,
                inspection_results=inspection_results,
            )
        )
        record = self._hold_for_capacity(
            record=record,
            candidates=candidates,
            inspection_results=inspection_results,
        )
        return record.model_copy(
            update={"launched_agent_work_identifiers": launched_identifiers}
        )

    def _launch_ready_candidates(
        self,
        *,
        record: SchedulerRecord,
        candidates: _ReadyAgentWork,
        inspection_results: list[AgentAssignmentInspectionResult],
    ) -> tuple[SchedulerRecord, list[AgentAssignmentInspectionResult], list[str]]:
        launched_identifiers: list[str] = []
        while len(self.rounds) < self.max_agents:
            work_kind = _choose_next_work_kind(
                candidates=candidates,
                last_selected_work_kind=self._last_selected_work_kind,
            )
            if work_kind is None:
                break
            self._last_selected_work_kind = work_kind
            record, inspection_results, launched_identifier = (
                self._launch_next_candidate(
                    record=record,
                    work_kind=work_kind,
                    candidates=candidates,
                    inspection_results=inspection_results,
                )
            )
            if launched_identifier is not None:
                launched_identifiers.append(launched_identifier)
        return record, inspection_results, launched_identifiers

    def _hold_for_capacity(
        self,
        *,
        record: SchedulerRecord,
        candidates: _ReadyAgentWork,
        inspection_results: list[AgentAssignmentInspectionResult],
    ) -> SchedulerRecord:
        if len(self.rounds) >= self.max_agents and (
            candidates.is_assignment_ready or candidates.is_conversation_ready
        ):
            capacity_reason = (
                f"at cap: {len(self.rounds)} of {self.max_agents} agents running"
            )
            record = record.model_copy(
                update={
                    "hold": combine_scheduler_failures(
                        failures=[capacity_reason, record.hold]
                    ),
                    "assignment_observations": list_assignment_observations(
                        inspection_results=inspection_results,
                        required_reason=capacity_reason,
                    ),
                }
            )
        return record

    def _launch_next_candidate(
        self,
        *,
        record: SchedulerRecord,
        work_kind: AgentWorkKind,
        candidates: _ReadyAgentWork,
        inspection_results: list[AgentAssignmentInspectionResult],
    ) -> tuple[SchedulerRecord, list[AgentAssignmentInspectionResult], str | None]:
        running_before_launch = self.rounds.copy()
        hold_before_launch = record.hold
        if work_kind is AgentWorkKind.ASSIGNMENT:
            record, inspection_results = self._launch_next_assignment_candidate(
                record=record,
                candidates=candidates,
                inspection_results=inspection_results,
            )
        else:
            record = launch_issue_conversation_round(
                scheduler=self,
                record=record,
                candidate=candidates.conversations.pop(0),
            )
        launched_identifier = next(
            (
                identifier
                for identifier, running in self.rounds.items()
                if running_before_launch.get(identifier) is not running
            ),
            None,
        )
        if record.hold != hold_before_launch or launched_identifier is None:
            if work_kind is AgentWorkKind.ASSIGNMENT:
                candidates.assignments.clear()
            else:
                candidates.conversations.clear()
        return record, inspection_results, launched_identifier

    def _launch_next_assignment_candidate(
        self,
        *,
        record: SchedulerRecord,
        candidates: _ReadyAgentWork,
        inspection_results: list[AgentAssignmentInspectionResult],
    ) -> tuple[SchedulerRecord, list[AgentAssignmentInspectionResult]]:
        candidate = candidates.assignments.pop(0)
        if isinstance(candidate, RequiredAgentRound):
            record = self._launch_assignment_round(
                record=record,
                required=candidate,
            )
            if candidate.assignment.identifier in self.rounds:
                inspection_results = [
                    result for result in inspection_results if result is not candidate
                ]
                record = record.model_copy(
                    update={
                        "assignment_observations": list_assignment_observations(
                            inspection_results=inspection_results
                        )
                    }
                )
            return record, inspection_results
        return (
            self._start_available_assignment(
                record=record,
                issue=candidate,
            ),
            inspection_results,
        )

    def _inspect_assignments(
        self,
        *,
        assignments: list[AgentAssignment],
        most_recent_cooldown_ended: datetime | None,
        observed_at: datetime,
    ) -> list[AgentAssignmentInspectionResult]:
        """Return what each assignment needs next, and what each is waiting on."""
        inspection_results: list[AgentAssignmentInspectionResult] = []
        open_assignments = find_open_agent_assignments_by_issue(assignments=assignments)
        for assignment in open_assignments.values():
            if (
                assignment.identifier in self.rounds
                and assignment.rounds[-1].outcome is AgentRoundOutcome.RUNNING
            ):
                continue
            inspection_result = inspect_agent_assignment(
                repository=self.repository,
                account=self.account,
                assignment=assignment,
                most_recent_cooldown_ended=most_recent_cooldown_ended,
                observed_at=observed_at,
            )
            if inspection_result is not None:
                inspection_results.append(inspection_result)
            else:
                inspection_results.append(
                    compose_assignment_observation(
                        assignment=assignment,
                        reason="no round required",
                        is_round_required=False,
                    )
                )
        return inspection_results

    def _launch_assignment_round(
        self,
        *,
        record: SchedulerRecord,
        required: RequiredAgentRound,
    ) -> SchedulerRecord:
        """Launch the next round for the highest-priority assignment."""
        try:
            self._launch_required_round(required=required)
        except ReportableError as failure:
            return record.model_copy(
                update={
                    "hold": combine_scheduler_failures(
                        failures=[record.hold, str(failure)]
                    ),
                }
            )
        return record

    def _launch_required_round(self, *, required: RequiredAgentRound) -> None:
        """Start an assignment round through the assignment policy boundary."""
        launch_required_round(scheduler=self, required=required)

    def _start_available_assignment(
        self,
        *,
        record: SchedulerRecord,
        issue: IssueObservation,
    ) -> SchedulerRecord:
        """Start an assignment for one issue whose facts make it available."""
        labels = issue.assignment_labels or []
        try:
            self._launch_assignment(issue=issue.issue, label=labels[0], at=record.at)
        except ReportableError as failure:
            return record.model_copy(
                update={
                    "hold": combine_scheduler_failures(
                        failures=[record.hold, str(failure)]
                    )
                }
            )
        return record

    def _launch_assignment(self, *, issue: int, label: str, at: datetime) -> None:
        """Create an assignment and start its first round."""
        creator = AgentAssignmentCreator(
            state=self.state,
            repository=self.repository,
        )
        assignment = creator.create(
            route=self.config.assignment_routes[label],
            requested_harness=self.requested_harness,
            issue=issue,
            at=at,
        )
        self._launch_required_round(
            required=compose_initial_round_requirement(assignment=assignment)
        )
