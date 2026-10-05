"""Persist issue conversations and prepare their trusted input."""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import Field

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    read_agent_round_records,
)
from dreamcatcher.agent_work import (
    read_harness_session_identifier,
    read_retry_requested_at,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import (
    AgentHarness,
    ConversationRoute,
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
from dreamcatcher.harness_adapters import HarnessConfig, HarnessSessionIdentifier
from dreamcatcher.harnesses import find_harness_session_identifier
from dreamcatcher.prompts import AGENT_POST_MARKER, compose_issue_instructions
from dreamcatcher.state import StateDirectory

_CONVERSATION_RECORD_NAME = "conversation.json"
_CONVERSATION_ROUNDS_DIRECTORY_NAME = "rounds"
NO_REPLY = "NO_REPLY"


def compose_conversation_identifier(*, issue: int) -> str:
    """Return the agent work identifier for an issue conversation."""
    return f"conversation-GH{issue}"


class InitialConversationIssue(DreamcatcherDocument):
    """Model the issue text delivered only with a conversation's first round."""

    title: str
    body: str


class ConversationInput(DreamcatcherDocument):
    """Model the trusted issue input frozen for one conversation round."""

    issue: int
    initial_issue: InitialConversationIssue | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    comments: list[ConversationComment]
    revision: str


class IssueCommentCursor(DreamcatcherDocument):
    """Identify the newest issue comment accepted for delivery."""

    written_at: str
    id: int


class ConversationRecord(DreamcatcherDocument):
    """Model one issue conversation's identity and settings.

    Creation writes the record once, and nothing writes it again.
    """

    issue: int
    title: str
    dispatch_label: str
    harness: AgentHarness
    model: QuotableText
    effort: QuotableText
    harness_config: HarnessConfig = Field(default_factory=dict)
    prompt: str


@dataclass(frozen=True, kw_only=True)
class Conversation:
    """Represent one persisted issue conversation as it currently reads.

    The record holds the conversation's settings, and the facts recorded since
    sit beside it.
    """

    directory: Path
    worktree: Path
    record: ConversationRecord
    harness_session_identifier: HarnessSessionIdentifier | None = None
    retry_requested_at: datetime | None = None
    rounds: list[AgentRoundRecord] = field(default_factory=list)

    @property
    def identifier(self) -> str:
        """The identifier that distinguishes this work from an assignment."""
        return compose_conversation_identifier(issue=self.record.issue)

    @property
    def next_round_number(self) -> int:
        """The number that the conversation's next round will carry."""
        return self.rounds[-1].number + 1 if self.rounds else 1

    def find_harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """Return the recorded or recoverable harness session identifier."""
        return find_harness_session_identifier(
            harness=self.record.harness,
            agent_work_identifier=self.identifier,
            recorded=self.harness_session_identifier,
            raw_outputs=(
                self.compose_round_paths(number=round_record.number).raw_output
                for round_record in reversed(self.rounds)
            ),
        )

    def compose_round_paths(self, *, number: int) -> AgentRoundPaths:
        """Return the paths for one numbered conversation round."""
        return AgentRoundPaths(
            worktree=self.worktree,
            rounds_directory=(self.directory / _CONVERSATION_ROUNDS_DIRECTORY_NAME),
            number=number,
        )


def is_conversation_ready_for_input(*, conversation: Conversation | None) -> bool:
    """Return whether a conversation can accept another comment batch."""
    if conversation is None or not conversation.rounds:
        return True
    return conversation.rounds[-1].outcome in {
        AgentRoundOutcome.SUCCESSFUL,
        AgentRoundOutcome.STOPPED,
    }


def read_conversations(*, state: StateDirectory) -> list[Conversation]:
    """Return every recorded issue conversation, ordered by issue."""
    if not state.conversations.is_dir():
        return []
    return [
        _read_conversation(state=state, directory=directory)
        for directory in sorted(state.conversations.iterdir())
        if (directory / _CONVERSATION_RECORD_NAME).is_file()
    ]


def read_conversation(*, state: StateDirectory, issue: int) -> Conversation | None:
    """Return the conversation for one issue when it exists."""
    directory = state.conversations / f"GH{issue}"
    if not (directory / _CONVERSATION_RECORD_NAME).is_file():
        return None
    return _read_conversation(state=state, directory=directory)


def create_conversation(
    *,
    state: StateDirectory,
    route: ConversationRoute,
    requested_harness: AgentHarness,
    issue: Issue,
) -> Conversation:
    """Create one conversation at fetched main with no rounds run yet."""
    existing = read_conversation(state=state, issue=issue.number)
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
        selected_harness = route.choose_harness(requested_harness=requested_harness)
        recipe = route.recipes[selected_harness]
        record = ConversationRecord(
            issue=issue.number,
            title=issue.title,
            dispatch_label=route.label,
            harness=selected_harness,
            model=recipe.model,
            effort=recipe.effort,
            harness_config=recipe.config,
            prompt=compose_issue_instructions(
                template=recipe.prompt, issue=issue.number
            ),
        )
        write_json(document=record, path=directory / _CONVERSATION_RECORD_NAME)
    except ReportableError:
        with suppress(CommandError):
            remove_worktree(root=state.root, path=worktree)
        raise
    return Conversation(directory=directory, worktree=worktree, record=record)


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


def prepare_conversation_input(
    *,
    state: StateDirectory,
    conversation: Conversation,
    issue: Issue,
    comments: list[ConversationComment],
) -> ConversationInput:
    """Refresh the worktree and freeze one issue's trusted round input."""
    revision = refresh_detached_worktree(
        root=state.root,
        worktree=conversation.worktree,
    )
    is_initial = not conversation.rounds
    return ConversationInput(
        issue=issue.number,
        initial_issue=(
            InitialConversationIssue(title=issue.title, body=issue.body)
            if is_initial
            else None
        ),
        comments=comments,
        revision=revision,
    )


def read_conversation_input(
    *, conversation: Conversation, number: int
) -> ConversationInput:
    """Read and validate the durable input for one conversation round."""
    round_input = _read_conversation_input_document(
        conversation=conversation, number=number
    )
    if number == 1 and round_input.initial_issue is None:
        raise ReportableError(
            f"Conversation {conversation.identifier} round 1 input does not "
            "contain its initial issue title and body."
        )
    return round_input


def _read_conversation_input_document(
    *, conversation: Conversation, number: int
) -> ConversationInput:
    """Read and validate one round input without comparing adjacent rounds."""
    round_input = read_json(
        model=ConversationInput,
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


def describe_conversation_revision(
    *, previous_revision: str | None, revision: str
) -> str:
    """Describe the revision investigated by one conversation round."""
    if previous_revision is None:
        return f"code revision {revision}"
    if previous_revision == revision:
        return f"code revision {revision} (unchanged)"
    return f"code revision {previous_revision} -> {revision}"


def read_issue_comment_delivery_cursor(
    *, conversation: Conversation
) -> IssueCommentCursor | None:
    """Return the newest comment saved in the latest durable round input."""
    if not conversation.rounds:
        return None
    latest_round = conversation.rounds[-1]
    round_input = read_conversation_input(
        conversation=conversation,
        number=latest_round.number,
    )
    newest = round_input.comments[-1]
    return IssueCommentCursor(
        written_at=newest.written_at,
        id=newest.id,
    )


def is_no_reply(*, final_output: str) -> bool:
    """Return whether a round's final output declines to post an answer."""
    return final_output.strip() == NO_REPLY


def post_conversation_answer(
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
    if is_no_reply(final_output=answer):
        return
    response = post_issue_comment(
        repository=repository,
        issue=issue,
        body=f"{answer}\n\n> written by an agent\n\n{AGENT_POST_MARKER}",
    )
    if isinstance(response, UnknownGitHubResponse):
        raise ReportableError(
            f"could not post the answer on GH{issue}: {response.reason}"
        )


def _read_conversation(*, state: StateDirectory, directory: Path) -> Conversation:
    record = read_json(
        model=ConversationRecord,
        path=directory / _CONVERSATION_RECORD_NAME,
    )
    if directory.name != f"GH{record.issue}":
        raise ReportableError(
            f"{directory} records GH{record.issue}, but its directory is "
            f"{directory.name}."
        )
    return Conversation(
        directory=directory,
        worktree=state.conversation_worktrees / directory.name,
        record=record,
        harness_session_identifier=read_harness_session_identifier(directory=directory),
        retry_requested_at=read_retry_requested_at(directory=directory),
        rounds=read_agent_round_records(
            cache=state.document_cache,
            directory=directory / _CONVERSATION_ROUNDS_DIRECTORY_NAME,
        ),
    )
