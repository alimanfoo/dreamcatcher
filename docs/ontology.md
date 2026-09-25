# Dreamcatcher ontology

This document establishes the language Dreamcatcher uses to describe its domain.
It is an enduring part of the project: changes to the code, user interface,
specifications, and agent contract should preserve these meanings or update this
document deliberately.

The dated specifications record the design of particular phases. Where their
terminology conflicts with this document, this document is authoritative.

## Definitions

### Repository

A **repository** is a GitHub repository in which a Dreamcatcher instance manages
agent work.

### User

A **user** is the person on whose behalf a Dreamcatcher instance manages agent
work. The user provides decisions and reviews work through GitHub.

### Dreamcatcher instance and daemon

A **Dreamcatcher instance** is one local body of configuration and state which
manages agent work in one repository on behalf of one user. It endures while
Dreamcatcher is stopped and across successive runs. Several users may each run
their own Dreamcatcher instance for the same repository.

A **daemon** is the process that runs a Dreamcatcher instance. At most one
daemon runs an instance at a time.

### Issue and issue identifier

An **issue** is a GitHub issue that may be considered for implementation. Its
GitHub number is its **issue identifier**, conventionally written as `GH123`.

### Agent assignment and agent assignment identifier

An **agent assignment** is Dreamcatcher's durable commission to an agent to
implement one issue. It is the central unit of work managed by Dreamcatcher.

An **agent assignment identifier** identifies one agent assignment. It combines
the issue identifier with a timestamp, as in `GH123-20260912-192458`, and is
distinct from the issue identifier because an issue can receive more than one
assignment over its lifetime.

### Pull request

The assignment's **pull request** is both the proposed change and the primary
communication channel between the agent and the user.

### Issue conversation

An **issue conversation** is Dreamcatcher's durable commission to an agent to
answer the user on an issue without implementing a change. It owns a detached
worktree at a recorded main revision, one harness session, and its agent rounds.
Each round input records the comment batch delivered in that round. The issue
remains its communication channel; it has no implementation branch or pull
request.

An issue conversation starts with one initial round. Each later eligible comment
batch resumes the same harness session in another round. Each successful round
posts its final answer on the issue before it ends, unless the answer is
`NO_REPLY`, which means no post is needed. Automatic recovery is not supported
yet.

### Agent work and agent work identifier

**Agent work** is either an agent assignment or an issue conversation. Its
**agent work identifier** is the agent assignment identifier for an assignment,
or the issue identifier prefixed with `conversation-`, as in
`conversation-GH123`, for an issue conversation.

### Agent harness and harness session

An **agent harness** is a program, such as Claude Code or Codex, through which
Dreamcatcher runs an agent.

A **harness session** is the continuing context maintained by the agent harness
for one agent assignment or issue conversation. The harness supplies its own
**harness session identifier**, which is distinct from the agent work
identifier.

### Assignment skill

An **assignment skill** is an agent skill which follows Dreamcatcher's
agent-facing contract and guides an agent through an agent assignment. It may be
invoked by an assignment recipe.

### Assignment recipe

An **assignment recipe** specifies how Dreamcatcher starts an agent working on
an assignment through a particular agent harness. It supplies the model, effort,
and initial prompt for that harness. The initial prompt normally invokes an
assignment skill.

### Dispatch label

A **dispatch label** is a GitHub issue label configured to mark issues for
handling by Dreamcatcher.

### Dispatch route

A **dispatch route** maps one dispatch label to one or more assignment recipes.
Each recipe uses a particular agent harness. A route may offer recipes for all
the harnesses Dreamcatcher supports or for only some of them.

### Agent round

An **agent round** is one bounded activation of an assignment's or issue
conversation's harness session. Its core is a contiguous sequence of actions
taken by the agent within that harness session. It begins when Dreamcatcher
starts or resumes the harness with a prompt, and ends when that invocation exits
or is interrupted.

An agent round is a Dreamcatcher concept. It is not a model turn, a tool call,
or the harness session itself. An agent round has a number which identifies its
position within one assignment or issue conversation.

### Round purpose

Every agent round has one **round purpose**. An assignment round has one of
these:

