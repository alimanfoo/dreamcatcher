"""Write the records a state directory holds, as the daemon would have left them.

A test that starts from a state directory already holding assignments and rounds
writes them here, rather than creating them through the scheduler. So it reaches
the state it is about without a GitHub, an origin to cut from, or a harness to run.
"""

from collections.abc import Sequence
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

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
from dreamcatcher.lock import hold_daemon_lock
from dreamcatcher.scheduler.models import SchedulerRecord
from dreamcatcher.state import StateDirectory

# The daemon locks that the running test holds, by path.
_HELD_DAEMON_LOCKS: dict[Path, ExitStack] = {}

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


def hold_daemon_lock_for_test(*, path: Path) -> None:
    """Hold the daemon lock, as a running daemon would, until the test ends."""
    held = ExitStack()
    held.enter_context(hold_daemon_lock(path=path))
    _HELD_DAEMON_LOCKS[path] = held


def release_daemon_lock(*, path: Path) -> None:
    """Release a lock that the test holds, as a daemon that dies would."""
    _HELD_DAEMON_LOCKS.pop(path).close()


def release_daemon_locks() -> None:
    """Release every lock that the test still holds."""
    while _HELD_DAEMON_LOCKS:
        _, held = _HELD_DAEMON_LOCKS.popitem()
        held.close()


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
    (state.assignment_worktrees / identifier).mkdir(parents=True)
    directory = state.assignments / identifier
    write_json(
        document=agent_assignments.AssignmentRecord(
            issue=issue,
            title=f"Issue {issue}" if title is None else title,
            dispatch_label="dream:smith",
            branch=f"{agent_assignments._ASSIGNMENT_BRANCH_PREFIX}{identifier}",
            worktree=state.assignment_worktrees / identifier,
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
        document=issue_conversations.ConversationRoundInput(
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
