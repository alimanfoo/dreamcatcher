"""Define the shared shape of assignment and conversation schedulers."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from dreamcatcher.agent_rounds import AgentRound
from dreamcatcher.config import AgentHarness, DispatchRoute, DreamcatcherConfig
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import Issue, UnknownGitHubResponse, list_issues
from dreamcatcher.harness_adapters import HarnessSessionIdentifier
from dreamcatcher.scheduler.models import AgentWorkInspection, SchedulerRecord
from dreamcatcher.state import StateDirectory


@dataclass(frozen=True, kw_only=True)
class RouteIssueListing:
    """Collect the issues found through routes and any listing failures."""

    issues: list[Issue]
    failures: list[str]


@dataclass(frozen=True, kw_only=True)
class HarnessSessionResumption:
    """Hold the session and prompt with which to start a round."""

    identifier: HarnessSessionIdentifier | None
    prompt: str


@dataclass(frozen=True, kw_only=True)
class AgentWorkScheduler[CandidateT, ObservationT, RankT](ABC):
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
    def launch(self, *, candidate: CandidateT, at: datetime) -> AgentRound:
        """Launch one candidate for this kind of agent work."""

    def resolve_harness_session(
        self,
        *,
        agent_work_identifier: str,
        has_rounds: bool,
        harness_session_identifier: HarnessSessionIdentifier | None,
        is_recovery: bool,
        prompt: str,
        replacement_session_prompt: str,
    ) -> HarnessSessionResumption:
        """Choose whether to resume a session or begin a replacement."""
        if not has_rounds:
            return HarnessSessionResumption(identifier=None, prompt=prompt)
        if harness_session_identifier is not None:
            return HarnessSessionResumption(
                identifier=harness_session_identifier,
                prompt=prompt,
            )
        if not is_recovery:
            raise ReportableError(
                f"Could not resume {agent_work_identifier}: its first round did not "
                "report a harness session identifier."
            )
        return HarnessSessionResumption(
            identifier=None,
            prompt=replacement_session_prompt,
        )

    def list_route_issues(
        self, *, routes: Sequence[DispatchRoute]
    ) -> RouteIssueListing:
        """List and merge the issues found through configured routes."""
        issues_by_number: dict[int, Issue] = {}
        failures: list[str] = []
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
            failures=failures,
        )
