"""Compose the prompts for the agent rounds of every kind of agent work."""

from pathlib import Path

from dreamcatcher.agent_rounds import AgentRoundOutcome
from dreamcatcher.github import PullRequestSignal
from dreamcatcher.harness_adapters import AgentWorkKind

# The line that every post an agent makes on GitHub ends with. The daemon and the
# agent share one GitHub account, so this is what tells the two apart: a post
# carrying it is the agent's own, and the relay leaves it alone. It is a fixed
# literal with nothing in it to vary, and an HTML comment, so a reader of the post
# never sees it.
AGENT_POST_MARKER = "<!-- dreamcatcher -->"

# The word that a recipe's prompt holds where the issue's number goes. It is
# the only substitution that dreamcatcher makes in it.
_ISSUE_PLACEHOLDER = "{issue}"

# What every prompt that the daemon composes ends with, whichever harness runs
# the round and whatever woke it, before the words that say which posts carry
# the marker. The daemon adds this itself, so a skill it dispatches needs no
# knowledge of the marker.
_AGENT_POST_MARKER_LINES = f"""

End every post you make on GitHub with this line, on a line of its own:

{AGENT_POST_MARKER}

The line tells dreamcatcher that the post is yours, so it never relays your
own words back to you. GitHub renders nothing for an HTML comment, so nobody
reading the post sees the line. """

# What ends an assignment's or a conversation's prompt, where the marker goes on
# every post.
_AGENT_POST_INSTRUCTIONS = (
    _AGENT_POST_MARKER_LINES
    + """Every post counts: a pull request's
description, a comment, a reply on a line of the diff, and an issue you file."""
)

# What ends a campaign's prompt. The lead shares the user's GitHub account, so
# its feedback on a sub-issue's pull request reaches the assignment's agent
# through the ordinary relay only when it carries no marker.
_CAMPAIGN_POST_INSTRUCTIONS = (
    _AGENT_POST_MARKER_LINES
    + """Every post counts, such as a comment, a review, a
reply on a line of the diff and an issue you file, with one exception. Leave the
line off feedback that you give a sub-issue's assignment on its pull request,
such as a correction that you request or an answer to its agent's question.
dreamcatcher relays an unmarked post on that pull request to the assignment's
agent, as it relays the user's."""
)


# What opens the input of a round whose previous round the user stopped.
_STOPPED_ROUND_LINE = """The user stopped your previous round before it
finished. The new input says what to do next.

"""

# What opens the input of a round whose previous round errored or was
# interrupted. The round is given the same input again, less anything the user
# has deleted and with anything that has arrived since, and some of what the
# previous round did may already be done.
_UNFINISHED_ROUND_LINE = """Your previous round did not finish. Some of what it
did may already be done, so check before you repeat an action. The new input
says what to do next.

"""

# What opens the input of a round woken because the pull request is behind its
# base branch or conflicts with it.
_OUT_OF_DATE_LINE = """Your pull request is behind its base branch or conflicts with
it. Merge the base branch in, resolve any conflicts, and push.

"""

# What opens the input of a round woken because a check failed at the pull
# request's head.
_CHECK_FAILURE_LINE = """Checks failed on your pull request's latest commit. Read
their output, fix the cause, and push.

"""

# What an assignment round is given once its pull request exists. The user's own
# words are never in it: the posts go to a file, and this names the file. The
# file also says where the pull request has got to, which is what tells a round
# that answers the user from a round that wraps a merged or closed pull request
# up, so one prompt serves both. A round woken by a signal alone has no posts,
# and the signal's line before this prompt says what to do.
_ASSIGNMENT_INPUT_PROMPT = """Assignment input for pull request #{pull_request}:

  {round_input}

Read that JSON file. Read pull_request_state before anything else. If
pull_request_state is MERGED or CLOSED, finish per your assignment's rules.
Otherwise {open_work} End your turn when done."""

# What an open pull request's round does with its input.
_RELAY_WORK = """act on every post in user_posts, if it holds any, per your
assignment's rules."""

# What an open pull request's round does after a round that did not finish. Its
# input may hold nothing new, and the assignment is still not done.
_CONTINUED_WORK = """continue the unfinished assignment from where you stopped,
and act on every post in user_posts, if it holds any, per your assignment's
rules. Empty user_posts and signals do not mean the assignment is complete."""

_CONVERSATION_INPUT_PROMPT = """Issue-conversation input for GH{issue}:

  {round_input}

Read that JSON file and answer the user's comments together. You may read the
source and Git history, run code, and reproduce a suspected bug. Do not edit
project source, mutate Git, or implement a change. You may make issue changes on
GitHub when the user asks, such as filing a subissue. Inspect GitHub before each
change and do not repeat an action that an earlier attempt completed. Do not
close the conversation issue or change its assignees or labels, because closing
the issue ends the conversation and removing its label or assignee pauses it. Do
not fetch issue comments yourself, open or change a pull request, or post the
conversation reply yourself. dreamcatcher supplies the comments and publishes
your final output. The `revision` field names the checked-out commit.

Return Markdown ready for dreamcatcher to post, or exactly NO_REPLY when no
reply is needed."""


