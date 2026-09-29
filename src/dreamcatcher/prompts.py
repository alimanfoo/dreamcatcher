"""Compose assignment and issue-conversation prompts for agent rounds."""

from pathlib import Path

# The line that every post that an assignment makes on GitHub ends with. The daemon
# and the assignment share one GitHub account, so this is what tells the two
# apart: a post carrying it is the assignment's own, and the relay leaves it
# alone. It is a fixed literal with nothing in it to vary, and an HTML comment,
# so a reader of the post never sees it.
AGENT_POST_MARKER = "<!-- dreamcatcher -->"

# The word that a label's prompt template holds where the issue's number goes.
# It is the only substitution the dispatcher owns.
ISSUE_PLACEHOLDER = "{issue}"

# What every prompt that the daemon composes ends with, whichever harness runs
# the assignment and whatever woke it. The daemon adds this itself, so a skill it
# dispatches needs no knowledge of the marker.
AGENT_POST_INSTRUCTIONS = f"""

End every post you make on GitHub with this line, on a line of its own:

{AGENT_POST_MARKER}

The line tells dreamcatcher that the post is yours, so it never relays your
own words back to you. GitHub renders nothing for an HTML comment, so nobody
reading the post sees the line. Every post counts: a pull request's
description, a comment, a reply on a line of the diff, and an issue you file."""


# What a round that carries on from an unfinished one asks for. The transcript
# that the harness resumes carries the work itself, so the words say only that
# the round before this one stopped short. A round somebody interrupted and a
# round that failed both read that way, and either is recovered from where it
# stopped.
RECOVERY_PROMPT = (
    """Your previous round did not finish. Carry on from where it stopped, and
end your turn when the work is done."""
    + AGENT_POST_INSTRUCTIONS
)

# A conversation agent does not post on GitHub, so its recovery prompt carries
# no agent-post marker instructions.
ISSUE_CONVERSATION_RECOVERY_PROMPT = """Your earlier round was cut short, or its
answer could not be posted. Nothing from that round reached the issue. Carry on
from where it stopped.

Your final message must be the complete answer, as Markdown ready for
Dreamcatcher to post, or exactly NO_REPLY."""

STOPPED_ROUND_FEEDBACK_PROMPT = """The user stopped your previous round before it
finished. Their new feedback says what to do instead.

"""

# What a round resumed from the pull request asks for. It ports from the catcher
# this tool replaces, word for word. The user's own words are never in it: the
# posts go to a file, and this names the file. The file also says where the
# pull request has got to, which is what tells a round that answers the user
# from a round that wraps a merged or closed pull request up, so one prompt
# serves both.
USER_POSTS_PROMPT = """PR-inbox prompt for pull request #{pull_request}:

  {round_input}

Read that JSON file. Read pull_request_state before anything else. If
pull_request_state is MERGED or CLOSED, finish per your assignment's rules.
Otherwise act on user_posts per your assignment's rules. End your turn when
done."""

_ISSUE_CONVERSATION_ROUND_PROMPT = """Issue-conversation input for GH{issue}:

  {round_input}

Read that JSON file and answer the user's comments together. You may read the
source and Git history, run code, and reproduce a suspected bug. Do not edit
project source, mutate Git, mutate GitHub, or implement a change. Do not fetch
issue comments yourself or post a reply. Dreamcatcher supplies the comments and
publishes your final output. The `revision` field names the checked-out commit.

Return Markdown ready for Dreamcatcher to post, or exactly NO_REPLY when no
reply is needed."""


def compose_first_round_prompt(*, template: str, issue: int) -> str:
    """Return the first-round prompt for an issue.

    The selected recipe supplies the template, and the issue's
    number replaces the placeholder in it. Anything else that the template
    holds in braces reaches the first round as it was written.
    """
    return template.replace(ISSUE_PLACEHOLDER, str(issue)) + AGENT_POST_INSTRUCTIONS


def compose_user_posts_prompt(
    *, pull_request: int, round_input: Path, was_stopped: bool = False
) -> str:
    """Return the prompt that directs a resumed round to its input file.

    The input file holds the pull request state and the batch of user posts.
    """
    prompt = (
        USER_POSTS_PROMPT.format(
            pull_request=pull_request,
            round_input=round_input,
        )
        + AGENT_POST_INSTRUCTIONS
    )
    return _prefix_stopped_round_feedback(prompt=prompt) if was_stopped else prompt


def compose_issue_conversation_prompt(
    *, template: str, issue: int, round_input: Path
) -> str:
    """Return the first prompt that directs a conversation to its saved input."""
    instructions = template.replace(ISSUE_PLACEHOLDER, str(issue))
    round_prompt = compose_issue_conversation_round_prompt(
        issue=issue, round_input=round_input
    )
    return f"{instructions}\n\n{round_prompt}"


def compose_issue_conversation_round_prompt(
    *, issue: int, round_input: Path, was_stopped: bool = False
) -> str:
    """Return the prompt that directs a conversation round to its saved input."""
    prompt = _ISSUE_CONVERSATION_ROUND_PROMPT.format(
        issue=issue,
        round_input=round_input,
    )
    return _prefix_stopped_round_feedback(prompt=prompt) if was_stopped else prompt


def _prefix_stopped_round_feedback(*, prompt: str) -> str:
    return STOPPED_ROUND_FEEDBACK_PROMPT + prompt
