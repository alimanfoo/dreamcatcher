"""Write the records a state directory holds, as the daemon would have left them.

A test that starts from a state directory already holding sessions and rounds
writes them here, rather than dispatching them. So it reaches the state it is
about without a GitHub, an origin to cut from, or a harness to run.
"""

from pathlib import Path

from dreamcatcher import rounds, sessions
from dreamcatcher.config import Harness
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.feed import Line
from dreamcatcher.state import LastTick, StateDirectory


def write_session(state: StateDirectory, key: str, issue: int) -> Path:
    """Write a session's worktree and its record, and return its own directory."""
    (state.worktrees / key).mkdir(parents=True)
    directory = state.sessions / key
    write_json(
        sessions.SessionRecord(
            issue=issue,
            label="dream:smith",
            branch=f"{sessions.BRANCH_PREFIX}{key}",
            worktree=state.worktrees / key,
            harness=Harness.CLAUDE,
            model="opus[1m]",
            effort="xhigh",
            prompt=f"/dream:smith GH{issue}",
        ),
        directory / sessions.RECORD,
    )
    return directory


def write_round(
    directory: Path, number: int, record: rounds.RoundRecord
) -> rounds.RoundRecord:
    """Write the record of one round of the session at this directory."""
    write_json(record, _workspace(directory, number).record)
    return record


def write_feed(directory: Path, number: int, *lines: Line) -> None:
    """Write the feed of one round of the session at this directory."""
    write_text(
        "".join(line.render() for line in lines), _workspace(directory, number).feed
    )


def write_tick(state: StateDirectory, tick: LastTick) -> None:
    """Write what the daemon's most recent tick saw."""
    write_json(tick, state.last_tick)


def _workspace(directory: Path, number: int) -> rounds.Workspace:
    """Where the numbered round of the session at this directory wrote."""
    return rounds.Workspace(directory, directory / sessions.ROUNDS / str(number))
