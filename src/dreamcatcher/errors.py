"""The failures dreamcatcher reports to the user."""


class ReportableError(Exception):
    """A failure the user needs to read, so the command reports it as a message.

    Every failure the tool raises for the user to act on derives from this. The
    command line then reports them all the same way, and none reaches the user
    as a traceback. So anything that is not a ReportableError is a bug in the
    tool, and the user sees it as the traceback it is.
    """
