# Agent-facing contracts

dreamcatcher watches a GitHub repository for issues that have been labelled for
implementation by an agent. The repository owner can configure which labels are
recognised by dreamcatcher, which agent harnesses are used to dispatch an agent
(Claude Code or Codex), and which assignment skill should guide the agent
through the implementation of an issue. This guide describes how to write an
assignment skill that works well with dreamcatcher.

To make this concrete, consider a hypothetical GitHub repository, where the
owner has configured dreamcatcher to look for issues with the "agent" label, and
to launch an agent for each labelled issue using an assignment skill named
"smith". For this to work, the "smith" assignment skill needs to follow this
guide.

## Arguments

An assignment skill must accept a GitHub issue number as an argument, and it
must recognise that its purpose is to implement the work described in that
issue.

For example, the hypothetical "smith" skill should be able to be invoked with a
prompt like "/smith GH123" and to know its job is then to implement GitHub issue
number 123.

## Branch adoption

Before dreamcatcher dispatches an agent, it fetches origin's main, cuts a branch
from it, adds a worktree on that branch, makes and pushes an empty commit, and
opens a linked draft pull request. The agent runs in that worktree, so the
published branch is checked out and the working tree is clean.

An assignment skill must instruct the agent to adopt the current branch and
worktree. It must also adopt the draft pull request that dreamcatcher has
already opened rather than opening another one.

## Using the draft pull request

An assignment skill must use the draft pull request that is already open as its
primary channel of communication with the user. It must mark the pull request
ready when the implementation is ready for review.

## Linking the pull request to the issue

Dreamcatcher opens the draft pull request with `Closes #123` in its description,
using the issue given to the assignment. An assignment skill must preserve that
link when it replaces the description with its final account of the work.

## Ending a turn

dreamcatcher runs an agent in rounds, and a round is over when the agent's
process exits. An assignment skill must instruct the agent to end its turn once
it has nothing left to do, and to post anything it has to tell the user on the
pull request rather than in its turn output. The harness runs headless, so
nobody reads that output.

An assignment skill must not instruct the agent to run anything that waits for a
person, such as a command that asks to be approved, an editor, or a prompt for
input. Nothing answers it, and the round stalls until dreamcatcher stops.

## Resumed rounds

dreamcatcher gives an agent a further round whenever there is more for it to do.
Each such round resumes the assignment's harness session where the last one left
off, so the agent still has what the earlier rounds said in front of it, and
dreamcatcher's prompt says what the round is for.

### User posts and feedback

dreamcatcher's prompt names a JSON file and asks the agent to read it.
`pull_request_state` in that file says where the pull request has got to, and
`user_posts` holds every user post not delivered to an earlier round, oldest
first. These posts are the user's feedback.

An assignment skill must instruct the agent to read `pull_request_state` before
anything else, and, when `pull_request_state` reads `OPEN`, to act on every user
post in `user_posts` and reply on the pull request. dreamcatcher advances the
assignment's user-post delivery cursor after the round starts. Once that write
lands, later ticks do not deliver that post again.

### A merged or closed pull request

dreamcatcher gives the agent a wrap-up round when the user merges or closes the
pull request, with the same prompt naming the same file. `pull_request_state`
then reads `MERGED` or `CLOSED`, so an assignment skill that needs to
distinguish the two states reads `pull_request_state`. `user_posts` still holds
any feedback that the user posted before merging or closing.

An assignment skill must instruct the agent to wind the work up when
`pull_request_state` reads anything but `OPEN`.

### A recovery round

A recovery round follows a round that was interrupted or exited with an error.
While the pull request is open, dreamcatcher's prompt says that the previous
round did not finish and asks the agent to carry on. A recovery round on a
merged or closed pull request receives the user-posts prompt instead, whose
`pull_request_state` tells the agent to wind up.

An assignment skill needs nothing of its own for recovery. The resumed agent
still has its own transcript, and dreamcatcher's prompt is enough to carry it
on.

## Issue conversation instructions

An issue-conversation prompt asks an agent to answer a question on a GitHub
issue. It must accept the issue number in the same `GH123` form as an assignment
skill. Dreamcatcher adds the operational contract around the configured prompt
and names a JSON input file for the agent to read.

Every input contains:

- `issue`, identifying the watched issue;
- `comments`, containing the signed-in user's eligible issue comments in order;
- `revision`, identifying the fetched main commit checked out in the detached
  worktree.

The first input also contains the issue's `title` and `body`. Later rounds keep
those in their resumed harness transcript and receive only new comments.

The agent must answer the saved question from the checked-out code and return
its final answer as Markdown in the harness's final result. It returns exactly
`NO_REPLY` when no issue comment should be posted. Progress output and tool
activity are feed records, not the answer.

The first round receives every eligible existing comment. Each later round
resumes the same harness session and receives only eligible comments after the
newest comment in the latest durable round input. The agent should use its
existing transcript when a new question refers to an earlier answer. Before a
later round starts, Dreamcatcher asks Git to update the idle worktree to fetched
main, discarding every local worktree change left by the earlier investigation.

An issue conversation is investigation-only work. Its instructions must not tell
the agent to create a branch, commit or push, open a pull request, change the
issue, post to GitHub, or contact the user elsewhere. Dreamcatcher reinforces
that contract with harness-specific controls. Claude denies its direct editing
and GitHub mutation tool families, though its general command tool can write
files. Codex runs commands in a workspace-write sandbox so it can use scratch
files and local reproductions, while command network access is off and approval
requests are rejected. Local checkout writes are discarded by the refresh before
the next batch.

Dreamcatcher owns publication: when the harness exits successfully, the round
appends the agent marker to the final result and posts it before the round ends.
A failed post makes the round errored.

Issue conversations run through Claude or Codex and keep the harness chosen at
creation. While the issue remains eligible, Dreamcatcher retries an interrupted
or errored round's saved input and revision without collecting comments or
refreshing the worktree. It resumes the recorded harness session with a recovery
prompt. If the first invocation did not record a session identifier, it starts a
new session with the configured prompt and the same saved input. The configured
conversation prompt needs no special recovery instructions.
