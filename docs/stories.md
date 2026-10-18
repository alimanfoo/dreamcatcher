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

The user has an issue that says what to build, and would rather an agent built
it than spend their own afternoon on it. The change is clear enough to describe,
and their time is better spent reviewing it than typing it. They assign the
issue to themselves to indicate they have taken responsibility for working on
it, and they put an assignment label on it to indicate they want an agent to
implement it and select what type of agent. As soon as _dreamcatcher_ has
available agent capacity, it sets up a working environment for the agent,
including a worktree and a draft pull request on a branch of its own.
_dreamcatcher_ then starts a new harness session, and the agent starts work in
that branch.

The agent has enough information from the issue description to do a complete
implementation, and it works through this, committing and pushing to its branch
as it works. The agent works until it has nothing left to do, then marks the
pull request ready for review and ends its turn. The user reviews the pull
request on GitHub as they would anyone's: comments, inline comments, a request
for changes. At the next update, _dreamcatcher_ gives the agent everything the
user posted since its last turn. The agent addresses it, pushes, and ends its
turn. Anything the user posts while the agent is working waits for the turn
after. That exchange repeats as often as the user likes.

While the pull request waits, main may move under it and the checks may go red.
The agent deals with both itself, as
[the moving main story](#the-user-leaves-a-pull-request-that-main-has-moved-under-to-the-agent)
and [the failing build story](#the-user-leaves-a-failing-build-to-the-agent)
tell.

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

The user wrote the issue as well as they could, but an implementation always
turns up something the issue does not settle, and they would rather answer a
question than have a guess built. So when the agent, partway through, meets a
requirement that reads two ways, a choice the user would want to make, or a test
that fails for a reason outside the change, it does not guess. It posts the
question as a comment on the pull request, leaves the pull request a draft, and
ends its turn.

The user sees the question posted on the pull request and answers it, as they
would answer a colleague, and may settle several questions at once or ask one
back. At the next update _dreamcatcher_ gives the agent everything the user
posted, and the agent carries on in the same session with what it has learned.
This may repeat until the agent has what it needs, and the story then continues
as [the implementation story](#the-user-asks-for-an-issue-to-be-implemented)
does, from the point where the agent marks the pull request ready for review.

The value to the user is that they settle a question in one comment at the
moment it matters, instead of finding the wrong guess at review.

#### The user leaves a failing build to the agent

The agent has marked its pull request ready for review, but the checks have gone
red: a test it did not run locally, or a lint rule it missed. The user would
rather not read the CI log themselves, and they do not have to. The agent is
woken to read the failure, fix it and push again. If the checks go red again, it
gets one more go. After two attempts without a green build it stops trying and
waits, because two attempts without progress means it needs something it does
not have. The row on the home page says the checks are still failing, and now
the user reads the failure, and a post telling the agent what it is missing
wakes it again.

A draft's checks wake nobody, because the agent has not finished, so only a pull
request that is ready for review gets this treatment.

The value to the user is that a red build usually fixes itself before they have
even seen it.

#### The user leaves a pull request that main has moved under to the agent

The agent's pull request is ready for review, and the user has not got to it
yet. Meanwhile other work merges to main, and the branch falls behind it, or now
conflicts with it. The user does not want to resolve someone else's merge
conflict in the agent's branch, and they do not have to. The agent is woken to
merge main in and push, without being asked, and the pull request is ready for
review again on a current base. If main moves again, so does the agent, once for
each move.

One limit is worth knowing. GitHub only reports a branch as behind when the
repository requires branches to be up to date before merging. Elsewhere a branch
that merely falls behind, without conflicting, wakes nobody until it conflicts
or the user posts. That is accepted, because such a branch still merges.

The value to the user is that the pull request they come to review is one that
merges cleanly, however long it waited.

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

The user asked a question, and the answer is taking longer than they expected.
They open the conversation's page, and the feed shows the agent has gone off
down the wrong path: reading code that has nothing to do with the question, or
answering a question they did not ask. Rather than wait for an answer they will
not use, the user stops the round, from the page or with `dreamcatcher stop`,
and the stopped round posts nothing.

The user then posts a sharper question on the issue. At the next update the
agent is given it, told that the previous round was stopped, and answers in the
same session, so it keeps what it had already learned.

The value to the user is that a misread question costs minutes, not a whole
answer.

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

#### The user sets up dreamcatcher on a new repository

The user has a repository with a backlog of small, well-described issues, and
more of them than they have evenings. They want an agent working through the
backlog while they review. They install _dreamcatcher_ as a tool, and make sure
the GitHub CLI is signed in as them and Claude Code runs, because _dreamcatcher_
acts as whoever `gh` is signed in as and runs its agents through the harness.
Then, in an ordinary clone of the repository on main, they run
`dreamcatcher init`. It checks what it will need, that it can push, commit and
fetch main, writes a default configuration with a route for each of the dream
plugin's skills, installs the plugin, and creates the labels on GitHub, printing
a line for each step. If a step fails, it says how to fix it, and the user fixes
it and runs `init` again. It ends by telling them to commit and push the
configuration, which they do, along with anything an agent will need to build
and test the project, because an agent sees only what is on main.

Then they start the daemon from the same checkout with `dreamcatcher run`, and
the home page comes up with nothing on it yet. They assign an issue to
themselves, put the `dream:smith` label on it, and from here
[the implementation story](#the-user-asks-for-an-issue-to-be-implemented) takes
over.

The value to the user is that setup is one command that checks its own
prerequisites and says what is missing, and the configuration lives in the
repository, so the next person to use it needs only `init` and `run`.

#### The user comes back to see what needs them

The user labelled a handful of issues in the morning and has been in meetings
since. Now they want to know what needs them, without opening every pull request
to find out. So they open the home page, or run `dreamcatcher status` if they
are already in a terminal. Every request they have made is a row, and the rows
come in the order that deserves attention: anything in fault first, then what is
working, then what is waiting for its turn, then what is idle, and after all of
those the issues where nothing has started yet. Each row says why it is where it
is. This pull request is ready for review. That one is still a draft, so the
agent is probably waiting on an answer. This issue has not started because
another pull request already claims it. The pull requests the user needs to read
are a click away, and ended work is folded under a collapsed list, so the page
shows only what is live. The terminal gives the same rows, with a count of ended
work in place of the list.

Both show the daemon's last update, and keep showing it after the daemon stops,
so the user can still see where things stood.

The value to the user is that they never have to hunt through GitHub to find out
what is waiting on them.

#### The user stops and starts the daemon

The user needs to stop the daemon: there is a new version to install, a setting
to change, or they are closing the laptop for the night. They do not want to
wait for every agent to finish first, and they do not want to lose anything
either. So they stop it. Every running round ends, and shows as interrupted.
When the daemon starts again, each interrupted round's work carries on in the
same session, told that the previous round did not finish, and nothing the user
posted in between is lost.

The value to the user is that stopping the daemon is always safe, whatever the
agents are in the middle of.

#### The user adds a recipe with a different model

The user has been running the default recipe for a few weeks, and it is not
quite right. Perhaps the assignments are burning through their usage allowance
on small issues, or perhaps the hard ones come back half done. Either way, they
want to try a different model, or a different reasoning effort, without giving
up the recipe they have. So they open `dreamcatcher.toml` and add a second
assignment route beside the first: a new label, with a recipe that names the
cheaper model and a lower effort, or the stronger model and a higher one. They
commit and push the file, so everyone watching the repository gets the same
routes, and run `dreamcatcher init` to create the new label on GitHub. Then they
stop the daemon and start it again, which is all it takes for the change to take
effect, and nothing in progress is lost.

From then on the label they put on an issue chooses the recipe. Small issues get
the light label, hard ones the heavy one, and assignments that were already
running keep the recipe they started with. If the new recipe turns out better
everywhere, the user edits the original to match, or removes its route, and
existing work carries on regardless.

The value to the user is that trying a different model is an edit and a restart,
and the choice is made issue by issue with a label.

## User errors

### Two labels of one kind on one issue

The user puts two assignment labels on an issue, or two conversation labels,
perhaps to try both recipes. That is a routing conflict: the request rows say so
and name the labels, and nothing of that kind starts, or carries on, while both
are there. The user needs to take one of the two labels off the issue, and the
one that stays decides the recipe. An assignment that already exists carries on
regardless.

### A label without an assignee

The user labels an issue but does not assign it to themselves. Nothing happens,
and the issue does not appear on the home page, because _dreamcatcher_ only
looks at issues assigned to the user. The user needs to assign the issue to
themselves on GitHub, and at the next update it appears and work starts.

### A label on an issue someone else is already working on

The user labels an issue that already has an open pull request linked to it, one
whose description says it closes the issue. The request row says the issue is
claimed by that pull request, and nothing starts while it is open. If the user
wants the agent to take over, they need to close the other pull request, and
work starts at the next update. If they would rather let it finish, they need do
nothing: once it merges, GitHub closes the issue, and the label is moot.

### Closing a pull request and leaving the assignment label on the issue

The user closes the agent's pull request without merging, and leaves the
assignment label on the issue. The agent wraps up, the assignment ends, and at
the next update a new assignment starts, because the label is a standing
request. A user who does not want the agent back needs to take the label off
before the next update, or cancel the new assignment once it has started.

### Removing a label to stop an assignment

The user takes the assignment label off an issue expecting the agent to stop. It
does not; the assignment carries on with its pull request whatever happens to
the label. To stop it, the user needs to cancel the assignment, from its page or
with `dreamcatcher cancel`.

### Talking to the agent in the wrong place

The user comments on the issue of an assignment, expecting the agent to see it.
It does not, because an assignment's channel is its pull request. The user needs
to post on the pull request instead. The reverse holds for a conversation, whose
channel is the issue, so a comment meant for it on the pull request needs to go
on the issue.

### Asking a colleague to give the agent feedback

The user asks a colleague to review the agent's pull request, and the colleague
leaves comments on it expecting the agent to address them. Nothing happens. The
agent only ever hears the user, because _dreamcatcher_ runs under the user's
account and relays nobody else's posts, so the colleague's review is for the
user to read. If the user wants the agent to act on it, they need to put the
colleague's points in a post of their own, quoting as much or as little as they
like. The same goes for a conversation: another person's comment on the issue
gets no answer from the agent.

This is deliberate. It stops anyone else from directing, or abusing, the agents
that run on the user's machine under the user's account.

### Editing the configuration while the daemon runs

The user changes `dreamcatcher.toml` and expects the change to take effect. It
does not until the daemon next starts, so the user needs to stop the daemon and
start it again. If the file is now invalid, the daemon refuses to start and says
why, and the user needs to fix the file and start it once more. Meanwhile the
home page keeps showing what the last daemon recorded.

### Deleting an assignment's worktree

The user deletes the folder under `.dreamcatcher/` that an assignment works in.
The assignment's next round errors with the reason, and a second failure puts
the assignment in fault. The user needs to cancel the assignment and close its
pull request. With the label still on the issue, a fresh assignment starts at
the next update.

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

### The daemon stops on an error it cannot carry on from

The daemon meets something it cannot work past: its own record of the last
update will not read back, it can no longer write that record, or another daemon
has taken the checkout's lock. It prints why and stops, ending every running
round as a stop of the daemon would, so each shows as interrupted. The user
reads the message, puts the cause right, and starts the daemon again, and the
interrupted work carries on in its session as the stop-and-start story says. An
update that merely fails, because GitHub could not be read, does not end the
daemon; the next update tries again.

### The daemon is killed

The daemon's process is killed outright, so it gets no chance to end its rounds.
On macOS and Linux a harness that was running outlives it, keeps working, and
may push or post before anyone notices; whatever it did stands. On Windows the
harness dies with the daemon. Either way the round has no ending, so the home
page shows its work as waiting. When the daemon next starts, it ends any harness
still running, records the round as interrupted, and the work carries on in its
session, given its input again.

### The machine sleeps

The laptop lid closes with the daemon running. Nothing dies. When the machine
wakes, the daemon and its rounds carry on from where they were. If a harness
lost its connection while the machine slept, its round errors like any other,
and the harness story says what happens next.

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
