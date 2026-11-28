# Concepts

This page is a glossary with rules. It names the things _dreamcatcher_
deals with and says what the words mean, while
[the architecture](architecture.md) says where each thing lives in the
code, [the user stories](stories.md) say what the user does and sees,
and [the standard](standard.md) says how good the work has to be.

This page is an enduring part of the project: changes to the code, user
interface, specifications, and agent contract should preserve these
meanings or update this page deliberately.

The product's name is _dreamcatcher_, in lower case even at the start of
a sentence. The documentation sets it in italics in running text, and
writes it plainly in headings, bold terms, code and the tool's own
output.

A section ends with the words that its concepts replace, where they
replace any, in a line that begins "Replaces:". A replaced word is not
used for its concept in code, documents, skills or issues. It may still
be used in another sense, as "running" still describes a round.

The dated specifications record the design of particular phases. Where
their terminology conflicts with this document, this document is
authoritative.

Replaces: "ontology", the name that this page was first written under.

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

Replaces: "installation", for a _dreamcatcher_ instance, and "run" on
its own, for a daemon run.

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

Replaces: "session" on its own, for an agent assignment.

### Pull request

An assignment's or campaign's **pull request** is both the proposed
change and the communication channel between the agent and the user. Its
**base branch** is the branch the pull request goes into. The work's
branch starts from that base. The work record holds the base branch when
the request chooses one other than the repository's default. Otherwise,
the opening round uses the default branch.

### Campaign, lead and parent issue

A **campaign** is _dreamcatcher_'s durable commission to an agent, its
**lead**, to carry a planned body of work through GitHub. The campaign's
**parent issue** holds the goal, and the parent's direct sub-issues hold
the work. The code, and the `children` field of a campaign round's
input, call each sub-issue a **child** of the parent. The **campaign
branch** starts from the default branch. The campaign's pull request
goes into the default branch and closes the parent when it merges. While
the pull request is a draft, the lead is in the **coordinating phase**.
It waits until it judges every sub-issue done before editing project
source, committing or pushing. It may then make its own changes before
marking the campaign's pull request ready for review. While the open
pull request is ready for review, the lead is in the **finishing
phase**. The lead responds to the same pull request signals as an
assignment's agent and can commit and push to the campaign branch. In
either phase the lead dispatches the parent's sub-issues and reviews and
merges their pull requests into the campaign branch. The user can add
sub-issues while the campaign is open, and a ready pull request stays
ready while the lead takes them up. Marking the pull request as a draft
again returns the campaign to coordinating. The user decides when to
merge it.

A **campaign's sub-issue** is a direct sub-issue in the same repository
whose parent carries a campaign label configured for the running daemon
or has a campaign on record in this instance, even after that campaign
ends. The newest recorded campaign supplies the campaign branch when it
is open or cancelled and its recorded pull request is open.

Replaces: "stage", for a sub-issue.

### Issue conversation

An **issue conversation** is _dreamcatcher_'s durable commission to an
agent to answer the user on an issue without implementing a change.

Replaces: "investigation".

### Agent work and agent work identifier

**Agent work** is an agent assignment, a campaign or an issue
conversation. Its **agent work identifier** combines the issue
identifier, the time the work was created and its kind, as in
`GH123-20260912-192458-assignment`, `GH123-20260912-193000-campaign` or
`GH123-20260912-193500-conversation`. The kind is in the name for a
person reading a directory listing, a daemon line or a web address, or
naming the work to a terminal command; the work's record says it too.

Each piece of agent work has one **work record**, written once when the
work is created. It holds the issue, the dispatch label, the kind of
agent work, the issue title and the harness settings the dispatch recipe
gave, so later configuration edits do not change work in progress. For
an assignment or campaign, it also holds when GitHub says the label that
made its request was applied.

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

Replaces: "dispatchable skill".

### Campaign skill

A **campaign skill** is an agent skill which follows _dreamcatcher_'s
campaign skill contract and guides a lead through a campaign. It may be
invoked by a dispatch recipe.

### Conversation skill

A **conversation skill** is an agent skill which follows
_dreamcatcher_'s conversation skill contract and guides an agent through
an issue conversation. It may be invoked by a dispatch recipe.

### Dispatch recipe

