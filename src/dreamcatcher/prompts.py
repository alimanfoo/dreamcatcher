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
_ISSUE_PLACEHOLDER = "{issue}"

# What every prompt that the daemon composes ends with, whichever harness runs
# the assignment and whatever woke it. The daemon adds this itself, so a skill it
# dispatches needs no knowledge of the marker.
_AGENT_POST_INSTRUCTIONS = f"""

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
    + _AGENT_POST_INSTRUCTIONS
)

CONVERSATION_RECOVERY_PROMPT = (
    """Your earlier round was cut short, or its
answer could not be posted. Carry on from where it stopped.

Some issue actions may already have succeeded. Inspect GitHub before repeating
any action.

Your final message must be the complete answer, as Markdown ready for
Dreamcatcher to post, or exactly NO_REPLY."""
    + _AGENT_POST_INSTRUCTIONS
)

_STOPPED_ROUND_FEEDBACK_PROMPT = """The user stopped your previous round before it
finished. The new input says what to do next.

"""

# What a round resumed from the pull request asks for. It ports from the catcher
# this tool replaces, word for word. The user's own words are never in it: the
# posts go to a file, and this names the file. The file also says where the
# pull request has got to, which is what tells a round that answers the user
# from a round that wraps a merged or closed pull request up, so one prompt
# serves both.
_USER_POSTS_PROMPT = """PR-inbox prompt for pull request #{pull_request}:

  {round_input}

Read that JSON file. Read pull_request_state before anything else. If
pull_request_state is MERGED or CLOSED, finish per your assignment's rules.
Otherwise act on user_posts per your assignment's rules. End your turn when
done."""

_CONVERSATION_ROUND_PROMPT = (
    """Issue-conversation input for GH{issue}:

  {round_input}

Read that JSON file and answer the user's comments together. You may read the
source and Git history, run code, and reproduce a suspected bug. Do not edit
project source, mutate Git, or implement a change. You may make issue changes on
GitHub when the user asks, such as filing a subissue. Inspect GitHub before each
change and do not repeat an action that an earlier attempt completed. Do not
close the conversation issue or change its assignees or labels, because
Dreamcatcher needs it to remain eligible until your answer is published. Do not
fetch issue comments yourself, open or change a pull request, or post the
conversation reply yourself. Dreamcatcher supplies the comments and publishes
your final output. The `revision` field names the checked-out commit.

Return Markdown ready for Dreamcatcher to post, or exactly NO_REPLY when no
reply is needed."""
    + _AGENT_POST_INSTRUCTIONS
)


def compose_first_round_prompt(*, template: str, issue: int) -> str:
    """Return the first-round prompt for an issue.

    The selected recipe supplies the template, and the issue's
    number replaces the placeholder in it. Anything else that the template
    holds in braces reaches the first round as it was written.
    """
    instructions = compose_issue_instructions(template=template, issue=issue)
    return instructions + _AGENT_POST_INSTRUCTIONS


def compose_issue_instructions(*, template: str, issue: int) -> str:
    """Fill the issue placeholder in a recipe's prompt instructions."""
    return template.replace(_ISSUE_PLACEHOLDER, str(issue))


def compose_user_posts_prompt(
    *, pull_request: int, round_input: Path, was_stopped: bool = False
) -> str:
    """Return the prompt that directs a resumed round to its input file.

    The input file holds the pull request state and the batch of user posts.
    """
    prompt = (
        _USER_POSTS_PROMPT.format(
            pull_request=pull_request,
            round_input=round_input,
        )
        + _AGENT_POST_INSTRUCTIONS
    )
    return _prefix_stopped_round_feedback(prompt=prompt) if was_stopped else prompt


def compose_conversation_prompt(*, instructions: str, round_prompt: str) -> str:
    """Add a conversation round prompt to the saved recipe instructions."""
    return f"{instructions}\n\n{round_prompt}"


def compose_conversation_round_prompt(
    *, issue: int, round_input: Path, was_stopped: bool = False
) -> str:
    """Return the prompt that directs a conversation round to its saved input."""
    prompt = _CONVERSATION_ROUND_PROMPT.format(
        issue=issue,
        round_input=round_input,
    )
    return _prefix_stopped_round_feedback(prompt=prompt) if was_stopped else prompt


def _prefix_stopped_round_feedback(*, prompt: str) -> str:
    return _STOPPED_ROUND_FEEDBACK_PROMPT + prompt
