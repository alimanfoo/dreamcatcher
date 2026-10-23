# Ontology

This document names the things _dreamcatcher_ deals with and says what
the words mean, while [the architecture](architecture.md) says where
each thing lives in the code, [the user stories](stories.md) say what
the user does and sees, and [the standard](standard.md) says how good
the work has to be.

The ontology is an enduring part of the project: changes to the code,
user interface, specifications, and agent contract should preserve these
meanings or update this document deliberately.

The product's name is _dreamcatcher_, in lower case even at the start of
a sentence. The documentation sets it in italics in running text, and
writes it plainly in headings, bold terms, code and the tool's own
output.

The dated specifications record the design of particular phases. Where
their terminology conflicts with this document, this document is
authoritative.

## Definitions

### Repository

A **repository** is a GitHub repository in which a _dreamcatcher_
instance manages agent work.

### User

A **user** is the person whose account `gh` is signed in to. A
_dreamcatcher_ instance manages agent work on the user's behalf, and the
user provides decisions and reviews work through GitHub.

### dreamcatcher instance and daemon

A **dreamcatcher instance** is one local body of configuration and state
which manages agent work in one repository on behalf of one user. It
endures while _dreamcatcher_ is stopped and across successive daemon
runs. Several users may each run their own _dreamcatcher_ instance for
the same repository.

A **daemon** is the process that runs a _dreamcatcher_ instance. At most
one daemon runs an instance at a time. A **daemon run** is one daemon
process from start to stop. Each daemon run writes a **daemon run
record** when it starts, holding its process, start time, preferred
harness, version, capacity, interval and the dispatch routes it loaded,
each as a dispatch label and its kind of agent work. Status reports take
the labels they name from that record.

### Issue and issue identifier

An **issue** is a GitHub issue that _dreamcatcher_ may handle. Its
GitHub number is its **issue identifier**, written as `GH123` in the
terminal and in the identifiers built from it. The web pages write an
issue or pull request number as `#123`, as GitHub does. An issue in
another repository is written with that repository, as `owner/name#123`,
in the terminal and on the web pages alike.

### Agent assignment and agent assignment identifier

An **agent assignment** is _dreamcatcher_'s durable commission to an
agent to implement one issue.

An **agent assignment identifier** is the agent work identifier of one
agent assignment, as in `GH123-20260912-192458-assignment`. It is
distinct from the issue identifier because an issue can receive more
than one assignment over its lifetime.

### Pull request

The assignment's **pull request** is both the proposed change and the
primary communication channel between the agent and the user.

### Issue conversation

An **issue conversation** is _dreamcatcher_'s durable commission to an
agent to answer the user on an issue without implementing a change.

### Campaign, lead and parent issue

A **campaign** is _dreamcatcher_'s durable commission to an agent, its
**lead**, to carry a planned body of work through GitHub. The campaign's
**parent issue** holds the goal, and the parent's direct sub-issues are
the stages. The code, and the `children` field of a campaign round's
input, call each sub-issue a **child** of the parent.

### Agent work and agent work identifier

**Agent work** is an agent assignment, an issue conversation or a
campaign. Its **agent work identifier** combines the issue identifier,
the time the work was created and its kind, as in
`GH123-20260912-192458-assignment`, `GH123-20260912-193000-conversation`
or `GH123-20260912-193500-campaign`. The kind is in the name for a
person reading a directory listing, a daemon line or a web address, or
naming the work to a terminal command; the work's record says it too.

Each piece of agent work has one **work record**, written once when the
work is created. It holds the issue, the dispatch label, the kind of
agent work, the issue title and the harness settings the dispatch recipe
gave, so later configuration edits do not change work in progress.

### Agent harness and harness session

An **agent harness** is a program, such as Claude Code or Codex, through
which _dreamcatcher_ runs an agent.

