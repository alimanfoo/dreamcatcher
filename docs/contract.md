# Agent-facing contract

Contract version **1** covers assignments, campaigns and issue
conversations. See the
[compatibility policy](compatibility.md#agent-contract) for what this
version promises and when it changes.

This page contains three contracts. The assignment skill contract covers
a skill that guides an agent through an agent assignment. The campaign
skill contract covers a skill that guides a lead through a campaign. The
conversation skill contract covers a skill that guides an agent through
an issue conversation.

Each contract holds what _dreamcatcher_ relies on a skill to do and does
not ask of the agent itself. Every round's prompt adds _dreamcatcher_'s
own instructions around the dispatch recipe's prompt, and this page says
what they tell the agent. A skill does not need to repeat them and must
not contradict them. The same holds for a recipe whose prompt gives the
agent its instructions directly.

For working examples, read the skills in
[dream](https://alimanfoo.github.io/dream/) that follow this contract:
the `dream:smith` and `dream:less` assignment skills, the `dream:big`
campaign skill, and the `dream:scout` conversation skill.

## Default routes

`dreamcatcher init` installs the `dream@dream` plugin from the
`alimanfoo/dream` marketplace, and writes dispatch routes whose recipes
invoke dream's skills by name with the issue number in the `GH{issue}`
form:

| Label                   | Claude prompt            | Codex prompt             |
| ----------------------- | ------------------------ | ------------------------ |
| `agent-assignment`      | `/dream:smith GH{issue}` | `$dream:smith GH{issue}` |
| `agent-assignment-easy` | `/dream:less GH{issue}`  | `$dream:less GH{issue}`  |
| `agent-campaign`        | `/dream:big GH{issue}`   | `$dream:big GH{issue}`   |
| `agent-conversation`    | `/dream:scout GH{issue}` | `$dream:scout GH{issue}` |

These routes rely on dream keeping the marketplace, the plugin and the
four skill names, and on each skill accepting its issue in that form and
following the contract for its kind of work.

## Assignment skill contract

An assignment skill must guide the agent to implement the issue on the
branch and pull request that _dreamcatcher_ prepared, then continue the
assignment through review and wrap-up.

### Arguments

An assignment skill must accept a GitHub issue number as an argument,
and it must recognise that its purpose is to implement the work
described in that issue.

For example, an assignment skill named "smith" should be able to be
invoked with a prompt like "/smith GH123" and know that its job is to
implement GitHub issue number 123.

### Branch adoption

Before _dreamcatcher_ runs the agent in the round that opens an
assignment's pull request, it fetches the default branch, cuts a branch
from it, adds a worktree on that branch, makes and pushes an empty
commit, and opens a linked draft pull request into the default branch.
The agent runs in that worktree, so the published branch is checked out
and the working tree is clean.

An assignment skill must instruct the agent to adopt the current branch
and worktree. It must also adopt the draft pull request that
_dreamcatcher_ has already opened rather than opening another one.

### Using the draft pull request

An assignment skill must use the draft pull request that is already open
as its primary channel of communication with the user. It must mark the
pull request ready when the implementation is ready for review.

### Linking the pull request to the issue

_dreamcatcher_ opens the draft pull request with `Closes #123` in its
description, using the issue given to the assignment. An assignment
skill must preserve that link when it replaces the description with its
final account of the work.

### Ending a turn

_dreamcatcher_ runs an agent in rounds, and a round's harness invocation
is over when the agent ends its turn and its process exits. An
assignment skill must instruct the agent to end its turn once it has
nothing left to do, and to post anything it has to tell the user on the
pull request rather than relying on its final output. _dreamcatcher_
records that output in the feed, but does not publish it as a message to
the user. A later round's prompt also tells the agent to end its turn
when done, but the round that opens the pull request runs the recipe's
prompt with no input, so nothing but the skill tells the agent then.

An assignment skill must not instruct the agent to run anything that
waits for a person, such as a command that asks to be approved, an
editor, or a prompt for input. Nothing answers it, and the round stalls
until _dreamcatcher_ stops.

### Resumed rounds

_dreamcatcher_ gives an agent a further round whenever there is more for
it to do. Each such round normally resumes the assignment's harness
session where the last one left off, so the agent still has what the
earlier rounds said in front of it, and _dreamcatcher_'s prompt names
the round's input. When there is no session identifier to resume,
_dreamcatcher_ starts a new session with the assignment's configured
prompt followed by the prompt naming the input.

#### User posts and feedback

_dreamcatcher_'s prompt names a JSON file and asks the agent to read it.
`pull_request_state` in that file says where the pull request has got
to, and `user_posts` holds every user post that no earlier round has
relayed, oldest first. These posts are the user's feedback.

`pull_request_state` is one of `OPEN`, `MERGED` or `CLOSED`.
`pull_request_head` is the pull request's head commit when the round
started. `signals` lists what else in the pull request woke the round,
as described below, and is empty for a round that the user's posts alone
woke. Every object in `user_posts` has `kind`, `id`, `author`,
`written_at` and `body`. Its `kind` determines the remaining fields:

- `comment` adds no fields;
- `review` adds `verdict`; and
- `inlineComment` adds `path`, `subject_type`, `side`, `line`,
  `start_line` and `diff_hunk`. Either line number may be `null` where
  GitHub supplies none.

The list includes only posts by the account through which `gh` was
authenticated that have a body, or a review verdict of `APPROVED` or
`CHANGES_REQUESTED`. It excludes the agent's own posts and omits
anything at or before the newest post that an earlier round relayed. A
review's `verdict` can also be `COMMENTED`, `DISMISSED` or `PENDING`
when its body says something.

_dreamcatcher_'s prompt tells the agent to read `pull_request_state`
before anything else and, while the pull request is open, to act on
every post in `user_posts` per the assignment's rules. An assignment
skill must give those rules: how the agent acts on a user post.
_dreamcatcher_ reads how far the agent has read from its recorded round
inputs, so later updates do not select those posts again.

#### An out-of-date pull request or failing checks

_dreamcatcher_ also wakes the agent when a pull request that is ready
for review needs work that no user asked for. `signals` then holds one
or both of these values, and the part of _dreamcatcher_'s prompt that
names the input opens with one line for each, after any line about the
previous round:

- `out_of_date`: the pull request is behind its base branch or conflicts
  with it. The line asks the agent to merge the base branch in, resolve
  any conflicts, and push.
- `check_failure`: a check failed at the pull request's head. The line
  asks the agent to read the checks' output, fix the cause, and push.

A round that consumes its input relays each once for each head commit,
so an agent that pushes nothing is not woken again for the same one.
After two rounds in a row relayed a check failure, _dreamcatcher_
withholds the next one until a round relays something else, such as a
user post. A draft raises neither.

An assignment skill needs nothing of its own for this. The prompt's
lines carry the instructions, and a skill may ignore `pull_request_head`
and `signals`. The assignment's harness may run `gh pr checks` and
`gh run view` without asking, so the agent can read the output of a
check that failed.

#### A merged or closed pull request

_dreamcatcher_ gives the agent a wrap-up round when the user merges or
closes the pull request, with the same prompt naming the same file.
`pull_request_state` then reads `MERGED` or `CLOSED`, and the prompt
tells the agent to finish per the assignment's rules. `user_posts` still
holds any feedback that the user posted before merging or closing.

An assignment skill must give those rules: what the agent does to wind
the work up once the pull request is merged, and once it is closed.

#### After a round that did not finish

A round that was interrupted or errored did not consume its input, so
the next round is given the same input again: `user_posts` holds the
posts that round was given and any that arrived since, `signals` holds
the signals it was given that still hold, and `pull_request_state` says
where the pull request has got to now. _dreamcatcher_'s prompt opens
with a line saying that the previous round did not finish, and that some
of what it did may already be done, before it names the input. While the
pull request is open, the prompt tells the agent to continue the
unfinished assignment from where it stopped as well as act on any posts,
and says that empty `user_posts` and `signals` do not mean the
assignment is complete. A merged or closed pull request still gets its
wrap-up.

An assignment skill needs nothing of its own for this. The resumed agent
normally still has its own transcript. A new session instead receives
the assignment's configured prompt before the input, so the skill's
initial instructions apply again.

A round that the user stopped consumed its input, so its input is not
given again. An open assignment waits for new feedback, or for a signal
at a head not yet relayed, before it resumes, and that next prompt says
the earlier round was stopped before directing the agent to the new
input. A merged or closed pull request can proceed to its wrap-up round
without new feedback.

## Campaign skill contract

A campaign skill guides the lead, the agent of a campaign, to carry a
parent issue's planned sub-issues through GitHub. It must accept the
parent issue's number in the same `GH123` form as an assignment skill.
_dreamcatcher_ adds the input and operational instructions around the
configured prompt.

### Input

Every input contains:

- `issue`, identifying the parent issue;
- `children`, the parent's direct sub-issues in GitHub's order, as the
  update that started the round observed them;
- `notifications`, the sub-issues whose changes since the last input
  delivered to the lead call for it, which may be empty;
- `comments`, the user's eligible comments on the parent since the last
  input delivered to the lead, oldest first, which may be empty;
- `cursor`, which _dreamcatcher_ uses to tell how far the lead has read
  in the parent's comments;
- `revision`, identifying the fetched default-branch commit checked out
  in the detached worktree;
- `assignment_routes`, the assignment routes of the running daemon, for
  the lead to choose among when it gives a sub-issue an assignment
  label. Each route names its `label`, and its `claude` and `codex`
  recipes, either of which may be `null`.

Each sub-issue names its `issue`, `title` and `state`, whether it
`is_settled`, and its newest `assignment`, which is `null` when the
sub-issue has never had one. A settled sub-issue has no assignment round
running or due, where an assignment that may start for the sub-issue
counts as a round due. An assignment names its `identifier`, its
`pull_request` number, the `observed_pull_request` that the update read,
the `finished_turn` of its newest round that consumed its input, its
`ending` and whether it `is_fault`. The observed pull request holds the
pull request's `state`, `is_draft`, `merge_state`, `head`,
`check_result` and `has_running_checks`, and is `null` when the update
read nothing of it, as for an assignment that has ended or is in fault.
The daemon's routes can differ from the configuration on the default
branch, which only takes effect when the daemon restarts.

Each notification names the sub-issue's `issue` and lists its `changes`,
each of which is one of these:

- `added` or `removed`: the sub-issue joined or left the parent;
- `issue_state`: the sub-issue was closed or reopened;
- `handback`: the sub-issue's assignment, its `finished_turn` or whether
  it `is_settled` differs;
- `pull_request`: the observed pull request's `state`, `is_draft` or
  `head` differs;
- `check_completion`: some checks ran and none still runs, and the
  `head`, the `check_result` or `has_running_checks` differs;
- `mergeable`: the `merge_state` entered one of `CLEAN`, `HAS_HOOKS` or
  `UNSTABLE` from a state outside that set. A move between two of those
  states does not notify;
- `ending` or `fault`: the assignment ended or entered fault.

A removed sub-issue is not among the `children`. Every change but
`added` and `removed` is notified only once the sub-issue is settled. A
replacement assignment is compared with nothing, so every fact that it
holds is a change. Only the current facts are in the input, so the lead
reads anything that it needs about what came before from GitHub or
remembers it from its session. The first input holds no notification.

The first input holds every eligible comment already on the parent. A
comment is eligible when the signed-in user wrote it, it says something
and it does not carry the agent marker, so the lead's own posts never
reach it as comments. The lead reads the parent, its sub-issues and
anything else it needs from GitHub itself. _dreamcatcher_ starts no
round while it cannot observe every sub-issue, so no input holds a
partial picture. A sub-issue in another repository is one it cannot
observe, so every sub-issue in an input is an issue of this repository.

### Workspace

Before every round, _dreamcatcher_ resets the lead's worktree to the
fetched default branch, deleting every local commit and file that an
earlier round left. The lead may comment on, create and edit issues,
comment on, review and merge pull requests, read checks, and fetch and
check out commits to verify work. _dreamcatcher_'s prompt tells the lead
not to commit, push or open a pull request from that worktree, and to
run each merge as a shell command of its own, because Claude's
unattended permissions approve a merge only when nothing else shares its
call. A campaign skill must not instruct the lead to edit project
source, because the next round's reset discards the edit.

### Publication

The lead publishes its own messages on GitHub. _dreamcatcher_ records
the lead's final output in the feed and posts none of it.

The lead's feedback on a sub-issue's pull request reaches the
assignment's agent as user posts, as the user's feedback does, because
_dreamcatcher_'s prompt asks the lead to leave the agent marker off that
feedback alone.

### The parent issue

The user ends a campaign by closing its parent issue. _dreamcatcher_'s
prompt tells the lead not to close the parent or change its assignees or
labels, because closing it ends the campaign and removing its label or
assignee pauses the campaign.

### Ending a turn

_dreamcatcher_'s prompt tells the lead to end its turn when done. A
campaign skill must not instruct the lead to run anything that waits for
a person, because nothing answers it and the round stalls.

### Rounds

The first round starts a new harness session with the configured prompt
followed by the prompt that names the input. Each later eligible comment
on the parent, and each update that finds a notification, wakes the lead
for another round, which resumes the recorded harness session with the
prompt that names the new input. One round takes every comment and
notification that waits. A campaign that is held takes no round, and its
first round after the hold ends is given every comment posted while it
was held, and the notifications of what changed among the sub-issues
since its last delivered input.

A round that errored or was interrupted did not consume its input, so
the next round is given the input again, composed afresh against the
last input delivered before it, with anything that has arrived since. It
resumes the recorded harness session, or starts a new session with the
configured prompt when none was recorded. Its prompt opens by saying
that the previous round did not finish, and tells the lead to inspect
GitHub before it repeats an action.

A round that the user stopped consumed its input, and no round follows
it on its own. The next comment on the parent, or the next notification,
wakes the lead, and that round's prompt opens by saying that the user
stopped the previous round.

## Conversation skill contract

A conversation skill must guide the agent to investigate and answer the
user's questions without implementing a change. It must accept the issue
number in the same `GH123` form as an assignment skill. _dreamcatcher_
adds the input, publication and operational instructions around the
configured prompt. These instructions set the conversation's scope and
output form.

### Input

Every input contains:

- `issue`, identifying the watched issue;
- `comments`, containing the signed-in user's eligible issue comments in
  order;
- `revision`, identifying the fetched default-branch commit checked out
  in the detached worktree.

Each object in `comments` has `kind` set to `comment`, followed by `id`,
`author`, `written_at` and `body`. Eligible comments are unmarked
comments by the account through which `gh` was authenticated, with a
non-empty body. The issue title and body do not by themselves ask the
agent a question; the comments are the request to answer.

The input of a round that starts a new harness session also contains
`initial_issue`, an object holding the issue's `title` and `body`.
Inputs of rounds that resume the session omit this object; the resumed
harness transcript keeps that original context.

### Answer

_dreamcatcher_'s prompt tells the agent to answer the saved comments and
to return its answer as Markdown in the harness's final result, or
exactly `NO_REPLY` when no reply is needed. `NO_REPLY` posts nothing.
Progress output and tool activity are feed records, not the answer.

### Continued conversations

The first round receives every eligible existing comment. Each new
comment batch after that resumes the same harness session and contains
only eligible comments after the newest comment given to a round that
consumed its input. The agent should use its existing transcript when a
new question refers to an earlier answer. Before every round,
_dreamcatcher_ resets the worktree to the fetched default branch,
deleting every local commit and file left by the earlier round.

### Scope of an issue conversation

An issue conversation investigates. _dreamcatcher_'s prompt lets the
agent read source and Git history, run code, reproduce a suspected bug,
and make issue changes on GitHub when the user asks, such as filing or
linking a sub-issue. It tells the agent to inspect GitHub before each
change and not to repeat an action that an earlier attempt completed. It
tells the agent not to close the conversation issue or change its
assignees or labels, because closing the issue ends the conversation and
removing its label or assignee pauses it. It tells the agent not to
fetch issue comments itself, because the saved input is the comment set
it must answer.

A conversation skill must not tell the agent to implement a change, edit
project source, mutate Git, create a branch, commit or push, open or
change a pull request, post the conversation reply itself, or contact
the user elsewhere.

### Publication

_dreamcatcher_ owns publication: when the harness exits successfully,
the round trims the final result, adds an agent attribution and posts it
before the round ends. A missing or empty final result is an error. A
failed post makes the round errored.

### Rounds that did not finish and stopped rounds

Issue conversations run through Claude or Codex and keep the harness
chosen at creation. While the conversation is not held, the round after
an interrupted or errored one is given that round's comments again, less
any the user has deleted and with any that arrived since, against a
refreshed worktree. Its prompt opens by saying that the previous round
did not finish. It resumes the recorded harness session, or starts a new
session with the configured prompt and the issue's title and body when
no session identifier was recorded. The configured conversation prompt
needs no special instructions for this.

A conversation round that the user stopped waits for a new eligible
comment. The next round begins by saying that the earlier round was
stopped.
