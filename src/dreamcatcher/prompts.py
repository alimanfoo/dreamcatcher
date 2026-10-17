"""Compose assignment and issue-conversation prompts for agent rounds."""

from pathlib import Path

from dreamcatcher.agent_rounds import AgentRoundOutcome

# The line that every post an agent makes on GitHub ends with. The daemon and the
# agent share one GitHub account, so this is what tells the two apart: a post
# carrying it is the agent's own, and the relay leaves it alone. It is a fixed
# literal with nothing in it to vary, and an HTML comment, so a reader of the post
# never sees it.
AGENT_POST_MARKER = "<!-- dreamcatcher -->"

# The word that a label's prompt template holds where the issue's number goes.
# It is the only substitution the dispatcher owns.
_ISSUE_PLACEHOLDER = "{issue}"

# What every prompt that the daemon composes ends with, whichever harness runs
# the round and whatever woke it. The daemon adds this itself, so a skill it
# dispatches needs no knowledge of the marker.
_AGENT_POST_INSTRUCTIONS = f"""

End every post you make on GitHub with this line, on a line of its own:

{AGENT_POST_MARKER}

The line tells dreamcatcher that the post is yours, so it never relays your
own words back to you. GitHub renders nothing for an HTML comment, so nobody
reading the post sees the line. Every post counts: a pull request's
description, a comment, a reply on a line of the diff, and an issue you file."""


# What opens the input of a round whose previous round the user stopped.
_STOPPED_ROUND_LINE = """The user stopped your previous round before it
finished. The new input says what to do next.

"""

# What opens the input of a round whose previous round errored or was
# interrupted. The round is given the same input again, with anything that has
# arrived since, and some of what the previous round did may already be done.
_UNFINISHED_ROUND_LINE = """Your previous round did not finish. Some of what it
did may already be done, so check before you repeat an action. The new input
says what to do next.

"""

# What a round resumed from the pull request asks for. It ports from the catcher
# this tool replaces, word for word. The user's own words are never in it: the
# posts go to a file, and this names the file. The file also says where the
# pull request has got to, which is what tells a round that answers the user
# from a round that wraps a merged or closed pull request up, so one prompt
# serves both.
_ASSIGNMENT_INPUT_PROMPT = """User-posts prompt for pull request #{pull_request}:

  {round_input}

Read that JSON file. Read pull_request_state before anything else. If
pull_request_state is MERGED or CLOSED, finish per your assignment's rules.
Otherwise act on user_posts per your assignment's rules. End your turn when
done."""

_CONVERSATION_INPUT_PROMPT = """Issue-conversation input for GH{issue}:

  {round_input}

Read that JSON file and answer the user's comments together. You may read the
source and Git history, run code, and reproduce a suspected bug. Do not edit
project source, mutate Git, or implement a change. You may make issue changes on
GitHub when the user asks, such as filing a subissue. Inspect GitHub before each
change and do not repeat an action that an earlier attempt completed. Do not
close the conversation issue or change its assignees or labels, because
dreamcatcher needs it to remain eligible until your answer is published. Do not
fetch issue comments yourself, open or change a pull request, or post the
conversation reply yourself. dreamcatcher supplies the comments and publishes
your final output. The `revision` field names the checked-out commit.

Return Markdown ready for dreamcatcher to post, or exactly NO_REPLY when no
reply is needed."""


def compose_issue_instructions(*, template: str, issue: int) -> str:
    """Fill the issue placeholder in a recipe's prompt instructions.

    Anything else that the template holds in braces reaches the agent as it was
    written.
    """
    return template.replace(_ISSUE_PLACEHOLDER, str(issue))


def compose_assignment_input_prompt(*, pull_request: int, round_input: Path) -> str:
    """Return the words that direct an assignment round to its input file.

    The input file holds the pull request state and the batch of user posts.
    """
    return _ASSIGNMENT_INPUT_PROMPT.format(
        pull_request=pull_request, round_input=round_input
    )


def compose_conversation_input_prompt(*, issue: int, round_input: Path) -> str:
    """Return the words that direct a conversation round to its input file."""
    return _CONVERSATION_INPUT_PROMPT.format(issue=issue, round_input=round_input)


def compose_round_prompt(
    *,
    instructions: str,
    is_resuming: bool,
    input_prompt: str | None,
    previous_outcome: AgentRoundOutcome | None,
) -> str:
    """Return the whole prompt for one round of agent work.

    A round that resumes a harness session and has input to relay is given that
    input alone. Any other round begins with the work's instructions, because a
    new session has not seen them. The input opens with a line saying why the
    previous round ended when the user stopped it or it did not finish.
    """
    parts = [] if is_resuming and input_prompt is not None else [instructions]
    if input_prompt is not None:
        parts.append(_PREVIOUS_ROUND_LINES.get(previous_outcome, "") + input_prompt)
    return "\n\n".join(parts) + _AGENT_POST_INSTRUCTIONS


# What opens a round's input, by how the previous round ended.
_PREVIOUS_ROUND_LINES = {
    AgentRoundOutcome.STOPPED: _STOPPED_ROUND_LINE,
    AgentRoundOutcome.ERRORED: _UNFINISHED_ROUND_LINE,
    AgentRoundOutcome.INTERRUPTED: _UNFINISHED_ROUND_LINE,
}
