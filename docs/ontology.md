# Ontology

This document names the things _dreamcatcher_ deals with and says what the words
mean, while [the architecture](architecture.md) says where each thing lives in
the code, [the user stories](stories.md) say what the user does and sees, and
[the standard](standard.md) says how good the work has to be.

The ontology is an enduring part of the project: changes to the code, user
interface, specifications, and agent contract should preserve these meanings or
update this document deliberately.

The product's name is _dreamcatcher_, in lower case even at the start of a
sentence. The documentation sets it in italics in running text, and writes it
plainly in headings, bold terms, code and the tool's own output.

The dated specifications record the design of particular phases. Where their
terminology conflicts with this document, this document is authoritative.

## Definitions

### Repository

A **repository** is a GitHub repository in which a _dreamcatcher_ instance
manages agent work.

### User

A **user** is the person whose account `gh` is signed in to. A _dreamcatcher_
instance manages agent work on the user's behalf, and the user provides
decisions and reviews work through GitHub.

### dreamcatcher instance and daemon

A **dreamcatcher instance** is one local body of configuration and state which
manages agent work in one repository on behalf of one user. It endures while
_dreamcatcher_ is stopped and across successive daemon runs. Several users may
each run their own _dreamcatcher_ instance for the same repository.

A **daemon** is the process that runs a _dreamcatcher_ instance. At most one
daemon runs an instance at a time. A **daemon run** is one daemon process from
start to stop. Each daemon run writes a **daemon run record** when it starts,
holding its process, preferred harness, version, capacity, interval and the
dispatch routes it loaded, each as a dispatch label and its kind of agent work.
Status reports take the labels they name from that record.

### Issue and issue identifier

An **issue** is a GitHub issue that _dreamcatcher_ may handle. Its GitHub number
is its **issue identifier**, written as `GH123` in the terminal and in the
identifiers built from it. The web pages write an issue or pull request number
as `#123`, as GitHub does.

### Agent assignment and agent assignment identifier

An **agent assignment** is _dreamcatcher_'s durable commission to an agent to
implement one issue.

An **agent assignment identifier** is the agent work identifier of one agent
assignment, as in `GH123-20260912-192458-assignment`. It is distinct from the
issue identifier because an issue can receive more than one assignment over its
lifetime.

### Pull request

The assignment's **pull request** is both the proposed change and the primary
communication channel between the agent and the user.

### Issue conversation

An **issue conversation** is _dreamcatcher_'s durable commission to an agent to
answer the user on an issue without implementing a change.

### Agent work and agent work identifier

**Agent work** is either an agent assignment or an issue conversation. Its
**agent work identifier** combines the issue identifier, the time the work was
created and its kind, as in `GH123-20260912-192458-assignment` or
`GH123-20260912-193000-conversation`. The kind is in the name for a person
reading a directory listing, a daemon line or a web address; the work's record
says it too.

Each piece of agent work has one **work record**, written once when the work is
created. It holds the issue, the dispatch label, the kind of agent work, the
issue title and the harness settings the dispatch recipe gave, so later
configuration edits do not change work in progress.

### Agent harness and harness session

An **agent harness** is a program, such as Claude Code or Codex, through which
_dreamcatcher_ runs an agent.

A **harness session** is the continuing context maintained by the agent harness
for one agent assignment or issue conversation. The harness supplies its own
**harness session identifier**, which is distinct from the agent work
identifier.

### Assignment skill

An **assignment skill** is an agent skill which follows _dreamcatcher_'s
assignment skill contract and guides an agent through an agent assignment. It
may be invoked by a dispatch recipe.

### Conversation skill

A **conversation skill** is an agent skill which follows _dreamcatcher_'s
conversation skill contract and guides an agent through an issue conversation.
It may be invoked by a dispatch recipe.

### Dispatch recipe

A **dispatch recipe** specifies how _dreamcatcher_ starts one kind of agent work
through a particular agent harness. It supplies the model, effort, and initial
prompt for that harness. A recipe may also supply harness config, the settings
beyond the model and effort that _dreamcatcher_ passes to the harness on every
round. The harness adapter decides which harness config it takes. An assignment
recipe normally invokes an assignment skill; a conversation recipe normally
invokes a conversation skill, but may instead give the agent its instructions
directly.

