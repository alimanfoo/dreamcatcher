"""Write the records a state directory holds, as the daemon would have left them.

A test that starts from a state directory already holding assignments and rounds
writes them here, rather than dispatching them. So it reaches the state it is
about without a GitHub, an origin to cut from, or a harness to run.
"""

from collections.abc import Sequence
from pathlib import Path

from dreamcatcher import agent_assignments, agent_rounds
from dreamcatcher.config import Harness
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.feed import Line
from dreamcatcher.state import LastTick, StateDirectory


def write_agent_assignment(
    *, state: StateDirectory, identifier: str, issue: int
) -> Path:
    """Write an assignment's worktree and its record, and return its own directory."""
    (state.worktrees / identifier).mkdir(parents=True)
    directory = state.assignments / identifier
    write_json(
        document=agent_assignments.AgentAssignmentRecord(
            issue=issue,
            label="dream:smith",
            branch=f"{agent_assignments.BRANCH_PREFIX}{identifier}",
            worktree=state.worktrees / identifier,
            pull_request=52,
            harness=Harness.CLAUDE,
            model="opus[1m]",
            effort="xhigh",
            prompt=f"/dream:smith GH{issue}",
        ),
        path=directory / agent_assignments.RECORD,
    )
    return directory


def write_round(
    *, directory: Path, number: int, record: agent_rounds.AgentRoundRecord
) -> agent_rounds.AgentRoundRecord:
    """Write the record of one round of the assignment at this directory."""
    write_json(
        document=record, path=_workspace(directory=directory, number=number).record
    )
    return record


def write_feed(*, directory: Path, number: int, lines: Sequence[Line]) -> None:
    """Write the feed of one round of the assignment at this directory."""
    write_text(
        text="".join(line.render() for line in lines),
        path=_workspace(directory=directory, number=number).feed,
    )


def write_tick(*, state: StateDirectory, tick: LastTick) -> None:
    """Write what the daemon's most recent tick saw."""
    write_json(document=tick, path=state.last_tick)


def _workspace(*, directory: Path, number: int) -> agent_rounds.AgentRoundPaths:
    """Where the numbered round of the assignment at this directory wrote."""
    return agent_rounds.AgentRoundPaths(
        worktree=directory,
        directory=directory / agent_assignments.ROUNDS / str(number),
    )
