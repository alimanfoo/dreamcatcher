"""Run one scheduler tick over both kinds of agent work."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial

from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundPreparationError,
    AgentRoundStartRequest,
    start_agent_round,
)
from dreamcatcher.agent_work import (
    AgentWork,
    create_agent_work,
    read_agent_work,
    record_harness_session_identifier,
    request_round_stop_if_ended,
)
from dreamcatcher.config import AgentHarness
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Issue, UnknownGitHubResponse, list_issues
from dreamcatcher.harness_adapters import AgentRoundLaunchRequest, AgentWorkKind
from dreamcatcher.prompts import compose_round_prompt
from dreamcatcher.scheduler.assignments import (
    inspect_assignment_request,
    inspect_open_assignment,
)
from dreamcatcher.scheduler.conversations import (
    inspect_conversation_request,
    inspect_open_conversation,
)
from dreamcatcher.scheduler.faults import (
    derive_agent_work_fault,
    read_scheduler_record,
    start_cooldown_if_required,
)
from dreamcatcher.scheduler.inspection import (
    Candidate,
    Inspection,
    SchedulingContext,
    compose_agent_work_row,
)
from dreamcatcher.scheduler.models import (
    DEFAULT_MAX_AGENTS,
    RequestRow,
    SchedulerRecord,
    StartedRound,
)


@dataclass(frozen=True, kw_only=True)
class _IssueListing:
    """Collect the listed issues, oldest first, and the listings that failed."""

    issues: list[Issue]
    failures: list[str]


@dataclass(kw_only=True)
class Scheduler:
    """Choose and start the work for one dreamcatcher instance."""

    context: SchedulingContext
    preferred_harness: AgentHarness
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
        """Inspect every request and fill every free agent slot.

        A round that has ended is forgotten first, so the cap counts what is
        running now. A failure reaches the daemon, which reports it before the
        next tick tries again.

        The requests come from the open agent work on disk and from the
        dispatch labels on the listed issues. Open work is inspected first, in
        identifier order, then the requests with no open work, in listing
        order, and that is the order in which candidates start. A failed
        listing starts no work for the issues it would have listed, and leaves
        open work inspected.

        A global cooldown prevents every launch but does not prevent reads, so
        the rows remain current while the cooldown is active.
        """
        self._forget_ended_rounds()
        previous_record = read_scheduler_record(state=self.context.state, at=at)
        most_recent_cooldown_ended = (
            None
            if previous_record is None
            else previous_record.most_recent_cooldown_ended
        )
        open_work = [
            work for work in read_agent_work(state=self.context.state) if work.is_open
        ]
        listing = self._list_issues()
        inspections = [
            *(
                self._inspect_open_work(
                    work=work, most_recent_cooldown_ended=most_recent_cooldown_ended
                )
                for work in open_work
            ),
            *self._inspect_requests(issues=listing.issues, open_work=open_work),
        ]
        cooldown = start_cooldown_if_required(
            active=None if previous_record is None else previous_record.cooldown,
            fault_count=sum(inspection.is_fault for inspection in inspections),
            at=at,
        )
        record = SchedulerRecord(
            at=at,
            failures=listing.failures,
            rows=[inspection.row for inspection in inspections],
            cooldown=cooldown,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        if cooldown is not None:
            return record
        return self._launch_candidates(
            record=record,
            candidates=[
                inspection.candidate
                for inspection in inspections
                if inspection.candidate is not None
            ],
        )

    def _forget_ended_rounds(self) -> None:
        ended_identifiers = [
            identifier
            for identifier, running in self.rounds.items()
            if not running.is_alive
        ]
        for identifier in ended_identifiers:
            del self.rounds[identifier]

    def _list_issues(self) -> _IssueListing:
        """List the open issues assigned to the account under every dispatch label."""
        issues_by_number: dict[int, Issue] = {}
        failures: list[str] = []
        for route in self.context.config.routes:
            listed = list_issues(
                repository=self.context.repository,
                label=route.label,
                assignee=self.context.account,
            )
            if isinstance(listed, UnknownGitHubResponse):
                failures.append(
                    f"could not list issues for {route.label}: {listed.reason}"
                )
            else:
                issues_by_number.update((issue.number, issue) for issue in listed)
        return _IssueListing(
            issues=sorted(
                issues_by_number.values(),
                key=lambda issue: (issue.created_at, issue.number),
            ),
            failures=failures,
        )

    def _inspect_open_work(
        self, *, work: AgentWork, most_recent_cooldown_ended: datetime | None
    ) -> Inspection:
        """Inspect one piece of open work through its kind's channel.

        Nothing is read for work whose round is running, since it can start no
        round.
        """
        if work.rounds and work.rounds[-1].ending is None:
            return Inspection(row=compose_agent_work_row(work=work, finding=None))
        is_fault = derive_agent_work_fault(
            rounds=work.rounds,
            retry_requested_at=work.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        if work.record.kind is AgentWorkKind.ASSIGNMENT:
            return inspect_open_assignment(
                context=self.context, assignment=work, is_fault=is_fault
            )
        return inspect_open_conversation(
            context=self.context, conversation=work, is_fault=is_fault
        )

    def _inspect_requests(
        self, *, issues: list[Issue], open_work: list[AgentWork]
    ) -> Iterator[Inspection]:
        """Inspect each dispatch label on each listed issue that no open work answers.

        Open work answers the request it came from. An open assignment also
        answers every assignment label on its issue, since an issue has at most
        one, while a conversation answers only its own label.
        """
        answered = {
            (work.record.issue, work.record.dispatch_label.casefold())
            for work in open_work
        }
        assigned_issues = {
            work.record.issue
            for work in open_work
            if work.record.kind is AgentWorkKind.ASSIGNMENT
        }
        config = self.context.config
        for issue in issues:
            labels = [label.name for label in issue.labels]
            assignment_routes = config.identify_assignment_routes(labels=labels)
            conversation_routes = config.identify_conversation_routes(labels=labels)
            yield from (
                inspect_assignment_request(
                    context=self.context,
                    issue=issue,
                    route=route,
                    routes=assignment_routes,
                )
                for route in assignment_routes
                if issue.number not in assigned_issues
            )
            yield from (
                inspect_conversation_request(
                    context=self.context,
                    issue=issue,
                    route=route,
                    routes=conversation_routes,
                )
                for route in conversation_routes
                if (issue.number, route.label.casefold()) not in answered
            )

    def _launch_candidates(
        self, *, record: SchedulerRecord, candidates: list[Candidate]
    ) -> SchedulerRecord:
        """Fill free capacity in candidate order, alternating between work kinds.

        A launch that fails takes no slot, and the next candidate is tried. The
        row of each request names the round started for it, and why that round
        errored if it did so before its harness ran. A launch that fails before
        any round exists is a scheduler failure.
        """
        while candidates and not self.is_at_capacity:
            candidate = self._choose_next_candidate(candidates=candidates)
            candidates.remove(candidate)
            self._last_selected_work_kind = candidate.row.kind
            try:
                launched = self._launch(candidate=candidate, at=record.at)
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
                identifier = launched.agent_work_identifier
                self.rounds[identifier] = launched
                started_round = StartedRound(number=launched.record.number)
            record = record.model_copy(
                update={
                    "rows": _mark_row_started(
                        rows=record.rows,
                        started=candidate.row,
                        agent_work_identifier=identifier,
                        started_round=started_round,
                    )
                }
            )
        return record

    def _choose_next_candidate(self, *, candidates: list[Candidate]) -> Candidate:
        """Return the first candidate of the kind whose turn it is.

        The kinds take turns while both have candidates, and either kind goes
        on alone once the other has none.
        """
        turn = (
            AgentWorkKind.CONVERSATION
            if self._last_selected_work_kind is AgentWorkKind.ASSIGNMENT
            else AgentWorkKind.ASSIGNMENT
        )
        return next(
            (candidate for candidate in candidates if candidate.row.kind is turn),
            candidates[0],
        )

    def _launch(self, *, candidate: Candidate, at: datetime) -> AgentRound:
        """Create the candidate's work if it is a request, then start its next round.

        The round resumes the work's harness session when there is one. A
        round whose work has ended by the time it starts is asked to stop.
        """
        work = (
            candidate.work
            if isinstance(candidate.work, AgentWork)
            else create_agent_work(
                state=self.context.state,
                route=candidate.work,
                preferred_harness=self.preferred_harness,
                issue=candidate.row.issue,
                title=candidate.row.title,
                at=at,
            )
        )
        plan = candidate.compose_round(work=work)
        harness_session_identifier = work.find_harness_session_identifier()
        if harness_session_identifier is not None:
            record_harness_session_identifier(
                work=work, identifier=harness_session_identifier
            )
        paths = work.compose_round_paths(number=work.next_round_number)
        started_round = start_agent_round(
            request=AgentRoundStartRequest(
                harness=work.record.harness,
                launch_request=AgentRoundLaunchRequest(
                    agent_work_identifier=work.identifier,
                    model=work.record.model,
                    effort=work.record.effort,
                    harness_config=work.record.harness_config,
                    prompt=compose_round_prompt(
                        instructions=work.record.prompt,
                        is_resuming=harness_session_identifier is not None,
                        input_prompt=plan.input_prompt,
                        previous_outcome=(
                            work.rounds[-1].outcome if work.rounds else None
                        ),
                    ),
                    work_kind=work.record.kind,
                ),
                harness_session_identifier=harness_session_identifier,
                record_harness_session_identifier=partial(
                    record_harness_session_identifier, work=work
                ),
                finish_round=plan.finish_round,
                paths=paths,
                prepare_round=plan.prepare_round,
            ),
            clock=self.context.clock,
        )
        request_round_stop_if_ended(work=work, paths=paths)
        return started_round


def _mark_row_started(
    *,
    rows: list[RequestRow],
    started: RequestRow,
    agent_work_identifier: str,
    started_round: StartedRound,
) -> list[RequestRow]:
    """Return the rows with the started request's row naming its work and round."""
    return [
        row.model_copy(
            update={
                "agent_work_identifier": agent_work_identifier,
                "started_round": started_round,
            }
        )
        if row.issue == started.issue and row.dispatch_label == started.dispatch_label
        else row
        for row in rows
    ]
