"""Derive the status of agent work of either kind."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cached_property
from typing import Protocol

from dreamcatcher.agent_assignments import (
    read_assignment_pull_request_number,
    read_relayed_pull_request_state,
)
from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    interpret_agent_round_outcome,
)
from dreamcatcher.agent_work import AgentWork
from dreamcatcher.documents import read_text
from dreamcatcher.github import PullRequestState
from dreamcatcher.harness_adapters import AgentWorkKind, HarnessSessionIdentifier
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.issue_conversations import is_no_reply
from dreamcatcher.scheduler.faults import (
    derive_agent_work_fault,
    is_last_round_unfinished,
)
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    PausedFinding,
    PullRequestFinding,
    ReadFailureFinding,
    RequestFinding,
    RequestRow,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status.findings import (
    describe_comments_to_answer,
    describe_conflicting_labels,
    describe_idle_pull_request,
    describe_pause,
    describe_pull_request,
    describe_read_failure,
    describe_signal,
)
from dreamcatcher.status.rounds import (
    AgentRoundStatus,
    compose_round_duration_description,
    describe_round_ending,
    describe_round_trigger,
    describe_running_round,
    find_stoppable_round_paths,
    list_round_statuses,
)
from dreamcatcher.words import describe_count


class AgentWorkStatusValue(StrEnum):
    """List the summary statuses of agent work of either kind.

    Working means that a round is running. Waiting means that a round is due
    but has not started. Fault takes two consecutive errored rounds. Unknown
    means that the latest tick could not tell. Idle means that no round is known
    to be due. Ended means that the work's ending is recorded.
    """

    WORKING = "working"
    WAITING = "waiting"
    FAULT = "fault"
    UNKNOWN = "unknown"
    IDLE = "idle"
    ENDED = "ended"


AGENT_WORK_STATUS_VALUES_IN_ATTENTION_ORDER = (
    AgentWorkStatusValue.FAULT,
    AgentWorkStatusValue.WORKING,
    AgentWorkStatusValue.WAITING,
    AgentWorkStatusValue.IDLE,
    AgentWorkStatusValue.UNKNOWN,
    AgentWorkStatusValue.ENDED,
)


@dataclass(frozen=True, kw_only=True)
class AgentWorkStatus:
    """Describe the derived summary status of one piece of agent work."""

    work: AgentWork
    row: RequestRow | None
    value: AgentWorkStatusValue
    detail: str
    latest_output: str | None

    @property
    def has_ended(self) -> bool:
        """Whether the work has ended and no round of it is still running."""
        return self.value is AgentWorkStatusValue.ENDED

    @property
    def is_active(self) -> bool:
        """Whether the status report lists the work as active work."""
        return not self.has_ended

    @property
    def is_working(self) -> bool:
        """Whether a round of the work is running."""
        return self.value is AgentWorkStatusValue.WORKING

    @cached_property
    def pull_request(self) -> int | None:
        """The number of the assignment's pull request, once a round opened it."""
        return read_assignment_pull_request_number(assignment=self.work)

    @property
    def pull_request_summary(self) -> str | None:
        """Where the pull request stands in status-report words, when it is known.

        The latest tick's read of an open assignment's pull request gives it.
        Otherwise it is the merged or closed state that the newest relayed round
        input carried, as for an assignment that has ended. An assignment whose
        pull request no round has opened yet has none.
        """
        if self.pull_request is None:
            return None
        finding = None if self.row is None else self.row.finding
        if self.work.is_open and isinstance(finding, PullRequestFinding):
            return describe_pull_request(finding=finding)
        relayed = read_relayed_pull_request_state(assignment=self.work)
        if relayed is None or relayed is PullRequestState.OPEN:
            return None
        return relayed.value.lower()

    @cached_property
    def round_statuses(self) -> list[AgentRoundStatus]:
        """The derived status of every round in run order."""
        return list_round_statuses(work=self.work, is_working=self.is_working)

    @cached_property
    def harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """The recorded harness session identifier, or else one found in output."""
        return self.work.find_harness_session_identifier()

    @cached_property
    def hand_resume_command(self) -> list[str] | None:
        """The hand-resume command when nobody is running the session."""
        identifier = self.harness_session_identifier
        if self.is_working or identifier is None:
            return None
        record = self.work.record
        return HARNESS_ADAPTERS[record.harness].build_hand_resume(
            model=record.model,
            effort=record.effort,
            harness_config=record.harness_config,
            harness_session_identifier=identifier,
        )

    @property
    def faulted_round_number(self) -> int | None:
        """The latest round while the work is in fault, else None."""
        if self.value is not AgentWorkStatusValue.FAULT:
            return None
        return self.work.rounds[-1].number

    @cached_property
    def stoppable_round_paths(self) -> AgentRoundPaths | None:
        """The live round that can accept a stop request, when one exists."""
        work = self.work
        return find_stoppable_round_paths(
            is_working=self.is_working,
            harness_session_identifier=(
                self.harness_session_identifier if self.is_working else None
            ),
            paths=(
                None
                if not work.rounds
                else work.compose_round_paths(number=work.rounds[-1].number)
            ),
        )


