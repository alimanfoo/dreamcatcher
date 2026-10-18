# User stories

This document says what the user does with _dreamcatcher_, why, and what they
see, while [the ontology](ontology.md) says what the words mean and
[the architecture](architecture.md) says where each thing lives in the code. It
is an enduring part of the project. Each story is told from the user's seat, in
the order things happen, using the ontology's words without defining them and
citing no rule and no mechanism. The user works through GitHub, and the agent
hears only the user: a post or a comment from anyone else is never relayed, so
nobody else can direct an agent that runs under the user's account. The home
page and the terminal show what the daemon is doing, and carry the few controls
that GitHub has no place for: stop, cancel and retry.

Agents should read the stories before judging a finding in the code. A story
that does not hold is a bug. A user error is something the user did that the
system handles, or accepts, and the story says how. An expected fault is
something outside _dreamcatcher_ going wrong, and the story says what the system
does about it, or that it accepts the consequence. Of any finding, agents should
ask which of the three it is.

## Happy paths

### Assignments

#### The user asks for an issue to be implemented

The user has an issue that says what to build. They assign it to themselves to
indicate they have taken responsibility for working on it, and they put an
assignment label on it to indicate they want an agent to implement it and select
what type of agent. As soon as _dreamcatcher_ has available agent capacity, it
sets up a working environment for the agent, including a worktree and a draft
pull request on a branch of its own. _dreamcatcher_ then starts a new harness
session, and the agent starts work in that branch.

The agent has enough information from the issue description to do a complete
implementation, and it works through this, committing and pushing to its branch
as it works. The agent works until it has nothing left to do, then marks the
pull request ready for review and ends its turn. The user reviews the pull
request on GitHub as they would anyone's: comments, inline comments, a request
for changes. At the next update, _dreamcatcher_ gives the agent everything the
user posted since its last turn. The agent addresses it, pushes, and ends its
turn. Anything the user posts while the agent is working waits for the turn
after. That exchange repeats as often as the user likes.

While the pull request waits, main may move under it. If the repository asks for
branches to be up to date, or the branch now conflicts, the agent is woken once
to merge main in and push, without the user asking. If the checks fail on what
the agent pushed, it is woken once to read the failure and fix it, and once more
if the next push fails too; after that it waits for the user, because two
attempts without progress means it needs something it does not have.

The user merges when satisfied. GitHub closes the issue, and at the next update
the agent takes one last turn to wrap up, which allows it to raise any issues
for outstanding work not addressed in the pull request.

The value to the user is that they need only label an issue, wait for the pull
request to be ready, then review it and iterate until happy with the work, then
merge, just as they would if delegating a self-contained piece of work to a
junior colleague. Everything else is automated by _dreamcatcher_.

#### The user asks for several issues to be implemented at once

The user has several issues ready, each self-contained, and wants them all
worked on. They assign and label each one. Work begins on them in the order the
issues were raised, as many at once as the daemon's capacity allows, and the
rest wait for a free slot. Each assignment has its own branch, its own draft
pull request and its own agent, so no two interfere, and each pull request
becomes ready for review in its own time. Whenever an agent ends its turn, its
slot goes to the next issue waiting. The user reviews each pull request as it
arrives, in whatever order they like, and the exchanges on different pull
requests overlap freely.

With several assignments in flight, GitHub shows each pull request but not the
whole. The home page does: every labelled issue is a row, saying whether its
work is still to start, working, idle with a pull request ready for review, or
ended, and an assignment's page shows what its agent is doing as it works. The
user can see at a glance which assignments need them, and read along when they
want to check that an agent is on the right track.

The value to the user is that they can delegate as much as they have ready, and
keep an eye on all of it from one page.

#### The user labels issues that depend on each other

The user has two issues where the second builds on the first, so work on it
should not start until the first is done. They mark the second as blocked by the
first on GitHub, as they would for any pair of issues, then assign and label
both. Work starts on the first straight away.

If the user wants to reassure themselves that _dreamcatcher_ is handling the
dependencies correctly, they can open the home page or run
`dreamcatcher status`. Either will show the second issue as blocked, naming the
issue it waits for.

When the first pull request merges, GitHub closes its issue, and at the next
_dreamcatcher_ update the second issue is no longer blocked. Work starts on it,
on a branch from main that already carries the first change. The user did
nothing between the two beyond reviewing and merging the first.

The value to the user is that they can label a whole chain of issues at once and
let the dependencies set the order that agents work on them.

#### An agent needs user input to complete an assignment

The agent is partway through an implementation and meets something the issue
does not settle: a requirement that reads two ways, a choice the user would want
to make, or a test that fails for a reason outside the change. Rather than
guess, it posts the question as a comment on the pull request, leaves the pull
request a draft, and ends its turn.

