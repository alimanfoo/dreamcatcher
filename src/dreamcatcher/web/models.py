"""Flask-free models for dreamcatcher's web views."""

from dataclasses import dataclass
from typing import Literal

from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.status import (
    AgentRoundRevision,
    AgentWorkStatusValue,
    DreamcatcherDaemonStatus,
    RequestStatus,
    StatusFact,
)


@dataclass(frozen=True, kw_only=True)
class WebAgentWorkCard:
    """Represent the values rendered in one card for agent work of either kind.

    Only an assignment has a pull request.
    """

    identifier: str
    kind: AgentWorkKind
    issue: int
    title: str
    status: AgentWorkStatusValue
    detail: str
    dispatch_label: str
    harness: str
    model: str
    effort: str
    pull_request: int | None
    pull_request_summary: str | None
    latest_output: str | None


@dataclass(frozen=True, kw_only=True)
class WebAgentRound:
    """Represent one round row on an agent-work page."""

    number: int
    trigger: str
    started: str
    duration: str
    outcome: str
    outcome_description: str
    revision: AgentRoundRevision | None


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
    is_subagent: bool = False
    is_boundary: bool = False


@dataclass(frozen=True, kw_only=True)
class WebFeedRound:
    """Represent one round's boundary and stored feed lines."""

    number: int
    lines: tuple[WebFeedLine, ...]


@dataclass(frozen=True, kw_only=True)
class WebAgentFeed:
    """Represent a complete agent feed and the feed cursor after its last line."""

    rounds: tuple[WebFeedRound, ...]
    feed_cursor: str


@dataclass(frozen=True, kw_only=True)
class WebFeedCursor:
    """Identify the next feed byte to read within an agent round."""

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

    status: AgentWorkStatusValue
    detail: str
    rounds: tuple[WebAgentRound, ...]
    heading_controls: tuple[WebAgentWorkControl, ...]
    foot_controls: tuple[WebAgentWorkControl, ...]
    hand_resume: WebHandResume | None


@dataclass(frozen=True, kw_only=True)
class WebAgentTail:
    """Represent one incremental agent-feed response."""

    feed_cursor: str
    feed_rounds: tuple[WebFeedRound, ...]
    live: WebAgentLiveState
    has_empty_feed_placeholder: bool


@dataclass(frozen=True, kw_only=True)
class WebAssignmentView:
    """Represent every value that the assignment template lays out."""

    repository: str
    github_repository_url: str | None
    daemon: DreamcatcherDaemonStatus
    identifier: str
    issue: int
    title: str
    pull_request: int | None
    pull_request_summary: str | None
    dispatch_label: str
    harness: str
    model: str
    effort: str
    live: WebAgentLiveState
    feed_rounds: tuple[WebFeedRound, ...]
    feed_cursor: str


@dataclass(frozen=True, kw_only=True)
class WebConversationView:
    """Represent every value that the conversation template lays out."""

    repository: str
    github_repository_url: str | None
    daemon: DreamcatcherDaemonStatus
    identifier: str
    issue: int
    title: str
    facts: tuple[StatusFact, ...]
    live: WebAgentLiveState
    feed_rounds: tuple[WebFeedRound, ...]
    feed_cursor: str


@dataclass(frozen=True, kw_only=True)
class WebAgentWorkSection:
    """Represent one kind of agent work as a section of the home page.

    The section lists the active work, then the requests with no open work,
    then the guidance, then the ended work.
    """

    kind: AgentWorkKind
    heading: str
    empty_message: str | None
    active: tuple[WebAgentWorkCard, ...]
    requests: tuple[RequestStatus, ...]
    ended: tuple[WebAgentWorkCard, ...]


@dataclass(frozen=True, kw_only=True)
class WebHomeView:
    """Represent every value that the home template lays out."""

    repository: str
    github_repository_url: str | None
    daemon: DreamcatcherDaemonStatus
    instance_facts: tuple[StatusFact, ...]
    sections: tuple[WebAgentWorkSection, ...]
