"""Persistent scheduler records and shared scheduling facts."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Protocol, Self, overload

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from dreamcatcher.agent_rounds import AssignmentRoundPurpose
from dreamcatcher.documents import DreamcatcherDocument

GLOBAL_COOLDOWN_DURATION = timedelta(minutes=15)
DEFAULT_MAX_AGENTS = 1
NO_ROUND_HAS_RUN = "no round has run yet"


@dataclass(frozen=True, kw_only=True)
class AgentWorkInspection[CandidateT, ObservationT]:
    """Collect one kind's ranked candidates, observations, faults and failures."""

    candidates: list[CandidateT]
    observations: list[ObservationT]
    fault_count: int
    failures: list[str]


def _normalize_utc(at: datetime, /) -> datetime:
    """Return an aware datetime expressed in UTC; pydantic calls this validator."""
    return at.astimezone(UTC)


_UtcDateTime = Annotated[AwareDatetime, AfterValidator(_normalize_utc)]


class IssueFactValue(StrEnum):
    """List the truth states of an observed issue fact."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class IssueFact(DreamcatcherDocument):
    """Model an independently observed issue fact and its evidence."""

    value: IssueFactValue
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
    is_open: IssueFact
    is_assigned_to_user: IssueFact
    claimed_here: IssueFact
    claimed_elsewhere: IssueFact
    setup_failure: str | None = None
    blocked: IssueFact
    routing_conflict: IssueFact

    @property
    def availability(self) -> IssueFact:
        """Whether the observed facts make the issue available for assignment."""
        return derive_issue_availability(observation=self)


class AgentWorkObservation(DreamcatcherDocument):
    """Model whether one agent work item requires a round and why."""

    identifier: str
    issue: int
    requires_round: IssueFact


class ConversationObservation(AgentWorkObservation):
    """Model what the scheduler found for one conversation issue in one tick.

    The scheduler observes every issue matching at least one conversation route.
    When it cannot list matching issues, it observes the previous tick's issues
    again with unknown facts.
    """

    title: str
    routing_conflict: IssueFact = Field(
        default_factory=lambda: IssueFact(
            value=IssueFactValue.FALSE,
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
    requires_round = IssueFact(
        value=IssueFactValue.FALSE,
        evidence=f"round {round_number} started",
    )
    if observation is None:
        return AgentWorkObservation(
            identifier=identifier,
            issue=issue,
            requires_round=requires_round,
        )
    return observation.model_copy(update={"requires_round": requires_round})


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
    issue_observations: list[IssueObservation] = Field(default_factory=list)
    assignment_observations: list[AgentWorkObservation] = Field(default_factory=list)
    conversation_observations: list[ConversationObservation] = Field(
        default_factory=list
    )
    cooldown: GlobalCooldown | None = None
    most_recent_cooldown_ended: _UtcDateTime | None = None


def derive_issue_availability(*, observation: IssueObservation) -> IssueFact:
    """Derive whether an issue is available from its independent facts."""
    preventing = _find_preventing_issue_fact(observation=observation)
    if preventing is not None:
        return IssueFact(
            value=IssueFactValue.FALSE,
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
    unknown = next(
        (fact for fact in required if fact.value is IssueFactValue.UNKNOWN), None
    )
    if unknown is not None:
        return unknown
    if observation.details is None:
        return IssueFact(
            value=IssueFactValue.UNKNOWN,
            evidence="cannot tell which assignment labels it carries",
        )
    return IssueFact(
        value=IssueFactValue.TRUE,
        evidence="available for assignment",
    )


def _find_preventing_issue_fact(*, observation: IssueObservation) -> IssueFact | None:
    """Return the first known fact that prevents assignment."""
    preventing = [
        observation.routing_conflict,
        observation.claimed_here,
        observation.claimed_elsewhere,
        observation.blocked,
    ]
    for fact in preventing:
        if fact.value is IssueFactValue.TRUE:
            return fact
    for fact in [observation.is_open, observation.is_assigned_to_user]:
        if fact.value is IssueFactValue.FALSE:
            return fact
    if (
        observation.details is not None
        and len(observation.details.assignment_labels) != 1
    ):
        return IssueFact(
            value=IssueFactValue.FALSE,
            evidence="carries no configured assignment label",
        )
    return None


class _PullRequestRoundFacts(Protocol):
    """Describe the pull-request facts that choose a round purpose."""

    @property
    def is_open(self) -> bool:
        """Whether the pull request is open."""

    @property
    def is_draft(self) -> bool:
        """Whether the pull request is a draft."""


def derive_round_purpose(
    *, pull_request: _PullRequestRoundFacts
) -> AssignmentRoundPurpose:
    """Return the purpose that the pull request currently requires."""
    if not pull_request.is_open:
        return AssignmentRoundPurpose.WRAP_UP
    if pull_request.is_draft:
        return AssignmentRoundPurpose.IMPLEMENT
    return AssignmentRoundPurpose.ADDRESS_FEEDBACK
