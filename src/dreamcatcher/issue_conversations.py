"""Persist issue conversations and prepare their trusted input."""

from datetime import datetime

from pydantic import Field

from dreamcatcher.agent_rounds import AgentRoundOutcome
from dreamcatcher.agent_work import (
    AgentWork,
    AgentWorkRecord,
    compose_agent_work_identifier,
    record_agent_work,
)
from dreamcatcher.config import AgentHarness, ConversationRoute
from dreamcatcher.documents import DreamcatcherDocument, read_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    refresh_detached_worktree,
)
from dreamcatcher.github import (
    ConversationComment,
    Issue,
    UnknownGitHubResponse,
    post_issue_comment,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.prompts import AGENT_POST_MARKER, compose_issue_instructions
from dreamcatcher.state import StateDirectory

NO_REPLY = "NO_REPLY"


class InitialConversationIssue(DreamcatcherDocument):
    """Model the issue text delivered only with a conversation's first round."""

    title: str
    body: str


class ConversationRoundInput(DreamcatcherDocument):
    """Model the trusted issue input frozen for one conversation round."""

    issue: int
    initial_issue: InitialConversationIssue | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    comments: list[ConversationComment]
    revision: str


class IssueCommentDeliveryPosition(DreamcatcherDocument):
    """Identify the newest issue comment accepted for delivery."""

    written_at: str
    id: int


def is_conversation_ready_for_input(*, conversation: AgentWork | None) -> bool:
    """Return whether a conversation can accept another comment batch."""
    if conversation is None or not conversation.rounds:
        return True
    return conversation.rounds[-1].outcome is not AgentRoundOutcome.RUNNING


def create_conversation(
    *,
    state: StateDirectory,
    route: ConversationRoute,
    preferred_harness: AgentHarness,
    issue: Issue,
    at: datetime,
) -> AgentWork:
    """Record one conversation at the issue with no rounds run yet.

    Every round's preparation makes the worktree, so creation writes the record
    alone.
    """
    selected_harness = route.choose_harness(preferred_harness=preferred_harness)
    recipe = route.recipes[selected_harness]
    record = AgentWorkRecord(
        issue=issue.number,
        title=issue.title,
        dispatch_label=route.label,
        kind=AgentWorkKind.CONVERSATION,
        harness=selected_harness,
        model=recipe.model,
        effort=recipe.effort,
        harness_config=recipe.config,
        prompt=compose_issue_instructions(template=recipe.prompt, issue=issue.number),
    )
    return record_agent_work(
        state=state,
        identifier=compose_agent_work_identifier(
            issue=issue.number, kind=AgentWorkKind.CONVERSATION, at=at
        ),
        record=record,
    )


def list_undelivered_issue_comments(
    *,
    comments: list[ConversationComment],
    account: str,
    delivery_position: IssueCommentDeliveryPosition | None,
) -> list[ConversationComment]:
    """Return trusted comments after the delivery position, oldest first."""
    after = (
        (delivery_position.written_at, delivery_position.id)
        if delivery_position is not None
        else ("", 0)
    )
    return sorted(
        (
            comment
            for comment in comments
            if comment.author.casefold() == account.casefold()
            and bool(comment.body.strip())
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
    comments: list[ConversationComment],
    is_resuming: bool,
) -> ConversationRoundInput:
    """Reset the worktree to fetched main and freeze the round's trusted input.

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


def read_issue_comment_delivery_position(
    *, conversation: AgentWork
) -> IssueCommentDeliveryPosition | None:
    """Return the newest comment already relayed.

    A round stopped before its preparation wrote an input relayed nothing, so
    the position comes from the latest relayed round that has one.
    """
    for round_record in reversed(conversation.relayed_rounds):
        if conversation.compose_round_paths(
            number=round_record.number
        ).round_input.exists():
            newest = read_conversation_input(
                conversation=conversation, number=round_record.number
            ).comments[-1]
            return IssueCommentDeliveryPosition(
                written_at=newest.written_at, id=newest.id
            )
    return None


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