A **harness session** is the continuing context maintained by the agent
harness for one piece of agent work. The harness supplies its own
**harness session identifier**, which is distinct from the agent work
identifier.

### Assignment skill

An **assignment skill** is an agent skill which follows _dreamcatcher_'s
assignment skill contract and guides an agent through an agent
assignment. It may be invoked by a dispatch recipe.

### Conversation skill

A **conversation skill** is an agent skill which follows
_dreamcatcher_'s conversation skill contract and guides an agent through
an issue conversation. It may be invoked by a dispatch recipe.

### Campaign skill

A **campaign skill** is an agent skill which follows _dreamcatcher_'s
campaign skill contract and guides a lead through a campaign. It may be
invoked by a dispatch recipe.

### Dispatch recipe

A **dispatch recipe** specifies how _dreamcatcher_ starts one kind of
agent work through a particular agent harness. It supplies the model,
effort, and initial prompt for that harness. A recipe may also supply
harness config, the settings beyond the model and effort that
_dreamcatcher_ passes to the harness on every round. The harness adapter
decides which harness config it takes. An assignment recipe normally
invokes an assignment skill; a conversation recipe normally invokes a
conversation skill, and a campaign recipe a campaign skill, but either
may instead give the agent its instructions directly.

### Dispatch label

A **dispatch label** is a GitHub issue label configured to mark issues
for handling by _dreamcatcher_.

### Dispatch, assignment, conversation and campaign routes

A **dispatch route** maps one dispatch label to one dispatch recipe for
each agent harness that the route configures. An **assignment route** is
a dispatch route for agent assignments. A **conversation route** is a
dispatch route for issue conversations. A **campaign route** is a
dispatch route for campaigns. A route may offer recipes for all the
harnesses _dreamcatcher_ supports or for only some of them.

### Agent round

An **agent round** is one attempt by a piece of agent work to take a
turn. It begins when _dreamcatcher_ records it, before anything else
happens, and it holds everything the attempt does, in this order:

1. the **preparation**, which resets a conversation's or a campaign's
   worktree to main or, for an assignment whose pull request does not
   exist yet, makes the worktree and branch and opens the pull request,
   and then freezes the round's input;
2. the harness invocation, which starts or resumes the harness session
   with a prompt; and
3. the finishing step after a successful exit, which posts a
   conversation's answer or records that an assignment has completed. A
   campaign round has none, because the lead posts its own messages.

An agent round is a _dreamcatcher_ concept. It is not a model turn, a
tool call, or the harness session itself. An agent round has a number
which identifies its position within one piece of agent work.

### Round outcome

An agent round is **running** until it becomes **successful**,
**errored**, **interrupted** by daemon shutdown or an internal failure,
or **stopped** at the user's request.

An errored round records which step failed. A round that fails in its
preparation, or while its harness invocation starts, is errored with a
reason and no recorded exit status. A round whose harness exits
unsuccessfully is errored with that exit status. A round whose finishing
step fails after its harness exited successfully is errored with the
reason, and keeps that successful exit status.

A successful or stopped round has taken its turn. An errored or
interrupted round has not, so the next round is given its input again,
together with anything new. A post or comment that the user has deleted
since is not given again.

A conversation round is successful only once its answer is posted on the
issue, or the agent has answered that no reply is needed. A round whose
answer is missing or cannot be posted is errored.

### User post and feedback

A **user post** is a contribution to an assignment's pull request by the
signed-in account that does not carry the marker _dreamcatcher_ asks
every agent post to end with, since the agent posts under that same
account. A campaign's lead posts under that account too, and leaves the
marker off its feedback on a sub-issue's pull request, so _dreamcatcher_
relays that feedback to the assignment's agent as it relays the user's.
A user post normalizes the different places in which GitHub lets the
user write: comments on the pull request, review bodies, review
verdicts, and inline review comments.

Collectively, user posts are **feedback**. _dreamcatcher_ **relays** new
user posts into a later agent round. Relay is an action, not a separate
durable domain object.

