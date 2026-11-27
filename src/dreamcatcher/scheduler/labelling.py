"""Start and resume work only on a dispatch label that the user applied.

A colleague who labels an issue assigned to the user, or puts back the label of
the user's paused work, then starts nothing on the user's machine.
"""

from dreamcatcher.config import identify_label
from dreamcatcher.github import (
    LabellingEvent,
    UnknownGitHubResponse,
    is_login_of_account,
    list_labelling_events,
)
from dreamcatcher.scheduler.inspection import SchedulingContext
from dreamcatcher.scheduler.models import LabelAppliedByOtherFinding, ReadFailureFinding


def read_user_label_application(
    *, context: SchedulingContext, issue: int, label: str
) -> LabellingEvent | LabelAppliedByOtherFinding | ReadFailureFinding:
    """Return the user's latest application of the label or what holds it.

    The latest application decides who applied the label. GitHub may record
    the event a few seconds after the label appears on the issue.
    """
    events = list_labelling_events(repository=context.repository, issue=issue)
    if isinstance(events, UnknownGitHubResponse):
        return ReadFailureFinding(reason=events.reason)
    identity = identify_label(name=label)
    application = next(
        (
            event
            for event in reversed(events)
            if identify_label(name=event.label_name) == identity
        ),
        None,
    )
    if application is None:
        return ReadFailureFinding(
            reason="GitHub has not yet recorded who applied the label"
        )
    if is_login_of_account(login=application.account, account=context.account):
        return application
    return LabelAppliedByOtherFinding(applier=application.account)
