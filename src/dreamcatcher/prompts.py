"""Compose what the daemon asks a session to do."""

# The line that every post a session makes on GitHub ends with. The daemon and
# the session share one GitHub account, so this is what tells the two apart: a
# post carrying it is the session's own, and the relay leaves it alone. It is a
# fixed literal with nothing in it to vary, and an HTML comment, so a reader of
# the post never sees it.
MARKER = "<!-- dreamcatcher -->"

# The word a label's prompt template holds where the issue's number goes. It
# is the only substitution the dispatcher owns.
ISSUE_PLACEHOLDER = "{issue}"

# What every prompt the daemon composes ends with, so a session is asked to mark
# its posts however it was dispatched.
POSTSCRIPT = f"""

End every post you make on GitHub with this line, on a line of its own:

{MARKER}

That means a pull request's description, a comment, a reply on a line of the
diff, and an issue you file. The line tells dreamcatcher that the post is
yours, so it never relays your own words back to you. GitHub renders nothing
for an HTML comment, so nobody reading the post sees the line."""


def first_round(template: str, issue: int) -> str:
    """Return the prompt that opens a session on the issue.

    The template is the label's own, from the config, and the issue's number
    replaces the placeholder in it. Anything else the template holds in
    braces reaches the session as it was written.
    """
    return template.replace(ISSUE_PLACEHOLDER, str(issue)) + POSTSCRIPT
