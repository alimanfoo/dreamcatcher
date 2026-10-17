"""Run one scheduler tick across assignment and conversation work."""

from dataclasses import dataclass, field
from datetime import datetime

from dreamcatcher.agent_rounds import AgentRound, AgentRoundPreparationError
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.assignments import (
    AssignmentCandidate,
    AssignmentScheduler,
    NewAssignmentCandidate,
)
from dreamcatcher.scheduler.conversations import (
    ConversationBatchCandidate,
    ConversationScheduler,
)
from dreamcatcher.scheduler.faults import (
    read_scheduler_record,
    start_cooldown_if_required,
)
from dreamcatcher.scheduler.models import (
    DEFAULT_MAX_AGENTS,
    RequestRow,
    SchedulerRecord,
    StartedRound,
)
from dreamcatcher.state import StateDirectory


@dataclass(kw_only=True)
class _ReadyAgentWork:
    assignments: list[AssignmentCandidate]
    conversations: list[ConversationBatchCandidate]


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


def _read_candidate_request(
    *, work_kind: AgentWorkKind, candidates: _ReadyAgentWork
) -> tuple[int, str]:
    """Return the issue and dispatch label of the next candidate of this kind."""
    if work_kind is AgentWorkKind.ASSIGNMENT:
        candidate = candidates.assignments[0]
        if isinstance(candidate, NewAssignmentCandidate):
            return candidate.issue, candidate.route.label
        record = candidate.assignment.record
        return record.issue, record.dispatch_label
    conversation_candidate = candidates.conversations[0]
    if conversation_candidate.conversation is None:
        return conversation_candidate.issue.number, conversation_candidate.route.label
    record = conversation_candidate.conversation.record
    return record.issue, record.dispatch_label


def _mark_row_started(
    *,
    rows: list[RequestRow],
    request: tuple[int, str],
    agent_work_identifier: str,
    started_round: StartedRound,
) -> list[RequestRow]:
    """Return the rows with the request's row naming its work and the started round."""
    issue, label = request
    return [
        row.model_copy(
            update={
                "agent_work_identifier": agent_work_identifier,
                "started_round": started_round,
            }
        )
        if row.issue == issue and row.dispatch_label == label
        else row
        for row in rows
    ]


@dataclass(kw_only=True)
class Scheduler:
    """Choose and start the work for one dreamcatcher instance."""

    state: StateDirectory
    assignments: AssignmentScheduler
    conversations: ConversationScheduler
    rounds: dict[str, AgentRound]
    max_agents: int = DEFAULT_MAX_AGENTS
    _last_selected_work_kind: AgentWorkKind | None = field(
        default=None, init=False, repr=False
    )

    @property
    def is_at_capacity(self) -> bool:
        """Whether every agent slot has a round running in it."""
        return len(self.rounds) >= self.max_agents

    def tick(self, *, at: datetime) -> SchedulerRecord:
        """Inspect current work and fill every free agent slot.

        A round that has ended is forgotten first, so the cap counts what is
        running now. A failure reaches the daemon, which reports it before the
        next tick tries again.

        Every tick writes a row for each request it sees, so that status stays
        current while open work runs or waits for capacity. A failed read
        prevents only the launches that depend on what it would have read.

        A global cooldown prevents every launch but does not prevent reads, so
        the rows remain current while the cooldown is active.
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
        record = SchedulerRecord(
            at=at,
            failures=[
                *assignment_inspection.failures,
                *conversation_inspection.failures,
            ],
            cooldown=cooldown,
            most_recent_cooldown_ended=(
                None
                if previous_record is None
                else previous_record.most_recent_cooldown_ended
            ),
            rows=[*assignment_inspection.rows, *conversation_inspection.rows],
        )
        if cooldown is not None:
            return record
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
        """Fill free capacity while alternating between ready work kinds.

        A launch that fails takes no slot, and the next candidate is tried. The
        row of each request names the round started for it, and why that round
        errored if it did so before its harness ran. A launch that fails before
        any round exists is a scheduler failure.
        """
        while not self.is_at_capacity:
            work_kind = _choose_next_work_kind(
                candidates=candidates,
                last_selected_work_kind=self._last_selected_work_kind,
            )
            if work_kind is None:
                break
            self._last_selected_work_kind = work_kind
            request = _read_candidate_request(
                work_kind=work_kind,
                candidates=candidates,
            )
            try:
                launched_round = self._launch_next_candidate(
                    work_kind=work_kind,
                    candidates=candidates,
                    at=record.at,
                )
            except AgentRoundPreparationError as failure:
                identifier = failure.agent_work_identifier
                started_round = StartedRound(
                    number=failure.round_number,
                    preparation_failure=failure.reason,
                )
            except ReportableError as failure:
                record = record.model_copy(
                    update={"failures": [*record.failures, str(failure)]}
                )
                continue
            else:
                identifier = launched_round.agent_work_identifier
                self.rounds[identifier] = launched_round
                started_round = StartedRound(number=launched_round.record.number)
            record = record.model_copy(
                update={
                    "rows": _mark_row_started(
                        rows=record.rows,
                        request=request,
                        agent_work_identifier=identifier,
                        started_round=started_round,
                    )
                }
            )
        return record

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
