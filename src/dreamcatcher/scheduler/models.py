"""Persistent scheduler records and shared scheduling facts."""

from collections.abc import Container
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self, overload

from pydantic import (
    AfterValidator,
    AwareDatetime,
    Field,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

from dreamcatcher.documents import DreamcatcherDocument
from dreamcatcher.github import PullRequestState
from dreamcatcher.harness_adapters import AgentWorkKind

GLOBAL_COOLDOWN_DURATION = timedelta(minutes=15)
DEFAULT_MAX_AGENTS = 1
NO_ROUND_HAS_RUN = "no round has run yet"


def _normalize_utc(at: datetime, /) -> datetime:
    """Return an aware datetime expressed in UTC; pydantic calls this validator."""
    return at.astimezone(UTC)


_UtcDateTime = Annotated[AwareDatetime, AfterValidator(_normalize_utc)]


class Truth(StrEnum):
    """List the truth states of an observed fact."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class ObservedFact(DreamcatcherDocument):
    """Model an independently observed fact and its evidence."""

    value: Truth
    evidence: str


class ObservedIssueDetails(DreamcatcherDocument):
    """Model the issue details returned together by GitHub."""

    title: str
    created_at: datetime
    assignment_labels: list[str]


class IssueObservation(DreamcatcherDocument):
    """Model the independent facts observed about an issue in one tick."""

    issue: int
    details: ObservedIssueDetails | None = None
    observed_at: _UtcDateTime | None = None
    is_open: ObservedFact
    is_assigned_to_user: ObservedFact
    claimed_here: ObservedFact
    claimed_elsewhere: ObservedFact
    blocked: ObservedFact
    routing_conflict: ObservedFact

    @property
    def availability(self) -> ObservedFact:
        """Whether the observed facts make the issue available for assignment."""
        return derive_issue_availability(observation=self)


class AgentWorkObservation(DreamcatcherDocument):
    """Model whether one agent work item requires a round and why.

    A conversation that the tick observed before it was saved has no identifier
    yet.
    """

    identifier: str | None
    issue: int
    requires_round: ObservedFact


class ConversationObservation(AgentWorkObservation):
    """Model what the scheduler found for one conversation issue in one tick.

    The scheduler observes every issue matching at least one conversation route.
    When it cannot list matching issues, it observes the previous tick's issues
    again with unknown facts.
    """

    title: str
    routing_conflict: ObservedFact = Field(
        default_factory=lambda: ObservedFact(
            value=Truth.FALSE,
            evidence="has no conversation routing conflict",
        )
    )


@overload
def mark_round_started[ObservationT: AgentWorkObservation](
    *,
    observation: ObservationT,
    identifier: str,
    issue: int,
    round_number: int,
) -> ObservationT: ...


@overload
def mark_round_started(
    *, observation: None, identifier: str, issue: int, round_number: int
) -> AgentWorkObservation: ...


def mark_round_started(
    *,
    observation: AgentWorkObservation | None,
    identifier: str,
    issue: int,
    round_number: int,
) -> AgentWorkObservation:
    """Mark or create an agent work observation for a started round."""
    requires_round = ObservedFact(
        value=Truth.FALSE,
        evidence=f"round {round_number} started",
    )
    if observation is None:
        return AgentWorkObservation(
            identifier=identifier,
            issue=issue,
            requires_round=requires_round,
        )
    return observation.model_copy(
        update={"identifier": identifier, "requires_round": requires_round}
    )


class PullRequestFinding(DreamcatcherDocument):
    """Hold what the tick read of an open assignment's pull request."""

    found: Literal["pull request"] = "pull request"
    number: PositiveInt
    state: PullRequestState
    is_draft: bool
    new_posts: NonNegativeInt


class IssueCommentsFinding(DreamcatcherDocument):
    """Hold how many of the user's issue comments no round has been given."""

    found: Literal["issue comments"] = "issue comments"
    new_comments: NonNegativeInt


class StartTimeFinding(DreamcatcherDocument):
    """Hold the open pull requests that claim an issue and the open issues blocking it.

    Work may start for the request when both are empty.
    """

    found: Literal["start-time answers"] = "start-time answers"
    linked_pull_requests: list[PositiveInt]
    blocking_issues: list[PositiveInt]


class ConflictingLabelsFinding(DreamcatcherDocument):
    """Hold the dispatch labels of one kind that an issue carries together."""

    found: Literal["conflicting labels"] = "conflicting labels"
    labels: list[str] = Field(min_length=2)


class UnlistedIssueFinding(DreamcatcherDocument):
    """Say that the listing did not return the issue of open work."""

    found: Literal["issue not listed"] = "issue not listed"


class ReadFailure(DreamcatcherDocument):
    """Hold why a read failed, in place of what it would have found."""

    found: Literal["read failed"] = "read failed"
    reason: str


type RequestFinding = Annotated[
    PullRequestFinding
    | IssueCommentsFinding
    | StartTimeFinding
    | ConflictingLabelsFinding
    | UnlistedIssueFinding
    | ReadFailure,
    Field(discriminator="found"),
]


class StartedRound(DreamcatcherDocument):
    """Name the round that a tick started, and why it errored before its harness ran."""

    number: PositiveInt
    preparation_failure: str | None = None


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
    agent_work: str | None = None
    finding: RequestFinding | None = None
    started_round: StartedRound | None = None


@dataclass(frozen=True, kw_only=True)
class AgentWorkInspection[CandidateT, ObservationT]:
    """Collect one kind's ranked candidates, rows, faults and failures."""

    candidates: list[CandidateT]
    observations: list[ObservationT]
    rows: list[RequestRow]
    fault_count: int
    failures: list[str]


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
    """Record what one scheduler tick observed and decided."""

    at: _UtcDateTime
    failures: list[str] = Field(default_factory=list)
    launched_agent_work_identifiers: list[str] = Field(default_factory=list)
    rows: list[RequestRow] = Field(default_factory=list)
    issue_observations: list[IssueObservation] = Field(default_factory=list)
    assignment_observations: list[AgentWorkObservation] = Field(default_factory=list)
    conversation_observations: list[ConversationObservation] = Field(
        default_factory=list
    )
    cooldown: GlobalCooldown | None = None
    most_recent_cooldown_ended: _UtcDateTime | None = None


def observe_claimed_here(
    *, issue: int, open_assignment_issues: Container[int]
) -> ObservedFact:
    """Observe whether this instance has an open assignment for the issue."""
    if issue in open_assignment_issues:
        return ObservedFact(
            value=Truth.TRUE,
            evidence="this checkout has an open assignment for it",
        )
    return ObservedFact(
        value=Truth.FALSE,
        evidence="this checkout has no open assignment for it",
    )


def derive_issue_availability(*, observation: IssueObservation) -> ObservedFact:
    """Derive whether an issue is available from its independent facts."""
    preventing = _find_preventing_fact(observation=observation)
    if preventing is not None:
        return ObservedFact(
            value=Truth.FALSE,
            evidence=preventing.evidence,
        )
    required = [
        observation.is_open,
        observation.is_assigned_to_user,
        observation.claimed_here,
        observation.claimed_elsewhere,
        observation.blocked,
        observation.routing_conflict,
    ]
    unknown = next((fact for fact in required if fact.value is Truth.UNKNOWN), None)
    if unknown is not None:
        return unknown
    if observation.details is None:
        return ObservedFact(
            value=Truth.UNKNOWN,
            evidence="cannot tell which assignment labels it carries",
        )
    return ObservedFact(
        value=Truth.TRUE,
        evidence="available for assignment",
    )


def _find_preventing_fact(*, observation: IssueObservation) -> ObservedFact | None:
    """Return the first known fact that prevents assignment."""
    preventing = [
        observation.routing_conflict,
        observation.claimed_here,
        observation.claimed_elsewhere,
        observation.blocked,
    ]
    for fact in preventing:
        if fact.value is Truth.TRUE:
            return fact
    for fact in [observation.is_open, observation.is_assigned_to_user]:
        if fact.value is Truth.FALSE:
            return fact
    if (
        observation.details is not None
        and len(observation.details.assignment_labels) != 1
    ):
        return ObservedFact(
            value=Truth.FALSE,
            evidence="carries no configured assignment label",
        )
    return None
