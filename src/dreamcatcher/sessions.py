"""Create a session for an issue, and read back the ones a repo already has.

A session is what one dispatch of an issue makes. It gets a key of its own: the
issue's number, and the time the session started. That key names its branch, its
worktree, and the directory that holds its own files. So three worktrees for one
issue read as three sessions at one thing, each with its own pull request.

Nothing here decides which issue to dispatch, or when. A caller that has decided
asks for the session.
"""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dreamcatcher import prompts
from dreamcatcher.commands import CommandError
from dreamcatcher.config import DispatchMapping, Harness
from dreamcatcher.documents import (
    Document,
    read_json,
    read_text,
    write_json,
    write_text,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import add_worktree, delete_branch, fetch, remove_worktree
from dreamcatcher.rounds import Cause, RoundReader, RoundRecord, Workspace
from dreamcatcher.state import StateDirectory

# What a session's branch is called, before its key. The prefix keeps
# dreamcatcher's own branches apart from everyone else's, and from the branches
# that the catcher it replaces left behind.
BRANCH_PREFIX = "dreamcatcher-"

# The file in a session's directory saying what the session was dispatched
# with.
RECORD = "session.json"

# The directory in a session's directory holding a directory per round.
ROUNDS = "rounds"

# The file in a session's directory holding the newest post the session has
# been told about.
WATERMARK = "watermark"


class SessionRecord(Document):
    """The issue a session works on, and the settings it runs its rounds with.

    The dispatch settles all of these, and no later round changes any of
    them. Every round reads them from here rather than from the config, so
    editing the config while a session is in flight cannot reach that
    session.
    """

    issue: int
    label: str
    branch: str
    worktree: Path
    harness: Harness
    model: str
    effort: str
    prompt: str


@dataclass(frozen=True)
class Session:
    """One session at one issue, as it stands.

    The directory is where the session keeps its own files, and its own name is
    the session's key, which is how a reader of the disk finds one. The record
    says what the dispatch settled, and the rounds are what the session has run
    so far, oldest first.

    The watermark is the newest post the session has been told about. A session
    that has been told about none has the beginning of time, so the first peek
    at its pull request returns the whole history.
    """

    directory: Path
    record: SessionRecord
    rounds: list[RoundRecord] = field(default_factory=list)
    watermark: str = ""

    @property
    def key(self) -> str:
        """The key that the branch, the worktree and the files all carry."""
        return self.directory.name

    @property
    def has_run_final_round(self) -> bool:
        """Whether the session has already run the round that winds it up.

        Any round of the session having been the final round is what this
        reads, and no record's ending comes into it. A session whose last round
        did not finish is carried on before this is ever asked, and that
        carry-on finishes what the final round started, so by the time the
        question is put the work the final round stood for is done however many
        rounds it took.
        """
        return any(record.cause is Cause.FINAL for record in self.rounds)

    def describe_unfinished_round(self) -> str | None:
        """Return what the session's last round left unfinished, or nothing.

        A record with no ending is a round the daemon stopped or outlived, and
        a round that ended with a failing status stopped short of its own
        accord. Both leave the work part done, so both are carried on from
        where they stopped.

        A session that has run no round at all has left nothing unfinished. Its
        first round never started, which is another matter, and one that only a
        person can take further.
        """
        if not self.rounds:
            return None
        ending = self.rounds[-1].ending
        if ending is None:
            return "the last round was interrupted"
        if ending.is_failed:
            return f"the last round failed (exit {ending.status})"
        return None

    def workspace(self, number: int) -> Workspace:
        """Where the session's numbered round ran, and where it wrote.

        Every round runs in the session's worktree, and writes into a
        directory named by the number of the round it is.

        A session runs one round at a time, and each round is numbered by how
        many the session had run before it, so the rounds are numbered from one
        in the order they ran. The place of a record in `rounds` is therefore
        the number of the round it records, which is how a reader of the round
        list finds each round's own files.
        """
        return Workspace(self.record.worktree, self.directory / ROUNDS / str(number))

    @property
    def next_workspace(self) -> Workspace:
        """Where the session's next round runs, and where it writes."""
        return self.workspace(len(self.rounds) + 1)


class SessionReader:
    """What one process has read of a state directory's sessions.

    Reading a session reads its record, its watermark and the records of every
    round it has run, and a round's record is the only one of those that can be
    written a second time. So a reader keeps every complete round record it
    reads, and a later read of the same session opens only the records that are
    still incomplete.

    One reader is one process's reading. A process that looks once makes one
    and lets it go. A process that looks again and again holds the one it made:
    the daemon holds one for its whole run, and a view holds one for as long as
    it stays on the screen. A reader made afresh for each look has read nothing
    yet, so each look would cost what the first one did.
    """

    def __init__(self, state: StateDirectory) -> None:
        """Set up a reader of that state directory, having read nothing yet."""
        self.state = state
        self._rounds = RoundReader()

    def read_sessions(self) -> list[Session]:
        """Return every session the state directory holds, by key.

        A worktree under `worktrees/` is what says a session exists, since that
        is the one place a session of this daemon's can be. The session's own
        files sit under `sessions/`, in a directory the same key names.

        A state directory with no worktrees in it yet holds no sessions, so
        this answers with nothing rather than failing. Anything under
        `worktrees/` that is not a directory is not a worktree, which is what
        keeps a file a file browser left there from reading as a session.

        A worktree whose record is not there is not a session either. A
        creation cuts the worktree and then writes the record, so a daemon that
        died between the two leaves one, and it stands for a session that ran
        nothing and opened no pull request. Reading it as no session leaves its
        issue free to go again, and leaves the worktree itself for whoever
        wants the disk back. A record that is there and will not read is
        another matter, and says so.
        """
        if not self.state.worktrees.is_dir():
            return []
        directories = [
            self.state.sessions / worktree.name
            for worktree in sorted(self.state.worktrees.iterdir())
            if worktree.is_dir()
        ]
        return [
            self._read_session(directory)
            for directory in directories
            if (directory / RECORD).exists()
        ]

    def _read_session(self, directory: Path) -> Session:
        """Return the session whose own files sit in this directory."""
        return Session(
            directory=directory,
            record=read_json(SessionRecord, directory / RECORD),
            rounds=self._rounds.read_records(directory / ROUNDS),
            watermark=_read_watermark(directory),
        )


def create_session(
    state: StateDirectory,
    mapping: DispatchMapping,
    named: Harness,
    issue: int,
    at: datetime,
) -> Session:
    """Create a session for the issue, and return it with no rounds run yet.

    The session runs on the harness that this label and the run settle between
    them, with that harness's own model, effort and prompt template.

    This fetches origin's main first, so the branch starts from main as it is
    now.

    Should anything from the worktree onwards fail, the worktree and the
    branch go away again, so a failed creation leaves neither behind. git
    makes the branch before it reaches the worktree, so an add that failed
    has one to take away. The caller hears the failure that stopped the
    creation, not any failure that removing them hits.
    """
    harness = mapping.choose_harness(named)
    settings = mapping.harness_settings[harness]
    key = f"GH{issue}-{at:%Y%m%d-%H%M%S}"
    record = SessionRecord(
        issue=issue,
        label=mapping.label,
        branch=f"{BRANCH_PREFIX}{key}",
        worktree=state.worktrees / key,
        harness=harness,
        model=settings.model,
        effort=settings.effort,
        prompt=prompts.compose_first_round_prompt(settings.prompt, issue),
    )
    directory = state.sessions / key
    fetch(state.root)
    try:
        add_worktree(state.root, record.worktree, record.branch)
        write_json(record, directory / RECORD)
    except ReportableError:
        discard_session(state, record)
        raise
    return Session(directory=directory, record=record)


def _read_watermark(directory: Path) -> str:
    """Return the newest post this session has been told about.

    A session is told about a batch of posts when a round launches with that
    batch, and that launch is what writes this file. So a session no round has
    yet carried the user's words to has no file here, and the beginning of time
    is what it has seen.

    Whatever wrote the file may have left a line ending after the timestamp, so
    the surrounding space goes: an ISO-8601 time is the whole value.
    """
    path = directory / WATERMARK
    if not path.exists():
        return ""
    return read_text(path).strip()


def advance_watermark(session: Session, newest: str) -> None:
    """Write the time of the newest post the session has now been told about.

    A round launching with a batch of posts as its inbox is what tells the
    session about them, and this is that launch's own write. Until it lands the
    session has heard nothing, so a daemon that died before the round started
    reads those same posts again on its next tick rather than losing them.
    """
    write_text(newest, session.directory / WATERMARK)


def discard_session(state: StateDirectory, record: SessionRecord) -> None:
    """Take away the worktree and the branch that a session was given.

    A creation that failed part way calls this, and so does a dispatch whose
    round would not start. A session with no round claims its issue and can
    never advance by itself, so the dispatch takes it away rather than leave
    it, and its issue is free to go again.

    The worktree goes first, because git keeps a branch that a worktree has
    checked out. Either command can fail in its turn, and neither failure
    travels. The failure that stopped the dispatch is the one worth reporting,
    and the caller already holds it.

    The record stays where it is. Nothing reads a session's record without a
    worktree beside it, so a record left under `sessions/` costs a reader
    nothing.
    """
    with suppress(CommandError):
        remove_worktree(state.root, record.worktree)
    with suppress(CommandError):
        delete_branch(state.root, record.branch)