### Dispatch label

A **dispatch label** is a GitHub issue label configured to mark issues for
handling by _dreamcatcher_.

### Dispatch, assignment and conversation routes

A **dispatch route** maps one dispatch label to one dispatch recipe for each
agent harness that the route configures. An **assignment route** is a dispatch
route for agent assignments. A **conversation route** is a dispatch route for
issue conversations. A route may offer recipes for all the harnesses
_dreamcatcher_ supports or for only some of them.

### Agent round

An **agent round** is one attempt by an assignment or an issue conversation to
take a turn. It begins when _dreamcatcher_ records it, before anything else
happens, and it holds everything the attempt does, in this order:

1. the **preparation**, which resets a conversation's worktree to main or, for
   an assignment whose pull request does not exist yet, makes the worktree and
   branch and opens the pull request, and then freezes the round's input;
2. the harness invocation, which starts or resumes the harness session with a
   prompt; and
3. the finishing step after a successful exit, which posts a conversation's
   answer or records that an assignment has completed.

An agent round is a _dreamcatcher_ concept. It is not a model turn, a tool call,
or the harness session itself. An agent round has a number which identifies its
position within one assignment or issue conversation.

### Round outcome

An agent round is **running** until it becomes **successful**, **errored**,
**interrupted** by daemon shutdown or an internal failure, or **stopped** at the
user's request. A round whose preparation fails, or whose harness cannot start,
is errored with a reason and no exit status.

A successful or stopped round has taken its turn. An errored or interrupted
round has not, so the next round is given its input again, together with
anything new.

A conversation round is successful only once its answer is posted on the issue,
or the agent has answered that no reply is needed. A round whose answer is
missing or cannot be posted is errored.

### User post and feedback

A **user post** is a contribution to an assignment's pull request by the
signed-in account that does not carry the marker _dreamcatcher_ asks every agent
post to end with, since the agent posts under that same account. It normalizes
the different places in which GitHub lets the user write: comments on the pull
request, review bodies, review verdicts, and inline review comments.

Collectively, user posts are **feedback**. _dreamcatcher_ **relays** new user
posts into a later agent round. Relay is an action, not a separate durable
domain object.

### Scheduler

The **scheduler** decides what work _dreamcatcher_ starts and when. It decides
once per **scheduler tick**, and the daemon runs one tick per interval. Users
see a scheduler tick called an update.

### Channel and cursor

A piece of agent work's **channel** is the GitHub object through which the agent
and the user talk: an assignment's pull request, or a conversation's issue. An
assignment's channel exists once the round that opens its pull request has done
so.

The **cursor** is how far the agent has read in its channel. Nothing stores it
on its own: it is read back from the inputs of the rounds that took their turn
or are still running, so the input of a round that errored or was interrupted is
given again. Anything in the channel past the cursor is new, and something new
calls for a round.

### Signal

A **signal** is something new in a piece of agent work's channel that calls for
a turn. A conversation has one kind, an **eligible comment** past the cursor: a
comment on the issue by the signed-in account that says something and does not
carry the marker that _dreamcatcher_ asks every agent post to end with. An
assignment has four: a user post past the cursor; its pull request being merged
or closed before its wrap-up round has taken its turn; **out-of-date**, a pull
request that is ready for review and behind its base branch or in conflict with
it; and **check-failure**, a pull request that is ready for review with a
finished check that failed. The last two are the **pull request signals**, which
_dreamcatcher_ raises from the pull request's merge state and checks rather than
from anything the user did. A draft raises neither, because the agent has not
finished. GitHub reports a branch as behind its base only when the repository
requires branches to be up to date before merging, so elsewhere a pull request
that falls behind without a conflict raises no out-of-date signal. A round that
takes its turn relays each pull request signal at most once for each head commit
of the pull request, so the signal is raised again only once the head moves.

The **relay rule** gives an agent two attempts at a red build on its own. A
check-failure is withheld when the last two rounds whose input is behind the
cursor both relayed one, so the work stays idle until another signal, such as a
user post, wakes it. A round that relayed no check-failure starts the count
again, and a round that did not finish its turn does not count.

### Status report