- **Implement**: advance an assignment whose pull request is still a draft.
- **Address feedback**: respond after the pull request is ready for the user to
  review.
- **Wrap up**: finish an assignment whose pull request has been merged or
  closed.

An issue conversation round always has the same purpose:

- **Discuss**: answer the user in an issue conversation.

### Round outcome

An agent round may be:

- **running**;
- **successful**, when its harness invocation exits without an error;
- **errored**, when the invocation exits with an error; or
- **interrupted**, when it was stopped before recording an ending.

### Recovery round

A **recovery round** is an agent round run because the preceding round was
interrupted or exited with an error. Recovery is a true-or-false property of a
round, independent of its purpose.

### User post and feedback

A **user post** is a user-authored contribution to an assignment's pull request.
It normalizes the different places in which GitHub lets the user write:
conversation comments, review bodies, review verdicts, and inline review
comments.

Collectively, user posts are **feedback**. Dreamcatcher **relays** new user
posts into a later agent round. Relay is an action, not a separate durable
domain object.

### Scheduler

The **scheduler** decides what work Dreamcatcher starts and when.

### Status report

A **status report** is Dreamcatcher's read-only account of a Dreamcatcher
instance, its issue conversations, agent assignments, failed assignment setups,
issues that are available for new assignments, and issues with known open
blockers at a particular time.

An **issue observation** records the independent facts that one scheduler tick
found for an issue. Its availability is derived from those facts.

An **agent assignment status** is an assignment's single summary status in a
status report. It summarizes the assignment record, recorded rounds, live
process state, and the latest scheduler evidence about whether another round was
required or launched.

An **issue conversation status** is a conversation's single summary status in a
status report. It is derived from the conversation record, its latest round, the
daemon process, and the latest scheduler evidence about whether its issue is
eligible and whether comments wait to be answered.

### Global cooldown

A **global cooldown** is a temporary pause on starting agent work when there is
evidence of a shared problem affecting agent harnesses, such as overload or an
exhausted usage allowance.

## Relationships and rules

### Agent assignment composition

Each agent assignment has exactly one:

- issue;
- branch;
- Git worktree;
- pull request;
- agent harness; and
- harness session.

An assignment has no agent rounds until work begins and one or more afterwards.
Its rounds form a sequence numbered within the assignment; their numbers have no
meaning outside it.

An issue can receive more than one assignment over its lifetime, but a
Dreamcatcher instance can never have more than one open assignment for the same
issue. An agent assignment remains open until it is complete, including while
its pull request is being wrapped up.

### Dispatch labels and routes

An issue with no dispatch label is outside Dreamcatcher's scope. An issue with
more than one dispatch label has a routing conflict. The order of dispatch
routes in the configuration does not give one route precedence over another.

Exactly one dispatch label selects exactly one dispatch route. Dreamcatcher then
selects an assignment recipe for the agent harness through which the assignment
will run.

### Completing an assignment

An assignment becomes **complete** only when a wrap-up round exits successfully.
A successful implementation or feedback round does not complete the assignment.

If the pull request was merged, GitHub closes the issue and there can be no
later assignment for it. If the pull request was closed without being merged,
the issue remains open and may receive another assignment after the previous
assignment has completed.

### Describing an agent round

Number, purpose, recovery, and outcome describe different aspects of an agent
round. For example, the **first round** is round number one. A **wrap-up round**
has wrapping up after a pull request is merged or closed as its purpose. A
**recovery round** follows an interrupted or errored round and resumes the
assignment's work. An implementation, feedback, or wrap-up round may therefore
also be a recovery round, and two or more rounds may have the same purpose.

### Issue observations and availability

An issue observation records these independent facts, each of which can be true,
false, or unknown:

- **Claimed here**: this Dreamcatcher instance has an open agent assignment for
  the issue.
- **Claimed elsewhere**: the issue has an open linked pull request other than
  the pull request belonging to its local assignment, if any.
- **Blocked**: an open issue dependency prevents work from starting.
- **Routing conflict**: the issue carries more than one dispatch label.

These facts can coexist. In particular, an issue may be claimed both here and
elsewhere if somebody opens another pull request after Dreamcatcher creates its
assignment. A claimed issue may also become blocked or develop a routing
conflict after an assignment has started.

