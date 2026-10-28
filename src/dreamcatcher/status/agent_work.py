"""Derive the status of agent work of any kind."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Protocol, cast

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
from dreamcatcher.agent_work import AgentWork, AgentWorkEnding, AgentWorkEndReason
from dreamcatcher.campaigns import CampaignChild
from dreamcatcher.documents import read_text
from dreamcatcher.github import IssueState, PullRequestState
from dreamcatcher.harness_adapters import AgentWorkKind, HarnessSessionIdentifier
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.issue_conversations import is_no_reply
from dreamcatcher.scheduler.faults import (
    derive_agent_work_fault,
    is_last_round_unfinished,
)
from dreamcatcher.scheduler.models import (
    CampaignFinding,
    HoldFinding,
    IssueCommentsFinding,
    PullRequestFinding,
    ReadFailureFinding,
    RequestFinding,
    RequestRow,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status.findings import (
    IssueFact,
    describe_changed_children,
    describe_comments_to_answer,
    describe_hold,
    describe_idle_pull_request,
    describe_issue_state,
    describe_pull_request,
    describe_signal,
)
from dreamcatcher.status.rounds import (
    AgentRoundStatus,
    compose_round_duration_description,
    describe_round_ending,
    describe_round_outcome,
    describe_round_trigger,
    describe_running_round,
    find_stoppable_round_paths,
    list_round_statuses,
)
from dreamcatcher.words import describe_count


class AgentWorkStatusValue(StrEnum):
    """List the summary statuses of agent work of any kind.

    Working means that a round is running. Waiting means that a round is due
    but has not started. Fault takes two consecutive errored rounds. Unknown
    means that the latest tick could not tell. Idle means that no round is known
    to be due. Held means that the scheduler takes no round of the work until
    something on GitHub changes. Ended means that the work's ending is recorded.
    """

    WORKING = "working"
    WAITING = "waiting"
    FAULT = "fault"
    UNKNOWN = "unknown"
    IDLE = "idle"
    HELD = "held"
    ENDED = "ended"


AGENT_WORK_STATUS_VALUES_IN_ATTENTION_ORDER = (
    AgentWorkStatusValue.FAULT,
    AgentWorkStatusValue.WORKING,
    AgentWorkStatusValue.WAITING,
    AgentWorkStatusValue.IDLE,
    AgentWorkStatusValue.HELD,
    AgentWorkStatusValue.UNKNOWN,
    AgentWorkStatusValue.ENDED,
)

# What ended work shows as its status: how _dreamcatcher_'s work ended. The
# saved reason "issue closed" names GitHub's cause, which the issue's state
# already shows, so the work shows as ended.
AGENT_WORK_ENDING_WORDS = {
    AgentWorkEndReason.COMPLETED: "completed",
    AgentWorkEndReason.CANCELLED: "cancelled",
    AgentWorkEndReason.ISSUE_CLOSED: "ended",
}


@dataclass(frozen=True, kw_only=True)
class AgentWorkStatus:
    """Describe the derived summary status of one piece of agent work.

    Ended work has no detail, because its status words already say how it ended.
    The issue's facts are what GitHub says that holds the work back.
    """

    work: AgentWork
    row: RequestRow | None
    value: AgentWorkStatusValue
    detail: str | None
    latest_output: str | None
    issue_facts: Sequence[IssueFact] = ()

    @property
    def words(self) -> str:
        """The status in words: the state ended work ended in, else the value."""
        if not self.has_ended:
            return str(self.value)
        return AGENT_WORK_ENDING_WORDS[cast("AgentWorkEnding", self.work.ending).reason]

    @property
    def issue_state(self) -> str | None:
        """The state of the issue that a conversation or a campaign stands for.

        Ended work's issue is closed, since only that ends a conversation or a
        campaign. Open work's is the state that the latest tick read, and it
        has none when that read failed or the tick did not see the work. An
        assignment has none, because its pull request stands for it.
        """
        if self.work.record.kind is AgentWorkKind.ASSIGNMENT:
            return None
        if self.has_ended:
            return describe_issue_state(state=IssueState.CLOSED)
        state = None if self.row is None else self.row.issue_state
        return None if state is None else describe_issue_state(state=state)

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

    @property
    def is_in_fault(self) -> bool:
        """Whether the work is in fault."""
        return self.value is AgentWorkStatusValue.FAULT

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
        finding = self._pull_request_finding
        if finding is not None:
            return describe_pull_request(finding=finding)
        relayed = read_relayed_pull_request_state(assignment=self.work)
        if relayed is None or relayed is PullRequestState.OPEN:
            return None
        return relayed.value.lower()

    @property
    def is_pull_request_ready_for_review(self) -> bool:
        """Whether the latest tick read an open assignment's pull request as ready.

        A pull request that no tick has read, or whose read failed, is not.
        """
        finding = self._pull_request_finding
        return finding is not None and finding.is_ready_for_review

    @property
    def _pull_request_finding(self) -> PullRequestFinding | None:
        finding = None if self.row is None else self.row.finding
        if self.work.is_open and isinstance(finding, PullRequestFinding):
            return finding
        return None

    @property
    def children(self) -> Sequence[CampaignChild] | None:
        """An active campaign's children as the latest tick observed them.

        Other work has none, and so does a campaign whose children the latest
        tick could not observe, or that it did not see.
        """
        if not self._is_active_campaign:
            return None
        return None if self.row is None else self.row.children

    @property
    def closed_children_summary(self) -> str | None:
        """How many of an active campaign's children GitHub holds closed, of how many.

        Other work has no summary.
        """
        if not self._is_active_campaign:
            return None
        children = self.children
        if children is None:
            return "sub-issues unknown"
        if not children:
            return "no sub-issues"
        closed = sum(child.is_closed for child in children)
        total = describe_count(number=len(children), noun="sub-issue")
        return f"{closed} of {total} closed"

    @property
    def _is_active_campaign(self) -> bool:
        return self.work.record.kind is AgentWorkKind.CAMPAIGN and self.is_active

    @cached_property
    def round_statuses(self) -> list[AgentRoundStatus]:
        """The derived status of every round in run order."""
        return list_round_statuses(work=self.work, is_working=self.is_working)

    @cached_property
    def harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """The recorded harness session identifier, or else one found in output."""
        return self.work.find_harness_session_identifier()

    @property
    def worktree(self) -> Path | None:
        """The work's worktree, unless the work has ended and its worktree is gone."""
        work = self.work
        return work.worktree if work.is_open or work.worktree.exists() else None

    @cached_property
    def hand_resume_command(self) -> list[str] | None:
        """The hand-resume command when nobody is running the session.

        Work whose worktree is gone has none, since the command runs there.
        """
        identifier = self.harness_session_identifier
        if self.is_working or identifier is None or self.worktree is None:
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
        if not self.is_in_fault:
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

        The first that applies of working, ended, fault, unknown, held, idle
        while awaiting an update, and waiting is the status. Otherwise the
        work is idle, or unknown when the latest tick has no row for it or
        read nothing for it.
        """
        steps: tuple[_StatusStep, ...] = (
            self._derive_working,
            self._derive_ended,
            self._derive_fault,
            self._derive_unknown,
            self._derive_held,
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
            trigger=describe_round_trigger(work=work, number=latest.number),
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
            detail=None,
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
        return _compose_unknown(work=work, row=row, detail=row.finding.reason)

    def _derive_held(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        """Derive the status of work that the scheduler holds back for its issue.

        The user paused it, its issue carries a second label of its kind, or
        someone other than the user applied its label.
        """
        finding = None if row is None else row.finding
        if not isinstance(finding, HoldFinding):
            return None
        fact, advice = describe_hold(finding=finding, kind=work.record.kind)
        return AgentWorkStatus(
            work=work,
            row=row,
            value=AgentWorkStatusValue.HELD,
            detail=advice,
            latest_output=None,
            issue_facts=(fact,),
        )

    def _derive_awaiting_update(
        self, *, work: AgentWork, row: RequestRow | None
    ) -> AgentWorkStatus | None:
        """Derive idle when the latest tick read the work before its round ended.

        A finding that started the round was relayed by that round. Other news
        found while the round ran makes another round due instead.
        """
        if not work.rounds or row is None:
            return None
        latest = work.rounds[-1]
        if (
            latest.ending is None
            or latest.is_unfinished
            or _did_tick_read_ending(row=row, record=latest)
        ):
            return None
        news = _describe_what_is_new(finding=row.finding)
        did_tick_start_round = (
            row.started_round is not None and row.started_round.number == latest.number
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
            detail = _describe_idle_round(
                work=work, ending=_describe_conversation_answer(work=work)
            )
        elif isinstance(finding, CampaignFinding):
            detail = _describe_idle_round(work=work, ending=None)
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
        cursor, so nothing is due once a tick that read the work after the round
        ended found none of them left. An assignment's or a campaign's
        unfinished round is always due.
        """
        if not is_last_round_unfinished(
            rounds=work.rounds, is_daemon_running=self.is_daemon_running
        ):
            return False
        finding = None if row is None else row.finding
        return not (
            isinstance(finding, IssueCommentsFinding)
            and not finding.new_comments
            and _did_tick_read_ending(row=row, record=work.rounds[-1])
        )

    def _is_round_working(self, *, record: AgentRoundRecord) -> bool:
        """Return whether the round is still running under a daemon."""
        return (
            interpret_agent_round_outcome(
                record=record, is_daemon_running=self.is_daemon_running
            )
            is AgentRoundOutcome.RUNNING
        )


