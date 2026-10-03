"""Run one scheduler tick across assignment and conversation work."""

from dataclasses import dataclass, field
from datetime import datetime

from dreamcatcher.agent_rounds import AgentRound
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.assignments import (
    AssignmentCandidate,
    AssignmentInspection,
    AssignmentLaunchRequest,
    AssignmentScheduler,
    NewAssignmentCandidate,
)
from dreamcatcher.scheduler.conversations import (
    ConversationBatchCandidate,
    ConversationCandidate,
    ConversationLaunchRequest,
    ConversationScheduler,
)
from dreamcatcher.scheduler.faults import (
    read_scheduler_record,
    start_cooldown_if_required,
)
from dreamcatcher.scheduler.models import (
    DEFAULT_MAX_AGENTS,
    AgentWorkInspection,
    AgentWorkObservation,
    ConversationObservation,
    IssueFact,
    IssueFactValue,
    SchedulerRecord,
    combine_scheduler_failures,
)


@dataclass(kw_only=True)
class _ReadyAgentWork:
    assignments: list[AssignmentCandidate]
    conversations: list[ConversationCandidate]

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


def _read_candidate_issue(
    *, work_kind: AgentWorkKind, candidates: _ReadyAgentWork
) -> int:
    if work_kind is AgentWorkKind.ASSIGNMENT:
        candidate = candidates.assignments[0]
        if isinstance(candidate, NewAssignmentCandidate):
            return candidate.issue
        return candidate.assignment.record.issue
    candidate = candidates.conversations[0]
    if isinstance(candidate, ConversationBatchCandidate):
        return candidate.issue.number
    return candidate.conversation.record.issue


def _record_started_round(
    *,
    record: SchedulerRecord,
    round_: AgentRound,
    issue: int,
    work_kind: AgentWorkKind,
) -> SchedulerRecord:
    requires_round = IssueFact(
        value=IssueFactValue.FALSE,
        evidence=f"round {round_.record.number} started",
    )
    identifier = round_.agent_work_identifier
    if work_kind is AgentWorkKind.CONVERSATION:
        observations = [
            observation.model_copy(update={"requires_round": requires_round})
            if observation.identifier == identifier
            else observation
            for observation in record.conversation_observations
        ]
        return record.model_copy(update={"conversation_observations": observations})
    observations = [
        observation.model_copy(update={"requires_round": requires_round})
        if observation.identifier == identifier
        else observation
        for observation in record.assignment_observations
    ]
    if not any(observation.identifier == identifier for observation in observations):
        observations.append(
            AgentWorkObservation(
                identifier=identifier,
                issue=issue,
                requires_round=requires_round,
            )
        )
    return record.model_copy(update={"assignment_observations": observations})


