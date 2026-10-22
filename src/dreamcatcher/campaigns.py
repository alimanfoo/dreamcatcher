"""Model a campaign's children, compare them, prepare rounds and read their input.

A campaign's channel is its parent issue, and its children are the parent's
direct sub-issues. Every round runs in a detached worktree refreshed to fetched
main, and the lead publishes its own messages, so a round has no finishing step.
"""

from enum import StrEnum

from pydantic import PositiveInt

from dreamcatcher.agent_assignments import ObservedPullRequest
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
)
from dreamcatcher.relay import IssueCommentCursor
from dreamcatcher.state import StateDirectory


class CampaignChildAssignment(DreamcatcherDocument):
    """Model where a child's newest assignment stands.

    The pull request is the one that a round of the assignment opened, and the
    observed pull request is what the tick read of it. An assignment that has
    ended or is in fault has its pull request read by no tick. The finished
    turn is the newest round that took its turn, as a successful or a stopped
    round does.
    """

    identifier: str
    pull_request: PositiveInt | None
    observed_pull_request: ObservedPullRequest | None
    finished_turn: PositiveInt | None
    ending: AgentWorkEndReason | None
    is_fault: bool


class CampaignChild(DreamcatcherDocument):
    """Model one child of a campaign's parent issue, as a tick observed it.

    A settled child has no assignment round running or due, where a request
    that may start an assignment counts as a round due. A child with no
    assignment has never had one.
    """

    issue: PositiveInt
    title: str
    state: IssueState
    is_settled: bool
    assignment: CampaignChildAssignment | None

    @property
    def is_closed(self) -> bool:
        """Whether the child's issue is closed."""
        return self.state is IssueState.CLOSED


class CampaignChildChange(StrEnum):
    """List the changes to a child that call for the lead's attention."""

    ADDED = "added"
    REMOVED = "removed"
    ISSUE_STATE = "issue_state"
    HANDBACK = "handback"
    PULL_REQUEST = "pull_request"
    CHECK_COMPLETION = "check_completion"
    MERGEABLE = "mergeable"
    ENDING = "ending"
    FAULT = "fault"


class CampaignChildNotification(DreamcatcherDocument):
    """Model the changes to one child since the newest input delivered to the lead."""

    issue: PositiveInt
    changes: list[CampaignChildChange]


class CampaignRoundInput(WriteOnceDreamcatcherDocument):
    """Model the input frozen for one campaign round.

    The children are the parent's children as the tick that started the
    round observed them, and the notifications name those whose changes since
    the previous delivered input call for the lead. The comments are the user's
    eligible comments on the parent past the cursor, oldest first. The cursor
    is how far this input reaches in the parent's comments: the newest
    comment's position, or the previous delivered input's cursor when the input
    holds no comment. The assignment routes are those of the daemon that
    started the round, which the lead chooses among for a child.
    """

    issue: int
    children: list[CampaignChild]
    notifications: list[CampaignChildNotification]
    comments: list[IssueComment]
    cursor: IssueCommentCursor | None
    revision: str
    assignment_routes: list[AssignmentRoute]


def compare_campaign_children(
    *, previous: list[CampaignChild], current: list[CampaignChild]
) -> list[CampaignChildNotification]:
    """Return a notification for each child whose changes call for the lead.

    The previous children are those of the newest input delivered to the lead.
    Children are matched by issue, so a change of order is none. A child added
    or removed notifies at once, and any other change waits until the child is
    settled. The notifications follow the current children's order, then the
    removed children's.
    """
    previous_by_issue = {child.issue: child for child in previous}
    current_issues = {child.issue for child in current}
    changes_by_issue = [
        (
            child.issue,
            _list_child_changes(
                previous=previous_by_issue.get(child.issue), current=child
            ),
        )
        for child in current
    ] + [
        (child.issue, [CampaignChildChange.REMOVED])
        for child in previous
        if child.issue not in current_issues
    ]
    return [
        CampaignChildNotification(issue=issue, changes=changes)
        for issue, changes in changes_by_issue
        if changes
    ]


