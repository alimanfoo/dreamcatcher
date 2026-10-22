"""Decide whether an issue's labels and assignee pause the open work at it."""

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.github import Issue
from dreamcatcher.scheduler.inspection import SchedulingContext
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    PauseCause,
    PausedFinding,
)


def find_pause(
    *, context: SchedulingContext, work: AgentWork, issue: Issue
) -> PausedFinding | ConflictingLabelsFinding | None:
    """Return why the open work at this open issue is paused, if it is.

    Work whose channel is its issue belongs to its own label. Another configured
    label of its kind on the issue is a routing conflict, held as the labels.
    The work's own label counts whether or not its route is still configured.
    """
    labels = [label.name for label in issue.labels]
    label = work.record.dispatch_label.casefold()
    if label not in {name.casefold() for name in labels}:
        return PausedFinding(cause=PauseCause.LABEL_REMOVED)
    account = context.account.casefold()
    if account not in {assignee.login.casefold() for assignee in issue.assignees}:
        return PausedFinding(cause=PauseCause.ISSUE_UNASSIGNED)
    others = [
        route.label
        for route in context.config.identify_routes(
            kind=work.record.kind, labels=labels
        )
        if route.label.casefold() != label
    ]
    if others:
        return ConflictingLabelsFinding(
            labels=sorted([work.record.dispatch_label, *others], key=str.casefold)
        )
    return None