A **status report** is _dreamcatcher_'s read-only account of a _dreamcatcher_
instance, its agent work and its requests at a particular time.

A **request** is one dispatch label on one issue. It exists while the label is
on the issue, so one issue with two labels is two requests. Nothing is stored
for a request: each scheduler tick reads the labels from GitHub, and the agent
work a request led to is what is stored.

A **request row** is what one scheduler tick found for one request, held as
typed values rather than sentences. It names the open agent work the request led
to, if any, and the round the tick started for it. Its **finding** is what the
tick read for the request, such as the pull request's state and the user posts
past the cursor, the open pull requests that claim the issue and the open issues
that block it, or the conflicting labels. When a read fails, the finding holds
the reason in place of what the read would have found.

An **agent work status** is one piece of agent work's single summary status in a
status report, derived the same way for both kinds from the work's record, its
rounds, the daemon process and its request row.

A **request status** is the single summary status of a request with no open
agent work. It says why no work has started for it.

### Global cooldown

A **global cooldown** is a temporary pause on starting agent work when there is
evidence of a shared problem affecting agent harnesses, such as overload or an
exhausted usage allowance.

## Relationships and rules

### Agent work composition

Agent work has no agent rounds until work begins and one or more afterwards.

Agent work is open until its ending is recorded, with the time and the reason,
and then it has **ended**. An assignment ends when it is complete or cancelled.
A conversation ends when its issue closes.

Agent work keeps the harness, route and recipe settings that its work record
holds, even after its route is removed from the configuration.

The rounds normally share one harness session. A round with no recorded harness
session to resume starts a new one, and its prompt begins with the work's
instructions, because the new session has not seen them.

### Agent assignment composition

Each agent assignment has exactly one:

- issue;
- branch;
- Git worktree;
- agent harness.

It has one pull request once the round that opens it has done so. The assignment
exists from the moment its work record is written, before any Git or GitHub
step. Making the worktree, the branch and the draft pull request is the opening
round's preparation, never a task for the agent or the assignment skill.

Once an assignment exists, the issue's labels, assignee and dependencies no
longer decide its rounds; its pull request does, until the assignment ends.

An issue can receive more than one assignment over its lifetime, but a
_dreamcatcher_ instance can never have more than one open assignment for the
same issue. An agent assignment remains open until it is complete or cancelled,
including while its pull request is being wrapped up.

An assignment round's input records the user posts and other signals relayed to
it, and the state and head commit of its pull request. A round that opens the
pull request carries no input beyond its prompt.

### Issue conversation composition

Each issue conversation has exactly one:

- issue;
- detached Git worktree;
- agent harness.

It has no branch or pull request, so the issue is its communication channel. A
conversation belongs to the dispatch label that started it. A _dreamcatcher_
instance has at most one open issue conversation for each conversation label on
an issue, and it keeps a paused conversation until the issue closes.

Each conversation round input records the comment batch and the main revision. A
round that starts a new harness session also records the issue title and body.

### Dispatch labels and routes

An issue with no dispatch label is outside _dreamcatcher_'s scope. Each
configured dispatch label belongs to exactly one dispatch route, so one label
cannot be both an assignment label and a conversation label.

An issue with more than one assignment label has an assignment routing conflict.
An issue with more than one conversation label has a conversation routing
conflict. One assignment label and one conversation label can coexist without a
routing conflict. The order of routes in the configuration does not give one
route precedence over another.

Exactly one assignment label selects exactly one assignment route, and exactly
one conversation label selects exactly one conversation route. _dreamcatcher_
then selects the dispatch recipe for the harness through which that agent work
will run.

### Completing an assignment

An assignment becomes **complete** only when a round given a merged or closed
pull request exits successfully. That round records the assignment's ending,
with the reason "completed", as it finishes. No other round completes the
assignment.

If the pull request was merged, GitHub closes the issue and there can be no
later assignment for it. If the pull request was closed without being merged,
the issue remains open and may receive another assignment after the previous
assignment has completed.

### Stopping a round

The user can **stop** a running round, from the work's page or the command line,
once the round's harness session is known. The round ends stopped and has taken
its turn, so what it was given is not given again, and the next round's prompt
says that the previous one was stopped.

### Cancelling an assignment

