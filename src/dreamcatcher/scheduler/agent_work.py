"""Define the shared shape of assignment and conversation schedulers."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from dreamcatcher.agent_rounds import AgentRound
from dreamcatcher.config import AgentHarness, DreamcatcherConfig
from dreamcatcher.errors import ReportableError
from dreamcatcher.state import StateDirectory


class LaunchedAgentRoundError(ReportableError):
    """Report a failure that happened after an agent round started."""

    def __init__(self, *, agent_round: AgentRound, failure: ReportableError) -> None:
        """Keep the started round so that the scheduler can register it."""
        super().__init__(str(failure))
        self.agent_round = agent_round


@dataclass(frozen=True, kw_only=True)
class AgentWorkScheduler[CandidateT, RankT, InspectionRequestT, LaunchRequestT](ABC):
    """Hold the facts that every kind of agent work needs for scheduling."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    requested_harness: AgentHarness
    clock: Callable[[], datetime]

    @abstractmethod
    def inspect(self, *, request: InspectionRequestT) -> object:
        """Inspect this kind of agent work."""

    @abstractmethod
    def rank(self, candidate: CandidateT, /) -> RankT:
        """Return this kind's rank for one candidate."""

    @abstractmethod
    def launch(self, *, request: LaunchRequestT) -> object:
        """Launch one candidate for this kind of agent work."""
