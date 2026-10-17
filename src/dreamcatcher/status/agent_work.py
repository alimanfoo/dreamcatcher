"""Derive the status of agent work of either kind."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cached_property
from typing import cast

from dreamcatcher.agent_assignments import (
    PullRequestObservation,
    read_pull_request_observation,
)
from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.agent_work import AgentWork, AgentWorkEndReason
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
    PullRequestFinding,
    ReadFailureFinding,
    RequestFinding,
    RequestRow,
    SchedulerRecord,
    UnlistedIssueFinding,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status.findings import (
    describe_comments_to_answer,
    describe_conflicting_labels,
    describe_read_failure,
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
    but has not started, or that a round has just ended and no tick has looked
    since. Fault takes two consecutive errored rounds. Unknown means that the
    latest tick could not tell. Idle means that nothing is due until something
    new appears in the work's channel. Ended means that the work's ending is
    recorded.
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
    AgentWorkStatusValue.UNKNOWN,
    AgentWorkStatusValue.IDLE,
    AgentWorkStatusValue.ENDED,
)


@dataclass(frozen=True, kw_only=True)
class AgentWorkStatus:
    """Describe the derived summary status of one piece of agent work."""

    work: AgentWork
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
    def pull_request_observation(self) -> PullRequestObservation | None:
        """The assignment's pull request as last observed, once a round opened it."""
        return read_pull_request_observation(assignment=self.work)

    @property
    def pull_request(self) -> int | None:
        """The number of the assignment's pull request, once a round opened it."""
        observation = self.pull_request_observation
        return None if observation is None else observation.number

    @property
    def pull_request_state(self) -> str | None:
        """The latest observed pull-request state in status-report words.

        A cancelled assignment has none, because nothing observes its pull
        request once the user has taken it over, and neither does one whose
        pull request no round has opened yet.
        """
        ending = self.work.ending
        if ending is not None and ending.reason is AgentWorkEndReason.CANCELLED:
            return None
        observation = self.pull_request_observation
        if observation is None:
            return None
        if observation.is_open:
            return "draft" if observation.is_draft else "ready"
        return observation.state.value.lower()

    @cached_property
    def round_statuses(self) -> list[AgentRoundStatus]:
        """The derived status of every round in run order."""
        return list_round_statuses(work=self.work, is_working=self.is_working)

    @cached_property
    def harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """The recorded or recoverable harness session identifier."""
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