# What a campaign round is given beside its instructions. The lead works through
# GitHub and publishes its own messages, so the prompt names the input and the
# limits that keep the campaign in the user's hands. The user's comments go to
# the input file, never into the prompt.
_CAMPAIGN_INPUT_PROMPT = """Campaign input for parent issue GH{issue}:

  {round_input}

Read that JSON file. Act on every comment in `comments`, the user's new comments
on the parent issue, and every entry in `notifications`, the sub-issues whose
changes since your previous delivered input call for you, if either holds any,
per your campaign's rules. A round that errored or was interrupted delivered
nothing, so after one the notifications run from the input before it, and you
may already have acted on some of them. Each notification names its sub-issue's
`issue` and its `changes`. The `children` field is the current picture of the
parent's sub-issues and their assignments, and `assignment_routes` holds the
labels and recipes that the running daemon can dispatch a sub-issue's assignment
with. The `revision` field names the commit of main checked out in your
worktree, which dreamcatcher refreshes to main before every round, discarding
any local change. Do not commit, push or open a pull request from this worktree.
Inspect GitHub before each change and do not repeat an action that an earlier
attempt completed. Do not close the parent issue or change its assignees or
labels, because the user closes it to end the campaign and removing its label or
assignee pauses it. Post anything the user needs to read on GitHub yourself:
dreamcatcher keeps your final output in the feed and posts none of it. End your
turn when done."""


def compose_issue_instructions(*, template: str, issue: int) -> str:
    """Fill the issue placeholder in a recipe's prompt instructions.

    Anything else that the template holds in braces reaches the agent as it was
    written.
    """
    return template.replace(_ISSUE_PLACEHOLDER, str(issue))


def compose_assignment_input_prompt(
    *,
    pull_request: int,
    round_input: Path,
    pull_request_signals: list[PullRequestSignal],
    is_previous_round_unfinished: bool,
) -> str:
    """Return the words that direct an assignment round to its input file.

    The input file holds the pull request state, the pull request signals and
    the batch of user posts. One line for each signal opens the words. After a
    round that errored or was interrupted, an open pull request's round is told
    to continue the unfinished assignment as well as act on the posts.
    """
    return "".join(_SIGNAL_LINES[signal] for signal in pull_request_signals) + (
        _ASSIGNMENT_INPUT_PROMPT.format(
            pull_request=pull_request,
            round_input=round_input,
            open_work=(
                _CONTINUED_WORK if is_previous_round_unfinished else _RELAY_WORK
            ),
        )
    )


def compose_conversation_input_prompt(*, issue: int, round_input: Path) -> str:
    """Return the words that direct a conversation round to its input file."""
    return _CONVERSATION_INPUT_PROMPT.format(issue=issue, round_input=round_input)


def compose_campaign_input_prompt(*, issue: int, round_input: Path) -> str:
    """Return the words that direct a campaign round to its input file."""
    return _CAMPAIGN_INPUT_PROMPT.format(issue=issue, round_input=round_input)


def compose_round_prompt(
    *,
    instructions: str,
    is_resuming: bool,
    input_prompt: str | None,
    previous_outcome: AgentRoundOutcome | None,
    work_kind: AgentWorkKind,
) -> str:
    """Return the whole prompt for one round of agent work.

    A round that resumes a harness session and has input to relay is given that
    input alone. Any other round begins with the work's instructions, because a
    new session has not seen them. The input opens with a line saying why the
    previous round ended when the user stopped it or it did not finish. The
    prompt ends by saying which of the agent's posts carry the agent marker,
    which depends on the kind of work.
    """
    parts = [] if is_resuming and input_prompt is not None else [instructions]
    if input_prompt is not None:
        parts.append(_PREVIOUS_ROUND_LINES.get(previous_outcome, "") + input_prompt)
    return "\n\n".join(parts) + _POST_INSTRUCTIONS[work_kind]


# What opens a round's input, by how the previous round ended.
_PREVIOUS_ROUND_LINES = {
    AgentRoundOutcome.STOPPED: _STOPPED_ROUND_LINE,
    AgentRoundOutcome.ERRORED: _UNFINISHED_ROUND_LINE,
    AgentRoundOutcome.INTERRUPTED: _UNFINISHED_ROUND_LINE,
}

# What ends a round's prompt, by the kind of its work.
_POST_INSTRUCTIONS = {
    AgentWorkKind.ASSIGNMENT: _AGENT_POST_INSTRUCTIONS,
    AgentWorkKind.CONVERSATION: _AGENT_POST_INSTRUCTIONS,
    AgentWorkKind.CAMPAIGN: _CAMPAIGN_POST_INSTRUCTIONS,
}

# What opens a round's input, for each signal it relays.
_SIGNAL_LINES = {
    PullRequestSignal.OUT_OF_DATE: _OUT_OF_DATE_LINE,
    PullRequestSignal.CHECK_FAILURE: _CHECK_FAILURE_LINE,
}