### Scheduler

The **scheduler** decides what work _dreamcatcher_ starts and when. It
decides once per **scheduler tick**, and the daemon waits its interval
after each tick finishes before it starts the next. Users see a
scheduler tick called an update.

### Channel and cursor

A piece of agent work's **channel** is the GitHub object through which
the agent and the user talk: an assignment's pull request, a
conversation's issue, or a campaign's parent issue. A conversation and a
campaign are **issue work**, because the issue is the channel of each.
An assignment's channel exists once the round that opens its pull
request has done so.

The **cursor** is how far the agent has read in its channel. Nothing
stores it on its own: it is read back from the inputs of the rounds that
took their turn or are still running, so the input of a round that
errored or was interrupted is given again. Anything in the channel past
the cursor is new, and something new calls for a round.

### Signal

A **signal** is something new in a piece of agent work's channel that
calls for a turn. A conversation and a campaign have one kind, an
**eligible comment** past the cursor: a comment on the issue by the
signed-in account that says something and does not carry the marker that
_dreamcatcher_ asks every agent post to end with. An assignment has
four: a user post past the cursor; its pull request being merged or
closed before its wrap-up round has taken its turn; **out-of-date**, a
pull request that is ready for review and behind its base branch or in
conflict with it; and **check-failure**, a pull request that is ready
for review with a finished check that failed. The last two are the
**pull request signals**, which _dreamcatcher_ raises from the pull
request's merge state and checks rather than from anything the user did.
A draft raises neither, because the agent has not finished. GitHub
reports a branch as behind its base only when the repository requires
branches to be up to date before merging, so elsewhere a pull request
that falls behind without a conflict raises no out-of-date signal. A
round that takes its turn relays each pull request signal at most once
for each head commit of the pull request, so the signal is raised again
only once the head moves.

The **relay rule** gives an agent two attempts at a red build on its
own. A check-failure is withheld when the last two rounds whose input is
behind the cursor both relayed one, so the work stays idle until another
signal, such as a user post, wakes it. A round that relayed no
check-failure starts the count again, and a round that did not finish
its turn does not count.

### Status report

A **status report** is _dreamcatcher_'s read-only account of a
_dreamcatcher_ instance, its agent work and its requests at a particular
time.

A **request** is one dispatch label on one issue. It exists while the
label is on the issue, so one issue with two labels is two requests.
Nothing is stored for a request: each scheduler tick reads the labels
from GitHub, and the agent work a request led to is what is stored.

A **request row** is what one scheduler tick found for one request, held
as typed values rather than sentences. It names the open agent work the
request led to, if any, and the round the tick started for it. Its
**finding** is what the tick read for the request, such as the pull
request's state and the user posts past the cursor, the open pull
requests that claim the issue and the open issues that block it, or the
conflicting labels. When a read fails, the finding holds the reason in
place of what the read would have found.

An **agent work status** is one piece of agent work's single summary
status in a status report, derived the same way for every kind from the
work's record, its rounds, the daemon process and its request row.

A **request status** is the single summary status of a request with no
open agent work. It says why no work has started for it.

### Global cooldown

A **global cooldown** is a temporary pause on starting agent work when
there is evidence of a shared problem affecting agent harnesses, such as
overload or an exhausted usage allowance.

## Relationships and rules

### Agent work composition

Agent work has no agent rounds until work begins and one or more
afterwards.

Agent work is open until its ending is recorded, with the time and the
reason, and then it has **ended**. An assignment ends when it is
complete or cancelled. A conversation ends when its issue closes, and a
campaign when its parent issue closes.

Agent work keeps the harness, route and recipe settings that its work
record holds, even after its route is removed from the configuration.

The rounds normally share one harness session. A round with no recorded
harness session to resume starts a new one, and its prompt begins with
the work's instructions, because the new session has not seen them.

### Agent assignment composition

