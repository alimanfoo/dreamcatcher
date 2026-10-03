"""Define the shared shape of assignment and conversation schedulers."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from dreamcatcher.agent_rounds import AgentRound
from dreamcatcher.config import AgentHarness, DispatchRoute, DreamcatcherConfig
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Issue, UnknownGitHubResponse, list_issues
from dreamcatcher.scheduler.models import (
    AgentWorkInspection,
    SchedulerRecord,
    combine_scheduler_failures,
)
from dreamcatcher.state import StateDirectory


class LaunchedAgentRoundError(ReportableError):
    """Report a failure that happened after an agent round started."""

    def __init__(self, *, agent_round: AgentRound, failure: ReportableError) -> None:
        """Keep the started round so that the scheduler can register it."""
        super().__init__(str(failure))
        self.agent_round = agent_round


@dataclass(frozen=True, kw_only=True)
class RouteIssueListing:
    """Collect the issues found through routes and any listing failures."""

    issues: list[Issue]
    failure: str | None


@dataclass(frozen=True, kw_only=True)
class AgentWorkScheduler[CandidateT, ObservationT, RankT, LaunchRequestT](ABC):
    """Hold the facts that every kind of agent work needs for scheduling."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    requested_harness: AgentHarness
    clock: Callable[[], datetime]

    @abstractmethod
    def inspect(
        self, *, previous_record: SchedulerRecord | None, at: datetime
    ) -> AgentWorkInspection[CandidateT, ObservationT]:
        """Inspect this kind of agent work."""

    @abstractmethod
    def rank(self, candidate: CandidateT, /) -> RankT:
        """Return this kind's rank for one candidate."""

    @abstractmethod
    def launch(self, *, request: LaunchRequestT) -> object:
        """Launch one candidate for this kind of agent work."""

    def list_route_issues(
        self, *, routes: Sequence[DispatchRoute]
    ) -> RouteIssueListing:
        """List and merge the issues found through configured routes."""
        issues_by_number: dict[int, Issue] = {}
        failures: list[str | None] = []
        for route in routes:
            issue_response = list_issues(
                repository=self.repository,
                label=route.label,
                assignee=self.account,
            )
            if isinstance(issue_response, UnknownGitHubResponse):
                failures.append(
                    f"could not list issues for {route.label}: {issue_response.reason}"
                )
            else:
                issues_by_number.update(
                    (issue.number, issue) for issue in issue_response
                )
        return RouteIssueListing(
            issues=sorted(
                issues_by_number.values(),
                key=lambda issue: (issue.created_at, issue.number),
            ),
            failure=combine_scheduler_failures(failures=failures),
        )