The user sees the question posted on the pull request and answers it, as they
would answer a colleague, and may settle several questions at once or ask one
back. At the next update _dreamcatcher_ gives the agent everything the user
posted, and the agent carries on in the same session with what it has learned.
This may repeat until the agent has what it needs, and the story then continues
as [the implementation story](#the-user-asks-for-an-issue-to-be-implemented)
does, from the point where the agent marks the pull request ready for review.

#### The user stops a round and redirects the agent

An assignment has been working for longer than the user expected. They open its
page on the _dreamcatcher_ web UI to see what the agent is doing, and the feed
shows it heading the wrong way: rewriting something the issue never asked for,
or chasing a problem that is not the one. Rather than let it finish and review
the result, the user stops the round from the page, or with `dreamcatcher stop`,
and it stops within a few seconds. Whatever the agent has pushed so far stays on
the branch.

The user goes to the pull request and posts what they want changed, as they
would for a colleague. At the next update the agent is given that post, told
that the previous round was stopped, and it carries on in the same session, so
it remembers what it had done. The agent takes the new direction, pushes, and
ends its turn as usual.

The value to the user is that a wrong turn costs minutes rather than a whole
round, and the correction goes through the pull request like any other feedback.

#### The user cancels an assignment to finish its pull request by hand

An assignment has got as far as the agent can take it, and the user wants to
finish the pull request themselves. They cancel it, from its page or with
`dreamcatcher cancel`. Any running round stops, no further round runs, and the
pull request, branch and worktree are the user's to work on outside of
_dreamcatcher_. The assignment shows as ended, cancelled. While the pull request
stays open, no new assignment starts for the issue.

### Conversations

#### The user asks for an issue to be investigated

The user has an issue they want investigated rather than built: a question about
the code, a suspected bug, a design doubt. They assign it to themselves, put a
conversation label on it, and write the question as a comment, because the title
and body alone ask nothing. At the next update the agent reads the code and
answers as a comment on the issue, marked as the agent's own. When a comment
needs no reply, the agent posts nothing.

The user replies, and the agent answers again in the same session, so it
remembers what it said. A comment the user posts while the agent is still
answering waits for its next answer. Each answer is based on main as it stands
then, and nothing the agent changed while answering earlier carries over.

What the user does next will depend on what they learned from the conversation.
For example, if the conversation verified a bug, then the user might start an
assignment for the issue, which leads to a pull request, and ultimately closes
the issue as resolved. Or, if the conversation showed a bug report invalid, the
user may close the issue as unplanned. Once the issue is closed, the
conversation is ended.

The value to the user is that they need only label an issue and ask their
question as a comment, then read the answer and reply, as they would with a
colleague on GitHub who knows the codebase and can investigate. They check out
no code, run nothing, and have nothing to clean up afterwards.

#### The user stops a round and asks again

The agent is partway through an answer and heading the wrong way. The user stops
its round, from the conversation's page or with `dreamcatcher stop`. The stopped
round posts no answer, and the conversation waits for the user's next comment.
The round that comment starts is told the previous one was stopped.

#### The user pauses a conversation by removing its label

The user has had their question answered, but the issue is going to stay open
for a while, perhaps because the fix is for another day. In the meantime they
don't want the agent chiming in on every comment, because the discussion that
follows is between people. So they take the conversation label off the issue,
and that is all it takes. The conversation pauses, and the user can comment on
the issue without the agent answering.

Later, something comes up that they want the agent's view on again. They put the
label back, and the same conversation picks up where it left off. It still
remembers everything it said before, and it is given everything the user posted
while it was paused, so they can ask their new question without recapping.

### The daemon

#### The user reads the status report

The user opens the home page, or runs `dreamcatcher status`, to see what the
daemon is doing without reading GitHub. Every request the user has made is a
row: an issue with a label and no work yet says why nothing has started, and one
with work shows the work's status and its detail. The home page also shows an
assignment's pull request with its state and checks, and ended work under a
collapsed list; the terminal shows the count of ended work. Both show the last
update, and keep showing it when the daemon is stopped.

#### The user stops and starts the daemon

The user stops the daemon to upgrade, to change its configuration, or for the
night. Stopping it ends every running round, which then shows as interrupted.
When the daemon starts again, each interrupted round's work carries on in the
same session, told that the previous round did not finish. Nothing the user
posted in between is lost.

## User errors

### Two labels of one kind on one issue

The user puts two assignment labels on an issue, or two conversation labels,
perhaps to try both recipes. That is a routing conflict: the request rows say so
and name the labels, and nothing of that kind starts, or carries on, until one
label is removed. An assignment that already exists carries on regardless.

### A label without an assignee

The user labels an issue but does not assign it to themselves. Nothing happens,
and the issue does not appear on the home page, because _dreamcatcher_ only
looks at issues assigned to the user. Assigning it is the fix.

### A label on an issue someone else is already working on

The user labels an issue that already has an open pull request linked to it, one
whose description says it closes the issue. The request row says the issue is
claimed by that pull request, and nothing starts until it is closed or merged. A
user who wants the agent to take over closes the other pull request first.

### Closing a pull request and leaving the label on

The user closes the agent's pull request without merging, and leaves the
assignment label on the issue. The agent wraps up, the assignment ends, and at
the next update a new assignment starts, because the label is a standing
request. A user who does not want the agent back takes the label off.

### Removing a label to stop an assignment

The user takes the assignment label off an issue expecting the agent to stop. It
does not; the assignment carries on with its pull request whatever happens to
the label. Cancelling the assignment is the way to stop it.

### Talking to the agent in the wrong place

The user comments on the issue of an assignment, expecting the agent to see it.
It does not, because an assignment's channel is its pull request. The reverse
holds for a conversation, whose channel is the issue.

### Asking a colleague to give the agent feedback

The user asks a colleague to review the agent's pull request, and the colleague
leaves comments on it expecting the agent to address them. Nothing happens. The
agent only ever hears the user, because _dreamcatcher_ runs under the user's
account and relays nobody else's posts, so the colleague's review is for the
user to read. If the user wants the agent to act on it, they say so in a post of
their own, in as many or as few words as they like. The same goes for a
conversation: another person's comment on the issue gets no answer from the
agent.

### Editing the configuration while the daemon runs

The user changes `dreamcatcher.toml` and expects the change to take effect. It
takes effect when the daemon next starts. If the file is now invalid, the daemon
refuses to start and says why; the home page keeps showing what the last daemon
recorded.

### Deleting an assignment's worktree

The user deletes the folder under `.dreamcatcher/` that an assignment works in.
The assignment's next round errors with the reason, a second failure puts the
assignment in fault, and the user cancels the assignment.

## Expected faults

### GitHub cannot be reached

GitHub is down, or rate-limited, or the network is. The update's reads fail,
nothing starts, and nothing is lost. A failed listing shows among the scheduler
failures on the status report while the daemon runs, and a failed read for one
piece of work or one request shows on its row. The next update tries again. Work
whose round is already running carries on, and its pushes and posts fail or
succeed as GitHub allows.

### The harness refuses or breaks

The agent's harness hits a usage limit, is overloaded, or crashes mid-round. The
round errors, with the harness's words in the feed. The next update gives the
work its input again. If that round errors too, the work is in fault, so a
problem that two attempts did not clear does not burn more attempts. Nothing
runs for it, not even the last turn after a merge, until the user fixes the
cause and retries, from the work's page or with `dreamcatcher retry`. If two
pieces of work are in fault at once, the daemon pauses all starts for a while,
because two faults suggest a shared cause such as an exhausted allowance. When
the pause ends, the daemon tries that work again.

### The checks fail on the agent's push

CI is red on what the agent pushed, and the pull request is ready for review; a
draft's checks wake nobody, because the agent has not finished. The agent is
woken once to fix it, and once more if its fix is red too. After that it waits
for the user: the row says the checks are still failing, and a post from the
user wakes it again.

### Main moves under a pull request

Someone merges to main while the agent's pull request waits. If the branch is
now behind in a repository that requires it to be up to date, or conflicts, the
agent is woken to merge main in. In a repository without that requirement a
branch that merely falls behind wakes nobody until it conflicts or the user
posts; that is accepted.

### The daemon dies

The machine sleeps, the process is killed, or the daemon hits an error it cannot
carry on from. When the daemon can still act, it ends its rounds as the
stop-and-start story says. When it cannot, as when it is killed, a running
harness outlives it, keeps working, and may push or post before the next daemon
start ends it; whatever it did stands. The round then shows as interrupted, and
the work carries on in its session.

### The agent does not end its turn

The agent waits on something that never answers, or loops. Nothing in
_dreamcatcher_ ends a round for taking too long; the user stops it, from the
page or the command line, and posts what they want next. That is accepted,
because a long round and a stuck one look the same from outside.

### The agent's answer cannot be posted

A conversation round finished but GitHub refused the comment, or the agent
returned nothing. The round errors with that reason, and the next update gives
it the same comments again.

### A local write fails

The disk is full or a folder is unwritable. A write that fails while a round is
being prepared errors the round with the reason. One that fails before a round
has started shows among the scheduler failures instead, without counting towards
a fault. Either way the work is tried again at the next update. No more than
that is handled, and that is accepted, because a disk that will not write is the
user's to fix, and nothing _dreamcatcher_ holds is the only copy of anything.