Each agent assignment has exactly one:

- issue;
- branch;
- Git worktree;
- agent harness.

It has one pull request once the round that opens it has done so. The
assignment exists from the moment its work record is written, before any
Git or GitHub step. Making the worktree, the branch and the draft pull
request is the opening round's preparation, never a task for the agent
or the assignment skill.

Once an assignment exists, the issue's labels, assignee and dependencies
no longer decide its rounds; its pull request does, until the assignment
ends.

An issue can receive more than one assignment over its lifetime, but a
_dreamcatcher_ instance can never have more than one open assignment for
the same issue. An agent assignment remains open until it is complete or
cancelled, including while its pull request is being wrapped up.

An assignment round's input records the user posts and other signals
relayed to it, and the state and head commit of its pull request. A
round that opens the pull request carries no input beyond its prompt.

### Issue conversation composition

Each issue conversation has exactly one:

- issue;
- detached Git worktree;
- agent harness.

It has no branch or pull request, so the issue is its communication
channel. A conversation belongs to the dispatch label that started it. A
_dreamcatcher_ instance has at most one open issue conversation for each
conversation label on an issue, and it keeps a paused conversation until
the issue closes.

Each conversation round input records the comment batch and the main
revision. A round that starts a new harness session also records the
issue title and body.

### Dispatch labels and routes

An issue with no dispatch label is outside _dreamcatcher_'s scope. Each
configured dispatch label belongs to exactly one dispatch route, so one
label configures exactly one kind of agent work.

An issue with more than one assignment label has an assignment routing
conflict. An issue with more than one conversation label has a
conversation routing conflict, and one with more than one campaign label
has a campaign routing conflict. Labels of different kinds can coexist
without a routing conflict. The order of routes in the configuration
does not give one route precedence over another.

Exactly one label of a kind selects exactly one route of that kind.
_dreamcatcher_ then selects the dispatch recipe for the harness through
which that agent work will run.

### Completing an assignment

An assignment becomes **complete** only when a round given a merged or
closed pull request exits successfully. That round records the
assignment's ending, with the reason "completed", as it finishes. No
other round completes the assignment.

If the pull request was merged, GitHub closes the issue and there can be
no later assignment for it. If the pull request was closed without being
merged, the issue remains open and may receive another assignment after
the previous assignment has completed.

### Stopping a round

The user can **stop** a running round, from the work's page or the
command line, once the round's harness session is known. The round ends
stopped and has taken its turn, so what it was given is not given again,
and the next round's prompt says that the previous one was stopped.

### Cancelling an assignment

The user can **cancel** an open assignment to finish its pull request by
hand. A cancelled assignment is no longer open, so _dreamcatcher_ runs
no further rounds for it and relays no further user posts from its pull
request. A round that is running when the user cancels is asked to stop,
and the assignment is working until that round ends. A cancel records
the assignment's ending, with the reason "cancelled", and cannot be
undone.

_dreamcatcher_ leaves the pull request as it is, and while it is open it
claims the issue, so no new assignment starts for the issue. If the user
merges it, GitHub closes the issue. If the user closes it without
merging, the issue may receive another assignment.

### Campaign composition

Each campaign has exactly one:

- parent issue;
- detached Git worktree;
- agent harness.

It has no branch or pull request, so the parent issue is its
communication channel. A campaign belongs to the dispatch label that
started it. A _dreamcatcher_ instance has at most one open campaign for
each campaign label on an issue, and it keeps a paused campaign until
the parent issue closes.

Each campaign round input records the parent issue, the parent's
sub-issues and where each one's newest assignment stands, the
notifications, the eligible comments past the cursor, the cursor that
the input reaches, the main revision and the running daemon's assignment
routes. A round given no new comment carries the cursor forward. No
round starts while a tick cannot observe every sub-issue. The lead reads
anything else it needs from GitHub, and posts its own messages there.
Its final output stays in the feed.

