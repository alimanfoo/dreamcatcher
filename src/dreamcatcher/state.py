"""Where dreamcatcher keeps its own files, and what those files hold."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cached_property
from pathlib import Path

from pydantic import Field

from dreamcatcher.agent_rounds import AgentRoundReader
from dreamcatcher.documents import Document, write_text

STATE_DIRECTORY = ".dreamcatcher"


class IssueFactValue(StrEnum):
    """A known true or false issue fact, or one that could not be observed."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class IssueFact(Document):
    """One independently observed issue fact and its diagnostic evidence."""

    value: IssueFactValue
    evidence: str | None = None


class IssueObservation(Document):
    """The independent facts that one scheduler tick observed about an issue."""

    issue: int
    created_at: datetime | None = None
    is_open: IssueFact
    is_assigned_to_user: IssueFact
    dispatch_labels: list[str] | None = None
    claimed_here: IssueFact
    claimed_elsewhere: IssueFact
    blocked: IssueFact
    routing_conflict: IssueFact


class WaitingAgentAssignment(Document):
    """An assignment with no round running, waiting for the round that would
    carry it on.

    The reason is a string that says what the assignment is waiting on, in the
    words the tick found it in. Where the last round did not complete, the
    reason carries the status it ended with, so a run of usage-limit failures
    is recognisable from this reason string. An assignment is also waiting when the
    tick found it a round and had no slot to launch it, when no round has run
    yet, and when a read of GitHub could not tell.

    A wait marked stuck requires a person to clear it. Every other wait can
    clear on a later tick.
    """

    assignment: str
    issue: int
    reason: str
    is_stuck: bool = False


# What an assignment that has run no round at all is waiting on. Its complete
# setup stays ready for the scheduler to retry its first round before ordinary
# scheduling continues. Both the tick that writes a wait and the board that
# reads one say this, so a reader hears it the one way.
NO_ROUND_HAS_RUN = "no round has run yet"


class LastTick(Document):
    """What the daemon's most recent tick observed and decided.

    The record carries the tick's own time rather than taking it from the file,
    so copying a state directory cannot make a stale tick look fresh.

    A tick launches at most one round, and its assignment identifier is what the
    tick launched. A tick that launched nothing at all says in one line what
    held it. A tick that was held at the cap still observed the relevant issues,
    and the cap is what it writes down against every assignment it is holding.

    The issue observations preserve each independent fact for later reporting.
    Their order is the order in which available issues would be dispatched.
    """

    at: datetime
    hold: str | None = None
    launched: str | None = None
    issue_observations: list[IssueObservation] = Field(default_factory=list)
    waiting: list[WaitingAgentAssignment] = Field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class StateDirectory:
    """The directory holding everything dreamcatcher knows about one repo.

    One of these is what a process reads the directory through, so it also
    holds what that process has read and need not read again.
    """

    root: Path

    @cached_property
    def round_reader(self) -> AgentRoundReader:
        """What this process has read of the round records under here.

        Reading an assignment reads the records of every round it has run, and a
        reader keeps the complete ones, so a later read of that assignment opens
        only the records that are still incomplete.

        Whoever holds the directory holds them, and holds them for as long:
        the daemon holds one for its whole run, a view holds one for as long as
        it runs, and a process that looks once lets both go together.
        """
        return AgentRoundReader()

    @property
    def path(self) -> Path:
        """The directory itself."""
        return self.root / STATE_DIRECTORY

    @property
    def lock(self) -> Path:
        """The file the running daemon writes its pid to."""
        return self.path / "daemon.pid"

    @property
    def last_tick(self) -> Path:
        """The file the daemon overwrites with what each tick decided."""
        return self.path / "last-tick.json"

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
        """Return the path as it reads from the checkout, for a reader to open.

        The one way of writing it on every platform, so what a reader is told
        to open reads the same wherever they are.

        A path the checkout does not hold reads whole. The dispatch writes the
        checkout's own path into the assignment's record, and a reader can be
        standing in that same checkout under another name, a symlink's for
        instance, so the two do not always meet.
        """
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
        return path.as_posix()

    def bootstrap(self) -> None:
        """Create the directory, ignoring itself, so git never sees its files.

        Writing the .gitignore is what creates the directory. Bootstrap writes
        it on every run, so a directory that was deleted comes back.
        """
        write_text(text="*\n", path=self.path / ".gitignore")
