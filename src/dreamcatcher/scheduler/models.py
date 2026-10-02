"""Persistent scheduler records and shared observed facts."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Protocol, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from dreamcatcher.agent_rounds import AgentAssignmentRoundPurpose
from dreamcatcher.documents import DreamcatcherDocument

GLOBAL_COOLDOWN_DURATION = timedelta(minutes=15)
DEFAULT_MAX_AGENTS = 1
NO_ROUND_HAS_RUN = "no round has run yet"


def _normalize_utc(at: datetime, /) -> datetime:
    """Return an aware datetime expressed in UTC; pydantic calls this validator."""
    return at.astimezone(UTC)


UtcDateTime = Annotated[AwareDatetime, AfterValidator(_normalize_utc)]


class IssueFactValue(StrEnum):
    """List the truth states of an observed issue fact."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class IssueFact(DreamcatcherDocument):
    """Model an independently observed issue fact and its evidence."""

    value: IssueFactValue
    evidence: str


class IssueObservation(DreamcatcherDocument):
    """Model the independent facts observed about an issue in one tick."""

    issue: int
    title: str | None = None
    created_at: datetime | None = None
    observed_at: UtcDateTime | None = None
    is_open: IssueFact
    is_assigned_to_user: IssueFact
    assignment_labels: list[str] | None = None
    claimed_here: IssueFact
    claimed_elsewhere: IssueFact
    setup_failure: str | None = None
    blocked: IssueFact
    routing_conflict: IssueFact

    @property
    def availability(self) -> IssueFact:
        """Whether the observed facts make the issue available for assignment."""
        return derive_issue_availability(observation=self)


class AgentAssignmentObservation(DreamcatcherDocument):
    """Model what the scheduler found for one idle assignment."""

    assignment_identifier: str
    issue: int
    reason: str
    is_known: bool = True
    is_round_required: bool = True


class IssueConversationObservation(DreamcatcherDocument):
    """Model what the scheduler found for one conversation issue in one tick.

    The scheduler observes every issue matching at least one conversation route.
    When it cannot list matching issues, it observes the previous tick's issues
    again with unknown facts.
    """

    issue: int
    title: str
    has_comments_to_answer: IssueFact
    routing_conflict: IssueFact = Field(
        default_factory=lambda: IssueFact(
            value=IssueFactValue.FALSE,
            evidence="has no conversation routing conflict",
        )
    )


class GlobalCooldown(DreamcatcherDocument):
    """Model an interval during which the scheduler starts no agent work."""

    started: UtcDateTime
    ends: UtcDateTime

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> Self:
        """Refuse an empty or backwards cooldown interval."""
        if self.ends <= self.started:
            raise ValueError("cooldown end must follow its start")
        return self


class SchedulerRecord(DreamcatcherDocument):
    """Record what one scheduler tick observed and decided."""

    at: UtcDateTime
    hold: str | None = None
    launched_agent_work_identifiers: list[str] = Field(default_factory=list)
    issue_observations: list[IssueObservation] = Field(default_factory=list)
    assignment_observations: list[AgentAssignmentObservation] = Field(
        default_factory=list
    )
    conversation_observations: list[IssueConversationObservation] = Field(
        default_factory=list
    )
    cooldown: GlobalCooldown | None = None
    most_recent_cooldown_ended: UtcDateTime | None = None


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
    if observation.assignment_labels is None:
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
    labels = observation.assignment_labels
    if labels is not None and len(labels) != 1:
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
) -> AgentAssignmentRoundPurpose:
    """Return the purpose that the pull request currently requires."""
    if not pull_request.is_open:
        return AgentAssignmentRoundPurpose.WRAP_UP
    if pull_request.is_draft:
        return AgentAssignmentRoundPurpose.IMPLEMENT
    return AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK


def combine_scheduler_failures(*, failures: list[str | None]) -> str | None:
    """Join independent scheduler failures."""
    present = [failure for failure in failures if failure is not None]
    return "; ".join(present) if present else None