### Starting an issue conversation

A conversation request starts a conversation only when its issue carries
no other configured conversation label and has at least one eligible
comment. The issue's title and body alone start nothing. An open
assignment at the issue, a linked pull request, a dependency and an
assignment routing conflict have no bearing on conversations.

### Starting a campaign

A campaign request starts a campaign when its issue carries no other
configured campaign label and no open issue dependency blocks it. The
label on an open issue assigned to the signed-in account is the whole
request, so it needs no comment. An open assignment or conversation at
the issue and a linked pull request have no bearing on campaigns. Once a
campaign exists, its parent's dependencies no longer decide its rounds.

A campaign's first round is due as soon as the campaign starts, and its
input holds every eligible comment already on the parent. After that,
each eligible comment past the cursor, and each notification, makes a
round due, which resumes the lead's harness session.

### Campaign notifications

A campaign round input is **delivered** once its round took its turn or
while the round runs. A round that errored or was interrupted delivered
nothing, so the input before it stays the newest delivered. A
**notification** names a sub-issue whose changes since the newest
delivered input call for the lead, and lists those **changes**. Each
tick compares the sub-issues that it observes with those of the newest
delivered input, matched by issue number. A sub-issue is **settled**
when no round of its assignment is running and none is due, where an
assignment request that may start counts as a round due. The comparison
selects these changes:

- **added** or **removed**: the sub-issue joined or left the parent;
- **issue state**: the sub-issue was closed or reopened;
- **handback**: the sub-issue's assignment, the newest round of it that
  took its turn, or whether the sub-issue is settled differs;
- **pull request**: the pull request's state, draft flag or head
  differs;
- **check completion**: some checks ran and none still runs, and the
  head, the check result or whether any check runs differs;
- **mergeable**: GitHub's merge status entered one of `CLEAN`,
  `HAS_HOOKS` or `UNSTABLE` from a state outside that set. A move
  between two of those states does not notify;
- **ending** or **fault**: the assignment ended or entered fault.

A sub-issue added or removed notifies at once. Every other change waits
until the sub-issue is settled, so the lead hears of an assignment's
work once it has stopped. A replacement assignment shares nothing with
the one that it replaced, so every fact that it holds is a change. A
change that reverts before the lead is given it is no change. Until an
input has been delivered there is nothing to compare with, so a first
round is given no notification.

### Pausing and ending a conversation or campaign

An open conversation or campaign is **paused** while its own dispatch
label is off its issue, the issue is not assigned to the signed-in
account, or the issue carries another configured label of its kind.
Paused is derived each tick from the issue, not recorded. Paused work
starts no round, its issue's comments are not read, and the fault of
paused work does not count towards a global cooldown. Removing the cause
resumes the work in the same harness session, and the work is then given
every comment posted since its last finished round. A lead is also given
the notifications of the changes among the sub-issues since then.

When a tick finds the issue of a conversation or campaign closed, it
records the work's ending with the reason "issue closed" once no round
is running. A round that is running when the issue closes finishes
first. Only the user closes a campaign's parent issue.

Paused work does not block new work of its kind under another label.
Taking label A off an issue and adding label B starts fresh work under
B, while A's stays paused.

### Describing an agent round

Number, trigger and outcome describe different aspects of an agent
round. The **first round** is round number one. A round's **trigger** is
what woke it. It is read from the round's input, so nothing else records
it:

- **start**: an assignment round with no input, which opens the pull
  request, or a campaign's first round;
- a count of posts or comments: the user posts or issue comments
  relayed, or **comments** without a count for a conversation round that
  has no input yet;
- each notification that a campaign round was given, after any count of
  comments: the sub-issue's number and the words for its changes. Each
  change reads as its name, except that a change of issue state reads as
  **closed** or **reopened**, by the state that the sub-issue entered,
  check completion reads as **checks finished**, and ending reads as
  **ended**. A campaign round, other than a start or a recover, that has
  no input yet reads as **comments or changes**;