An issue whose assignment setup was interrupted has an incomplete assignment
setup. If a later tick can safely resume the assignment setup, claimed elsewhere
is false. Otherwise, the reason that the assignment setup cannot resume is
evidence that claimed elsewhere is unknown, unless an open linked pull request
proves the fact true. The issue observation records the failed setup attempt
separately, so the status report can show it even when another fact determines
availability. Every later tick tries to perform the assignment setup again.

An issue with a local assignment appears through its agent assignment rather
than in the report's available issues.

An issue is **available for an agent assignment** only when:

- it is open;
- it is assigned to the user for this Dreamcatcher instance;
- it carries exactly one dispatch label;
- claimed here is known to be false;
- claimed elsewhere is known to be false;
- blocked is known to be false; and
- routing conflict is known to be false.

Availability is derived rather than an independent fact. It is false as soon as
any known fact prevents assignment. If no known fact prevents assignment but a
required fact is unknown, availability is also unknown. A failure to observe
external state can delay work, but must never cause Dreamcatcher to create
duplicate or improperly routed work.

There is no durable issue queue. The status report preserves the scheduler's
order for available issues, which is the order in which it will consider them
for new assignments.

### Agent assignment status

An agent assignment has one of these summary statuses in a status report:

- **Working**: an agent round is running.
- **Waiting**: an agent round is required but has not started, or a round has
  just ended and the scheduler has not inspected its result yet.
- **Needs user feedback**: no agent round is currently required and the
  assignment awaits a user post, review decision, merge, or closure.
- **Fault**: two consecutive agent rounds for this assignment have exited with
  errors and ordinary recovery has stopped.
- **Complete**: a wrap-up round has exited successfully.
- **Unknown**: Dreamcatcher cannot determine the assignment's status from what
  it can currently observe.

These statuses summarize what matters now; they are not a persisted lifecycle or
a substitute for the underlying facts. In particular, pull-request state, round
purpose, whether another round is required, and assignment health remain
separate concepts even though they contribute to the summary.

An issue that is claimed here has a corresponding open assignment. That
assignment can have any assignment status except complete.

### Issue conversation status

An issue conversation has one of these summary statuses. Each uses the word of
the agent assignment status that means the same thing:

- **Working**: an agent round is running. Its counterpart is working.
- **Waiting**: a round is due but has not started, because comments wait to be
  answered, the first batch included. A free agent slot, or the end of a
  cooldown, starts it. Its counterpart is waiting.
- **Idle**: no round is due, because the latest answer is posted or the user has
  not commented yet. Its counterpart is needs user feedback.
- **Fault**: the latest round errored or was interrupted, or a round's input
  cannot be read. Dreamcatcher does not resume a conversation round
  automatically yet. Its counterpart is fault.
- **Unknown**: Dreamcatcher cannot tell whether the issue is eligible or whether
  comments wait. Its counterpart is unknown.

Idle differs from needs user feedback on purpose. An assignment at rest has a
pull request waiting for review, so it asks something of the user. A
conversation at rest has already posted its answer, so it asks nothing. A
conversation has no complete status.

Every eligible issue has a conversation status from the first scheduler tick
that observes it, whether or not a conversation record exists yet. Once the
issue is not eligible, the status report lists its conversation only while a
round runs. The conversation's own view still shows it, as idle with the reason.
Conversations are listed as fault, working, waiting, unknown and then idle,
since idle is not a call to action.

These statuses are derived reporting projections, not persisted lifecycle state.

### Status reports do not control work

A status report may include operational facts such as the repository identity,
whether the daemon is running, when the last scheduler tick occurred, current
capacity, whether a global cooldown is active, and the scheduler hold. The
scheduler hold says why the latest tick launched nothing, such as a cooldown,
full capacity, a failed issue listing, or a failed launch. Its issue
observations, issue conversation statuses and agent assignment statuses are
projections derived for a person to read.

The status report never schedules work and is never an input to scheduling.
Scheduling and reporting must nevertheless interpret the same underlying facts
consistently.

## Processes

### Creating an agent assignment

