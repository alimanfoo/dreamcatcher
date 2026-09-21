"""Write the records a state directory holds, as the daemon would have left them.

A test that starts from a state directory already holding assignments and rounds
writes them here, rather than dispatching them. So it reaches the state it is
about without a GitHub, an origin to cut from, or a harness to run.
"""

from collections.abc import Sequence
from pathlib import Path

from dreamcatcher import agent_assignments, agent_rounds
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.scheduler import SchedulerRecord
from dreamcatcher.state import StateDirectory


def write_daemon_run(
    *,
    state: StateDirectory,
    pid: int,
    harness: AgentHarness = AgentHarness.CLAUDE,
    version: str = "3.0.0.beta1",
    max_agents: int = 1,
) -> None:
    """Write the facts fixed for one daemon run."""
    write_json(
        document=DaemonRunRecord(
            pid=pid,
            harness=harness,
            version=version,
            max_agents=max_agents,
        ),
        path=state.daemon_run_record,
    )


def write_agent_assignment(
    *,
    state: StateDirectory,
    identifier: str,
    issue: int,
    harness_session_identifier: str | None = "abc-123",
) -> Path:
    """Write an assignment's worktree and its record, and return its own directory."""
    (state.worktrees / identifier).mkdir(parents=True)
    directory = state.assignments / identifier
    write_json(
        document=agent_assignments.AgentAssignmentRecord(
            issue=issue,
            dispatch_label="dream:smith",
            branch=f"{agent_assignments.AGENT_ASSIGNMENT_BRANCH_PREFIX}{identifier}",
            worktree=state.worktrees / identifier,
            pull_request=52,
            harness=AgentHarness.CLAUDE,
            harness_session_identifier=harness_session_identifier,
            model="opus[1m]",
            effort="xhigh",
            prompt=f"/dream:smith GH{issue}",
        ),
        path=directory / agent_assignments.AGENT_ASSIGNMENT_RECORD_NAME,
    )
    return directory


def write_round(
    *, directory: Path, number: int, record: agent_rounds.AgentRoundRecord
) -> agent_rounds.AgentRoundRecord:
    """Write the record of one round of the assignment at this directory."""
    write_json(
        document=record, path=_round_paths(directory=directory, number=number).record
    )
    return record


def write_feed(*, directory: Path, number: int, lines: Sequence[FeedLine]) -> None:
    """Write the feed of one round of the assignment at this directory."""
    write_text(
        text="".join(line.render() for line in lines),
        path=_round_paths(directory=directory, number=number).feed,
    )


def write_tick(*, state: StateDirectory, tick: SchedulerRecord) -> None:
    """Write what the daemon's most recent tick saw."""
    write_json(document=tick, path=state.scheduler_record)


def _round_paths(*, directory: Path, number: int) -> agent_rounds.AgentRoundPaths:
    """Where the numbered round of the assignment at this directory wrote."""
    return agent_rounds.AgentRoundPaths(
        worktree=directory,
        rounds_directory=directory / agent_assignments.AGENT_ROUNDS_DIRECTORY_NAME,
        number=number,
    )