def _did_tick_read_ending(*, row: RequestRow | None, record: AgentRoundRecord) -> bool:
    """Return whether the latest tick read the work once the round had ended."""
    return row is not None and row.ended_round == record.number


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
    """Describe why the latest tick's finding makes a round due, if it does.

    A merged or closed pull request awaits its wrap-up round, whatever else
    the tick found new; otherwise the words say what is new in the work's
    channel.
    """
    if isinstance(finding, CampaignFinding):
        words = []
        if finding.new_comments:
            words.append(describe_comments_to_answer(count=finding.new_comments))
        if finding.changed_children:
            words.append(describe_changed_children(count=finding.changed_children))
        return ", ".join(words) or None
    if isinstance(finding, IssueCommentsFinding) and finding.new_comments:
        return describe_comments_to_answer(count=finding.new_comments)
    if not isinstance(finding, PullRequestFinding):
        return None
    if finding.is_wrap_up_due:
        return "awaiting wrap-up"
    words = [
        describe_signal(signal=signal) for signal in finding.new_pull_request_signals
    ]
    if finding.new_posts:
        posts = describe_count(number=finding.new_posts, noun="new post")
        words.insert(0, f"{posts} to answer")
    return ", ".join(words) or None


def _describe_conversation_answer(*, work: AgentWork) -> str | None:
    """Say what the latest conversation round posted, when it was successful.

    Only a successful round posted an answer or found that none was needed.
    """
    latest = work.rounds[-1]
    if latest.outcome is not AgentRoundOutcome.SUCCESSFUL:
        return None
    final_output = read_text(
        path=work.compose_round_paths(number=latest.number).final_output
    )
    return "no reply needed" if is_no_reply(final_output=final_output) else "answered"


def _describe_idle_round(*, work: AgentWork, ending: str | None) -> str:
    """Describe how the latest round of idle work ended, and how long it ran.

    The ending is said in words of the work's kind when it has some, and as the
    round's outcome otherwise. An interrupted round has no duration.
    """
    latest = work.rounds[-1]
    words = [
        f"round {latest.number}",
        ending or describe_round_outcome(record=latest, outcome=latest.outcome),
        compose_round_duration_description(record=latest),
    ]
    return ", ".join(word for word in words if word)
