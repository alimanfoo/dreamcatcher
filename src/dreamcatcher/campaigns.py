"""Prepare campaign rounds and read back the input each round was given.

A campaign's channel is its parent issue. Every round runs in a detached
worktree refreshed to fetched main, and the lead publishes its own messages, so
a round has no finishing step.
"""

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.documents import WriteOnceDreamcatcherDocument, read_json
from dreamcatcher.git import refresh_detached_worktree
from dreamcatcher.github import IssueComment
from dreamcatcher.relay import IssueCommentCursor
from dreamcatcher.state import StateDirectory


class CampaignRoundInput(WriteOnceDreamcatcherDocument):
    """Model the input frozen for one campaign round.

    The comments are the user's eligible comments on the parent past the
    cursor, oldest first.
    """

    issue: int
    comments: list[IssueComment]
    revision: str


def prepare_campaign_round(
    *, state: StateDirectory, campaign: AgentWork, comments: list[IssueComment]
) -> CampaignRoundInput:
    """Reset the worktree to fetched main and freeze the round's input."""
    revision = refresh_detached_worktree(root=state.root, worktree=campaign.worktree)
    return CampaignRoundInput(
        issue=campaign.record.issue, comments=comments, revision=revision
    )


def read_campaign_input(*, campaign: AgentWork, number: int) -> CampaignRoundInput:
    """Read the durable input of one campaign round."""
    return read_json(
        model=CampaignRoundInput,
        path=campaign.compose_round_paths(number=number).round_input,
    )


def read_parent_comment_cursor(*, campaign: AgentWork) -> IssueCommentCursor | None:
    """Return the newest parent comment among those already delivered to the lead.

    A campaign that has delivered no comment reads the parent's comments from
    the beginning.
    """
    for paths in campaign.list_relayed_round_paths():
        comments = read_campaign_input(campaign=campaign, number=paths.number).comments
        if comments:
            return IssueCommentCursor(
                written_at=comments[-1].written_at, id=comments[-1].id
            )
    return None
