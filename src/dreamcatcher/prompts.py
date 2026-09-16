"""Compose the prompts that the daemon starts and resumes an assignment with.

An assignment is asked something at each of the four points its life can turn on: a
dispatch opens it, an unfinished round is recovered, the user posts on the pull
request, and a merged or closed pull request calls for a wrap-up round. Every one
of those prompts ends with the same postscript, so an assignment marks its posts
whichever woke it.
"""

from pathlib import Path

# The line that every post that an assignment makes on GitHub ends with. The daemon
# and the assignment share one GitHub account, so this is what tells the two
# apart: a post carrying it is the assignment's own, and the relay leaves it
# alone. It is a fixed literal with nothing in it to vary, and an HTML comment,
# so a reader of the post never sees it.
MARKER = "<!-- dreamcatcher -->"

# The word that a label's prompt template holds where the issue's number goes.
# It is the only substitution the dispatcher owns.
ISSUE_PLACEHOLDER = "{issue}"

# What every prompt that the daemon composes ends with, whichever harness runs
# the assignment and whatever woke it. The daemon adds this itself, so a skill it
# dispatches needs no knowledge of the marker.
POSTSCRIPT = f"""

End every post you make on GitHub with this line, on a line of its own:

{MARKER}

The line tells dreamcatcher that the post is yours, so it never relays your
own words back to you. GitHub renders nothing for an HTML comment, so nobody
reading the post sees the line. Every post counts: a pull request's
description, a comment, a reply on a line of the diff, and an issue you file."""


# What a round that carries on from an unfinished one asks for. The transcript
# that the harness resumes carries the work itself, so the words say only that
# the round before this one stopped short. A round somebody interrupted and a
# round that failed both read that way, and either is recovered from where it
# stopped.
CARRY_ON_PROMPT = (
    """Your previous round did not finish. Carry on from where it stopped, and
end your turn when the work is done."""
    + POSTSCRIPT
)

# What a round woken by the pull request asks for. It ports from the catcher
# this tool replaces, word for word. The user's own words are never in it: the
# posts go to a file, and this names the file. The file also says where the
# pull request has got to, which is what tells a round that answers the user
# from a round that wraps a merged or closed pull request up, so one prompt
# serves both.
INBOX_PROMPT = """PR-inbox prompt for pull request #{pull_request}:

  {inbox}

Read that JSON file. Read state before anything else. If state is MERGED or
CLOSED, finish per your assignment's rules. Otherwise act on posts per your
assignment's rules. End your turn when done."""


def compose_first_round_prompt(*, template: str, issue: int) -> str:
    """Return the prompt that opens an assignment on the issue.

    The template is the label's own, from the config, and the issue's number
    replaces the placeholder in it. Anything else that the template holds in
    braces reaches the assignment as it was written.
    """
    return template.replace(ISSUE_PLACEHOLDER, str(issue)) + POSTSCRIPT


def compose_inbox_prompt(*, pull_request: int, inbox: Path) -> str:
    """Return the prompt that sends an assignment to the inbox a round was given.

    The pull request is the assignment's own, and the inbox is the file that the
    round writes the batch to before it starts.
    """
    return INBOX_PROMPT.format(pull_request=pull_request, inbox=inbox) + POSTSCRIPT
