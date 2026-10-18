# User stories

This document says what the user does with _dreamcatcher_, why, and what they
see, while [the ontology](ontology.md) says what the words mean and
[the architecture](architecture.md) says where each thing lives in the code. It
is an enduring part of the project. Each story is told from the user's seat, in
the order things happen, using the ontology's words without defining them and
citing no rule and no mechanism.

Agents should read the stories before judging a finding in the code. A story
that does not hold is a bug. A user error is something the user did that the
system handles, or accepts, and the story says how. An expected fault is
something outside _dreamcatcher_ going wrong, and the story says what the system
does about it, or that it accepts the consequence. Of any finding, agents should
ask which of the three it is.

## Happy paths

### The user asks for an issue to be implemented

The user has an issue that says what to build. They assign it to themselves,
because _dreamcatcher_ acts only on the user's issues, and they put an
assignment label on it, because the label says what kind of help they want and
which recipe runs it. At the daemon's next update an assignment appears on the
home page, and a draft pull request opens on a branch of its own with an empty
first commit. The agent starts work in that branch. While the pull request is
still a draft, the agent may end its turn to ask the user a question; the user
answers on the pull request, and at the next update the agent carries on.

The agent works until it has nothing left to do, then marks the pull request
ready for review and ends its turn. The assignment shows as idle, ready for
review, because the next move is the user's. The user reviews the pull request
on GitHub as they would anyone's: comments, inline comments, a request for
changes. At the next update the agent is given everything the user posted since
its last turn, addresses it, pushes, and ends its turn. Anything the user posts
while the agent is working waits for the turn after. That exchange repeats as
often as the user likes.

While the pull request waits, main may move under it. If the repository asks for
branches to be up to date, or the branch now conflicts, the agent is woken once
to merge main in and push, without the user asking. If the checks fail on what
the agent pushed, it is woken once to read the failure and fix it, and once more
if the next push fails too; after that it waits for the user, because two
attempts without progress means it needs something it does not have.

The user merges when satisfied. GitHub closes the issue, and at the next update
the agent takes one last turn to wrap up. The assignment then shows as ended,
under the collapsed list on the home page, and its branch and worktree stay in
place.

### The user asks for an issue to be investigated

The user has an issue they want investigated rather than built: a question about
the code, a suspected bug, a design doubt. They assign it to themselves, put a
conversation label on it, and write the question as a comment, because the title
and body alone ask nothing. At the next update the agent reads the code and
answers as a comment on the issue, marked as the agent's own. When a comment
needs no reply, the agent posts nothing.

The user replies, and the agent answers again in the same session, so it
remembers what it said. A comment the user posts while the agent is still
answering waits for its next answer. Each answer is based on main as it stands
then, and nothing the agent changed while answering earlier carries over. The
conversation shows as idle between the user's comments, because it asks nothing
of them. When the user has what they need, they close the issue, and the
conversation ends.

### The user stops a round and redirects the agent

The agent is partway through an assignment and heading the wrong way. The user
stops its round, from the assignment's page or with `dreamcatcher stop`, and it
stops within a few seconds. A round can be stopped once its harness has reported
its session, which is within its first moments. Nothing the stopped round was
given is given again. The next round starts when something new reaches the pull
request: a post from the user, main moving under it, a failing check, or a
merge. That round is told the previous one was stopped. The user posts what they
want changed, and work resumes in the same session.

The user stops a conversation's round the same way, from the conversation's page
or with `dreamcatcher stop`. The stopped round posts no answer, and the
conversation waits for the user's next comment. The round that comment starts is
told the previous one was stopped.

### The user cancels an assignment to finish its pull request by hand

An assignment has got as far as the agent can take it, and the user wants to
finish the pull request themselves. They cancel it, from its page or with
`dreamcatcher cancel`. Any running round stops, no further round runs, and the
pull request, branch and worktree are the user's. The assignment shows as ended,
cancelled.

