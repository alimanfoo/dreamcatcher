"""Write the records a state directory holds, as the daemon would have left them.

A test that starts from a state directory already holding sessions and rounds
writes them here, rather than dispatching them. So it reaches the state it is
about without a GitHub, an origin to cut from, or a harness to run.
"""

from pathlib import Path

from dreamcatcher import rounds, sessions
from dreamcatcher.config import Harness
from dreamcatcher.documents import write_json
from dreamcatcher.state import StateDirectory


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
    write_json(record, directory / sessions.ROUNDS / str(number) / rounds.RECORD)
    return record