- **main moved** or **checks failed**: the other signals an assignment
  round relayed, after any count of posts;
- **merged** or **closed**: the state of a finished pull request, which
  calls for the assignment's final round, its **wrap-up round**;
- **recover**: an assignment round whose input relays nothing new, given
  again after a round that did not finish, or a campaign round that
  follows one that did not finish. A campaign's start or recover comes
  before the count of comments and the notifications it was given.

### Requests

A scheduler tick finds requests in two places: each dispatch label on
each open issue assigned to the signed-in account, and each piece of
open agent work, which names its own issue and label. Open work answers
the request it came from. An open assignment also answers every
assignment label on its issue, so those labels make no request row of
their own. A conversation or a campaign answers only its own label, so
another label of its kind on its issue is a request of its own.

For a request with no open work the tick records what decides whether
work may start, and the tick makes these reads only for an issue whose
open work does not answer the request. An assignment request that
carries the issue's only assignment label is asked the **start-time
questions**: which open pull requests linked to the issue claim it, and
which open issue dependencies block it. They are asked only while no
open assignment exists, because they decide only whether one may start.
An open pull request **claims** an issue when GitHub links it as one
that will close the issue, as `Closes #123` in its description does. A
conversation request reads the issue's comments to give them to its
first round. A campaign request asks which open issue dependencies block
the parent, and only when none does reads the parent's comments to give
them to its first round. A request whose issue carries more than one
label of its kind has a routing conflict, and nothing of that kind
starts while it lasts.

A request with no open work has one of these request statuses:

- **Available**: work starts once an agent slot is free.
- **Blocked**: an open pull request claims an assignment request's
  issue, or an open issue blocks the issue of an assignment or campaign
  request.
- **Idle**: a conversation request waits for the user's first comment.
- **Routing conflict**: the issue carries more than one label of the
  request's kind.
- **Unknown**: a read that decides whether work may start failed. A
  failure to read external state can delay work, but must never cause
  _dreamcatcher_ to create duplicate or improperly routed work.

There is no durable issue queue. Requests keep the order in which the
scheduler listed their issues, oldest first, which is the order in which
it starts new work.

### Scheduling work

A **candidate** is open work with something new past its cursor, unless
its last round is running or it is in fault, or a request whose work may
start. The input of a round that errored or was interrupted is past the
cursor, so it is new again. An assignment is also a candidate when no
round has opened its pull request yet, or when its last round errored or
was interrupted, because it is then given its pull request's state again
even with nothing new. A conversation has nothing to give but comments,
so once the user deletes every comment that its unfinished round was
given, it is not a candidate until a new eligible comment arrives. A
campaign is also a candidate when no round has run yet, when a tick
finds a notification, and when its last round errored or was
interrupted, because the lead is then given its input again even with
nothing new.

Rounds of every kind share the daemon's capacity and the global
cooldown. Within each kind, open work takes precedence over new work.
Open work starts in the order of its identifiers, and new work in the
order of its requests. The kinds take turns for each free agent slot, in
the order assignment, conversation, campaign, and a kind with no
candidate gives up its turn to the next. A launch that fails takes no
slot.

