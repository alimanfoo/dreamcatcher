"""Describe what inspecting one request gives the tick, for both kinds of work."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from dreamcatcher.agent_rounds import AgentRoundFinisher
from dreamcatcher.agent_work import AgentWork
from dreamcatcher.config import DispatchRoute, DreamcatcherConfig
from dreamcatcher.documents import DreamcatcherDocument
from dreamcatcher.scheduler.models import RequestFinding, RequestRow
from dreamcatcher.state import StateDirectory


@dataclass(frozen=True, kw_only=True)
class SchedulingContext:
    """Hold what the tick reads GitHub and local state with, for both kinds."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    clock: Callable[[], datetime]


@dataclass(frozen=True, kw_only=True)
class RoundPlan:
    """Describe a round's preparation, its input prompt and its finishing step.

    The preparation runs inside the round, before its harness, and returns the
    input the round is given. A plan with no input prompt gives the agent its
    instructions alone.
    """

    prepare_round: Callable[[], DreamcatcherDocument | None]
    input_prompt: str | None
    finish_round: AgentRoundFinisher | None


class RoundComposer(Protocol):
    """Compose the plan of a candidate's next round, once its work exists."""

    def __call__(self, *, work: AgentWork) -> RoundPlan:
        """Return the plan of the work's next round."""


@dataclass(frozen=True, kw_only=True)
class Candidate:
    """Open work the tick may start a round for, or a request it may start work for.

    The work is the open work, or the route of the work that a request would
    create. The row is the request's row, which the tick marks with the round
    it starts.
    """

    row: RequestRow
    work: AgentWork | DispatchRoute
    compose_round: RoundComposer


@dataclass(frozen=True, kw_only=True)
class Inspection:
    """Hold the row the tick writes for one request, and what it may start for it.

    A fault counts towards a global cooldown.
    """

    row: RequestRow
    candidate: Candidate | None = None
    is_fault: bool = False


def compose_agent_work_row(
    *, work: AgentWork, finding: RequestFinding | None
) -> RequestRow:
    """Return the row of the request that led to open work, with what the tick found."""
    record = work.record
    return RequestRow(
        issue=record.issue,
        title=record.title,
        dispatch_label=record.dispatch_label,
        kind=record.kind,
        agent_work_identifier=work.identifier,
        finding=finding,
    )
