"""Model a campaign's children, prepare its rounds and read back their input.

A campaign's channel is its parent issue, and its children are the parent's
direct sub-issues. Every round runs in a detached worktree refreshed to fetched
main, and the lead publishes its own messages, so a round has no finishing step.
"""

from pydantic import PositiveInt

from dreamcatcher.agent_work import AgentWork, AgentWorkEndReason
from dreamcatcher.config import AssignmentRoute
from dreamcatcher.documents import (
    DreamcatcherDocument,
    WriteOnceDreamcatcherDocument,
    read_json,
)
from dreamcatcher.git import refresh_detached_worktree
from dreamcatcher.github import (
    CheckResult,
    IssueComment,
    IssueState,
    PullRequestMergeState,
    PullRequestState,
)
from dreamcatcher.relay import IssueCommentCursor
from dreamcatcher.state import StateDirectory


class CampaignChildPullRequest(DreamcatcherDocument):
    """Model what an update read of a child assignment's pull request.

    The checks are those at the head. A failing check result can still have
    checks running.
    """

    state: PullRequestState
    is_draft: bool
    merge_state: PullRequestMergeState
    head: str
    check_result: CheckResult
    has_running_checks: bool


class CampaignChildAssignment(DreamcatcherDocument):
    """Model where a child's newest assignment stands.

    The pull request is the one that a round of the assignment opened, and the
    observed pull request is what the update read of it. An assignment that has
    ended or is in fault has its pull request read by no update. The finished
    turn is the newest round that took its turn, as a successful or a stopped
    round does.
    """

    identifier: str
    pull_request: PositiveInt | None
    observed_pull_request: CampaignChildPullRequest | None
    finished_turn: PositiveInt | None
    ending: AgentWorkEndReason | None
    is_fault: bool


class CampaignChild(DreamcatcherDocument):
    """Model one child of a campaign's parent issue, as an update observed it.

    A settled child has no assignment round running or due, where a request
    that may start an assignment counts as a round due. A child with no
    assignment has never had one.
    """

    issue: PositiveInt
    title: str
    state: IssueState
    is_settled: bool
    assignment: CampaignChildAssignment | None


class CampaignRoundInput(WriteOnceDreamcatcherDocument):
    """Model the input frozen for one campaign round.

    The children are the parent's children as the update that started the
    round observed them. The comments are the user's eligible comments on the
    parent past the cursor, oldest first. The cursor is how far this input
    reaches in the parent's comments: the newest comment's position, or the
    previous delivered input's cursor when the input holds no comment. The
    assignment routes are those of the daemon that started the round, which
    the lead chooses among for a child.
    """

    issue: int
    children: list[CampaignChild]
    comments: list[IssueComment]
    cursor: IssueCommentCursor | None
    revision: str
    assignment_routes: list[AssignmentRoute]


def prepare_campaign_round(
    *,
    state: StateDirectory,
    campaign: AgentWork,
    children: list[CampaignChild],
    comments: list[IssueComment],
    assignment_routes: list[AssignmentRoute],
) -> CampaignRoundInput:
    """Reset the worktree to fetched main and freeze the round's input."""
    revision = refresh_detached_worktree(root=state.root, worktree=campaign.worktree)
    return CampaignRoundInput(
        issue=campaign.record.issue,
        children=children,
        comments=comments,
        cursor=(
            IssueCommentCursor(written_at=comments[-1].written_at, id=comments[-1].id)
            if comments
            else read_parent_comment_cursor(campaign=campaign)
        ),
        revision=revision,
        assignment_routes=assignment_routes,
    )


def read_campaign_input(*, campaign: AgentWork, number: int) -> CampaignRoundInput:
    """Read the durable input of one campaign round."""
    return read_json(
        model=CampaignRoundInput,
        path=campaign.compose_round_paths(number=number).round_input,
    )


def read_parent_comment_cursor(*, campaign: AgentWork) -> IssueCommentCursor | None:
    """Return the cursor of the newest input delivered to the lead.

    No input delivered yet leaves the cursor at the beginning of the parent's
    comments.
    """
    delivered = campaign.list_relayed_round_paths()
    if not delivered:
        return None
    return read_campaign_input(campaign=campaign, number=delivered[0].number).cursor