Dreamcatcher creates the branch and worktree, makes and pushes an empty commit,
and opens a linked draft pull request before it asks the agent to do any work.
These steps are part of creating the assignment, not responsibilities delegated
to the agent or to the assignment skill. Every recorded agent assignment
therefore already has a pull request before the agent starts working.

Creating the durable assignment and starting its first agent round are separate
operations, but the scheduler performs them as one scheduling action. As soon as
assignment setup succeeds, it starts the first implementation round without
waiting for another scheduler tick.

### Starting an issue conversation

An open issue becomes a conversation candidate when it carries the configured
conversation label, is assigned to the signed-in account, and has at least one
eligible comment from that account after the newest comment in its latest round
input. Issue title and body alone do not start a round. Assignment ownership,
linked pull requests, dependencies and dispatch-label conflicts do not govern
conversation eligibility.

Dreamcatcher fetches main, creates a detached worktree, records its revision and
the chosen conversation settings, freezes the issue and eligible comment batch,
then starts the initial conversation round. The round shares the daemon's
capacity and global cooldown with assignment rounds. The round posts its final
result on the issue before it records its ending. A failed post makes the round
errored.

After the round ends, another eligible comment batch resumes the same harness
session in another conversation round. Before it accepts that batch,
Dreamcatcher fetches main and asks Git to move the detached worktree to the
fetched revision, discarding local changes left by the earlier investigation.
Comments that arrive while a round runs stay beyond the latest round input.
Closing the issue, removing its conversation label or unassigning the signed-in
account stops new comment batches and takes the conversation off the status
report once no round runs for it. The saved conversation is kept, and making the
issue eligible again brings it back.

### Working through an assignment

An assignment normally progresses as follows:

1. Dreamcatcher opens its pull request as a draft during assignment setup.
2. The agent works on the implementation and may ask the user questions while it
   remains a draft.
3. The agent marks it ready when the work is ready for the user to review.
4. The user may review it and leave feedback over any number of exchanges.
5. The agent addresses the feedback and leaves the pull request ready for the
   user to review again. Steps 4 and 5 may repeat.
6. The user merges it or closes it without merging.
7. The agent wraps the assignment up.
8. A successful wrap-up round completes the assignment.

### Scheduling rounds in response to events

One or more new user posts cause an agent round to be scheduled. If a user posts
again while that round is running, the later posts remain unrelayed and cause a
further round to be scheduled at the next available opportunity. User posts and
agent rounds do not therefore alternate in strict turns.

The round is launched in the same way in either case. Its recorded purpose is
implementation while the pull request is a draft and feedback after the pull
request is ready for review. For example, if the first implementation round ends
by asking the user a question, the user's answer causes another implementation
round to be scheduled.

Merging or closing the pull request causes a wrap-up round to be scheduled. An
errored or interrupted round does not require user input. Dreamcatcher schedules
a recovery round automatically unless the assignment has entered a fault.

### Scheduling work

The scheduler creates agent assignments and starts agent rounds. A failed issue
read prevents launches in the workflow that depends on those facts without
preventing work in the other workflow.

Existing assignments take precedence over new ones, ranked in this order:

1. recover an interrupted or first-time errored assignment round;
2. wrap up an assignment whose pull request has been merged or closed;
3. start an assignment round for new user posts; and
4. create an assignment for the oldest available issue.

Conversation candidates are ordered by their oldest waiting comment. When both
an assignment candidate and a conversation candidate are ready, the scheduler
alternates which kind receives the next free slot. When only one kind is ready,
it proceeds without waiting for the other.

### Handling errors and global cooldown

A known global error may start a global cooldown immediately.

For errors that cannot be diagnosed reliably, one assignment's first consecutive
error calls for a recovery round and its second places that assignment in fault.
If two assignments enter fault, that is evidence of a shared problem and starts
a global cooldown. When the cooldown ends, Dreamcatcher clears those faults and
permits recovery. This deliberately simple policy prevents one
assignment-specific failure from blocking all other work.

After resolving an assignment-specific problem, the user may request a retry.
That request clears the assignment's current fault without erasing its errored
rounds, and the scheduler may start a recovery round on its next tick. Only
errors at or after the later of the latest retry request and the latest
completed global cooldown count towards a new fault.
