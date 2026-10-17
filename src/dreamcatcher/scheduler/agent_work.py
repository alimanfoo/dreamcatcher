"""Define the shared shape of assignment and conversation schedulers."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from dreamcatcher.agent_rounds import (
    AgentRound,
    AgentRoundFinisher,
    AgentRoundStartRequest,
    start_agent_round,
)
from dreamcatcher.agent_work import (
    AgentWork,
    record_harness_session_identifier,
    request_round_stop_if_ended,
)
from dreamcatcher.config import AgentHarness, DispatchRoute, DreamcatcherConfig
from dreamcatcher.documents import DreamcatcherDocument
from dreamcatcher.github import Issue, UnknownGitHubResponse, list_issues
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    HarnessSessionIdentifier,
)
from dreamcatcher.prompts import compose_round_prompt
from dreamcatcher.scheduler.models import (
    AgentWorkInspection,
    RequestFinding,
    RequestRow,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory


@dataclass(frozen=True, kw_only=True)
class RouteIssueListing:
    """Collect the issues found through routes and any listing failures."""

    issues: list[Issue]
    failures: list[str]


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
        agent_work=work.identifier,
        finding=finding,
    )


@dataclass(frozen=True, kw_only=True)
class AgentWorkScheduler[CandidateT, ObservationT, RankT](ABC):
    """Hold the facts that every kind of agent work needs for scheduling."""

    repository: str
    account: str
    config: DreamcatcherConfig
    state: StateDirectory
    preferred_harness: AgentHarness
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

    def start_round(
        self,
        *,
        work: AgentWork,
        harness_session_identifier: HarnessSessionIdentifier | None,
        prepare_round: Callable[[], DreamcatcherDocument | None],
        input_prompt: str | None,
        finish_round: AgentRoundFinisher | None,
    ) -> AgentRound:
        """Start the work's next round, resuming the harness session when given one.

        The round runs the preparation step before its harness. A round whose
        work has ended by the time it starts is asked to stop.
        """
        if harness_session_identifier is not None:
            record_harness_session_identifier(
                work=work, identifier=harness_session_identifier
            )
        paths = work.compose_round_paths(number=work.next_round_number)
        started_round = start_agent_round(
            request=AgentRoundStartRequest(
                harness=work.record.harness,
                launch_request=AgentRoundLaunchRequest(
                    agent_work_identifier=work.identifier,
                    model=work.record.model,
                    effort=work.record.effort,
                    harness_config=work.record.harness_config,
                    prompt=compose_round_prompt(
                        instructions=work.record.prompt,
                        is_resuming=harness_session_identifier is not None,
                        input_prompt=input_prompt,
                        previous_outcome=(
                            work.rounds[-1].outcome if work.rounds else None
                        ),
                    ),
                    work_kind=work.record.kind,
                ),
                harness_session_identifier=harness_session_identifier,
                record_harness_session_identifier=partial(
                    record_harness_session_identifier, work=work
                ),
                finish_round=finish_round,
                paths=paths,
                prepare_round=prepare_round,
            ),
            clock=self.clock,
        )
        request_round_stop_if_ended(work=work, paths=paths)
        return started_round

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