A **dispatch recipe** specifies how _dreamcatcher_ starts one kind of
agent work through a particular agent harness. It supplies the model,
effort, and initial prompt for that harness. A recipe may also supply
harness config, the settings beyond the model and effort that
_dreamcatcher_ passes to the harness on every round. The harness adapter
decides which harness config it takes. An assignment recipe normally
invokes an assignment skill; a campaign recipe normally invokes a
campaign skill, and a conversation recipe a conversation skill, but
either may instead give the agent its instructions directly.

Replaces: "agent recipe", "harness recipe", "harness block" and "recipe
table".

### Dispatch label

A **dispatch label** is a GitHub issue label configured to mark issues
for handling by _dreamcatcher_. The account that **applied** a dispatch
label to an issue is the one that GitHub names in the latest event that
put that label on the issue.

### Dispatch, assignment, campaign and conversation routes

A **dispatch route** maps one dispatch label to one dispatch recipe for
each agent harness that the route configures. An **assignment route** is
a dispatch route for agent assignments. A **campaign route** is a
dispatch route for campaigns. A **conversation route** is a dispatch
route for issue conversations. A route may offer recipes for all the
harnesses _dreamcatcher_ supports or for only some of them.

### Agent round

An **agent round** is one bounded run of a piece of agent work's harness
session: one headless invocation of its agent harness, with what
_dreamcatcher_ does before and after it. It begins when _dreamcatcher_
records it, before anything else happens, and it holds everything that
run does, in this order:

1. the **preparation**, which resets a conversation's worktree to the
   default branch or, for an assignment or campaign whose pull request
   does not exist yet, makes the worktree and branch and opens the pull
   request, and then freezes the round's input;
2. the harness invocation, which starts or resumes the harness session
   with a prompt; and
3. the finishing step after a successful exit, which posts a
   conversation's answer or records that an assignment or campaign has
   completed.

