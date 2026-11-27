"""Describe what inspecting one request gives the tick, for every kind of work."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from dreamcatcher.agent_rounds import AgentRoundFinisher
from dreamcatcher.agent_work import AgentWork, DispatchRequest
from dreamcatcher.config import DreamcatcherConfig
from dreamcatcher.documents import DreamcatcherDocument
from dreamcatcher.github import Issue, IssueState
from dreamcatcher.scheduler.models import RequestFinding, RequestRow
from dreamcatcher.state import StateDirectory


@dataclass(frozen=True, kw_only=True)
class SchedulingContext:
    """Hold what the tick reads GitHub and local state with, for every kind."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    clock: Callable[[], datetime]


@dataclass(frozen=True, kw_only=True)
class PreparedRoundInput:
    """Hold the round's input, its prompt and any step to run after success."""

    document: DreamcatcherDocument | None = None
    prompt: str | None = None
    finish_round: AgentRoundFinisher | None = None


class _RoundPreparer(Protocol):
    """Prepare a candidate's next round inside its recorded launch attempt."""

    def __call__(self, *, work: AgentWork) -> PreparedRoundInput:
        """Return the prepared input and any finishing step."""


@dataclass(frozen=True, kw_only=True)
class Candidate:
    """Open work the tick may start a round for, or a request it may start work for.

    It holds the open work or the dispatch request that would create work.
    """

    work_or_request: AgentWork | DispatchRequest
    prepare_round: _RoundPreparer


@dataclass(frozen=True, kw_only=True)
class Inspection:
    """Hold the row the tick writes for one request, and what it may start for it.

    A counted fault is work in fault whose fault counts towards a global
    cooldown.
    """

    row: RequestRow
    candidate: Candidate | None = None
    is_counted_fault: bool = False


class OpenWorkInspector(Protocol):
    """Inspect the channel of one piece of open work of a kind."""

    def __call__(
        self, *, context: SchedulingContext, work: AgentWork, is_in_fault: bool
    ) -> Inspection:
        """Return the work's row, and its candidate when a round is due."""


class RequestInspector(Protocol):
    """Inspect one label of a kind on a listed issue that no open work answers."""

    def __call__(
        self,
        *,
        issue: Issue,
        request: DispatchRequest,
        row: RequestRow,
    ) -> Inspection:
        """Return what the request's row holds, given the row before any read."""


def compose_open_work_row(
    *,
    work: AgentWork,
    finding: RequestFinding | None,
    issue_state: IssueState | None = None,
) -> RequestRow:
    """Return the row of the request that led to open work, with what the tick found.

    The issue's state is the one that the tick read, when it read the issue.
    """
    record = work.record
    return RequestRow(
        issue=record.issue,
        title=record.title,
        dispatch_label=record.dispatch_label,
        kind=record.kind,
        agent_work_identifier=work.identifier,
        ended_round=(
            work.rounds[-1].number
            if work.rounds and work.rounds[-1].ending is not None
            else None
        ),
        finding=finding,
        issue_state=issue_state,
    )
