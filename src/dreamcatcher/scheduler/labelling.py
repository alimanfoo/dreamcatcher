"""Hold work whose dispatch label the user did not apply themselves.

Work starts, and paused work resumes, only on a label that the user applied, so
a colleague who labels an issue assigned to the user starts nothing on the
user's machine.
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


def hold_unless_user_applied_label(
    *, context: SchedulingContext, inspection: Inspection
) -> Inspection:
    """Return the inspection, holding its candidate unless the user applied the label.

    The label is the row's dispatch label, and the user applied it when the
    latest event that applied it to the issue names the user's account. Only a
    candidate is checked, so the issue's events are read only for work that
    would start a round. A failed read holds the candidate too, and the row
    says why.
    """
    if inspection.candidate is None:
        return inspection
    row = inspection.row
    events = list_labelling_events(repository=context.repository, issue=row.issue)
    if isinstance(events, UnknownGitHubResponse):
        finding = ReadFailureFinding(reason=events.reason)
    else:
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
        finding = LabelAppliedByOtherFinding(applier=applier)
    return replace(
        inspection,
        row=row.model_copy(update={"finding": finding}),
        candidate=None,
    )
