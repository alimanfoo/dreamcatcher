"""Define the paths and shared readers for Dreamcatcher's local state."""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from dreamcatcher.agent_rounds import AgentRoundReader
from dreamcatcher.documents import write_text

STATE_DIRECTORY_NAME = ".dreamcatcher"


@dataclass(frozen=True, kw_only=True)
class StateDirectory:
    """Represent Dreamcatcher's local state for one repository.

    One of these is what a process reads the directory through, so it also
    holds what that process has read and need not read again.
    """

    root: Path

    @cached_property
    def round_reader(self) -> AgentRoundReader:
        """The round-record reader shared by this process.

        Reading an assignment reads the records of every round it has run, and a
        reader keeps the complete ones, so a later read of that assignment opens
        only the records that are still incomplete.

        The reader and its cache live as long as this StateDirectory instance.
        """
        return AgentRoundReader()

    @property
    def path(self) -> Path:
        """The directory itself."""
        return self.root / STATE_DIRECTORY_NAME

    @property
    def lock(self) -> Path:
        """The file the running daemon writes its pid to."""
        return self.path / "daemon.pid"

    @property
    def repository(self) -> Path:
        """The file that names the repository this instance watches."""
        return self.path / "repository"

    @property
    def max_agents(self) -> Path:
        """The file that records the most recent daemon run's agent cap."""
        return self.path / "max-agents"

    @property
    def scheduler_record(self) -> Path:
        """The file the daemon overwrites with what the scheduler observed."""
        return self.path / "scheduler.json"

    @property
    def worktrees(self) -> Path:
        """The directory holding each assignment worktree by identifier.

        Every worktree that dreamcatcher makes lives under here, wherever the
        checkout would otherwise put its worktrees. A worktree under here is
        therefore one of dreamcatcher's, and that is how the daemon tells its
        own work from everyone else's.
        """
        return self.path / "worktrees"

    @property
    def assignments(self) -> Path:
        """The directory holding each assignment's files by identifier."""
        return self.path / "assignments"

    def describe_path(self, *, path: Path) -> str:
        """Return a portable path relative to the checkout when possible."""
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
        return path.as_posix()

    def bootstrap(self) -> None:
        """Create the state directory and make Git ignore its contents.

        Writing the .gitignore is what creates the directory. Bootstrap writes
        it on every run, so a directory that was deleted comes back.
        """
        write_text(text="*\n", path=self.path / ".gitignore")
