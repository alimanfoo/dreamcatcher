"""Define failures that Dreamcatcher reports without a traceback."""


class ReportableError(Exception):
    """Mark a failure that the user can act on.

    Every failure the tool raises for the user to act on derives from this. The
    command line catches these failures and prints their messages. Other
    exceptions reach the user as tracebacks because they indicate bugs.
    """
