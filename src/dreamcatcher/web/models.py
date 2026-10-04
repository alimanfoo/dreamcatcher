"""Flask-free models for Dreamcatcher's web views."""

from dataclasses import dataclass
from typing import Protocol

from dreamcatcher.agent_rounds import AgentRoundPaths, AgentRoundRecord
from dreamcatcher.status import AgentRoundRevision


@dataclass(frozen=True, kw_only=True)
class WebFact:
    """Represent one labelled fact on a web page."""

    label: str
    value: str
    is_warning: bool = False


@dataclass(frozen=True, kw_only=True)
class WebAssignmentCard:
    """Represent the values rendered in one assignment card."""

    identifier: str
    issue: int
    title: str | None
    status: str
    detail: str
    dispatch_label: str
    harness: str
    model: str
    effort: str
    pull_request: int
    pull_request_state: str | None
    latest_output: str | None


@dataclass(frozen=True, kw_only=True)
class WebConversationCard:
    """Represent the values rendered in one issue-conversation card."""

    issue: int
    title: str
    status: str
    detail: str
    settings: str | None
    latest_output: str | None


@dataclass(frozen=True, kw_only=True)
class WebAgentRound:
    """Represent one round row on an agent-work page."""

    number: int
    purpose: str
    is_recovery: bool
    started: str
    duration: str
    outcome: str
    outcome_description: str
    revision: AgentRoundRevision | None


@dataclass(frozen=True, kw_only=True)
class WebHandResume:
    """Represent the directory and command for one manual session resume."""

    worktree: str
    command: str


@dataclass(frozen=True, kw_only=True)
class WebFeedLine:
    """Represent one stored feed line on an assignment page."""

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
    """Represent a complete agent feed and the cursor after its last line."""

    rounds: tuple[WebFeedRound, ...]
    cursor: str


@dataclass(frozen=True, kw_only=True)
class WebFeedCursor:
    """Identify the next feed byte to read within an assignment round."""

    round_number: int
    position: int


@dataclass(frozen=True, kw_only=True)
class WebAgentTail:
    """Represent one incremental agent-feed response."""

    cursor: str
    feed_rounds: tuple[WebFeedRound, ...]
    status: str
    detail: str | None
    rounds: tuple[WebAgentRound, ...]
    stop_url: str | None
    has_empty_feed_placeholder: bool


@dataclass(frozen=True, kw_only=True)
class WebAgentTailContext:
    """Provide status values alongside one incremental feed read."""

    status: str
    rounds: tuple[WebAgentRound, ...]
    stop_url: str | None
    detail: str | None = None


@dataclass(frozen=True, kw_only=True)
class WebAssignmentView:
    """Represent every value that the assignment template lays out."""

    repository: str
    github_repository_url: str | None
    daemon_state: str
    daemon_summary: str
    identifier: str
    issue: int
    title: str | None
    status: str
    detail: str
    pull_request: int
    pull_request_state: str | None
    dispatch_label: str
    harness: str
    model: str
    effort: str
    rounds: tuple[WebAgentRound, ...]
    stop_url: str | None
    hand_resume: WebHandResume | None
    feed_rounds: tuple[WebFeedRound, ...]
    feed_cursor: str


@dataclass(frozen=True, kw_only=True)
class WebIssueRow:
    """Represent one issue row in the home view."""

    issue: int
    title: str | None
    labels: str
    status: str
    evidence: tuple[str | int, ...]


@dataclass(frozen=True, kw_only=True)
class WebConversationView:
    """Represent every value that the conversation template lays out."""

    repository: str
    github_repository_url: str | None
    daemon_state: str
    daemon_summary: str
    issue: int
    title: str
    status: str
    detail: str
    facts: tuple[WebFact, ...]
    rounds: tuple[WebAgentRound, ...]
    stop_url: str | None
    hand_resume: WebHandResume | None
    feed_rounds: tuple[WebFeedRound, ...]
    feed_cursor: str


@dataclass(frozen=True, kw_only=True)
class WebHomeView:
    """Represent every value that the home template lays out."""

    repository: str
    github_repository_url: str | None
    daemon_state: str
    daemon_summary: str
    instance_facts: tuple[WebFact, ...]
    cooldown_message: str | None
    conversations: tuple[WebConversationCard, ...]
    active_assignments: tuple[WebAssignmentCard, ...]
    complete_assignments: tuple[WebAssignmentCard, ...]
    failed_setups: tuple[WebIssueRow, ...]
    issues: tuple[WebIssueRow, ...]


class WebFeedOwner(Protocol):
    """Provide the saved rounds and paths that a web feed reads."""

    @property
    def rounds(self) -> list[AgentRoundRecord]:
        """The saved round records in their run order."""
        ...

    def compose_round_paths(self, *, number: int) -> AgentRoundPaths:
        """Return the paths of one numbered round."""
        ...