@dataclass(kw_only=True)
class Scheduler:
    """Choose and start the work for one Dreamcatcher instance."""

    assignments: AssignmentScheduler
    conversations: ConversationScheduler
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
        previous_record = read_scheduler_record(state=self.assignments.state, at=at)
        self._forget_ended_rounds()
        assignment_inspection = self.assignments.inspect(
            previous_record=previous_record, at=at
        )
        conversation_inspection = self.conversations.inspect(
            previous_record=previous_record, at=at
        )
        cooldown = start_cooldown_if_required(
            active=None if previous_record is None else previous_record.cooldown,
            fault_count=(
                assignment_inspection.fault_count + conversation_inspection.fault_count
            ),
            at=at,
        )
        scheduler_failure = combine_scheduler_failures(
            failures=[
                assignment_inspection.failure,
                conversation_inspection.failure,
            ]
        )
        record = SchedulerRecord(
            at=at,
            cooldown=cooldown,
            most_recent_cooldown_ended=(
                None
                if previous_record is None
                else previous_record.most_recent_cooldown_ended
            ),
            issue_observations=assignment_inspection.issue_observations,
            assignment_observations=assignment_inspection.observations,
            conversation_observations=conversation_inspection.observations,
        )
        if cooldown is not None:
            hold = combine_scheduler_failures(
                failures=["global cooldown", scheduler_failure]
            )
            return record.model_copy(update={"hold": hold})
        if len(self.rounds) >= self.max_agents:
            return self._hold_at_current_capacity(
                record=record,
                scheduler_failure=scheduler_failure,
            )
        return self._launch_available_work(
            record=record,
            assignment_inspection=assignment_inspection,
            conversation_inspection=conversation_inspection,
            scheduler_failure=scheduler_failure,
        )

    def _forget_ended_rounds(self) -> None:
        ended_identifiers = [
            identifier
            for identifier, running in self.rounds.items()
            if not running.is_alive
        ]
        for identifier in ended_identifiers:
            del self.rounds[identifier]

    def _hold_at_current_capacity(
        self,
        *,
        record: SchedulerRecord,
        scheduler_failure: str | None,
    ) -> SchedulerRecord:
        capacity_reason = self._describe_capacity()
        return record.model_copy(
            update={
                "hold": combine_scheduler_failures(
                    failures=[capacity_reason, scheduler_failure]
                ),
            }
        )

    def _launch_available_work(
        self,
        *,
        record: SchedulerRecord,
        assignment_inspection: AssignmentInspection,
        conversation_inspection: AgentWorkInspection[
            ConversationCandidate, ConversationObservation
        ],
        scheduler_failure: str | None,
    ) -> SchedulerRecord:
        """Fill free capacity while alternating between ready work kinds."""
        if scheduler_failure is not None:
            record = record.model_copy(update={"hold": scheduler_failure})
        candidates = _ReadyAgentWork(
            assignments=list(assignment_inspection.candidates),
            conversations=list(conversation_inspection.candidates),
        )
        record, launched_identifiers = self._launch_ready_candidates(
            record=record,
            candidates=candidates,
        )
        record = self._hold_for_capacity(
            record=record,
            candidates=candidates,
        )
        return record.model_copy(
            update={"launched_agent_work_identifiers": launched_identifiers}
        )

    def _launch_ready_candidates(
        self,
        *,
        record: SchedulerRecord,
        candidates: _ReadyAgentWork,
    ) -> tuple[SchedulerRecord, list[str]]:
        launched_identifiers: list[str] = []
        while len(self.rounds) < self.max_agents:
            work_kind = _choose_next_work_kind(
                candidates=candidates,
                last_selected_work_kind=self._last_selected_work_kind,
            )
            if work_kind is None:
                break
            self._last_selected_work_kind = work_kind
            record, launched_identifier = self._launch_next_candidate(
                record=record,
                work_kind=work_kind,
                candidates=candidates,
            )
            if launched_identifier is not None:
                launched_identifiers.append(launched_identifier)
        return record, launched_identifiers

    def _hold_for_capacity(
        self,
        *,
        record: SchedulerRecord,
        candidates: _ReadyAgentWork,
    ) -> SchedulerRecord:
        if len(self.rounds) >= self.max_agents and (
            candidates.is_assignment_ready or candidates.is_conversation_ready
        ):
            capacity_reason = self._describe_capacity()
            return record.model_copy(
                update={
                    "hold": combine_scheduler_failures(
                        failures=[capacity_reason, record.hold]
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
    ) -> tuple[SchedulerRecord, str | None]:
        hold_before_launch = record.hold
        issue = _read_candidate_issue(work_kind=work_kind, candidates=candidates)
        record, launched_round = self._try_launch_candidate(
            record=record,
            work_kind=work_kind,
            candidates=candidates,
        )
        launched_identifier = (
            None if launched_round is None else launched_round.agent_work_identifier
        )
        if launched_round is not None:
            self.rounds[launched_round.agent_work_identifier] = launched_round
            record = _record_started_round(
                record=record,
                round_=launched_round,
                issue=issue,
                work_kind=work_kind,
            )
        if record.hold != hold_before_launch or launched_identifier is None:
            if work_kind is AgentWorkKind.ASSIGNMENT:
                candidates.assignments.clear()
            else:
                candidates.conversations.clear()
        return record, launched_identifier

    def _try_launch_candidate(
        self,
        *,
        record: SchedulerRecord,
        work_kind: AgentWorkKind,
        candidates: _ReadyAgentWork,
    ) -> tuple[SchedulerRecord, AgentRound | None]:
        launched_round = None
        try:
            if work_kind is AgentWorkKind.ASSIGNMENT:
                launched_round = self._launch_next_assignment_candidate(
                    record=record,
                    candidates=candidates,
                )
            else:
                record, launched_round = self.conversations.launch(
                    request=ConversationLaunchRequest(
                        record=record,
                        candidate=candidates.conversations.pop(0),
                    )
                )
        except ReportableError as failure:
            record = self._record_launch_failure(record=record, failure=failure)
        return record, launched_round

    def _launch_next_assignment_candidate(
        self, *, record: SchedulerRecord, candidates: _ReadyAgentWork
    ) -> AgentRound:
        return self.assignments.launch(
            request=AssignmentLaunchRequest(
                candidate=candidates.assignments.pop(0),
                at=record.at,
            )
        )

    def _record_launch_failure(
        self, *, record: SchedulerRecord, failure: ReportableError
    ) -> SchedulerRecord:
        return record.model_copy(
            update={
                "hold": combine_scheduler_failures(failures=[record.hold, str(failure)])
            }
        )

    def _describe_capacity(self) -> str:
        return f"at cap: {len(self.rounds)} of {self.max_agents} agents running"