class _StatusStep(Protocol):
    """Derive one status from work and its row, or nothing when it does not apply."""

    def __call__(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        """Return the status this step derives, if it applies."""


@dataclass(frozen=True, kw_only=True)
class AgentWorkStatusReader:
    """Derive agent-work statuses from local state and the latest tick."""

    state: StateDirectory
    at: datetime
    is_daemon_running: bool
    scheduler_record: SchedulerRecord | None

    @cached_property
    def rows_by_work(self) -> dict[str, RequestRow]:
        """The latest tick's rows of requests with open work, by work identifier."""
        if self.scheduler_record is None:
            return {}
        return {
            row.agent_work_identifier: row
            for row in self.scheduler_record.rows
            if row.agent_work_identifier is not None
        }

    def derive(self, *, work: AgentWork) -> AgentWorkStatus:
        """Derive one piece of work's status from its records and the latest tick.

        The first that applies of working, ended, fault, unknown, idle for a
        paused conversation, idle while awaiting an update, and waiting is the
        status. Otherwise the work is idle, or unknown when the latest tick has
        no row for it or read nothing for it.
        """
        steps: tuple[_StatusStep, ...] = (
            self._derive_working,
            self._derive_ended,
            self._derive_fault,
            self._derive_unknown,
            self._derive_paused,
            self._derive_awaiting_update,
            self._derive_waiting,
        )
        row = self.rows_by_work.get(work.identifier)
        for step in steps:
            status = step(work=work, row=row)
            if status is not None:
                return status
        return self._derive_idle(work=work, row=row)

    def _derive_working(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        if not work.rounds or not self._is_round_working(record=work.rounds[-1]):
            return None
        latest = work.rounds[-1]
        detail, latest_output = describe_running_round(
            record=latest,
            trigger_description=describe_round_trigger(work=work, number=latest.number),
            paths=work.compose_round_paths(number=latest.number),
            at=self.at,
        )
        return AgentWorkStatus(
            work=work,
            row=row,
            value=AgentWorkStatusValue.WORKING,
            detail=detail,
            latest_output=latest_output,
        )

    def _derive_ended(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        if work.ending is None:
            return None
        return AgentWorkStatus(
            work=work,
            row=row,
            value=AgentWorkStatusValue.ENDED,
            detail=str(work.ending.reason),
            latest_output=None,
        )

    def _derive_fault(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        if not derive_agent_work_fault(
            rounds=work.rounds,
            retry_requested_at=work.retry_requested_at,
            most_recent_cooldown_ended=(
                None
                if self.scheduler_record is None
                else self.scheduler_record.most_recent_cooldown_ended
            ),
        ):
            return None
        latest = work.rounds[-1]
        detail, latest_output = describe_round_ending(
            record=latest, paths=work.compose_round_paths(number=latest.number)
        )
        return AgentWorkStatus(
            work=work,
            row=row,
            value=AgentWorkStatusValue.FAULT,
            detail=detail,
            latest_output=latest_output,
        )

    def _derive_unknown(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        if row is None or not isinstance(row.finding, ReadFailureFinding):
            return None
        return _compose_unknown(
            work=work, row=row, detail=describe_read_failure(reason=row.finding.reason)
        )

    def _derive_paused(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        """Derive the idle status of a paused conversation, which waits for nothing.

        A second conversation label on its issue pauses it as a routing
        conflict.
        """
        finding = None if row is None else row.finding
        if isinstance(finding, PausedFinding):
            cause = str(finding.cause)
        elif isinstance(finding, ConflictingLabelsFinding):
            cause = describe_conflicting_labels(
                kind=work.record.kind, labels=finding.labels
            )
        else:
            return None
        return AgentWorkStatus(
            work=work,
            row=row,
            value=AgentWorkStatusValue.IDLE,
            detail=describe_pause(cause=cause),
            latest_output=None,
        )

    def _derive_awaiting_update(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        """Derive idle when the latest tick predates a round that took its turn.

        A finding that started the round was relayed by that round. Other news
        found while the round ran makes another round due instead.
        """
        if not work.rounds or self.scheduler_record is None:
            return None
        latest = work.rounds[-1]
        if (
            latest.ending is None
            or latest.is_unfinished
            or self._is_ending_assessed(record=latest)
        ):
            return None
        news = None if row is None else _describe_what_is_new(finding=row.finding)
        did_tick_start_round = (
            row is not None
            and row.started_round is not None
            and row.started_round.number == latest.number
        )
        if news is not None and not did_tick_start_round:
            return None
        return AgentWorkStatus(
            work=work,
            row=row,
            value=AgentWorkStatusValue.IDLE,
            detail=f"round {latest.number} ended, awaiting next update",
            latest_output=None,
        )

    def _derive_waiting(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        """Derive the status of work that a round is due for, if it is due.

        A round is due to give again the input of a last round that did not
        finish, before the first round has run, while an assignment's pull
        request is not yet open, and when the latest tick found something new.
        """
        if self._is_unfinished_round_due(work=work, row=row):
            latest = work.rounds[-1]
            detail, _ = describe_round_ending(
                record=latest, paths=work.compose_round_paths(number=latest.number)
            )
            return _compose_waiting(work=work, row=row, detail=detail)
        if not work.rounds:
            return _compose_waiting(work=work, row=row, detail="no round has run yet")
        if (
            work.record.kind is AgentWorkKind.ASSIGNMENT
            and read_assignment_pull_request_number(assignment=work) is None
        ):
            return _compose_waiting(work=work, row=row, detail="no pull request yet")
        news = None if row is None else _describe_what_is_new(finding=row.finding)
        if news is None:
            return None
        return _compose_waiting(work=work, row=row, detail=news)

    def _derive_idle(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus:
        finding = None if row is None else row.finding
        if isinstance(finding, PullRequestFinding):
            detail = describe_idle_pull_request(finding=finding)
        elif isinstance(finding, IssueCommentsFinding):
            detail = _describe_idle_conversation_round(work=work)
        else:
            return _compose_unknown(work=work, row=row)
        return AgentWorkStatus(
            work=work,
            row=row,
            value=AgentWorkStatusValue.IDLE,
            detail=detail,
            latest_output=None,
        )

    def _is_unfinished_round_due(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> bool:
        """Return whether a round is due to give an unfinished round's input again.

        An unfinished conversation round's input is its comments past the
        cursor, so nothing is due once a tick that began after it ended found
        none of them left. An assignment's unfinished round is always due.
        """
        if not is_last_round_unfinished(
            rounds=work.rounds, is_daemon_running=self.is_daemon_running
        ):
            return False
        finding = None if row is None else row.finding
        return not (
            isinstance(finding, IssueCommentsFinding)
            and not finding.new_comments
            and self._is_ending_assessed(record=work.rounds[-1])
        )

    def _is_ending_assessed(self, *, record: AgentRoundRecord) -> bool:
        """Return whether the latest tick began once the round had ended.

        An interruption recorded without a time is never known to be assessed.
        """
        ended = None if record.ending is None else record.ending.at
        return (
            self.scheduler_record is not None
            and ended is not None
            and ended <= self.scheduler_record.at
        )

    def _is_round_working(self, *, record: AgentRoundRecord) -> bool:
        """Return whether the round is still running under a daemon."""
        return (
            interpret_agent_round_outcome(
                record=record, is_daemon_running=self.is_daemon_running
            )
            is AgentRoundOutcome.RUNNING
        )


def _compose_unknown(
    *,
    work: AgentWork,
    row: RequestRow | None,
    detail: str = "not seen by the latest update",
) -> AgentWorkStatus:
    return AgentWorkStatus(
        work=work,
        row=row,
        value=AgentWorkStatusValue.UNKNOWN,
        detail=detail,
        latest_output=None,
    )


def _compose_waiting(
    *, work: AgentWork, row: RequestRow | None, detail: str
) -> AgentWorkStatus:
    return AgentWorkStatus(
        work=work,
        row=row,
        value=AgentWorkStatusValue.WAITING,
        detail=detail,
        latest_output=None,
    )


def _describe_what_is_new(*, finding: RequestFinding | None) -> str | None:
    """Describe what the latest tick found new in the work's channel, if anything."""
    if isinstance(finding, IssueCommentsFinding) and finding.new_comments:
        return describe_comments_to_answer(count=finding.new_comments)
    if not isinstance(finding, PullRequestFinding):
        return None
    if finding.is_wrap_up_due:
        return f"the pull request is {finding.state.lower()}"
    words = [
        describe_signal(signal=signal) for signal in finding.new_pull_request_signals
    ]
    if finding.new_posts:
        posts = describe_count(number=finding.new_posts, noun="new post")
        words.insert(0, f"{posts} to answer")
    return ", ".join(words) or None


def _describe_idle_conversation_round(*, work: AgentWork) -> str:
    """Describe how the latest round of an idle conversation ended.

    Only a successful round posted an answer or found that none was needed. An
    interrupted round has no duration.
    """
    latest = work.rounds[-1]
    ending = str(latest.outcome)
    if latest.outcome is AgentRoundOutcome.SUCCESSFUL:
        final_output = read_text(
            path=work.compose_round_paths(number=latest.number).final_output
        )
        ending = (
            "no reply needed" if is_no_reply(final_output=final_output) else "answered"
        )
    words = [
        f"round {latest.number}",
        ending,
        compose_round_duration_description(record=latest),
    ]
    return ", ".join(word for word in words if word)