### The user pauses a conversation by removing its label

A conversation has answered what the user asked for now. They take its label off
the issue, and the conversation pauses: each update reads the issue, to see
whether the label is back or the issue closed, and reads no comments and starts
no round. When the user wants it back, they put the label on again, and it
carries on in the same session with everything it said before.

### The user reads the status report

The user opens the home page, or runs `dreamcatcher status`, to see what the
daemon is doing without reading GitHub. Every request the user has made is a
row: an issue with a label and no work yet says why nothing has started, and one
with work shows the work's status and its detail. The home page also shows an
assignment's pull request with its state and checks, and ended work under a
collapsed list; the terminal shows the count of ended work. Both read only what
the daemon has written down, so they never disagree with the daemon, and they
keep showing the last update when the daemon is stopped.

### The user stops and starts the daemon

The user stops the daemon to upgrade, to change its configuration, or for the
night. The stopping daemon ends every running round and records each as
interrupted, or as stopped if the user had asked it to stop. When the daemon
starts again, its updates give each interrupted round's work its input again, in
the same session, as capacity allows, with a line saying the previous round did
not finish; the round that opens a pull request is simply run again. Nothing the
user posted in between is lost.

## User errors

### Two labels of one kind on one issue

The user puts two assignment labels on an issue, or two conversation labels,
perhaps to try both recipes. That is a routing conflict: the request rows say so
and name the labels, and nothing of that kind starts, or carries on, until one
label is removed. An assignment that already exists is unaffected, because once
it exists its labels do not matter.

### A label without an assignee

The user labels an issue but does not assign it to themselves. Nothing happens,
and the issue does not appear on the home page, because _dreamcatcher_ only
looks at issues assigned to the user. Assigning it is the fix.

### A label on an issue someone else is already working on

The user labels an issue that already has an open pull request linked to it, one
whose description says it closes the issue. The request row says the issue is
claimed by that pull request, and nothing starts until it is closed or merged. A
pull request that does not name the issue does not claim it. A user who wants
the agent to take over closes the other pull request first.

### A label on a blocked issue

The user labels an issue that GitHub says is blocked by another open issue. The
row says blocked, names the blocker, and nothing starts until the blocker
closes.

### Closing a pull request and leaving the label on

The user closes the agent's pull request without merging, and leaves the
assignment label on the issue. The agent wraps up, the assignment ends, and at
the next update a new assignment starts, because the label is a standing
request. A user who does not want the agent back takes the label off.

### Removing a label to stop an assignment

The user takes the assignment label off an issue expecting the agent to stop. It
does not: an assignment belongs to its pull request from the moment it is
created, and labels no longer concern it. Cancelling the assignment is the way
to stop it.

### Talking to the agent in the wrong place

The user comments on the issue of an assignment, expecting the agent to see it.
It does not, because an assignment's channel is its pull request. The reverse
holds for a conversation, whose channel is the issue.

### Editing the configuration while the daemon runs

The user changes `dreamcatcher.toml` and expects the change to take effect. It
takes effect when the daemon next starts, because the daemon reads its
configuration once. If the file is now invalid, the daemon refuses to start and
says why; the home page keeps showing what the last daemon recorded.

### Deleting an assignment's worktree

The user deletes the folder under `.dreamcatcher/` that an assignment works in.
The assignment's next round cannot start, and today that ends the daemon run
with a traceback rather than erroring the round, which is a bug (#566). What the
stories expect is that the round errors with the reason, a second failure puts
the assignment in fault, and the user cancels it.

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
start ends it; whatever it did stands. The next start marks the round
interrupted and resumes the work in its session.

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
being prepared errors the round with the reason, and the work is tried again at
the next update. A write that fails before the round is recorded, or while the
round streams its output, is reported and the work is tried again, without
counting towards a fault. No more than that is handled, and that is accepted,
because a disk that will not write is the user's to fix, and nothing
_dreamcatcher_ holds is the only copy of anything.
