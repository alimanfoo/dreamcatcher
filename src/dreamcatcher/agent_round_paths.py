"""Name every path owned by one numbered agent round."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import PositiveInt

AGENT_ROUND_RECORD_NAME = "round.json"


@dataclass(frozen=True, kw_only=True)
class AgentRoundPaths:
    """Provide the worktree and file paths for a numbered round.

    The round runs in its owner's worktree and writes into the directory its
    number selects under that owner's rounds directory. Keeping the
    number beside that parent makes one value authoritative for both the path
    and the record the round writes.

    The paths are available before the round creates any files.
    """

    worktree: Path
    rounds_directory: Path
    number: PositiveInt

    @property
    def directory(self) -> Path:
        """The directory holding this numbered round's files."""
        return self.rounds_directory / str(self.number)

    @property
    def prompt(self) -> Path:
        """The file holding what the round asked the harness to do."""
        return self.directory / "prompt.txt"

    @property
    def record(self) -> Path:
        """The file saying when the round started, and how it ended."""
        return self.directory / AGENT_ROUND_RECORD_NAME

    @property
    def feed(self) -> Path:
        """The file holding the round as a reader reads it."""
        return self.directory / "feed.txt"

    @property
    def raw_output(self) -> Path:
        """The file holding the harness's own stdout, as it arrived."""
        return self.directory / "raw.jsonl"

    @property
    def round_input(self) -> Path:
        """The file holding the input that the round's owner delivered."""
        return self.directory / "inbox.json"

    @property
    def stop_request(self) -> Path:
        """The file asking this round to stop, when one has been requested."""
        return self.directory / "stop-request"

    @property
    def final_output(self) -> Path:
        """The file holding the final result that the harness reports, if any."""
        return self.directory / "final.md"
