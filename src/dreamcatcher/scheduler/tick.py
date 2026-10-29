"""Run one scheduler tick over every kind of agent work."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import partial

from dreamcatcher.agent_assignments import remove_assignment_worktree_and_branch
from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundLaunchError,
    AgentRoundStartRequest,
    start_agent_round,
)
from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkEndReason,
    create_agent_work,
    read_agent_work,
    record_harness_session_identifier,
    refresh_agent_work,
    remove_agent_work_worktree,
    request_round_stop_if_ended,
)
from dreamcatcher.config import AgentHarness, DispatchRoute
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Issue, UnknownGitHubResponse, list_issues
from dreamcatcher.harness_adapters import AgentRoundLaunchRequest, AgentWorkKind
from dreamcatcher.prompts import compose_round_prompt
from dreamcatcher.scheduler.assignments import (
    inspect_assignment_request,
    inspect_open_assignment,
)
from dreamcatcher.scheduler.campaigns import (
    AssignmentObservations,
    inspect_campaign_request,
    inspect_open_campaign,
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
    OpenWorkInspector,
    RequestInspector,
    SchedulingContext,
)
from dreamcatcher.scheduler.labelling import find_label_applied_by_other
from dreamcatcher.scheduler.models import (
    DEFAULT_MAX_AGENTS,
    ConflictingLabelsFinding,
    RequestRow,
    SchedulerRecord,
    StartedRound,
)
from dreamcatcher.state import StateDirectory

# How the tick's first pass inspects the channel of open work, by the work's
# kind. Campaigns are inspected in the second pass.
_OPEN_WORK_INSPECTORS: dict[AgentWorkKind, OpenWorkInspector] = {
    AgentWorkKind.ASSIGNMENT: inspect_open_assignment,
    AgentWorkKind.CONVERSATION: inspect_open_conversation,
}

# How the tick's first pass inspects a request that no open work answers, by
# its kind.
_REQUEST_INSPECTORS: dict[AgentWorkKind, RequestInspector] = {
    AgentWorkKind.ASSIGNMENT: inspect_assignment_request,
    AgentWorkKind.CONVERSATION: inspect_conversation_request,
}


@dataclass(frozen=True, kw_only=True)
class _IssueListing:
    """Hold the listed issues, oldest first, or why the listing failed."""

    issues: Sequence[Issue]
    failure: str | None


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
        running now. A failure reaches the daemon, which stops with it.

        The requests come from the open agent work on disk and from the
        dispatch labels on the listed issues. The first pass inspects the
        assignments and conversations, and the second pass the campaigns. Each
        pass inspects open work first, in identifier order, then the requests
        with no open work, in listing order, and within each kind that is the
        order in which candidates start. A failed listing starts no new work of
        any kind, and leaves open work inspected.

        A global cooldown prevents every launch but does not prevent reads, so
        the rows remain current while the cooldown is active. Nor does it
        prevent the removal of worktrees that ended work leaves.
        """
        forgotten_identifiers = self._forget_ended_rounds()
        previous_record = read_scheduler_record(state=self.context.state, at=at)
        most_recent_cooldown_ended = (
            None
            if previous_record is None
            else previous_record.most_recent_cooldown_ended
        )
        all_work = read_agent_work(state=self.context.state)
        open_work = [work for work in all_work if work.is_open]
        watched_work = [
            work
            for work in all_work
            if work.is_open or work.identifier in forgotten_identifiers
        ]
        listing = self._list_issues()
        inspect = partial(
            self._inspect,
            open_work=open_work,
            issues=listing.issues,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        ordinary_inspections = inspect(
            open_work_inspectors=_OPEN_WORK_INSPECTORS,
            request_inspectors=_REQUEST_INSPECTORS,
        )
        observations = _observe_assignments(
            work=all_work, inspections=ordinary_inspections, listing=listing
        )
        inspections = [
            *ordinary_inspections,
            *inspect(
                open_work_inspectors={
                    AgentWorkKind.CAMPAIGN: partial(
                        inspect_open_campaign, observations=observations
                    )
                },
                request_inspectors={
                    AgentWorkKind.CAMPAIGN: partial(
                        inspect_campaign_request, observations=observations
                    )
                },
            ),
        ]
        cooldown = start_cooldown_if_required(
            active=None if previous_record is None else previous_record.cooldown,
            fault_count=sum(inspection.is_counted_fault for inspection in inspections),
            at=at,
        )
        rows = [inspection.row for inspection in inspections]
        failures = [
            *([] if listing.failure is None else [listing.failure]),
            *self._remove_ended_worktrees(watched_work=watched_work),
        ]
        if cooldown is None:
            self._launch_candidates(rows=rows, inspections=inspections, at=at)
        return SchedulerRecord(
            at=at,
            finished=self.context.clock(),
            failures=failures,
            rows=rows,
            cooldown=cooldown,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )

    def _forget_ended_rounds(self) -> list[str]:
        """Forget every round that has ended, and return its work's identifier."""
        ended_identifiers = [
            identifier
            for identifier, running in self.rounds.items()
            if not running.is_alive
        ]
        for identifier in ended_identifiers:
            del self.rounds[identifier]
        return ended_identifiers

    def _remove_ended_worktrees(self, *, watched_work: list[AgentWork]) -> list[str]:
        """Remove the worktree of each piece of watched work that has now ended.

        Watched work was open when the tick read it, or had a round that the
        tick has just forgotten, so work that ended before then keeps its
        worktree. Work with a round that the daemon still holds waits for the
        tick that forgets the round. A cancelled assignment keeps its worktree
        and branch, because the user has taken them over. Each removal that
        fails is returned as a failure and is not tried again.
        """
        failures = []
        for work in watched_work:
            if work.identifier in self.rounds:
                continue
            ending = refresh_agent_work(state=self.context.state, work=work).ending
            if ending is None or ending.reason is AgentWorkEndReason.CANCELLED:
                continue
            try:
                _remove_worktree_and_branch(state=self.context.state, work=work)
            except ReportableError as failure:
                failures.append(str(failure))
        return failures

    def _list_issues(self) -> _IssueListing:
        """List the open issues assigned to the account, whatever their labels."""
        listed = list_issues(
            repository=self.context.repository, assignee=self.context.account
        )
        if isinstance(listed, UnknownGitHubResponse):
            return _IssueListing(
                issues=[], failure=f"could not list issues: {listed.reason}"
            )
        return _IssueListing(
            issues=sorted(listed, key=lambda issue: (issue.created_at, issue.number)),
            failure=None,
        )

    def _inspect(
        self,
        *,
        open_work: list[AgentWork],
        issues: Sequence[Issue],
        most_recent_cooldown_ended: datetime | None,
        open_work_inspectors: Mapping[AgentWorkKind, OpenWorkInspector],
        request_inspectors: Mapping[AgentWorkKind, RequestInspector],
    ) -> list[Inspection]:
        """Inspect the open work and then the requests of the inspectors' kinds."""
        return [
            *(
                self._inspect_open_work(
                    work=work,
                    inspect_work=open_work_inspectors[work.record.kind],
                    most_recent_cooldown_ended=most_recent_cooldown_ended,
                )
                for work in open_work
                if work.record.kind in open_work_inspectors
            ),
            *self._inspect_requests(
                issues=issues, open_work=open_work, inspectors=request_inspectors
            ),
        ]

    def _inspect_open_work(
        self,
        *,
        work: AgentWork,
        inspect_work: OpenWorkInspector,
        most_recent_cooldown_ended: datetime | None,
    ) -> Inspection:
        """Inspect one piece of open work through its kind's channel.

        A running round prevents another round from starting, but its channel
        is still read so that the request row stays current.
        """
        is_in_fault = derive_agent_work_fault(
            rounds=work.rounds,
            retry_requested_at=work.retry_requested_at,
            most_recent_cooldown_ended=most_recent_cooldown_ended,
        )
        inspection = inspect_work(
            context=self.context, work=work, is_in_fault=is_in_fault
        )
        if not work.is_round_running:
            return inspection
        return replace(inspection, candidate=None)

    def _inspect_requests(
        self,
        *,
        issues: Sequence[Issue],
        open_work: list[AgentWork],
        inspectors: Mapping[AgentWorkKind, RequestInspector],
    ) -> Iterator[Inspection]:
        """Inspect each label of the inspectors' kinds that no open work answers."""
        for issue in issues:
            labels = [label.name for label in issue.labels]
            for kind, inspect_request in inspectors.items():
                yield from self._inspect_requests_of_kind(
                    issue=issue,
                    routes=self.context.config.identify_routes(
                        kind=kind, labels=labels
                    ),
                    open_work=open_work,
                    inspect_request=inspect_request,
                )

    def _inspect_requests_of_kind(
        self,
        *,
        issue: Issue,
        routes: Sequence[DispatchRoute],
        open_work: list[AgentWork],
        inspect_request: RequestInspector,
    ) -> Iterator[Inspection]:
        """Inspect each label of one kind on the issue that no open work answers.

        The routes are every route of the kind that the issue's labels select.
        Two labels of one kind start nothing, so each is a request with
        conflicting labels and nothing is read for it. A label that someone
        other than the user applied holds its request, and nothing more is
        read for it either.
        """
        for route in routes:
            if any(
                work.answers_request(
                    issue=issue.number, kind=route.kind, label=route.label
                )
                for work in open_work
            ):
                continue
            row = RequestRow(
                issue=issue.number,
                title=issue.title,
                dispatch_label=route.label,
                kind=route.kind,
                issue_state=issue.state,
            )
            if len(routes) > 1:
                finding = ConflictingLabelsFinding(
                    labels=[conflicting.label for conflicting in routes]
                )
            else:
                finding = find_label_applied_by_other(
                    context=self.context, issue=issue.number, label=route.label
                )
            if finding is None:
                yield inspect_request(
                    context=self.context, issue=issue, route=route, row=row
                )
            else:
                yield Inspection(row=row.model_copy(update={"finding": finding}))

    def _launch_candidates(
        self,
        *,
        rows: list[RequestRow],
        inspections: list[Inspection],
        at: datetime,
    ) -> None:
        """Fill free capacity in candidate order, the work kinds in rotation.

        The rows are the inspections' rows, in the same order, and this updates
        them in place. The row of each request names the round started for it,
        and why that round errored if it did so during its preparation or
        startup. Such a round takes no slot, and the next candidate is tried. A
        launch that fails before its round is recorded fails the tick.
        """
        ready = [
            (position, candidate)
            for position, inspection in enumerate(inspections)
            if (candidate := inspection.candidate) is not None
        ]
        while ready and not self.is_at_capacity:
            position, candidate = self._choose_next_candidate(ready=ready, rows=rows)
            ready.remove((position, candidate))
            row = rows[position]
            self._last_selected_work_kind = row.kind
            try:
                launched = self._launch(row=row, candidate=candidate, at=at)
            except AgentRoundLaunchError as failure:
                identifier = failure.agent_work_identifier
                started_round = StartedRound(
                    number=failure.round_number,
                    launch_failure=failure.reason,
                )
            else:
                identifier = launched.agent_work_identifier
                started_round = StartedRound(number=launched.record.number)
            rows[position] = row.model_copy(
                update={
                    "agent_work_identifier": identifier,
                    "started_round": started_round,
                }
            )

    def _choose_next_candidate(
        self, *, ready: list[tuple[int, Candidate]], rows: list[RequestRow]
    ) -> tuple[int, Candidate]:
        """Return the first ready candidate of the kind next in rotation.

        Each candidate comes with the position of its request's row. The kinds
        rotate in their listed order, starting after the kind selected last, and
        a kind with no candidate gives up its place to the next.
        """
        kinds = list(AgentWorkKind)
        last = self._last_selected_work_kind
        first = 0 if last is None else kinds.index(last) + 1
        rotation = kinds[first:] + kinds[:first]
        return min(
            ready,
            key=lambda position_and_candidate: rotation.index(
                rows[position_and_candidate[0]].kind
            ),
        )

    def _launch(
        self, *, row: RequestRow, candidate: Candidate, at: datetime
    ) -> AgentRound:
        """Create the candidate's work if it is a request, then start its next round.

        The round resumes the work's harness session when there is one. The
        daemon holds the round as soon as it starts, so a failure after that
        still ends it with the daemon. A round whose work has ended by the time
        it starts is asked to stop.
        """
        work = (
            candidate.work_or_route
            if isinstance(candidate.work_or_route, AgentWork)
            else create_agent_work(
                state=self.context.state,
                route=candidate.work_or_route,
                preferred_harness=self.preferred_harness,
                issue=row.issue,
                title=row.title,
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
                        instructions=work.record.instructions,
                        is_resuming=harness_session_identifier is not None,
                        input_prompt=plan.input_prompt,
                        previous_outcome=(
                            work.rounds[-1].outcome if work.rounds else None
                        ),
                        work_kind=work.record.kind,
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
        self.rounds[work.identifier] = started_round
        request_round_stop_if_ended(work=work, paths=paths)
        return started_round


def _remove_worktree_and_branch(*, state: StateDirectory, work: AgentWork) -> None:
    """Remove the ended work's worktree, and an assignment's local branch."""
    if work.record.kind is AgentWorkKind.ASSIGNMENT:
        remove_assignment_worktree_and_branch(state=state, assignment=work)
    else:
        remove_agent_work_worktree(state=state, work=work)


def _observe_assignments(
    *, work: list[AgentWork], inspections: list[Inspection], listing: _IssueListing
) -> AssignmentObservations:
    """Return what the first pass found of the assignments, for the campaigns.

    The work is every piece of work in identifier order, so the last assignment
    at an issue is its newest.
    """
    return AssignmentObservations(
        assignments={
            assignment.record.issue: assignment
            for assignment in work
            if assignment.record.kind is AgentWorkKind.ASSIGNMENT
        },
        inspections={
            inspection.row.issue: inspection
            for inspection in inspections
            if inspection.row.kind is AgentWorkKind.ASSIGNMENT
        },
        listing_failure=listing.failure,
    )