The user can **cancel** an open assignment to finish its pull request by hand. A
cancelled assignment is no longer open, so _dreamcatcher_ runs no further rounds
for it and relays no further user posts from its pull request. A round that is
running when the user cancels is asked to stop, and the assignment is working
until that round ends. A cancel records the assignment's ending, with the reason
"cancelled", and cannot be undone.

_dreamcatcher_ leaves the pull request as it is, and while it is open it claims
the issue, so no new assignment starts for the issue. If the user merges it,
GitHub closes the issue. If the user closes it without merging, the issue may
receive another assignment.

### Starting an issue conversation

A conversation request starts a conversation only when its issue carries no
other configured conversation label and has at least one eligible comment. The
issue's title and body alone start nothing. An open assignment at the issue, a
linked pull request, a dependency and an assignment routing conflict have no
bearing on conversations.

### Pausing and ending a conversation

An open conversation is **paused** while its own dispatch label is off its
issue, the issue is not assigned to the signed-in account, or the issue carries
another configured conversation label. Paused is derived each tick from the
issue, not recorded. A paused conversation starts no round, its comments are not
read, and its fault does not count towards a global cooldown. Removing the cause
resumes it in the same harness session, and it is then given every comment
posted since its last finished round.

When a tick finds a conversation's issue closed, it records the conversation's
ending with the reason "issue closed" once no round is running. A round that is
running when the issue closes finishes first.

A paused conversation does not block a new one under another label. Taking label
A off an issue and adding label B starts a fresh conversation under B, while A's
stays paused.

### Describing an agent round

Number, trigger and outcome describe different aspects of an agent round. The
**first round** is round number one. A round's **trigger** is what woke it. It
is read from the round's input, so nothing else records it:

- **start**: an assignment round with no input, which opens the pull request;
- a count of posts or comments: the user posts or issue comments relayed, or
  **comments** without a count for a conversation round that has no input yet;
- **main moved** or **checks failed**: the other signals an assignment round
  relayed, after any count of posts;
- **merged** or **closed**: the state of a finished pull request, which calls
  for the assignment's final round, its **wrap-up round**;
- **carry on**: an assignment round whose input relays nothing new, given again
  after a round that did not finish.

### Requests

A scheduler tick finds requests in two places: each dispatch label on each open
issue assigned to the signed-in account, and each piece of open agent work,
which names its own issue and label. Open work answers the request it came from.
An open assignment also answers every assignment label on its issue, so those
labels make no request row of their own. A conversation answers only its own
label, so another conversation label on its issue is a request of its own.

For a request with no open work the tick records what decides whether work may
start, and the tick makes these reads only for an issue whose open work does not
answer the request. An assignment request that carries the issue's only
assignment label is asked the **start-time questions**: which open pull requests
linked to the issue claim it, and which open issue dependencies block it. They
are asked only while no open assignment exists, because they decide only whether
one may start. An open pull request **claims** an issue when GitHub links it as
one that will close the issue, as `Closes #123` in its description does. A
conversation request reads the issue's comments. A request whose issue carries
more than one label of its kind has a routing conflict, and nothing of that kind
starts while it lasts.

A request with no open work has one of these request statuses:

- **Available**: work starts once an agent slot is free.
- **Blocked**: an open pull request claims the issue, or an open issue blocks
  it.
- **Idle**: a conversation request waits for the user's first comment.
- **Routing conflict**: the issue carries more than one label of the request's
  kind.
- **Unknown**: a read that decides whether work may start failed. A failure to
  read external state can delay work, but must never cause _dreamcatcher_ to
  create duplicate or improperly routed work.

There is no durable issue queue. Requests keep the order in which the scheduler
listed their issues, oldest first, which is the order in which it starts new
work.

### Scheduling work

A **candidate** is open work with something new past its cursor, unless its last
round is running or it is in fault, or a request whose work may start. The input
of a round that errored or was interrupted is past the cursor, so it is new
again. An assignment is also a candidate when no round has opened its pull
request yet, or when its last round errored or was interrupted, because it is
then given its pull request's state again even with nothing new.

Rounds of both kinds share the daemon's capacity and the global cooldown. Open
work takes precedence over new work. Open work starts in the order of its
identifiers, and new work in the order of its requests. While both kinds have
candidates, they take turns for each free agent slot; when only one kind has
any, it goes on alone. A launch that fails takes no slot.

