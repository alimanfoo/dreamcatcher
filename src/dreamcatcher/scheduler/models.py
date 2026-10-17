"""Persistent scheduler records and shared scheduling facts."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    Field,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

from dreamcatcher.documents import DreamcatcherDocument
from dreamcatcher.github import (
    CheckResult,
    PullRequestMergeState,
    PullRequestSignal,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind

GLOBAL_COOLDOWN_DURATION = timedelta(minutes=15)
DEFAULT_MAX_AGENTS = 1


def _normalize_utc(at: datetime, /) -> datetime:
    """Return an aware datetime expressed in UTC; pydantic calls this validator."""
    return at.astimezone(UTC)


_UtcDateTime = Annotated[AwareDatetime, AfterValidator(_normalize_utc)]


class PullRequestFinding(DreamcatcherDocument):
    """Hold what the tick read of an open assignment's pull request.

    A withheld check failure is one that the relay rule kept from the agent.
    """

    found: Literal["pull request"] = "pull request"
    number: PositiveInt
    state: PullRequestState
    is_draft: bool
    merge_state: PullRequestMergeState
    check_result: CheckResult
    new_posts: NonNegativeInt
    new_pull_request_signals: list[PullRequestSignal]
    is_check_failure_withheld: bool
    is_wrap_up_due: bool


class IssueCommentsFinding(DreamcatcherDocument):
    """Hold how many of the user's eligible issue comments are past the cursor."""

    found: Literal["issue comments"] = "issue comments"
    new_comments: NonNegativeInt


class StartTimeFinding(DreamcatcherDocument):
    """Hold the open pull requests claiming an issue and the open issues blocking it."""

    found: Literal["start-time answers"] = "start-time answers"
    linked_pull_requests: list[PositiveInt]
    blocking_issues: list[PositiveInt]

    @property
    def is_clear(self) -> bool:
        """Whether no open pull request claims the issue and no open issue blocks it."""
        return not (self.linked_pull_requests or self.blocking_issues)


class ConflictingLabelsFinding(DreamcatcherDocument):
    """Hold the dispatch labels of one kind that an issue carries together."""

    found: Literal["conflicting labels"] = "conflicting labels"
    labels: list[str] = Field(min_length=2)


class PauseCause(StrEnum):
    """The causes of a pause that the issue's labels and assignee give alone.

    The tick checks them in this order. A second conversation label is the
    third cause, which the tick checks after them and holds as the conflicting
    labels.
    """

    LABEL_REMOVED = "label removed"
    ISSUE_UNASSIGNED = "issue unassigned"


class PausedFinding(DreamcatcherDocument):
    """Say which of the causes that the issue gives alone pauses a conversation."""

    found: Literal["paused"] = "paused"
    cause: PauseCause


class ReadFailureFinding(DreamcatcherDocument):
    """Hold why a read failed, in place of what it would have found."""

    found: Literal["read failed"] = "read failed"
    reason: str


type RequestFinding = Annotated[
    PullRequestFinding
    | IssueCommentsFinding
    | StartTimeFinding
    | ConflictingLabelsFinding
    | PausedFinding
    | ReadFailureFinding,
    Field(discriminator="found"),
]


class StartedRound(DreamcatcherDocument):
    """Name the round that a tick started, and why it errored before its harness ran."""

    number: PositiveInt
    launch_failure: str | None = None


class RequestRow(DreamcatcherDocument):
    """Record one request that a tick saw, and what the tick found for it.

    A request is one dispatch label on one issue. The row names the open agent
    work the request led to, if any. A row has no finding when the tick read
    nothing for it, as for work whose round is running or that is in fault.
    """

    issue: PositiveInt
    title: str
    dispatch_label: str
    kind: AgentWorkKind
    agent_work_identifier: str | None = None
    finding: RequestFinding | None = None
    started_round: StartedRound | None = None


class GlobalCooldown(DreamcatcherDocument):
    """Model an interval during which the scheduler starts no agent work."""

    started: _UtcDateTime
    ends: _UtcDateTime

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> Self:
        """Refuse an empty or backwards cooldown interval."""
        if self.ends <= self.started:
            raise ValueError("cooldown end must follow its start")
        return self


class SchedulerRecord(DreamcatcherDocument):
    """Record what one scheduler tick found and started.

    The tick writes one row per request it saw. Its failures are those that no
    row holds: a failed issue listing, or a launch that failed before its round
    was recorded.
    """

    at: _UtcDateTime
    failures: list[str] = Field(default_factory=list)
    rows: list[RequestRow] = Field(default_factory=list)
    cooldown: GlobalCooldown | None = None
    most_recent_cooldown_ended: _UtcDateTime | None = None

    @property
    def started_rounds(self) -> dict[str, StartedRound]:
        """The round the tick started for each piece of work, by work identifier."""
        return {
            row.agent_work_identifier: row.started_round
            for row in self.rows
            if row.agent_work_identifier is not None and row.started_round is not None
        }

    @property
    def launched_agent_work_identifiers(self) -> list[str]:
        """The work whose round the tick started and that got as far as its harness."""
        return [
            identifier
            for identifier, started_round in self.started_rounds.items()
            if started_round.launch_failure is None
        ]
