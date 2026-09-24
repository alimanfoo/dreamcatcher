"""Persist issue conversations and prepare their trusted input."""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock

from pydantic import AwareDatetime, model_validator

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
    read_worktree_revision,
    remove_worktree,
)
from dreamcatcher.github import ConversationComment, Issue
from dreamcatcher.harness_adapters import (
    HarnessSessionIdentifier,
    refuse_reportable_harness_session_identifier,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.state import StateDirectory

ISSUE_CONVERSATION_RECORD_NAME = "conversation.json"
ISSUE_CONVERSATION_ROUNDS_DIRECTORY_NAME = "rounds"
ISSUE_CONVERSATION_REPLY_NAME = "reply.json"
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
    worktree: Path
    revision: str
    harness: IssueConversationHarness
    harness_session_identifier: HarnessSessionIdentifier | None = None
    model: QuotableText
    effort: QuotableText
    prompt: str

    @model_validator(mode="before")
    @classmethod
    def _discard_legacy_delivery_cursor(
        cls, value: dict[str, object], /
    ) -> dict[str, object]:
        """Read records written before round inputs became the delivery ledger."""
        data = dict(value)
        data.pop("delivery_cursor", None)
        return data


class IssueConversationReply(DreamcatcherDocument):
    """Model a saved final answer and its GitHub publication."""

    body: str
    published_at: AwareDatetime | None = None

    @property
    def is_no_reply(self) -> bool:
        """Whether the agent explicitly said that no reply is needed."""
        return self.body == NO_REPLY

    @property
    def is_complete(self) -> bool:
        """Whether this answer needs no further publication attempt."""
        return self.is_no_reply or self.published_at is not None


@dataclass(frozen=True, kw_only=True)
class IssueConversation:
    """Represent one persisted issue conversation as it currently reads."""

    directory: Path
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

    def compose_round_paths(self, *, number: int) -> AgentRoundPaths:
        """Return the paths for one numbered conversation round."""
        return AgentRoundPaths(
            worktree=self.record.worktree,
            rounds_directory=(
                self.directory / ISSUE_CONVERSATION_ROUNDS_DIRECTORY_NAME
            ),
            number=number,
        )

    def compose_reply_path(self, *, number: int) -> Path:
        """Return the path of one round's saved reply record."""
        return self.compose_round_paths(number=number).directory / (
            ISSUE_CONVERSATION_REPLY_NAME
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
            worktree=worktree,
            revision=read_worktree_revision(worktree=worktree),
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
    return IssueConversation(directory=directory, record=record)


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


def compose_issue_conversation_input(
    *,
    issue: Issue,
    comments: list[ConversationComment],
    revision: str,
) -> IssueConversationInput:
    """Freeze one issue and its trusted comment batch as round input."""
    return IssueConversationInput(
        issue=issue.number,
        title=issue.title,
        body=issue.body,
        comments=comments,
        revision=revision,
    )


def read_issue_comment_delivery_cursor(
    *, conversation: IssueConversation
) -> IssueCommentCursor | None:
    """Return the newest comment saved in the latest durable round input."""
    if not conversation.rounds:
        return None
    latest_round = conversation.rounds[-1]
    round_input = read_json(
        model=IssueConversationInput,
        path=conversation.compose_round_paths(number=latest_round.number).round_input,
    )
    if not round_input.comments:
        raise ReportableError(
            f"Conversation {conversation.identifier} round {latest_round.number} "
            "has no delivered issue comments."
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


def save_issue_conversation_reply(
    *, conversation: IssueConversation, number: int, body: str
) -> IssueConversationReply:
    """Save and return one round's final answer before publication."""
    reply = IssueConversationReply(body=body.strip())
    write_json(document=reply, path=conversation.compose_reply_path(number=number))
    return reply


def read_issue_conversation_reply(
    *, conversation: IssueConversation, number: int
) -> IssueConversationReply | None:
    """Return one round's saved reply when it exists."""
    path = conversation.compose_reply_path(number=number)
    if not path.is_file():
        return None
    return read_json(model=IssueConversationReply, path=path)


def record_issue_conversation_reply_publication(
    *, conversation: IssueConversation, number: int, at: datetime
) -> IssueConversationReply:
    """Record that GitHub accepted one saved answer."""
    reply = read_issue_conversation_reply(conversation=conversation, number=number)
    if reply is None:
        raise ReportableError(
            f"Conversation {conversation.identifier} round {number} has no saved "
            "reply to publish."
        )
    published = reply.model_copy(update={"published_at": at})
    write_json(document=published, path=conversation.compose_reply_path(number=number))
    return published


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
