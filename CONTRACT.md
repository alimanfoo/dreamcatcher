# Agent-facing contracts

Contract version **1** covers assignments and issue conversations. See the
[compatibility policy](docs/compatibility.md#agent-contract) for what this
version promises and when it changes.

dreamcatcher watches a GitHub repository for issues that have been labelled for
implementation by an agent. The repository owner can configure which labels are
recognised by dreamcatcher, which agent harnesses run assignments (Claude Code
or Codex), and which assignment skill should guide the agent through the
implementation of an issue. This guide describes how to write an assignment
skill that works well with dreamcatcher.

To make this concrete, consider a hypothetical GitHub repository, where the
owner has configured dreamcatcher to look for issues with the "agent" label, and
to launch an agent for each labelled issue using an assignment skill named
"smith". For this to work, the "smith" assignment skill needs to follow this
guide.

Dreamcatcher adds one instruction to every assignment and conversation prompt:
every GitHub post the agent makes must end with this line on a line of its own:

```html
<!-- dreamcatcher -->
```

The marker is invisible when GitHub renders it. It distinguishes the agent's
posts from the user's, so Dreamcatcher does not deliver the agent's own words
back in a later round. It applies to every post, including pull request
descriptions, comments, inline replies and issues the agent files.

## Arguments

An assignment skill must accept a GitHub issue number as an argument, and it
must recognise that its purpose is to implement the work described in that
issue.

For example, the hypothetical "smith" skill should be able to be invoked with a
prompt like "/smith GH123" and to know its job is then to implement GitHub issue
number 123.

## Branch adoption

Before dreamcatcher starts an assignment, it fetches origin's main, cuts a
branch from it, adds a worktree on that branch, makes and pushes an empty
commit, and opens a linked draft pull request. The agent runs in that worktree,
so the published branch is checked out and the working tree is clean.

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
pull request rather than relying on its turn output. Dreamcatcher records that
output in the feed, but does not publish it as a message to the user.

An assignment skill must not instruct the agent to run anything that waits for a
person, such as a command that asks to be approved, an editor, or a prompt for
input. Nothing answers it, and the round stalls until dreamcatcher stops.

## Resumed rounds

dreamcatcher gives an agent a further round whenever there is more for it to do.
Each such round normally resumes the assignment's harness session where the last
one left off, so the agent still has what the earlier rounds said in front of
it, and dreamcatcher's prompt says what the round is for. When a recovery has no
session identifier to resume, Dreamcatcher starts a new session with the
assignment's first prompt followed by the prompt for the required round.

### User posts and feedback

dreamcatcher's prompt names a JSON file and asks the agent to read it.
`pull_request_state` in that file says where the pull request has got to, and
`user_posts` holds every user post not delivered to an earlier round, oldest
first. These posts are the user's feedback.

`pull_request_state` is one of `OPEN`, `MERGED` or `CLOSED`. Every object in
`user_posts` has `kind`, `id`, `author`, `written_at` and `body`. Its `kind`
determines the remaining fields:

- `comment` adds no fields;
- `review` adds `verdict`; and
- `inlineComment` adds `path`, `subject_type`, `side`, `line`, `start_line` and
  `diff_hunk`. Either line number may be `null` where GitHub supplies none.

The list includes only posts by the account through which `gh` was authenticated
that have a body, or a review verdict of `APPROVED` or `CHANGES_REQUESTED`. It
excludes posts carrying the agent marker and omits anything at or before the
latest delivery position. A review's `verdict` can also be `COMMENTED`,
`DISMISSED` or `PENDING` when its body says something.

An assignment skill must instruct the agent to read `pull_request_state` before
anything else, and, when `pull_request_state` reads `OPEN`, to act on every user
post in `user_posts` and reply on the pull request. Dreamcatcher derives the
assignment's user-post delivery position from its recorded round inputs, so
later ticks do not select those posts again.

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
normally still has its own transcript, and dreamcatcher's prompt is enough to
carry it on. A replacement session instead receives the assignment's first
prompt before the recovery prompt, so the skill's initial instructions apply
again.

A round that the user stopped is not a recovery round. An open assignment waits
for new feedback before it resumes, and that next prompt says the earlier round
was stopped before directing the agent to the new input. A merged or closed pull
request can proceed to its wrap-up round without new feedback.

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

Each object in `comments` has `kind` set to `comment`, followed by `id`,
`author`, `written_at` and `body`. Eligible comments are unmarked comments by
the account through which `gh` was authenticated, with a non-empty body. The
issue title and body do not by themselves ask the agent a question; the comments
are the request to answer.

The first input also contains `initial_issue`, an object holding the issue's
`title` and `body`. Ordinary follow-up inputs omit this object; the resumed
harness transcript keeps that original context.

The agent must answer the saved question from the checked-out code and return
its final answer as Markdown in the harness's final result. It returns exactly
`NO_REPLY` when no issue comment should be posted. Progress output and tool
activity are feed records, not the answer.

The first round receives every eligible existing comment. Each new comment batch
after that resumes the same harness session and contains only eligible comments
after the newest comment in the latest durable round input. The agent should use
its existing transcript when a new question refers to an earlier answer. Before
accepting a new batch, Dreamcatcher resets the idle worktree to fetched main,
deleting every local commit and file left by the earlier investigation. Recovery
instead reuses saved input and revision, as described below.

An issue conversation is investigation work. Its instructions may tell the agent
to read source and Git history, run code, reproduce a suspected bug, and make
issue changes on GitHub when the user asks, such as filing or linking a
subissue. Before making a GitHub change, the agent must inspect GitHub and must
not repeat an action that an earlier attempt completed. It must not close the
conversation issue or change its assignees or labels, because Dreamcatcher needs
the issue to remain eligible until the answer is published. It must not fetch
issue comments itself: the saved input is the comment set it must answer.

Its instructions must not tell the agent to implement a change, edit project
source, mutate Git, create a branch, commit or push, open or change a pull
request, post the conversation reply itself, or contact the user elsewhere.

Dreamcatcher reinforces that contract with harness-specific controls. Claude
allows selected `gh issue` commands and `gh api` while denying its direct
editing and Git mutation tool families, though its general command tool can
write files. Codex runs commands in a networked workspace-write sandbox so it
can use scratch files, local reproductions and authenticated GitHub commands,
while approval requests are rejected. These controls make the intended actions
practical rather than providing a hard security boundary. Local checkout writes
are discarded by the refresh before the next batch.

Dreamcatcher owns publication: when the harness exits successfully, the round
trims the final result, adds an agent attribution and the marker, and posts it
before the round ends. A missing or empty final result is an error. A failed
post makes the round errored.

Issue conversations run through Claude or Codex and keep the harness chosen at
creation. While the issue remains eligible, Dreamcatcher retries an interrupted
or errored round's saved input and revision without collecting comments or
refreshing the worktree. It resumes the recorded harness session with a recovery
prompt. If the first invocation did not record a session identifier, it starts a
new session with the configured prompt and the same saved input. The configured
conversation prompt needs no special recovery instructions.

A conversation round that the user stopped waits for a new eligible comment. The
next ordinary round uses a refreshed worktree and begins by saying that the
earlier round was stopped. It is not marked as a recovery round.
