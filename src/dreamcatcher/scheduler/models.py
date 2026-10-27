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

from dreamcatcher.agent_assignments import ObservedPullRequest
from dreamcatcher.campaigns import CampaignChild
from dreamcatcher.documents import DreamcatcherDocument, ReadOnlyList
from dreamcatcher.github import (
    PullRequestSignal,
)
from dreamcatcher.harness_adapters import AgentWorkKind

GLOBAL_COOLDOWN_DURATION = timedelta(minutes=15)
DEFAULT_MAX_AGENTS = 1


def _normalize_utc(at: datetime, /) -> datetime:
    """Return an aware datetime expressed in UTC; pydantic calls this validator."""
    return at.astimezone(UTC)


_UtcDateTime = Annotated[AwareDatetime, AfterValidator(_normalize_utc)]


class PullRequestFinding(ObservedPullRequest):
    """Hold what the tick read of an open assignment's pull request.

    A withheld check failure is one that the relay rule
    kept from the agent.
    """

    found: Literal["pull request"] = "pull request"
    number: PositiveInt
    new_posts: NonNegativeInt
    new_pull_request_signals: ReadOnlyList[PullRequestSignal]
    is_check_failure_withheld: bool
    is_wrap_up_due: bool


class IssueCommentsFinding(DreamcatcherDocument):
    """Hold how many of the user's eligible issue comments are past the cursor."""

    found: Literal["issue comments"] = "issue comments"
    new_comments: NonNegativeInt


class IssueReference(DreamcatcherDocument):
    """Name an issue by its number, and by its repository when that is another one.

    An issue without a repository is in the daemon's own repository. Another
    repository is named as its owner and name, as in `owner/name`.
    """

    number: PositiveInt
    repository: str | None = None


class StartTimeFinding(DreamcatcherDocument):
    """Hold the open pull requests claiming an issue and the open issues blocking it."""

    found: Literal["start-time answers"] = "start-time answers"
    linked_pull_requests: ReadOnlyList[PositiveInt]
    blocking_issues: ReadOnlyList[IssueReference]

    @property
    def is_clear(self) -> bool:
        """Whether no open pull request claims the issue and no open issue blocks it."""
        return not (self.linked_pull_requests or self.blocking_issues)


class BlockingIssuesFinding(DreamcatcherDocument):
    """Hold the open issues that block a campaign request's parent."""

    found: Literal["blocking issues"] = "blocking issues"
    blocking_issues: ReadOnlyList[IssueReference] = Field(min_length=1)


class ConflictingLabelsFinding(DreamcatcherDocument):
    """Hold the dispatch labels of one kind that an issue carries together."""

    found: Literal["conflicting labels"] = "conflicting labels"
    labels: ReadOnlyList[str] = Field(min_length=2)


class PauseCause(StrEnum):
    """The causes of a pause that the issue's labels and assignee give alone.

    The tick checks them in this order. A second label of the paused work's
    kind is the third cause, which the tick checks after them and holds as the
    conflicting labels. A label that someone other than the user applied is the
    fourth, which the tick reads last, never while a round runs, and holds as the
    account that applied it.
    """

    LABEL_REMOVED = "label removed"
    ISSUE_UNASSIGNED = "issue unassigned"


class PausedFinding(DreamcatcherDocument):
    """Say which of the causes that the issue gives alone pauses work at it."""

    found: Literal["paused"] = "paused"
    cause: PauseCause


class LabelAppliedByOtherFinding(DreamcatcherDocument):
    """Name who applied a request's dispatch label, when it was not the user.

    An empty applier is an account that GitHub no longer names.
    """

    found: Literal["label applied by another account"] = (
        "label applied by another account"
    )
    applier: str


class CampaignFinding(DreamcatcherDocument):
    """Hold what the tick found new for the lead.

    The tick found the parent open, assigned to the account and carrying the
    campaign's label and no other of its kind. The new comments are the user's
    eligible parent comments past the cursor, and the changed children are
    those whose changes since the newest input delivered to the lead call for
    it.
    """

    found: Literal["campaign"] = "campaign"
    new_comments: NonNegativeInt
    changed_children: NonNegativeInt


class ReadFailureFinding(DreamcatcherDocument):
    """Hold why a read failed or could not yet tell, in place of its answer."""

    found: Literal["read failed"] = "read failed"
    reason: str


type RequestFinding = Annotated[
    PullRequestFinding
    | IssueCommentsFinding
    | StartTimeFinding
    | BlockingIssuesFinding
    | ConflictingLabelsFinding
    | PausedFinding
    | LabelAppliedByOtherFinding
    | CampaignFinding
    | ReadFailureFinding,
    Field(discriminator="found"),
]


class StartedRound(DreamcatcherDocument):
    """Name the round that a tick started.

    A launch failure says why the round errored during its preparation or startup.
    """

    number: PositiveInt
    launch_failure: str | None = None


class RequestRow(DreamcatcherDocument):
    """Record one request that a tick saw, and what the tick found for it.

    A request is one dispatch label on one issue. The row names the open agent
    work the request led to, if any, and that work's latest round when it had
    ended as the tick read the work. A row has no finding when the tick found
    nothing to record for it. A campaign's row holds the children of its parent
    as the tick observed them, whether or not the campaign may take a round,
    and holds none when the tick could not observe them all.
    """

    issue: PositiveInt
    title: str
    dispatch_label: str
    kind: AgentWorkKind
    agent_work_identifier: str | None = None
    ended_round: PositiveInt | None = None
    finding: RequestFinding | None = None
    started_round: StartedRound | None = None
    children: ReadOnlyList[CampaignChild] | None = None


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

    The tick reads the clock once as it starts, for every decision it makes,
    and again as it finishes. It writes one row per request it saw. Its
    failures are those that no row holds: a failed issue listing, or a
    worktree or branch of ended work that Git would not remove.
    """

    at: _UtcDateTime
    finished: _UtcDateTime
    failures: ReadOnlyList[str] = Field(default_factory=list)
    rows: ReadOnlyList[RequestRow] = Field(default_factory=list)
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
