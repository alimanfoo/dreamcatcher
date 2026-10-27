"""Start and resume work only on a dispatch label that the user applied.

A colleague who labels an issue assigned to the user, or puts back the label of
the user's paused work, then starts nothing on the user's machine.
"""

from dreamcatcher.config import identify_label
from dreamcatcher.github import (
    UnknownGitHubResponse,
    is_login_of_account,
    list_labelling_events,
)
from dreamcatcher.scheduler.inspection import SchedulingContext
from dreamcatcher.scheduler.models import LabelAppliedByOtherFinding, ReadFailureFinding


def find_label_applied_by_other(
    *, context: SchedulingContext, issue: int, label: str
) -> LabelAppliedByOtherFinding | ReadFailureFinding | None:
    """Return who applied the label on the issue when it was not the user.

    The account that applied it is the one that the latest event applying it
    names. None means that the user applied it. GitHub records the event a few
    seconds after the label appears, so a label with no event yet cannot tell
    who applied it, just as a read that fails cannot.
    """
    events = list_labelling_events(repository=context.repository, issue=issue)
    if isinstance(events, UnknownGitHubResponse):
        return ReadFailureFinding(reason=events.reason)
    identity = identify_label(name=label)
    applier = next(
        (
            event.account
            for event in reversed(events)
            if identify_label(name=event.label_name) == identity
        ),
        None,
    )
    if applier is None:
        return ReadFailureFinding(
            reason="GitHub has not yet recorded who applied the label"
        )
    if is_login_of_account(login=applier, account=context.account):
        return None
    return LabelAppliedByOtherFinding(applier=applier)
