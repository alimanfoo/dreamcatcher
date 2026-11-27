"""Compose the prompts for the agent rounds of every kind of agent work."""

from collections.abc import Sequence
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
GitHub when the user asks, such as filing a sub-issue. Inspect GitHub before each
change and do not repeat an action that an earlier attempt completed. Do not
close the conversation issue or change its assignees or labels, because closing
the issue ends the conversation and removing its label or assignee pauses it. Do
not fetch issue comments yourself, open or change a pull request, or post the
conversation reply yourself. dreamcatcher supplies the comments and publishes
your final output. The `revision` field names the checked-out commit.

Return Markdown ready for dreamcatcher to post, or exactly NO_REPLY when no
reply is needed."""


_CAMPAIGN_INPUT_PROMPT = """Campaign input for parent issue GH{issue}:

  {round_input}

Read that JSON file. Read `pull_request_state` before anything else. If it is
MERGED or CLOSED, wrap up per your campaign's rules and end your turn.

The `pull_request` field names the campaign's pull request. Act on every entry
in `user_posts`, the user's new posts on that pull request, and in
`notifications`, the sub-issue changes since your last delivered input. Each
notification names its sub-issue's `issue` and `changes`. The `children` field
describes the parent's sub-issues and their assignments. The
`assignment_routes` field holds the labels and recipes available for dispatch.

Take up the parent's sub-issues in either phase, including any the user adds
after the campaign's pull request is ready. Keep it ready while they run.
Inspect GitHub before each change and skip actions an earlier attempt completed.
To dispatch an assignment, assign the sub-issue to the signed-in account,
remove its assignment label if present, then add the label to make a new
request. Review and merge sub-issue pull requests into the campaign branch.
Run every `gh pr merge` as a shell command of its own, with no other command
joined to it.

{phase_instructions}

Do not add sub-issues or open another pull request. The user decides when to
merge the campaign's pull request. Do not merge it yourself or close the
parent. The user's merge closes the parent. Leave the parent's assignees and
labels as they are.

Post anything the user needs to read on the campaign's pull request yourself.
dreamcatcher keeps your final output in the feed. End your turn when done."""

_COORDINATING_INSTRUCTIONS = """\
dreamcatcher creates your worktree on the campaign branch and preserves your
checkout between rounds. Wait until you judge every sub-issue done before
editing project source, committing or pushing. Then switch to the campaign
branch and pull it to pick up the merged sub-issues. You may make your own
changes there. When finished, mark the campaign's pull request ready for review."""

_FINISHING_INSTRUCTIONS = """\
Carry the campaign's pull request to merge. Before acting on any signals or
making changes, switch to the campaign branch `{campaign_branch}` and pull it
to pick up any sub-issues merged since your last round. Make the changes the
user requests and commit and push your fixes to that branch."""


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
    pull_request_signals: Sequence[PullRequestSignal],
    is_previous_round_unfinished: bool,
) -> str:
    """Return the words that direct an assignment round to its input file.

    The input file holds the pull request state, the pull request signals and
    the batch of user posts. One line for each signal opens the words. After a
    round that errored or was interrupted, an open pull request's round is told
    to continue the unfinished assignment as well as act on the posts.
    """
    return _compose_signal_lines(signals=pull_request_signals) + (
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


def compose_campaign_input_prompt(
    *,
    issue: int,
    round_input: Path,
    finishing_branch: str | None = None,
    pull_request_signals: Sequence[PullRequestSignal] = (),
) -> str:
    """Direct a lead to its input, with finishing instructions when given a branch."""
    phase_instructions = (
        _COORDINATING_INSTRUCTIONS
        if finishing_branch is None
        else _FINISHING_INSTRUCTIONS.format(campaign_branch=finishing_branch)
    )
    return _compose_signal_lines(
        signals=pull_request_signals
    ) + _CAMPAIGN_INPUT_PROMPT.format(
        issue=issue, round_input=round_input, phase_instructions=phase_instructions
    )


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
    return "\n\n".join(parts) + (
        _CAMPAIGN_POST_INSTRUCTIONS
        if work_kind is AgentWorkKind.CAMPAIGN
        else _AGENT_POST_INSTRUCTIONS
    )


# What opens a round's input, by how the previous round ended.
_PREVIOUS_ROUND_LINES = {
    AgentRoundOutcome.STOPPED: _STOPPED_ROUND_LINE,
    AgentRoundOutcome.ERRORED: _UNFINISHED_ROUND_LINE,
    AgentRoundOutcome.INTERRUPTED: _UNFINISHED_ROUND_LINE,
}

# What opens a round's input, for each signal it relays.
_SIGNAL_LINES = {
    PullRequestSignal.OUT_OF_DATE: _OUT_OF_DATE_LINE,
    PullRequestSignal.CHECK_FAILURE: _CHECK_FAILURE_LINE,
}


def _compose_signal_lines(*, signals: Sequence[PullRequestSignal]) -> str:
    return "".join(_SIGNAL_LINES[signal] for signal in signals)
