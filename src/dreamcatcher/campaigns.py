"""Model a campaign's children, compare them, prepare rounds and read their input.

A campaign's children are its parent's direct sub-issues. Each lead round
receives the current picture of them beside its pull request input.
"""

from collections.abc import Sequence
from enum import StrEnum

from pydantic import ConfigDict, Field, PositiveInt

from dreamcatcher.agent_work import AgentWork, AgentWorkEndReason
from dreamcatcher.config import AssignmentRoute
from dreamcatcher.documents import (
    DreamcatcherDocument,
    ReadOnlyList,
    read_json,
)
from dreamcatcher.github import (
    CheckResult,
    IssueState,
)
from dreamcatcher.pull_request_work import (
    ObservedPullRequest,
    PullRequestRoundInput,
)


class CampaignChildAssignment(DreamcatcherDocument):
    """Model where a child's newest assignment stands.

    The pull request is the one that a round of the assignment opened, and the
    observed pull request is what the tick read of it. An assignment that has
    ended or is in fault has its pull request read by no tick.
    `finished_turn` is the number of the newest round that consumed its input,
    as a successful or a stopped round does. The round input keeps the fault
    flag's published name, `is_fault`, which a lead's skill may read.
    """

    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True)

    identifier: str
    pull_request: PositiveInt | None
    observed_pull_request: ObservedPullRequest | None
    finished_turn: PositiveInt | None
    ending: AgentWorkEndReason | None
    is_in_fault: bool = Field(alias="is_fault")


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
    changes: ReadOnlyList[CampaignChildChange]


class CampaignRoundInput(PullRequestRoundInput):
    """Freeze the lead's pull request input, sub-issues and assignment routes."""

    children: ReadOnlyList[CampaignChild]
    notifications: ReadOnlyList[CampaignChildNotification]
    assignment_routes: ReadOnlyList[AssignmentRoute]


def compare_campaign_children(
    *, previous: Sequence[CampaignChild], current: Sequence[CampaignChild]
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
    or the newest round of it that consumed its input differs. A replacement
    shares nothing with the assignment it replaced, so every fact it holds is a
    change.
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
    if current.is_in_fault and (before is None or not before.is_in_fault):
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


def compose_campaign_round_input(
    *,
    pull_request_input: PullRequestRoundInput,
    children: Sequence[CampaignChild],
    notifications: Sequence[CampaignChildNotification],
    assignment_routes: Sequence[AssignmentRoute],
) -> CampaignRoundInput:
    """Add the lead's sub-issues and assignment routes to its channel input."""
    return CampaignRoundInput.model_validate(
        pull_request_input.model_dump()
        | {
            "children": children,
            "notifications": notifications,
            "assignment_routes": assignment_routes,
        }
    )


def read_delivered_campaign_input(*, campaign: AgentWork) -> CampaignRoundInput | None:
    """Return the newest input delivered to the lead, if one has been.

    It holds the picture of the sub-issues that the lead was last given.
    """
    delivered = campaign.list_relayed_round_paths()
    if not delivered:
        return None
    return read_json(model=CampaignRoundInput, path=delivered[0].round_input)
