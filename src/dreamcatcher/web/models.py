"""Flask-free models for dreamcatcher's web views."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.status import (
    AgentRoundTrigger,
    AgentWorkStatusValue,
    DreamcatcherDaemonStatus,
    IssueFact,
    RequestStatus,
    SectionGuidance,
    StatusFact,
)


@dataclass(frozen=True, kw_only=True)
class WebAgentWorkCard:
    """Represent the values rendered in the work card of agent work of any kind.

    Only an assignment has a pull request, and only a conversation or a
    campaign has an issue state. Only an active campaign's card on the home
    page has a child overview. Ended work has no detail.
    """

    identifier: str
    kind: AgentWorkKind
    issue: int
    title: str
    status: AgentWorkStatusValue
    status_words: str
    detail: str | None
    dispatch_label: str
    harness: str
    model: str
    effort: str
    pull_request: int | None
    pull_request_summary: str | None
    is_pull_request_ready_for_review: bool
    issue_state: str | None
    issue_facts: Sequence[IssueFact]
    child_overview: "WebCampaignChildOverview | None"
    latest_output: str | None


@dataclass(frozen=True, kw_only=True)
class WebCampaignChild:
    """Represent one child in its campaign's overview.

    The child shows its assignment's card and its requests' cards, or its issue
    and the issue's state alone when it has neither.
    """

    issue: int
    title: str
    issue_state: str
    is_closed: bool
    assignment: WebAgentWorkCard | None
    requests: Sequence[RequestStatus]


@dataclass(frozen=True, kw_only=True)
class WebCampaignChildOverview:
    """Represent an active campaign's children, with the words that count them."""

    summary: str
    children: Sequence[WebCampaignChild]


@dataclass(frozen=True, kw_only=True)
class WebAgentRound:
    """Represent one round row on an agent-work page."""

    number: int
    trigger: AgentRoundTrigger
    started: str
    duration: str
    outcome: str
    outcome_description: str


@dataclass(frozen=True, kw_only=True)
class WebHandResume:
    """Represent the directory and command for one hand resume."""

    worktree: str
    command: str


@dataclass(frozen=True, kw_only=True)
class WebFeedLine:
    """Represent one stored feed line on an agent work page."""

    timestamp: str | None
    label: str | None
    detail: str
    is_boundary: bool = False


@dataclass(frozen=True, kw_only=True)
class WebFeedRound:
    """Represent one round's boundary and stored feed lines."""

    number: int
    lines: Sequence[WebFeedLine]


@dataclass(frozen=True, kw_only=True)
class WebAgentFeed:
    """Represent a complete agent feed and the feed position after its last line."""

    rounds: Sequence[WebFeedRound]
    feed_position: str


@dataclass(frozen=True, kw_only=True)
class WebFeedPosition:
    """Identify how far a page has shown a feed, as a round and the next byte in it."""

    round_number: int
    position: int


@dataclass(frozen=True, kw_only=True)
class WebAgentWorkControl:
    """Represent one form that acts on the agent work a page shows."""

    action: Literal["stop", "retry", "cancel"]
    url: str


@dataclass(frozen=True, kw_only=True)
class WebAgentLiveState:
    """Represent the values of an agent-work page that its tail refreshes."""

    card: WebAgentWorkCard
    rounds: Sequence[WebAgentRound]
    card_controls: Sequence[WebAgentWorkControl]
    foot_controls: Sequence[WebAgentWorkControl]
    hand_resume: WebHandResume | None


@dataclass(frozen=True, kw_only=True)
class WebAgentTail:
    """Represent one incremental agent-feed response."""

    github_repository_url: str | None
    feed_position: str
    feed_rounds: Sequence[WebFeedRound]
    live: WebAgentLiveState
    has_empty_feed_placeholder: bool


@dataclass(frozen=True, kw_only=True)
class WebAgentWorkView:
    """Represent every value that the page of one piece of agent work lays out.

    The page opens with the work card that its live state holds.
    """

    repository: str
    github_repository_url: str | None
    daemon: DreamcatcherDaemonStatus
    live: WebAgentLiveState
    feed_rounds: Sequence[WebFeedRound]
    feed_position: str


@dataclass(frozen=True, kw_only=True)
class WebAgentWorkSection:
    """Represent one kind of agent work as a section of the home page.

    The section lists the active work, then the requests with no open work,
    then the guidance, then the ended work.
    """

    kind: AgentWorkKind
    heading: str
    guidance: SectionGuidance | None
    active: Sequence[WebAgentWorkCard]
    requests: Sequence[RequestStatus]
    ended: Sequence[WebAgentWorkCard]


@dataclass(frozen=True, kw_only=True)
class WebHomeView:
    """Represent every value that the home template lays out."""

    repository: str
    github_repository_url: str | None
    daemon: DreamcatcherDaemonStatus
    instance_facts: Sequence[StatusFact]
    scheduler_failures: Sequence[str]
    sections: Sequence[WebAgentWorkSection]
