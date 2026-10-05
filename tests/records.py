"""Write the records a state directory holds, as the daemon would have left them.

A test that starts from a state directory already holding assignments and rounds
writes them here, rather than creating them through the scheduler. So it reaches
the state it is about without a GitHub, an origin to cut from, or a harness to run.
"""

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import psutil
from clocks import PINNED

from dreamcatcher import (
    agent_assignments,
    agent_rounds,
    agent_work,
    issue_conversations,
)
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.github import PullRequestState
from dreamcatcher.lock import DaemonLockRecord
from dreamcatcher.scheduler.models import SchedulerRecord
from dreamcatcher.state import StateDirectory

# What a fabricated assignment saw of its pull request, unless a test says.
_OPEN_DRAFT = agent_assignments.PullRequestObservation(
    state=PullRequestState.OPEN, is_draft=True, observed_at=PINNED
)


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


def write_daemon_lock(
    *,
    path: Path,
    pid: int | None = None,
    process_started_at: datetime | None = None,
) -> None:
    """Write the identity of the process that holds the daemon lock."""
    lock_pid = os.getpid() if pid is None else pid
    lock_process_started_at = (
        datetime.fromtimestamp(psutil.Process(lock_pid).create_time(), tz=UTC)
        if process_started_at is None
        else process_started_at
    )
    write_json(
        document=DaemonLockRecord(
            pid=lock_pid,
            process_started_at=lock_process_started_at,
        ),
        path=path,
    )


def write_assignment(
    *,
    state: StateDirectory,
    identifier: str,
    issue: int,
    harness_session_identifier: str | None = "abc-123",
    title: str | None = None,
    pull_request_observation: agent_assignments.PullRequestObservation = _OPEN_DRAFT,
) -> Path:
    """Write an assignment's worktree and its records, and return its own directory.

    The title is `Issue <n>` unless the test gives one.
    """
    (state.worktrees / identifier).mkdir(parents=True)
    directory = state.assignments / identifier
    write_json(
        document=agent_assignments.AssignmentRecord(
            issue=issue,
            title=f"Issue {issue}" if title is None else title,
            dispatch_label="dream:smith",
            branch=f"{agent_assignments._ASSIGNMENT_BRANCH_PREFIX}{identifier}",
            worktree=state.worktrees / identifier,
            pull_request=52,
            harness=AgentHarness.CLAUDE,
            model="opus[1m]",
            effort="xhigh",
            prompt=f"/dream:smith GH{issue}",
        ),
        path=directory / agent_assignments._ASSIGNMENT_RECORD_NAME,
    )
    write_json(
        document=pull_request_observation,
        path=directory / agent_assignments._PULL_REQUEST_OBSERVATION_RECORD_NAME,
    )
    _write_harness_session(directory=directory, identifier=harness_session_identifier)
    return directory


def write_conversation(
    *,
    state: StateDirectory,
    issue: int,
    harness: AgentHarness = AgentHarness.CLAUDE,
    harness_session_identifier: str | None = "conversation-session",
) -> Path:
    """Write a conversation worktree and record, and return its directory."""
    worktree = state.conversation_worktrees / f"GH{issue}"
    worktree.mkdir(parents=True)
    directory = state.conversations / f"GH{issue}"
    write_json(
        document=issue_conversations.ConversationRecord(
            issue=issue,
            title=f"Issue {issue}",
            dispatch_label="dream:conversation",
            harness=harness,
            model="opus[1m]",
            effort="xhigh",
            prompt=f"/dream:conversation GH{issue}",
        ),
        path=directory / issue_conversations._CONVERSATION_RECORD_NAME,
    )
    _write_harness_session(directory=directory, identifier=harness_session_identifier)
    return directory


def _write_harness_session(*, directory: Path, identifier: str | None) -> None:
    """Write the harness session of the work at this directory, when it has one."""
    if identifier is not None:
        write_json(
            document=agent_work._HarnessSessionRecord(identifier=identifier),
            path=directory / agent_work._HARNESS_SESSION_RECORD_NAME,
        )


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
        rounds_directory=directory / agent_assignments._AGENT_ROUNDS_DIRECTORY_NAME,
        number=number,
    )


def write_running_conversation(
    *, state: StateDirectory, issue: int, started: datetime
) -> None:
    """Write a conversation whose first round has started and not ended.

    The round reads as running only while the state's lock names a live daemon.
    """
    directory = write_conversation(state=state, issue=issue)
    write_round(
        directory=directory,
        number=1,
        record=agent_rounds.AgentRoundRecord(
            number=1,
            purpose=agent_rounds.ConversationRoundPurpose.DISCUSS,
            started=started,
            pid=1,
        ),
    )
    write_json(
        document=issue_conversations.ConversationInput(
            issue=issue,
            initial_issue=issue_conversations.InitialConversationIssue(
                title=f"Issue {issue}",
                body="Explain it.",
            ),
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
