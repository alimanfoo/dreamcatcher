"""Run one scheduler tick across assignment and conversation work."""

from dataclasses import dataclass, field
from datetime import datetime

from dreamcatcher.agent_rounds import AgentRound
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.assignments import (
    AssignmentCandidate,
    AssignmentScheduler,
    NewAssignmentCandidate,
)
from dreamcatcher.scheduler.conversations import (
    ConversationBatchCandidate,
    ConversationCandidate,
    ConversationScheduler,
)
from dreamcatcher.scheduler.faults import (
    read_scheduler_record,
    start_cooldown_if_required,
)
from dreamcatcher.scheduler.models import (
    DEFAULT_MAX_AGENTS,
    SchedulerRecord,
    combine_scheduler_failures,
    mark_round_started,
)
from dreamcatcher.state import StateDirectory


@dataclass(kw_only=True)
class _ReadyAgentWork:
    assignments: list[AssignmentCandidate]
    conversations: list[ConversationCandidate]


def _choose_next_work_kind(
    *,
    candidates: _ReadyAgentWork,
    last_selected_work_kind: AgentWorkKind | None,
) -> AgentWorkKind | None:
    if candidates.assignments and candidates.conversations:
        if last_selected_work_kind is AgentWorkKind.ASSIGNMENT:
            return AgentWorkKind.CONVERSATION
        return AgentWorkKind.ASSIGNMENT
    if candidates.assignments:
        return AgentWorkKind.ASSIGNMENT
    if candidates.conversations:
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


@dataclass(kw_only=True)
class Scheduler:
    """Choose and start the work for one Dreamcatcher instance."""

    state: StateDirectory
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
        self._forget_ended_rounds()
        previous_record = read_scheduler_record(state=self.state, at=at)
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
            hold=scheduler_failure,
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
        return self._launch_ready_candidates(
            record=record,
            candidates=_ReadyAgentWork(
                assignments=list(assignment_inspection.candidates),
                conversations=list(conversation_inspection.candidates),
            ),
        )

    def _forget_ended_rounds(self) -> None:
        ended_identifiers = [
            identifier
            for identifier, running in self.rounds.items()
            if not running.is_alive
        ]
        for identifier in ended_identifiers:
            del self.rounds[identifier]

    def _launch_ready_candidates(
        self,
        *,
        record: SchedulerRecord,
        candidates: _ReadyAgentWork,
    ) -> SchedulerRecord:
        """Fill free capacity while alternating between ready work kinds."""
        was_at_capacity = len(self.rounds) >= self.max_agents
        launched_identifiers: list[str] = []
        while len(self.rounds) < self.max_agents:
            work_kind = _choose_next_work_kind(
                candidates=candidates,
                last_selected_work_kind=self._last_selected_work_kind,
            )
            if work_kind is None:
                break
            self._last_selected_work_kind = work_kind
            issue = _read_candidate_issue(
                work_kind=work_kind,
                candidates=candidates,
            )
            try:
                launched_round = self._launch_next_candidate(
                    work_kind=work_kind,
                    candidates=candidates,
                    at=record.at,
                )
            except ReportableError as failure:
                record = self._record_launch_failure(record=record, failure=failure)
                self._clear_candidates(work_kind=work_kind, candidates=candidates)
                continue
            identifier = launched_round.agent_work_identifier
            self.rounds[identifier] = launched_round
            record = self._mark_round_started(
                record=record,
                round_=launched_round,
                issue=issue,
                work_kind=work_kind,
            )
            launched_identifiers.append(identifier)
        if len(self.rounds) >= self.max_agents and (
            was_at_capacity or candidates.assignments or candidates.conversations
        ):
            record = record.model_copy(
                update={
                    "hold": combine_scheduler_failures(
                        failures=[self._describe_capacity(), record.hold]
                    )
                }
            )
        return record.model_copy(
            update={"launched_agent_work_identifiers": launched_identifiers}
        )

    def _launch_next_candidate(
        self,
        *,
        work_kind: AgentWorkKind,
        candidates: _ReadyAgentWork,
        at: datetime,
    ) -> AgentRound:
        if work_kind is AgentWorkKind.ASSIGNMENT:
            return self.assignments.launch(
                candidate=candidates.assignments.pop(0),
                at=at,
            )
        return self.conversations.launch(
            candidate=candidates.conversations.pop(0),
            at=at,
        )

    def _mark_round_started(
        self,
        *,
        record: SchedulerRecord,
        round_: AgentRound,
        issue: int,
        work_kind: AgentWorkKind,
    ) -> SchedulerRecord:
        identifier = round_.agent_work_identifier
        round_number = round_.record.number
        if work_kind is AgentWorkKind.CONVERSATION:
            observations = [
                mark_round_started(
                    observation=observation,
                    identifier=identifier,
                    issue=issue,
                    round_number=round_number,
                )
                if observation.identifier == identifier
                else observation
                for observation in record.conversation_observations
            ]
            return record.model_copy(update={"conversation_observations": observations})
        observation = next(
            (
                observation
                for observation in record.assignment_observations
                if observation.identifier == identifier
            ),
            None,
        )
        started = mark_round_started(
            observation=observation,
            identifier=identifier,
            issue=issue,
            round_number=round_number,
        )
        observations = [
            started if item.identifier == identifier else item
            for item in record.assignment_observations
        ]
        if observation is None:
            observations.append(started)
        return record.model_copy(update={"assignment_observations": observations})

    def _clear_candidates(
        self, *, work_kind: AgentWorkKind, candidates: _ReadyAgentWork
    ) -> None:
        if work_kind is AgentWorkKind.ASSIGNMENT:
            candidates.assignments.clear()
        else:
            candidates.conversations.clear()

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