An agent round is a _dreamcatcher_ concept. It is not a [turn](#turn), a
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

A successful or stopped round has **consumed its input**. An errored or
interrupted round has not, so the next round is given its input again,
together with anything new. A post or comment that the user has deleted
since is not given again.

A conversation round is successful only once its answer is posted on the
issue, or the agent has answered that no reply is needed. A round whose
answer is missing or cannot be posted is errored.

Replaces: "failed", for an errored round; and "taken its turn", for a
round that has consumed its input.

### User post and feedback

A **user post** is a contribution to the work's pull request by the
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
the agent and the user talk. An assignment or campaign is **pull request
work** and its channel exists once the opening round has opened its pull
request. A conversation is **issue work** because its issue is its
channel.

The **cursor** is how far the agent has read in its channel. Nothing
stores it on its own: it is read back from the inputs of the rounds that
consumed their input or are still running, so the input of a round that
errored or was interrupted is given again. Anything in the channel past
the cursor is new, and something new calls for a round. For pull request
posts in the newest relayed second, the post's kind and id show whether
it was already relayed.

Replaces: "delivery position" and "delivery cursor", for the cursor.

### Signal

A **signal** is something new in a piece of agent work's channel that
calls for a round. A conversation has one kind, an **eligible comment**
past the cursor: a comment on the issue by the signed-in account that
says something and does not carry the marker that _dreamcatcher_ asks
every agent post to end with. Pull request work has four: a user post
past the cursor; its pull request being merged or closed before its
wrap-up round has consumed its input; **out-of-date**, a pull request
that is ready for review and behind its base branch or in conflict with
it; and **check-failure**, a pull request that is ready for review with
a finished check that failed. The last two are the **pull request
signals**, which _dreamcatcher_ raises from the pull request's merge
state and checks rather than from anything the user did. A draft raises
neither, because the agent has not finished. GitHub reports a branch as
behind its base only when the repository requires branches to be up to
date before merging, so elsewhere a pull request that falls behind
without a conflict raises no out-of-date signal. A round that consumes
its input relays each pull request signal at most once for each head
commit of the pull request, so the signal is raised again only once the
head moves.

The **relay rule** gives an agent two attempts at a red build on its
own. A check-failure is withheld when the last two rounds whose input is
behind the cursor both relayed one, so the work stays idle until another
signal, such as a user post, wakes it. A round that relayed no
check-failure starts the count again, and a round that did not consume
its input does not count.

### Status report

A **status report** is _dreamcatcher_'s read-only account of a
_dreamcatcher_ instance, its agent work and its requests at a particular
time.

For an assignment or a campaign, a **request** is one application of a
dispatch label to an issue. The work it starts **consumes** it and
records when GitHub says the label was applied. When no open work
answers the label, work can start only if the label is still on and was
applied after every application consumed by work of that kind on the
issue. Removing and re-adding the label makes a new request. An issue
with no earlier work of that kind needs only its first label
application. Users see a consumed request called used.

A conversation's label is a switch. It makes a request while it is on
the issue and allows the conversation to start or resume in response to
the user's comments.

A **request row** is what one scheduler tick found for one request, held
as typed values rather than sentences. It names the open agent work the
request led to, if any, and the round the tick started for it. Its
**finding** is what the tick read for the request, such as the pull
request's state and the user posts past the cursor, the open pull
requests that claim the issue and the open issues that block it, the
conflicting labels, a consumed request, or the account that applied the
label when it was not the user. When a read fails, the finding holds the
reason in place of what the read would have found. The row also holds
the issue's state when the tick read the issue, as it does for every
request it lists and for every open conversation.

An **agent work status** is one piece of agent work's single summary
status in a status report, derived the same way for every kind from the
work's record, its rounds, the daemon process and its request row.

A **request status** is the single summary status of a request with no
open agent work. It says why no work has started for it.

A **card** is what _dreamcatcher_ shows for one piece of agent work, one
request, or one sub-issue under a campaign. Its first row gives the
issue and GitHub's state of what the card stands for; its second, the
route and _dreamcatcher_'s status; then any detail or advice; then,
while the agent works or after a fault, its latest output. A **work
card**, a **request card** and a **sub-issue card** are the three kinds.
A work page opens with its work card, less the latest output, which its
feed shows. The terminal's status table shows each card as one row: the
work, or the issue and its label, then its status, GitHub's state, then
the detail.

Replaces: "board"; and "request row", for what the user sees of a
request, which is its request card.

### Working motif and calm field

A **working motif** is the small moving figure that the web home page
shows in the side margin beside the page's text for each working agent:
a falling column of glyphs in Matrix, and in Nature a falling dandelion
seed on a light page or a firefly on a dark one.

A **calm field** is the field of the same theme's motif beneath the hint
on a tab with nothing active. The seeds in a calm field rise rather than
fall, so the field cannot be mistaken for working motifs.

### Global cooldown

A **global cooldown** is a temporary pause on starting agent work when
there is evidence of a shared problem affecting agent harnesses, such as
overload or an exhausted usage allowance.

## Relationships and rules

### Agent work composition

Agent work has no agent rounds until work begins and one or more
afterwards.

Agent work is open until its ending is recorded, with the time and the
reason, and then it has **ended**. The first ending recorded is the
work's ending for good, and an ending that comes after it changes
nothing. Pull request work ends when it is complete or cancelled. A
conversation ends when its issue closes.

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
relayed to it, and the number, state and head commit of its pull
request. A round that opens the pull request carries no input beyond its
prompt.

### Campaign composition

Each campaign has one parent issue, campaign branch, Git worktree and
agent harness. Its opening round makes the worktree and branch and opens
a draft pull request. The worktree starts on the campaign branch and
keeps the lead's checkout between rounds. A _dreamcatcher_ instance has
at most one open campaign per parent issue. Once the campaign exists,
its pull request drives its rounds.

Each lead round receives the pull request number, state and head commit,
the user posts and pull request signals, the parent's observed
sub-issues, notifications and the running daemon's assignment routes. An
opening round receives the initial sub-issue picture. A merged or closed
pull request calls for a wrap-up round. When it succeeds, the campaign
records completion and the scheduler removes the worktree and local
branch. The lead posts its messages on GitHub and its final output stays
in the feed.

### Issue conversation composition

Each issue conversation has exactly one:

- issue;
- detached Git worktree;
- agent harness.

It has no branch or pull request, so the issue is its communication
channel. A conversation belongs to the dispatch label that started it. A
_dreamcatcher_ instance has at most one open issue conversation for each
conversation label on an issue, and it keeps a held conversation until
the issue closes.

Each conversation round input records the comment batch and the
default-branch revision. A round that starts a new harness session also
records the issue title and body.

### Dispatch labels and routes

An issue with no dispatch label is outside _dreamcatcher_'s scope. Each
configured dispatch label belongs to exactly one dispatch route, so one
label configures exactly one kind of agent work.

An issue with more than one assignment label has an assignment routing
conflict. An issue with more than one campaign label has a campaign
routing conflict, and one with more than one conversation label has a
conversation routing conflict. Labels of different kinds can coexist
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

For a merge into the default branch, GitHub closes the issue. For a
merge into another base branch, _dreamcatcher_ closes the issue as
completed before preparing the wrap-up round's input and leaves a marked
comment naming the pull request. If the pull request was closed without
being merged, the issue remains open and may receive another assignment
after the previous assignment has completed.

Once a completed assignment's wrap-up round has ended, _dreamcatcher_
removes its worktree and its local branch, and keeps its record and the
branch on GitHub.

### Stopping a round

The user can **stop** a running round, from the work's page or the
command line, once the round's harness session is known. The round ends
stopped and has consumed its input, so what it was given is not given
again, and the next round's prompt says that the previous one was
stopped.

### Cancelling pull request work

The user can **cancel** an open assignment or campaign to finish its
pull request by hand. A cancel records the work's ending, with the
reason "cancelled", and cannot be undone. _dreamcatcher_ asks a running
round to stop and shows the work as working until that round ends. It
starts no further rounds and relays no further user posts for the work.

_dreamcatcher_ leaves the pull request, worktree and branch for the
user. An open pull request linked to close the issue still claims it.
While a cancelled campaign's pull request is open, the campaign still
supplies the base branch for its sub-issue assignments under the
[campaign branch rule](#campaign-lead-and-parent-issue). GitHub closes
the issue for a merge into the default branch. After merging into
another base branch, the user closes the issue themselves.

### Starting a campaign

A [campaign request](#requests) needs no comment to start. Once the
label checks clear, open pull requests that claim the parent and open
issues that block it hold the request. The opening round is due once the
tick can observe all the sub-issues and an agent slot is free.

Later rounds resume the lead's harness session. Pull request activity,
sub-issue notifications and an unfinished round can each make a round
due. A failed sub-issue observation leaves the next round waiting for a
complete picture.

### Campaign notifications

A campaign round input is **delivered** once its round consumed it or
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
  consumed its input, or whether the sub-issue is settled differs;
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

### Starting an issue conversation

A conversation request starts a conversation only when the signed-in
account applied its label, its issue carries no other configured
conversation label, and it has at least one eligible comment. The
issue's title and body alone start nothing. An open assignment at the
issue, a linked pull request, a dependency and an assignment routing
conflict have no bearing on conversations.

### Holding and ending a conversation

The user **pauses** an open conversation by taking its own dispatch
label off its issue, or by unassigning the issue from the signed-in
account. Pausing is one reason that the scheduler holds the work back.
It also holds the work back while an account other than the signed-in
one applied that label, or the issue carries another configured label of
its kind, and neither of those is a pause. Whether the work is held back
is derived each tick from the issue, not recorded. Work that is held
back starts no round, its issue's comments are not read, and its fault
does not count towards a global cooldown. Removing the cause resumes the
work in the same harness session, and the work is then given every
comment posted since its last finished round.

When a tick finds a conversation's issue closed, it records the work's
ending with the reason "issue closed" once no round is running. A round
that is running when the issue closes finishes first. Once the work has
ended and no round of it is running, _dreamcatcher_ removes its worktree
and keeps its record.

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
- each notification that a campaign round was given, after any words for
  pull request activity: the sub-issue's number and the words for its
  changes. Each change reads as its name, except that a change of issue
  state reads as **closed** or **reopened**, by the state that the
  sub-issue entered, handback reads as **handed back**, pull request
  reads as **pull request changed**, check completion reads as **checks
  finished**, and ending reads as **ended**. A later campaign round that
  has no input yet reads as **pull request or sub-issue changes**;
- **out of date** or **checks failed**: the pull request signals a round
  relayed, after any count of posts;
- **merged** or **closed**: the state of a finished pull request, which
  calls for its final round, the **wrap-up round**;
- **recover**: a round with no new pull request activity or sub-issue
  notifications, given again after a round that did not finish.

Replaces: "purpose", for a trigger; "carry on", for the recover trigger;
"wind up", for wrap-up; and "main moved", for the out-of-date trigger.

### Requests

A scheduler tick finds requests in two places: each dispatch label on
each open issue assigned to the signed-in account, and each piece of
open agent work, which names its own issue and label. Open work answers
the request it came from. Open pull request work answers every label of
its kind on its issue, so those labels make no request row of their own.
A conversation answers its own label, so another conversation label on
its issue is a request of its own.

For a request with no open work, the tick first checks the labels. An
issue carrying more than one label of the request's kind has a routing
conflict and holds the request. A label applied by another account also
holds it, as does an application already consumed by an assignment or
campaign. These holds need no further reads.

The tick then asks an eligible assignment or campaign request the
**start-time questions**. These ask which open pull requests linked to
the issue claim it and which open issue dependencies block it. An open
pull request **claims** an issue when GitHub links it as one that will
close the issue, as `Closes #123` in its description does. When neither
answer holds an assignment request, the tick checks the issue's parent.
It sets the base branch of a campaign's sub-issue to the campaign
branch, or holds the request and names the parent if no campaign pull
request is available. Every other assignment uses the default branch.
The base choice is recorded when work starts and does not follow later
changes to the parent or campaign. For a conversation request, the tick
reads the issue's comments to give them to its first round. For a
campaign request that clears the start-time questions, the tick observes
the parent's sub-issues for the opening round.

A request with no open work has one of these request statuses:

- **Available**: work starts once an agent slot is free.
- **Held**: the scheduler holds the request back for what GitHub says of
  its issue, until that changes. An open issue blocks the issue of an
  assignment or campaign request, an open pull request linked to its
  issue claims it, someone other than the user applied the request's
  label, the issue has a routing conflict, or earlier work already
  consumed the request, or the parent of a campaign's sub-issue has no
  available campaign pull request. Work can start once the blocker
  closes, the claiming pull request goes or the campaign pull request
  becomes available. A label that someone else applied, a routing
  conflict or a consumed request needs the user to act. An open
  conversation can also be held, as its agent work status says.
- **Idle**: a conversation request waits for the user's first comment.
- **Unknown**: a read that decides whether work may start failed, or
  GitHub could not yet tell. A failure to read external state can delay
  work, but must never cause _dreamcatcher_ to create duplicate or
  improperly routed work.

There is no durable issue queue. Requests keep the order in which the
scheduler listed their issues, oldest first, which is the order in which
it starts new work.

Replaces: "queued" and "waiting", for an available request; and
"blocked" and "routing conflict", for a request status.

### Scheduling work

A **candidate** is open work with something new past its cursor, unless
its last round is running or it is in fault, or a request whose work may
start. The input of a round that errored or was interrupted is past the
cursor, so it is new again. Pull request work is also a candidate when
it has no recorded pull request or when its last round did not finish. A
campaign is also a candidate when the tick finds a sub-issue
notification. A conversation whose unfinished round's comments have all
been deleted waits for another eligible comment.

Rounds of every kind share the daemon's capacity and the global
cooldown. Within each kind, open work takes precedence over new work.
Open work starts in the order of its identifiers, and new work in the
order of its requests. The kinds take each free agent slot in rotation,
in the order assignment, campaign, conversation, and a kind with no
candidate gives up its place to the next. A round that errors during its
preparation or startup takes no slot.

A failed read from GitHub prevents only the launches that depend on it.
A failed issue listing starts no new work of any kind. Open work reads
its own channel. An open campaign can take a round only when the tick
can observe all of its sub-issues, so a failed listing holds the round
if any sub-issue has no open assignment. A local record that cannot be
read instead stops the daemon, as
[the story about an unreadable local record](stories.md#a-local-record-cannot-be-read)
describes.

### Fault and global cooldown

Agent work is in **fault** when its last two rounds both errored. A
round that errored in its preparation or its finishing step counts like
any other, and a round that ended any other way, a stopped round
included, ends a run of errors. Work in fault starts no round, including
a wrap-up round, until a retry or the end of a global cooldown clears
the fault.

No single error is taken as a sign of a global problem. Each tick counts
all pull request work in fault, and every conversation in fault unless
it is held. A conversation whose issue could not be read counts, because
whether it is held is unknown. Two counted faults, of any kinds, are
evidence of a shared problem and start a global cooldown. When the
cooldown ends, the errors before it no longer count, so the faults it
saw are cleared. This simple policy keeps one piece of work's failure
from blocking all other work.

A **retry** clears the current fault of the work it names, and erases
none of its errored rounds. A retry from the command line clears the
fault of the one piece of agent work that the command selects; one from
the web page clears the fault of the work the page shows. Only errors at
or after the later of the work's latest retry and the end of the latest
global cooldown count towards a new fault.

### Agent work status

Agent work of every kind has one of these summary statuses:

- **Working**: a round is running under the daemon. Work whose round is
  still stopping after a cancel stays working until the round ends.
- **Ended**: the work's ending is recorded. Ended work shows how
  _dreamcatcher_'s work ended, with no detail: completed or cancelled
  for pull request work, and ended for a conversation, whose issue shows
  as closed.
- **Fault**: two consecutive rounds have errored, so no further round
  starts on its own.
- **Unknown**: the latest tick could not read what it needed for the
  work, and the reason is the detail; or the latest tick has no row for
  the work, or read nothing for it.
- **Waiting**: a round is due but has not started. Its last round
  errored or was interrupted, including a round left without an ending
  by a daemon that has gone; no round has run yet; the work's pull
  request is not yet open; its pull request is merged or closed and its
  wrap-up round is due, which the detail calls awaiting wrap-up; or the
  latest tick found a signal. A conversation whose last round errored or
  was interrupted is not waiting once a tick that read it after that
  round ended found no eligible comment past the cursor. A free agent
  slot, or the end of a cooldown, starts it.
- **Idle**: no round is known to be due. A round that consumed its input
  after the latest tick read the work is idle until the next tick,
  unless the earlier tick found input that the round did not consume.
  Its detail says that it is awaiting the next update. Otherwise the
  detail says why: the work's pull request is ready for review, still a
  draft and so needing feedback, merged or closed after its wrap-up
  round, or failing its checks after two attempts under the relay rule;
  a conversation's latest round answered, needed no reply, was stopped,
  errored or was interrupted. Idle work has nothing to do, and never
  waits for the user to change something on GitHub.
- **Held**: the scheduler takes no round of a conversation until
  something on GitHub changes, as for a held request: the user paused
  it, the issue has a routing conflict, or someone other than the user
  applied its label. The issue's state says why, and the detail says
  what brings the work back.

The statuses are decided in an order. Working comes first, then ended,
then fault, so the user can see a fault and retry whatever else is true.
A failed read comes next, as unknown. Held comes before waiting, because
no round will start however its last round ended. The awaiting-update
idle case comes before waiting when the latest tick found no new input,
or started the round that then consumed its input. Then come waiting and
idle, and work that the latest tick has no row for, or read nothing for,
is unknown when nothing else applies.

These statuses summarize what matters now; they are not a persisted
lifecycle or a substitute for the underlying facts. In particular,
pull-request state, what woke each round, whether another round is
required, and the work's health remain separate concepts even though
they contribute to the summary.

A status report lists the open work of each kind in attention order,
fault, working, waiting, idle, held and then unknown, followed by the
requests of that kind with no open work. Ended work of every kind is
counted apart from active work, in a collapsed list of ended work on the
web home page and in a count of ended work in the terminal.

A running round remains working when its issue gains a second label of
its kind, because a routing conflict does not cancel work already in
progress. The conversation is held after that round ends, unless it is
then in fault.

Replaces: "running", for the status working; "needs attention", for
fault; "needs user feedback" and "needs you", for idle; and "closed",
for how a conversation ended.

### Status reports do not control work

A status report may include operational facts such as the repository
identity, whether the daemon is running, how long until the next
scheduler tick, or that a tick is running, current capacity, whether a
global cooldown is active, and the scheduler failures. A scheduler
failure is a failure in the latest tick that no request row holds: a
failed issue listing, or a worktree or branch of ended work that Git
would not remove. A failed read for a request is held in its request
row, and so is a round that errored during its preparation or startup.
Its request statuses and agent work statuses are projections derived for
a person to read.

The status report never schedules work and is never an input to
scheduling. Scheduling and reporting must nevertheless interpret the
same underlying facts consistently.

## Ambiguous terms

Some words mean different things in the tools that _dreamcatcher_ works
with. _dreamcatcher_ does not name its own concepts with them, and uses
them only in the sense that each section here gives.

### Turn

The two agent harnesses use "turn" differently. Claude Code calls each
call of the model, with the tool calls that its output asks for, a turn,
so one harness invocation holds many turns; its `--max-turns` option and
the `num_turns` in its result count them. Codex calls the agent's whole
response to one prompt a turn, so one harness invocation holds one, from
`turn.started` to `turn.completed`.

In either sense, the agent **ends its turn** when the model answers
without asking for another tool, and its harness invocation then exits.
_dreamcatcher_ uses the word only in that phrase and to name a harness's
own events, such as Codex's `turn.failed`. A round is not a turn in
either sense.