type _StatusStep = Callable[[AgentWork], AgentWorkStatus | None]


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
        conversation that the tick starts no round for, and waiting is the
        status. Otherwise the work is idle, or unknown when the latest tick has
        no row for it or read nothing for it.
        """
        steps: tuple[_StatusStep, ...] = (
            self._derive_working,
            self._derive_ended,
            self._derive_fault,
            self._derive_unknown,
            self._derive_unscheduled_conversation,
            self._derive_waiting,
        )
        for step in steps:
            status = step(work)
            if status is not None:
                return status
        return self._derive_idle(work)

    def _derive_working(self, work: AgentWork, /) -> AgentWorkStatus | None:
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
            value=AgentWorkStatusValue.WORKING,
            detail=detail,
            latest_output=latest_output,
        )

    def _derive_ended(self, work: AgentWork, /) -> AgentWorkStatus | None:
        if work.ending is None:
            return None
        return AgentWorkStatus(
            work=work,
            value=AgentWorkStatusValue.ENDED,
            detail=str(work.ending.reason),
            latest_output=None,
        )

    def _derive_fault(self, work: AgentWork, /) -> AgentWorkStatus | None:
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
            value=AgentWorkStatusValue.FAULT,
            detail=detail,
            latest_output=latest_output,
        )

    def _derive_unknown(self, work: AgentWork, /) -> AgentWorkStatus | None:
        row = self.rows_by_work.get(work.identifier)
        if row is None or not isinstance(row.finding, ReadFailureFinding):
            return None
        return _compose_unknown(
            work=work, detail=describe_read_failure(reason=row.finding.reason)
        )

    def _derive_unscheduled_conversation(
        self, work: AgentWork, /
    ) -> AgentWorkStatus | None:
        """Derive the idle status of a conversation that the tick starts no round for.

        The tick starts no round for a conversation whose issue the listing did
        not return or carries a second conversation label, so neither waits.
        """
        row = self.rows_by_work.get(work.identifier)
        finding = None if row is None else row.finding
        if isinstance(finding, ConflictingLabelsFinding):
            detail = describe_conflicting_labels(
                kind=work.record.kind, labels=finding.labels
            )
        elif isinstance(finding, UnlistedIssueFinding):
            detail = "issue not listed"
        else:
            return None
        return AgentWorkStatus(
            work=work,
            value=AgentWorkStatusValue.IDLE,
            detail=detail,
            latest_output=None,
        )

    def _derive_waiting(self, work: AgentWork, /) -> AgentWorkStatus | None:
        """Derive the status of work that a round is due for, if it is due.

        A round is due once the last round did not finish, before the first
        round has run, while an assignment's pull request is not yet open, and
        when the latest tick found something new. A round that ended after the
        tick that started it, or after a tick that read nothing for the work, is
        one that no tick has looked at yet.
        """
        if is_last_round_unfinished(
            rounds=work.rounds, is_daemon_running=self.is_daemon_running
        ):
            latest = work.rounds[-1]
            detail, _ = describe_round_ending(
                record=latest, paths=work.compose_round_paths(number=latest.number)
            )
            return _compose_waiting(work=work, detail=detail)
        if not work.rounds:
            return _compose_waiting(work=work, detail="no round has run yet")
        if (
            work.record.kind is AgentWorkKind.ASSIGNMENT
            and read_pull_request_observation(assignment=work) is None
        ):
            return _compose_waiting(work=work, detail="no pull request yet")
        latest = work.rounds[-1]
        row = self.rows_by_work.get(work.identifier)
        if self._did_round_end_after_latest_tick(record=latest, row=row):
            return _compose_waiting(
                work=work, detail=f"round {latest.number} ended, awaiting next update"
            )
        signal = None if row is None else _describe_signal(finding=row.finding)
        if signal is None:
            return None
        return _compose_waiting(work=work, detail=signal)

    def _derive_idle(self, work: AgentWork, /) -> AgentWorkStatus:
        row = self.rows_by_work.get(work.identifier)
        finding = None if row is None else row.finding
        if isinstance(finding, PullRequestFinding):
            detail = (
                "ready for review"
                if finding.state is PullRequestState.OPEN and not finding.is_draft
                else "draft"
                if finding.state is PullRequestState.OPEN
                else finding.state.value.lower()
            )
        elif isinstance(finding, IssueCommentsFinding):
            detail = _describe_answered_round(work=work)
        else:
            return _compose_unknown(work=work)
        return AgentWorkStatus(
            work=work,
            value=AgentWorkStatusValue.IDLE,
            detail=detail,
            latest_output=None,
        )

    def _is_round_working(self, *, record: AgentRoundRecord) -> bool:
        """Return whether the round is still running under a daemon."""
        return record.ending is None and self.is_daemon_running

    def _did_round_end_after_latest_tick(
        self, *, record: AgentRoundRecord, row: RequestRow | None
    ) -> bool:
        """Return whether the latest tick cannot have seen the round's ending.

        The round is one that took its turn, and a tick records its start time,
        so a later ending is conclusive only when that tick started the round
        or read nothing for the work. With no tick recorded there is nothing to
        be later than.
        """
        scheduler_record = self.scheduler_record
        if scheduler_record is None:
            return False
        ending = cast(
            "SuccessfulAgentRoundEnding | StoppedAgentRoundEnding", record.ending
        )
        return ending.at > scheduler_record.at and (
            row is None
            or row.finding is None
            or (
                row.started_round is not None
                and row.started_round.number == record.number
            )
        )


def _compose_unknown(
    *, work: AgentWork, detail: str = "not seen by the latest update"
) -> AgentWorkStatus:
    return AgentWorkStatus(
        work=work,
        value=AgentWorkStatusValue.UNKNOWN,
        detail=detail,
        latest_output=None,
    )


def _compose_waiting(*, work: AgentWork, detail: str) -> AgentWorkStatus:
    return AgentWorkStatus(
        work=work,
        value=AgentWorkStatusValue.WAITING,
        detail=detail,
        latest_output=None,
    )


def _describe_signal(*, finding: RequestFinding | None) -> str | None:
    """Describe what the latest tick found new in the work's channel, if anything."""
    if isinstance(finding, IssueCommentsFinding) and finding.new_comments:
        return describe_comments_to_answer(count=finding.new_comments)
    if not isinstance(finding, PullRequestFinding):
        return None
    if finding.is_final_turn_due:
        return f"the pull request is {finding.state.value.lower()}"
    if finding.new_posts:
        posts = describe_count(number=finding.new_posts, noun="new post")
        return f"{posts} to answer"
    return None


def _describe_answered_round(*, work: AgentWork) -> str:
    """Describe how the latest round of a conversation at rest ended."""
    latest = work.rounds[-1]
    duration = compose_round_duration_description(record=latest)
    if latest.outcome is AgentRoundOutcome.STOPPED:
        return f"round {latest.number}, stopped, {duration}"
    final_output = read_text(
        path=work.compose_round_paths(number=latest.number).final_output
    )
    answer = "no reply needed" if is_no_reply(final_output=final_output) else "answered"
    return f"round {latest.number}, {answer}, {duration}"
