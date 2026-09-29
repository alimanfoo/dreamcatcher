"""Write the records a state directory holds, as the daemon would have left them.

A test that starts from a state directory already holding assignments and rounds
writes them here, rather than dispatching them. So it reaches the state it is
about without a GitHub, an origin to cut from, or a harness to run.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dreamcatcher import agent_assignments, agent_rounds, issue_conversations
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.scheduler import SchedulerRecord
from dreamcatcher.state import StateDirectory


@dataclass(frozen=True, kw_only=True)
class AssignmentReporting:
    """Provide the optional reporting facts for a fabricated assignment."""

    title: str
    pull_request_observation: agent_assignments.PullRequestObservation


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
            interval_seconds=DEFAULT_INTERVAL_SECONDS,
        ),
        path=state.daemon_run_record,
    )


def write_agent_assignment(
    *,
    state: StateDirectory,
    identifier: str,
    issue: int,
    harness_session_identifier: str | None = "abc-123",
    reporting: AssignmentReporting | None = None,
) -> Path:
    """Write an assignment's worktree and its record, and return its own directory."""
    (state.worktrees / identifier).mkdir(parents=True)
    directory = state.assignments / identifier
    write_json(
        document=agent_assignments.AgentAssignmentRecord(
            issue=issue,
            title=None if reporting is None else reporting.title,
            dispatch_label="dream:smith",
            branch=f"{agent_assignments.AGENT_ASSIGNMENT_BRANCH_PREFIX}{identifier}",
            worktree=state.worktrees / identifier,
            pull_request=52,
            pull_request_observation=(
                None if reporting is None else reporting.pull_request_observation
            ),
            harness=AgentHarness.CLAUDE,
            harness_session_identifier=harness_session_identifier,
            model="opus[1m]",
            effort="xhigh",
            prompt=f"/dream:smith GH{issue}",
        ),
        path=directory / agent_assignments.AGENT_ASSIGNMENT_RECORD_NAME,
    )
    return directory


def write_issue_conversation(
    *,
    state: StateDirectory,
    issue: int,
    harness_session_identifier: str | None = "conversation-session",
) -> Path:
    """Write a conversation worktree and record, and return its directory."""
    worktree = state.conversation_worktrees / f"GH{issue}"
    worktree.mkdir(parents=True)
    directory = state.conversations / f"GH{issue}"
    write_json(
        document=issue_conversations.IssueConversationRecord(
            issue=issue,
            title=f"Issue {issue}",
            label="dream:conversation",
            harness=AgentHarness.CLAUDE,
            harness_session_identifier=harness_session_identifier,
            model="opus[1m]",
            effort="xhigh",
            prompt=f"/dream:conversation GH{issue}",
        ),
        path=directory / issue_conversations.ISSUE_CONVERSATION_RECORD_NAME,
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


def write_running_conversation(
    *, state: StateDirectory, issue: int, started: datetime
) -> None:
    """Write a conversation whose first round has started and not ended.

    The round reads as running only while the state's lock names a live daemon.
    """
    directory = write_issue_conversation(state=state, issue=issue)
    write_round(
        directory=directory,
        number=1,
        record=agent_rounds.AgentRoundRecord(
            number=1,
            purpose=agent_rounds.IssueConversationRoundPurpose.DISCUSS,
            started=started,
            pid=1,
        ),
    )
    write_json(
        document=issue_conversations.IssueConversationInput(
            issue=issue,
            title=f"Issue {issue}",
            body="Explain it.",
            comments=[
                {
                    "id": 1,
                    "body": "Please explain.",
                    "author": "alice",
                    "written_at": "2026-09-23T01:00:00Z",
                }
            ],
            revision="abc123",
        ),
        path=_round_paths(directory=directory, number=1).round_input,
    )


def write_final_output(*, directory: Path, number: int, text: str) -> None:
    """Write the final output that one round of the work at this directory reported."""
    write_text(
        text=text, path=_round_paths(directory=directory, number=number).final_output
    )