A failed read prevents only the launches that depend on it. A failed listing for
a dispatch label starts no work for the issues it would have listed, but open
work reads its own channel, so the listing does not affect it.

### Fault and global cooldown

Agent work is in **fault** when its last two rounds both errored. A round that
errored in its preparation counts like any other, and a round that ended any
other way, a stopped round included, ends a run of errors. Work in fault starts
no round, not even an assignment's wrap-up round, until a retry or the end of a
global cooldown clears the fault.

No single error is taken as a sign of a global problem. Each tick counts every
assignment in fault, and every conversation in fault unless it is paused. A
conversation whose issue could not be read counts, because whether it is paused
is unknown. Two counted faults, of either kind, are evidence of a shared problem
and start a global cooldown. When the cooldown ends, the errors before it no
longer count, so the faults it saw are cleared. This simple policy keeps one
piece of work's failure from blocking all other work.

A **retry** clears the current fault of the work it names, and erases none of
its errored rounds. A retry from the command line names an issue and clears the
fault of the newest assignment and the newest conversation at that issue; one
from the web page clears the fault of the work the page shows. Only errors at or
after the later of the work's latest retry and the end of the latest global
cooldown count towards a new fault.

### Agent work status

Agent work of either kind has one of these summary statuses:

- **Working**: a round is running under the daemon. A cancelled assignment whose
  round is still stopping is working until the round ends.
- **Ended**: the work's ending is recorded, and its reason, completed, cancelled
  or issue closed, is the detail.
- **Fault**: two consecutive rounds have errored, so no further round starts on
  its own.
- **Unknown**: the latest tick could not read what it needed for the work, and
  the reason is the detail; or the latest tick has no row for the work, or read
  nothing for it.
- **Waiting**: a round is due but has not started. Its last round errored or was
  interrupted, including a round left without an ending by a daemon that has
  gone; no round has run yet; an assignment's pull request is not yet open; or
  the latest tick found a signal. A free agent slot, or the end of a cooldown,
  starts it.
- **Idle**: no round is known to be due. A successful or stopped round that
  ended after the latest tick is idle until the next tick determines whether
  another round is due, and its detail says that it is awaiting the next update.
  Otherwise the detail says why: an assignment's pull request is ready for
  review, still a draft, merged or closed after its wrap-up round, or failing
  its checks after two attempts under the relay rule; a conversation's latest
  round answered, needed no reply, or was stopped; or a conversation is paused,
  and the detail is the cause.

The statuses are decided in an order. Working comes first, then ended, then
fault, so the user can see a fault and retry whatever else is true. A failed
read comes next, as unknown. A paused conversation is idle before it can be
waiting, because no round will start however its last round ended. A successful
or stopped round that ended after the latest tick is idle before an earlier
finding can make it waiting. Then come waiting and idle, and work that the
latest tick has no row for, or read nothing for, is unknown when nothing else
applies.

These statuses summarize what matters now; they are not a persisted lifecycle or
a substitute for the underlying facts. In particular, pull-request state, what
woke each round, whether another round is required, and the work's health remain
separate concepts even though they contribute to the summary.

A status report lists the open work of each kind in attention order, fault,
working, waiting, idle and then unknown, followed by the requests of that kind
with no open work. Ended work of either kind is counted apart from active work,
in a collapsed list of ended work on the web home page and in a count of ended
work in the terminal.

A running round remains working when its issue gains a second conversation
label, because a routing conflict does not cancel work already in progress. The
conversation is paused after that round ends, unless it is then in fault.

### Status reports do not control work

A status report may include operational facts such as the repository identity,
whether the daemon is running, when the last scheduler tick occurred, current
capacity, whether a global cooldown is active, and the scheduler failures. A
scheduler failure is a failure in the latest tick that no request row holds: a
failed issue listing, or a launch that failed before its round was recorded. A
failed read for a request is held in its request row, and so is a round that
errored before its harness ran. Its request statuses and agent work statuses are
projections derived for a person to read.

The status report never schedules work and is never an input to scheduling.
Scheduling and reporting must nevertheless interpret the same underlying facts
consistently.
