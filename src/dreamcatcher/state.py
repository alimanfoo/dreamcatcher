"""Define the paths and the shared document cache for Dreamcatcher's local state."""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from dreamcatcher.documents import DocumentCache, write_text

STATE_DIRECTORY_NAME = ".dreamcatcher"
STATE_FORMAT_VERSION = 5


@dataclass(frozen=True, kw_only=True)
class StateDirectory:
    """Represent Dreamcatcher's local state for one repository.

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
        return self.root / STATE_DIRECTORY_NAME / f"v{STATE_FORMAT_VERSION}"

    @property
    def lock(self) -> Path:
        """The document that identifies the process holding the daemon lock."""
        return self.path.parent / "daemon.pid"

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
        """Create the state directory and make Git ignore its contents.

        Writing the .gitignore is what creates the directory. Bootstrap writes
        it on every run, so a directory that was deleted comes back.
        """
        write_text(text="*\n", path=self.path.parent / ".gitignore")
