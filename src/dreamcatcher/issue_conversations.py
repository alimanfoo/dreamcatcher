"""Prepare issue conversations' eligible input and post their answers."""

from pydantic import Field

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.documents import DreamcatcherDocument, read_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    refresh_detached_worktree,
)
from dreamcatcher.github import (
    Issue,
    IssueComment,
    UnknownGitHubResponse,
    post_issue_comment,
)
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.state import StateDirectory

NO_REPLY = "NO_REPLY"


class InitialConversationIssue(DreamcatcherDocument):
    """Model the issue text given to a round that starts a new harness session."""

    title: str
    body: str


class ConversationRoundInput(DreamcatcherDocument):
    """Model the eligible issue input frozen for one conversation round."""

    issue: int
    initial_issue: InitialConversationIssue | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    comments: list[IssueComment]
    revision: str


class IssueCommentCursor(DreamcatcherDocument):
    """Identify the newest issue comment behind a conversation's cursor."""

    written_at: str
    id: int


def list_issue_comments_past_cursor(
    *,
    comments: list[IssueComment],
    account: str,
    cursor: IssueCommentCursor | None,
) -> list[IssueComment]:
    """Return eligible comments past the cursor, oldest first."""
    after = (cursor.written_at, cursor.id) if cursor is not None else ("", 0)
    return sorted(
        (
            comment
            for comment in comments
            if comment.is_written_by(account=account)
            and comment.is_speaking
            and AGENT_POST_MARKER not in comment.body
            and (comment.written_at, comment.id) > after
        ),
        key=lambda comment: (comment.written_at, comment.id),
    )


def prepare_conversation_round(
    *,
    state: StateDirectory,
    conversation: AgentWork,
    issue: Issue,
    comments: list[IssueComment],
    is_resuming: bool,
) -> ConversationRoundInput:
    """Reset the worktree to fetched main and freeze the round's eligible input.

    A round that starts a new harness session is given the issue's title and
    body too, because the session has not seen them.
    """
    revision = refresh_detached_worktree(
        root=state.root,
        worktree=conversation.worktree,
    )
    return ConversationRoundInput(
        issue=issue.number,
        initial_issue=(
            None
            if is_resuming
            else InitialConversationIssue(title=issue.title, body=issue.body)
        ),
        comments=comments,
        revision=revision,
    )


def read_conversation_input(
    *, conversation: AgentWork, number: int
) -> ConversationRoundInput:
    """Read and validate the durable input for one conversation round."""
    round_input = read_json(
        model=ConversationRoundInput,
        path=conversation.compose_round_paths(number=number).round_input,
    )
    if not round_input.comments:
        raise ReportableError(
            f"Conversation {conversation.identifier} round {number} "
            "relayed no issue comments."
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


def read_issue_comment_cursor(*, conversation: AgentWork) -> IssueCommentCursor | None:
    """Return the newest comment already relayed.

    A round stopped before its preparation wrote an input relayed nothing.
    """
    relayed = conversation.list_relayed_round_paths()
    if not relayed:
        return None
    newest = read_conversation_input(
        conversation=conversation, number=relayed[0].number
    ).comments[-1]
    return IssueCommentCursor(written_at=newest.written_at, id=newest.id)


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
