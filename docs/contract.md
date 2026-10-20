# Agent-facing contract

Contract version **1** covers assignments and issue conversations. See the
[compatibility policy](compatibility.md#agent-contract) for what this version
promises and when it changes.

This page contains two contracts. The assignment skill contract covers a skill
that guides an agent through an agent assignment. The conversation skill
contract covers a skill that guides an agent through an issue conversation.

For working examples, read the skills in
[dream](https://alimanfoo.github.io/dream/) that follow this contract: the
[`dream:smith`](https://github.com/alimanfoo/dream/blob/main/plugins/dream/skills/smith/SKILL.md)
and
[`dream:less`](https://github.com/alimanfoo/dream/blob/main/plugins/dream/skills/less/SKILL.md)
assignment skills, and the
[`dream:scout`](https://github.com/alimanfoo/dream/blob/main/plugins/dream/skills/scout/SKILL.md)
conversation skill.

## Assignment skill contract

An assignment skill must guide the agent to implement the issue on the branch
and pull request that _dreamcatcher_ prepared, then continue the assignment
through review and wrap-up.

### Arguments

An assignment skill must accept a GitHub issue number as an argument, and it
must recognise that its purpose is to implement the work described in that
issue.

For example, an assignment skill named "smith" should be able to be invoked with
a prompt like "/smith GH123" and know that its job is to implement GitHub issue
number 123.

### Branch adoption

Before _dreamcatcher_ runs the agent in the round that opens an assignment's
pull request, it fetches origin's main, cuts a branch from it, adds a worktree
on that branch, makes and pushes an empty commit, and opens a linked draft pull
request. The agent runs in that worktree, so the published branch is checked out
and the working tree is clean.

An assignment skill must instruct the agent to adopt the current branch and
worktree. It must also adopt the draft pull request that _dreamcatcher_ has
already opened rather than opening another one.

### Using the draft pull request

An assignment skill must use the draft pull request that is already open as its
primary channel of communication with the user. It must mark the pull request
ready when the implementation is ready for review.

### Linking the pull request to the issue

_dreamcatcher_ opens the draft pull request with `Closes #123` in its
description, using the issue given to the assignment. An assignment skill must
preserve that link when it replaces the description with its final account of
the work.

### Ending a turn

_dreamcatcher_ runs an agent in rounds, and a round is over when the agent's
process exits. An assignment skill must instruct the agent to end its turn once
it has nothing left to do, and to post anything it has to tell the user on the
pull request rather than relying on its turn output. _dreamcatcher_ records that
output in the feed, but does not publish it as a message to the user.

An assignment skill must not instruct the agent to run anything that waits for a
person, such as a command that asks to be approved, an editor, or a prompt for
input. Nothing answers it, and the round stalls until _dreamcatcher_ stops.

### Resumed rounds

_dreamcatcher_ gives an agent a further round whenever there is more for it to
do. Each such round normally resumes the assignment's harness session where the
last one left off, so the agent still has what the earlier rounds said in front
of it, and _dreamcatcher_'s prompt names the round's input. When there is no
session identifier to resume, _dreamcatcher_ starts a new session with the
assignment's configured prompt followed by the prompt naming the input.

#### User posts and feedback

_dreamcatcher_'s prompt names a JSON file and asks the agent to read it.
`pull_request_state` in that file says where the pull request has got to, and
`user_posts` holds every user post that no earlier round has relayed, oldest
first. These posts are the user's feedback.

`pull_request_state` is one of `OPEN`, `MERGED` or `CLOSED`. `pull_request_head`
is the pull request's head commit when the round started. `signals` lists what
else in the pull request woke the round, as described below, and is empty for a
round that the user's posts alone woke. Every object in `user_posts` has `kind`,
`id`, `author`, `written_at` and `body`. Its `kind` determines the remaining
fields:

- `comment` adds no fields;
- `review` adds `verdict`; and
- `inlineComment` adds `path`, `subject_type`, `side`, `line`, `start_line` and
  `diff_hunk`. Either line number may be `null` where GitHub supplies none.

The list includes only posts by the account through which `gh` was authenticated
that have a body, or a review verdict of `APPROVED` or `CHANGES_REQUESTED`. It
excludes the agent's own posts and omits anything at or before the newest post
that an earlier round relayed. A review's `verdict` can also be `COMMENTED`,
`DISMISSED` or `PENDING` when its body says something.

An assignment skill must instruct the agent to read `pull_request_state` before
anything else, and, when `pull_request_state` reads `OPEN`, to act on every user
post in `user_posts` and reply on the pull request. _dreamcatcher_ reads how far
the agent has read from its recorded round inputs, so later updates do not
select those posts again.

#### An out-of-date pull request or failing checks

_dreamcatcher_ also wakes the agent when a pull request that is ready for review
needs work that no user asked for. `signals` then holds one or both of these
values, and the part of _dreamcatcher_'s prompt that names the input opens with
one line for each, after any line about the previous round:

- `out_of_date`: the pull request is behind its base branch or conflicts with
  it. The line asks the agent to merge the base branch in, resolve any
  conflicts, and push.
- `check_failure`: a check failed at the pull request's head. The line asks the
  agent to read the checks' output, fix the cause, and push.

A round that takes its turn relays each once for each head commit, so an agent
that pushes nothing is not woken again for the same one. After two rounds in a
row relayed a check failure, _dreamcatcher_ withholds the next one until a round
relays something else, such as a user post. A draft raises neither.

An assignment skill needs nothing of its own for this. The prompt's lines carry
the instructions, and a skill may ignore `pull_request_head` and `signals`. The
assignment's harness may run `gh pr checks` and `gh run view` without asking, so
the agent can read the output of a check that failed.

#### A merged or closed pull request

_dreamcatcher_ gives the agent a wrap-up round when the user merges or closes
the pull request, with the same prompt naming the same file.
`pull_request_state` then reads `MERGED` or `CLOSED`, so an assignment skill
that needs to distinguish the two states reads `pull_request_state`.
`user_posts` still holds any feedback that the user posted before merging or
closing.

An assignment skill must instruct the agent to wind the work up when
`pull_request_state` reads anything but `OPEN`.

#### After a round that did not finish

A round that was interrupted or errored did not finish its turn, so the next
round is given the same input again: `user_posts` holds the posts that round was
given and any that arrived since, `signals` holds the signals it was given that
still hold, and `pull_request_state` says where the pull request has got to now.
_dreamcatcher_'s prompt opens with a line saying that the previous round did not
finish, and that some of what it did may already be done, before it names the
input. `user_posts` may be empty, in which case the agent carries on with the
work in hand.

An assignment skill needs nothing of its own for this. The resumed agent
normally still has its own transcript. A new session instead receives the
assignment's configured prompt before the input, so the skill's initial
instructions apply again.

A round that the user stopped took its turn, so its input is not given again. An
open assignment waits for new feedback, or for a signal at a head not yet
relayed, before it resumes, and that next prompt says the earlier round was
stopped before directing the agent to the new input. A merged or closed pull
request can proceed to its wrap-up round without new feedback.

## Conversation skill contract

A conversation skill must guide the agent to investigate and answer the user's
questions without implementing a change. It must accept the issue number in the
same `GH123` form as an assignment skill. _dreamcatcher_ adds the input,
publication and operational instructions around the configured prompt. These
instructions set the investigation scope and output form, so the skill does not
need to repeat them and must not contradict them.

### Input

Every input contains:

- `issue`, identifying the watched issue;
- `comments`, containing the signed-in user's eligible issue comments in order;
- `revision`, identifying the fetched main commit checked out in the detached
  worktree.

Each object in `comments` has `kind` set to `comment`, followed by `id`,
`author`, `written_at` and `body`. Eligible comments are unmarked comments by
the account through which `gh` was authenticated, with a non-empty body. The
issue title and body do not by themselves ask the agent a question; the comments
are the request to answer.

The input of a round that starts a new harness session also contains
`initial_issue`, an object holding the issue's `title` and `body`. Inputs of
rounds that resume the session omit this object; the resumed harness transcript
keeps that original context.

### Answer

The agent must answer the saved question from the checked-out code and return
its final answer as Markdown in the harness's final result. It returns exactly
`NO_REPLY` when no issue comment should be posted. Progress output and tool
activity are feed records, not the answer.

### Continued conversations

The first round receives every eligible existing comment. Each new comment batch
after that resumes the same harness session and contains only eligible comments
after the newest comment given to a round that finished its turn. The agent
should use its existing transcript when a new question refers to an earlier
answer. Before every round, _dreamcatcher_ resets the worktree to fetched main,
deleting every local commit and file left by the earlier investigation.

### Investigation scope

An issue conversation is investigation work. Its instructions may tell the agent
to read source and Git history, run code, reproduce a suspected bug, and make
issue changes on GitHub when the user asks, such as filing or linking a
subissue. Before making a GitHub change, the agent must inspect GitHub and must
not repeat an action that an earlier attempt completed. It must not close the
conversation issue or change its assignees or labels, because closing the issue
ends the conversation and removing its label or assignee pauses it. It must not
fetch issue comments itself: the saved input is the comment set it must answer.

Its instructions must not tell the agent to implement a change, edit project
source, mutate Git, create a branch, commit or push, open or change a pull
request, post the conversation reply itself, or contact the user elsewhere.

### Publication

_dreamcatcher_ owns publication: when the harness exits successfully, the round
trims the final result, adds an agent attribution and posts it before the round
ends. A missing or empty final result is an error. A failed post makes the round
errored.

### Rounds that did not finish and stopped rounds

Issue conversations run through Claude or Codex and keep the harness chosen at
creation. While the conversation is not paused, the round after an interrupted
or errored one is given that round's comments again, less any the user has
deleted and with any that arrived since, against a refreshed worktree. When the
user has deleted them all, no round starts until a new eligible comment arrives.
Its prompt opens by saying that the previous round did not finish. It resumes
the recorded harness session, or starts a new session with the configured prompt
and the issue's title and body when no session identifier was recorded. The
configured conversation prompt needs no special instructions for this.

A conversation round that the user stopped waits for a new eligible comment. The
next round begins by saying that the earlier round was stopped.
