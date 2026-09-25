"""Persist issue conversations and prepare their trusted input."""

from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from dreamcatcher.agent_rounds import (
    AgentRoundPaths,
    AgentRoundRecord,
    IssueConversationInput,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import (
    IssueConversationConfig,
    IssueConversationHarness,
    QuotableText,
)
from dreamcatcher.documents import DreamcatcherDocument, read_json, write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    add_detached_worktree,
    fetch_main,
    is_linked_worktree,
    refresh_detached_worktree,
    remove_worktree,
)
from dreamcatcher.github import (
    ConversationComment,
    Issue,
    UnknownGitHubResponse,
    post_issue_comment,
)
from dreamcatcher.harness_adapters import (
    HarnessSessionIdentifier,
    refuse_reportable_harness_session_identifier,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.state import StateDirectory

ISSUE_CONVERSATION_RECORD_NAME = "conversation.json"
ISSUE_CONVERSATION_ROUNDS_DIRECTORY_NAME = "rounds"
NO_REPLY = "NO_REPLY"


class IssueCommentCursor(DreamcatcherDocument):
    """Identify the newest issue comment accepted for delivery."""

    written_at: str
    id: int


class IssueConversationRecord(DreamcatcherDocument):
    """Model one issue conversation's identity and settled settings."""

    issue: int
    title: str
    label: str
    harness: IssueConversationHarness
    harness_session_identifier: HarnessSessionIdentifier | None = None
    model: QuotableText
    effort: QuotableText
    prompt: str


@dataclass(frozen=True, kw_only=True)
class IssueConversation:
    """Represent one persisted issue conversation as it currently reads."""

    directory: Path
    worktree: Path
    record: IssueConversationRecord
    rounds: list[AgentRoundRecord] = field(default_factory=list)
    _record_lock: Lock = field(
        default_factory=Lock, init=False, repr=False, compare=False
    )

    @property
    def identifier(self) -> str:
        """The identifier that distinguishes this work from an assignment."""
        return f"conversation-{self.directory.name}"

    @property
    def next_round_number(self) -> int:
        """The number that the conversation's next round will carry."""
        return self.rounds[-1].number + 1 if self.rounds else 1

    @property
    def unrecorded_round_input(self) -> Path | None:
        """The next round's input when no corresponding round record exists."""
        path = self.compose_round_paths(number=self.next_round_number).round_input
        return path if path.is_file() else None

    def compose_round_paths(self, *, number: int) -> AgentRoundPaths:
        """Return the paths for one numbered conversation round."""
        return AgentRoundPaths(
            worktree=self.worktree,
            rounds_directory=(
                self.directory / ISSUE_CONVERSATION_ROUNDS_DIRECTORY_NAME
            ),
            number=number,
        )


def read_issue_conversations(*, state: StateDirectory) -> list[IssueConversation]:
    """Return every recorded issue conversation, ordered by issue."""
    if not state.conversations.is_dir():
        return []
    return [
        _read_issue_conversation(state=state, directory=directory)
        for directory in sorted(state.conversations.iterdir())
        if (directory / ISSUE_CONVERSATION_RECORD_NAME).is_file()
    ]


def read_issue_conversation(
    *, state: StateDirectory, issue: int
) -> IssueConversation | None:
    """Return the conversation for one issue when it exists."""
    directory = state.conversations / f"GH{issue}"
    if not (directory / ISSUE_CONVERSATION_RECORD_NAME).is_file():
        return None
    return _read_issue_conversation(state=state, directory=directory)


def create_issue_conversation(
    *, state: StateDirectory, config: IssueConversationConfig, issue: Issue
) -> IssueConversation:
    """Create one conversation at fetched main with no rounds run yet."""
    existing = read_issue_conversation(state=state, issue=issue.number)
    if existing is not None:
        return existing
    fetch_main(root=state.root)
    directory = state.conversations / f"GH{issue.number}"
    worktree = state.conversation_worktrees / f"GH{issue.number}"
    if is_linked_worktree(path=worktree):
        raise ReportableError(
            f"Could not create conversation for GH{issue.number}: its unrecorded "
            f"worktree already exists at {state.describe_path(path=worktree)}."
        )
    add_detached_worktree(root=state.root, path=worktree)
    try:
        record = IssueConversationRecord(
            issue=issue.number,
            title=issue.title,
            label=config.label,
            harness=config.harness,
            model=config.model,
            effort=config.effort,
            prompt=config.prompt,
        )
        write_json(document=record, path=directory / ISSUE_CONVERSATION_RECORD_NAME)
    except ReportableError:
        with suppress(CommandError):
            remove_worktree(root=state.root, path=worktree)
        raise
    return IssueConversation(directory=directory, worktree=worktree, record=record)


def list_undelivered_issue_comments(
    *,
    comments: list[ConversationComment],
    account: str,
    cursor: IssueCommentCursor | None,
) -> list[ConversationComment]:
    """Return trusted comments after the cursor, oldest first."""
    cursor_position = (cursor.written_at, cursor.id) if cursor is not None else ("", 0)
    return sorted(
        (
            comment
            for comment in comments
            if comment.author.casefold() == account.casefold()
            and bool(comment.body.strip())
            and AGENT_POST_MARKER not in comment.body
            and (comment.written_at, comment.id) > cursor_position
        ),
        key=lambda comment: (comment.written_at, comment.id),
    )


def prepare_issue_conversation_input(
    *,
    state: StateDirectory,
    conversation: IssueConversation,
    issue: Issue,
    comments: list[ConversationComment],
) -> IssueConversationInput:
    """Refresh the worktree and freeze one issue's trusted round input."""
    expected_revision = None
    if conversation.rounds:
        expected_revision = read_issue_conversation_input(
            conversation=conversation,
            number=conversation.rounds[-1].number,
        ).revision
    revision = refresh_detached_worktree(
        root=state.root,
        worktree=conversation.worktree,
        expected_revision=expected_revision,
    )
    is_initial = not conversation.rounds
    return IssueConversationInput(
        issue=issue.number,
        title=issue.title if is_initial else None,
        body=issue.body if is_initial else None,
        comments=comments,
        revision=revision,
    )


def read_issue_conversation_input(
    *, conversation: IssueConversation, number: int
) -> IssueConversationInput:
    """Read and validate the durable input for one conversation round."""
    round_input = _read_issue_conversation_input_document(
        conversation=conversation, number=number
    )
    if number == 1 and (round_input.title is None or round_input.body is None):
        raise ReportableError(
            f"Conversation {conversation.identifier} round 1 input does not "
            "contain its initial issue title and body."
        )
    return round_input


def _read_issue_conversation_input_document(
    *, conversation: IssueConversation, number: int
) -> IssueConversationInput:
    """Read and validate one round input without comparing adjacent rounds."""
    round_input = read_json(
        model=IssueConversationInput,
        path=conversation.compose_round_paths(number=number).round_input,
    )
    if not round_input.comments:
        raise ReportableError(
            f"Conversation {conversation.identifier} round {number} "
            "has no delivered issue comments."
        )
    if round_input.issue != conversation.record.issue:
        raise ReportableError(
            f"Conversation {conversation.identifier} round {number} "
            f"input names GH{round_input.issue}."
        )
    positions = [(comment.written_at, comment.id) for comment in round_input.comments]
    if positions != sorted(set(positions)):
        raise ReportableError(
            f"Conversation {conversation.identifier} round {number} "
            "comments are not strictly ordered."
        )
    return round_input


def describe_issue_conversation_revision(
    *, previous_revision: str | None, revision: str
) -> str:
    """Describe the revision investigated by one conversation round."""
    if previous_revision is None:
        return f"code revision {revision}"
    if previous_revision == revision:
        return f"code revision {revision} (unchanged)"
    return f"code revision {previous_revision} -> {revision}"


def read_issue_comment_delivery_cursor(
    *, conversation: IssueConversation
) -> IssueCommentCursor | None:
    """Return the newest comment saved in the latest durable round input."""
    if not conversation.rounds:
        return None
    latest_round = conversation.rounds[-1]
    round_input = read_issue_conversation_input(
        conversation=conversation,
        number=latest_round.number,
    )
    newest = round_input.comments[-1]
    return IssueCommentCursor(
        written_at=newest.written_at,
        id=newest.id,
    )


def record_issue_conversation_session_identifier(
    *, conversation: IssueConversation, identifier: str
) -> None:
    """Record the harness session identifier reported by the first round."""
    validated = refuse_reportable_harness_session_identifier(
        agent_work_identifier=conversation.identifier, identifier=identifier
    )
    with conversation._record_lock:
        recorded = conversation.record.harness_session_identifier
        if recorded is not None and recorded != validated:
            raise ReportableError(
                f"Conversation {conversation.identifier} reported harness session "
                f"{validated}, after it already reported {recorded}."
            )
        if recorded is None:
            _update_issue_conversation_record(
                conversation=conversation,
                updates={"harness_session_identifier": validated},
            )


def post_issue_conversation_answer(
    *, repository: str, issue: int, final_output: str | None
) -> None:
    """Post a conversation round's final output on its issue as one marked comment.

    Every conversation round must answer, so a missing or empty final output
    raises a `ReportableError`, as does a comment that GitHub does not accept.
    `NO_REPLY` posts nothing.
    """
    answer = (final_output or "").strip()
    if not answer:
        raise ReportableError("the harness returned no final output")
    if answer == NO_REPLY:
        return
    response = post_issue_comment(
        repository=repository,
        issue=issue,
        body=f"{answer}\n\n{AGENT_POST_MARKER}",
    )
    if isinstance(response, UnknownGitHubResponse):
        raise ReportableError(
            f"could not post the answer on GH{issue}: {response.reason}"
        )


def _read_issue_conversation(
    *, state: StateDirectory, directory: Path
) -> IssueConversation:
    record = read_json(
        model=IssueConversationRecord,
        path=directory / ISSUE_CONVERSATION_RECORD_NAME,
    )
    if directory.name != f"GH{record.issue}":
        raise ReportableError(
            f"{directory} records GH{record.issue}, but its directory is "
            f"{directory.name}."
        )
    return IssueConversation(
        directory=directory,
        worktree=state.conversation_worktrees / directory.name,
        record=record,
        rounds=state.round_reader.read_records(
            directory=directory / ISSUE_CONVERSATION_ROUNDS_DIRECTORY_NAME
        ),
    )


def _update_issue_conversation_record(
    *,
    conversation: IssueConversation,
    updates: dict[str, object],
) -> None:
    """Apply field updates while the caller holds the conversation's record lock."""
    updated = conversation.record.model_copy(update=updates)
    write_json(
        document=updated,
        path=conversation.directory / ISSUE_CONVERSATION_RECORD_NAME,
    )
    object.__setattr__(conversation, "record", updated)
