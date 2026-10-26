"""Start and resume work only on a dispatch label that the user applied.

A colleague who labels an issue assigned to the user, or puts back the label of
the user's paused work, then starts nothing on the user's machine.
"""

from dataclasses import replace

from dreamcatcher.config import identify_label
from dreamcatcher.github import (
    UnknownGitHubResponse,
    is_login_of_account,
    list_labelling_events,
)
from dreamcatcher.scheduler.inspection import Inspection, SchedulingContext
from dreamcatcher.scheduler.models import LabelAppliedByOtherFinding, ReadFailureFinding


def require_label_applied_by_user(
    *, context: SchedulingContext, inspection: Inspection
) -> Inspection:
    """Return the inspection, or one with no candidate and no counted fault.

    The label is the row's dispatch label, and the user applied it when the
    latest event that applied it to the issue names the user's account. Work
    on a label that someone else applied starts no round, and its fault does
    not count, as for work paused any other way. Only a candidate or a counted
    fault is checked, so the issue's events are read only when the answer
    changes what the tick does. A failed read starts nothing either, and the
    row says why, but leaves the fault counted, since whether the work is
    paused is then unknown.
    """
    if inspection.candidate is None and not inspection.is_counted_fault:
        return inspection
    row = inspection.row
    events = list_labelling_events(repository=context.repository, issue=row.issue)
    if isinstance(events, UnknownGitHubResponse):
        return replace(
            inspection,
            row=row.model_copy(
                update={"finding": ReadFailureFinding(reason=events.reason)}
            ),
            candidate=None,
        )
    label = identify_label(name=row.dispatch_label)
    applier = next(
        (
            event.account
            for event in reversed(events)
            if identify_label(name=event.label_name) == label
        ),
        "",
    )
    if is_login_of_account(login=applier, account=context.account):
        return inspection
    return replace(
        inspection,
        row=row.model_copy(
            update={"finding": LabelAppliedByOtherFinding(applier=applier)}
        ),
        candidate=None,
        is_counted_fault=False,
    )