A failed read from GitHub prevents only the launches that depend on it.
A failed issue listing starts no new work of any kind, but open work
reads its own channel, so the listing does not affect it. A local record
that cannot be read can instead fail the whole tick, as
[the story about an unreadable local record](stories.md#a-local-record-cannot-be-read)
describes.

### Fault and global cooldown

Agent work is in **fault** when its last two rounds both errored. A
round that errored in its preparation or its finishing step counts like
any other, and a round that ended any other way, a stopped round
included, ends a run of errors. Work in fault starts no round, not even
an assignment's wrap-up round, until a retry or the end of a global
cooldown clears the fault.

No single error is taken as a sign of a global problem. Each tick counts
every assignment in fault, and every conversation or campaign in fault
unless it is paused. A conversation or campaign whose issue could not be
read counts, because whether it is paused is unknown. Two counted
faults, of any kinds, are evidence of a shared problem and start a
global cooldown. When the cooldown ends, the errors before it no longer
count, so the faults it saw are cleared. This simple policy keeps one
piece of work's failure from blocking all other work.

A **retry** clears the current fault of the work it names, and erases
none of its errored rounds. A retry from the command line clears the
fault of the one piece of agent work that the command selects; one from
the web page clears the fault of the work the page shows. Only errors at
or after the later of the work's latest retry and the end of the latest
global cooldown count towards a new fault.

### Agent work status

Agent work of every kind has one of these summary statuses:

- **Working**: a round is running under the daemon. A cancelled
  assignment whose round is still stopping is working until the round
  ends.
- **Ended**: the work's ending is recorded, and its reason, completed,
  cancelled or issue closed, is the detail.
- **Fault**: two consecutive rounds have errored, so no further round
  starts on its own.
- **Unknown**: the latest tick could not read what it needed for the
  work, and the reason is the detail; or the latest tick has no row for
  the work, or read nothing for it.
- **Waiting**: a round is due but has not started. Its last round
  errored or was interrupted, including a round left without an ending
  by a daemon that has gone; no round has run yet; an assignment's pull
  request is not yet open; or the latest tick found a signal. A
  conversation whose last round errored or was interrupted is not
  waiting once a tick that read it after that round ended found no
  eligible comment past the cursor. A free agent slot, or the end of a
  cooldown, starts it.
- **Idle**: no round is known to be due. A round that took its turn
  after the latest tick read the work is idle until the next tick,
  unless the earlier tick found input that the round did not consume.
  Its detail says that it is awaiting the next update. Otherwise the
  detail says why: an assignment's pull request is ready for review,
  still a draft and so needing feedback, merged or closed after its
  wrap-up round, or failing its checks after two attempts under the
  relay rule; a conversation's latest round answered, needed no reply,
  was stopped, errored or was interrupted; a campaign's latest round
  ended; or a conversation or campaign is paused, and the detail is the
  cause.

The statuses are decided in an order. Working comes first, then ended,
then fault, so the user can see a fault and retry whatever else is true.
A failed read comes next, as unknown. A paused conversation or campaign
is idle before it can be waiting, because no round will start however
its last round ended. The awaiting-update idle case comes before waiting
when the latest tick found no new input, or started the round that then
took its turn. Then come waiting and idle, and work that the latest tick
has no row for, or read nothing for, is unknown when nothing else
applies.

These statuses summarize what matters now; they are not a persisted
lifecycle or a substitute for the underlying facts. In particular,
pull-request state, what woke each round, whether another round is
required, and the work's health remain separate concepts even though
they contribute to the summary.

A status report lists the open work of each kind in attention order,
fault, working, waiting, idle and then unknown, followed by the requests
of that kind with no open work. Ended work of every kind is counted
apart from active work, in a collapsed list of ended work on the web
home page and in a count of ended work in the terminal.

A running round remains working when its issue gains a second label of
its kind, because a routing conflict does not cancel work already in
progress. The conversation or campaign is paused after that round ends,
unless it is then in fault.

### Status reports do not control work

A status report may include operational facts such as the repository
identity, whether the daemon is running, how long until the next
scheduler tick, or that a tick is running, current capacity, whether a
global cooldown is active, and the scheduler failures. A scheduler
failure is a failure in the latest tick that no request row holds: a
failed issue listing, or a launch that failed before its round was
recorded. A failed read for a request is held in its request row, and so
is a round that errored during its preparation or startup. Its request
statuses and agent work statuses are projections derived for a person to
read.

The status report never schedules work and is never an input to
scheduling. Scheduling and reporting must nevertheless interpret the
same underlying facts consistently.