def _list_child_changes(
    *, previous: CampaignChild | None, current: CampaignChild
) -> list[CampaignChildChange]:
    """Return what changed of a child that the previous picture held, if anything."""
    if previous is None:
        return [CampaignChildChange.ADDED]
    if not current.is_settled:
        return []
    changes = (
        [] if current.state is previous.state else [CampaignChildChange.ISSUE_STATE]
    )
    if current.assignment is None:
        return changes
    return changes + _list_assignment_changes(
        previous=previous, current=current.assignment
    )


def _list_assignment_changes(
    *, previous: CampaignChild, current: CampaignChildAssignment
) -> list[CampaignChildChange]:
    """Return what changed of a settled child's assignment.

    The child hands back when it was not settled before, or when its assignment
    or its finished turn differs. A replacement shares nothing with the
    assignment it replaced, so every fact it holds is a change.
    """
    before = (
        previous.assignment
        if previous.assignment is not None
        and previous.assignment.identifier == current.identifier
        else None
    )
    changes = []
    if (
        before is None
        or not previous.is_settled
        or before.finished_turn != current.finished_turn
    ):
        changes.append(CampaignChildChange.HANDBACK)
    if current.observed_pull_request is not None:
        changes += _list_pull_request_changes(
            previous=None if before is None else before.observed_pull_request,
            current=current.observed_pull_request,
        )
    if current.ending is not None and (before is None or before.ending is None):
        changes.append(CampaignChildChange.ENDING)
    if current.is_fault and (before is None or not before.is_fault):
        changes.append(CampaignChildChange.FAULT)
    return changes


def _list_pull_request_changes(
    *, previous: ObservedPullRequest | None, current: ObservedPullRequest
) -> list[CampaignChildChange]:
    """Return what changed of a pull request since the previous read of it.

    With no previous read, every fact is a change. Checks complete when some
    ran and none still runs, compared by the head, the result and whether any
    runs, so a failing result whose last running check finishes completes.
    """
    changes = []
    if previous is None or (previous.state, previous.is_draft, previous.head) != (
        current.state,
        current.is_draft,
        current.head,
    ):
        changes.append(CampaignChildChange.PULL_REQUEST)
    if (
        current.check_result is not CheckResult.NONE
        and not current.has_running_checks
        and (
            previous is None
            or (previous.head, previous.check_result, previous.has_running_checks)
            != (current.head, current.check_result, current.has_running_checks)
        )
    ):
        changes.append(CampaignChildChange.CHECK_COMPLETION)
    if current.merge_state.is_mergeable and (
        previous is None or not previous.merge_state.is_mergeable
    ):
        changes.append(CampaignChildChange.MERGEABLE)
    return changes


def prepare_campaign_round(
    *,
    state: StateDirectory,
    campaign: AgentWork,
    children: list[CampaignChild],
    notifications: list[CampaignChildNotification],
    comments: list[IssueComment],
    delivered_cursor: IssueCommentCursor | None,
    assignment_routes: list[AssignmentRoute],
) -> CampaignRoundInput:
    """Reset the worktree to fetched main and freeze the round's input.

    The delivered cursor is that of the newest input delivered to the lead,
    which a round given no comment carries forward.
    """
    revision = refresh_detached_worktree(root=state.root, worktree=campaign.worktree)
    return CampaignRoundInput(
        issue=campaign.record.issue,
        children=children,
        notifications=notifications,
        comments=comments,
        cursor=(
            IssueCommentCursor(written_at=comments[-1].written_at, id=comments[-1].id)
            if comments
            else delivered_cursor
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


def read_delivered_campaign_input(*, campaign: AgentWork) -> CampaignRoundInput | None:
    """Return the newest input delivered to the lead, if one has been.

    It says how far the lead has read in the parent's comments, and holds the
    picture of the children that the lead was last given.
    """
    delivered = campaign.list_relayed_round_paths()
    if not delivered:
        return None
    return read_campaign_input(campaign=campaign, number=delivered[0].number)
