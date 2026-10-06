"""Define the paths and the shared document cache for dreamcatcher's local state."""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from dreamcatcher.documents import DocumentCache, write_text

_STATE_DIRECTORY_NAME = ".dreamcatcher"
STATE_FORMAT_VERSION = 5


@dataclass(frozen=True, kw_only=True)
class StateDirectory:
    """Represent dreamcatcher's local state for one repository.

    One of these is what a process reads the directory through, so it also
    holds what that process has read and need not read again.
    """

    root: Path

    @cached_property
    def document_cache(self) -> DocumentCache:
        """The documents read from the directory that nothing writes again.

        A process reads the same records again and again, so keeping the ones
        that cannot change means that each later read opens only the records
        that can. The cache lives as long as this StateDirectory instance.
        """
        return DocumentCache()

    @property
    def path(self) -> Path:
        """The directory holding state in this format."""
        return self.root / _STATE_DIRECTORY_NAME / f"v{STATE_FORMAT_VERSION}"

    @property
    def lock(self) -> Path:
        """The file that the running daemon holds locked."""
        return self.path.parent / "daemon.lock"

    @property
    def repository(self) -> Path:
        """The file that names the repository this instance watches."""
        return self.path / "repository"

    @property
    def daemon_run_record(self) -> Path:
        """The document describing the most recent daemon run."""
        return self.path / "daemon.json"

    @property
    def scheduler_record(self) -> Path:
        """The file the daemon overwrites with what the scheduler observed."""
        return self.path / "scheduler.json"

    @property
    def assignment_worktrees(self) -> Path:
        """The directory holding each assignment worktree by identifier."""
        return self.path / "worktrees"

    @property
    def assignments(self) -> Path:
        """The directory holding each assignment's files by identifier."""
        return self.path / "assignments"

    @property
    def conversation_worktrees(self) -> Path:
        """The directory holding detached issue-conversation worktrees."""
        return self.path / "conversation-worktrees"

    @property
    def conversations(self) -> Path:
        """The directory holding issue conversations by issue identifier."""
        return self.path / "conversations"

    def describe_path(self, *, path: Path) -> str:
        """Return a portable path relative to the checkout when possible."""
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
        return path.as_posix()

    def bootstrap(self) -> None:
        """Make Git ignore everything under `.dreamcatcher/`.

        Bootstrap writes the .gitignore on every daemon run, so one that was deleted
        comes back.
        """
        write_text(text="*\n", path=self.path.parent / ".gitignore")
