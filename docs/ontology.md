# Dreamcatcher ontology

This document establishes the language Dreamcatcher uses to describe its domain.
It is an enduring part of the project: changes to the code, user interface,
specifications, and agent contract should preserve these meanings or update this
document deliberately.

The dated specifications record the design of particular phases. Where their
terminology conflicts with this document, this document is authoritative.

## Definitions

### Repository

A **repository** is a GitHub repository managed by a Dreamcatcher instance.

### Dreamcatcher instance and daemon

A **Dreamcatcher instance** is one repository-scoped body of configuration and
local state. It endures while Dreamcatcher is stopped and across successive
runs.

A **daemon** is the process that runs a Dreamcatcher instance. At most one
daemon runs an instance at a time.

### Issue and issue identifier

An **issue** is a GitHub issue that may be considered for implementation. Its
GitHub number is its **issue identifier**, conventionally written as `GH123`.

### Dispatch route

A **dispatch route** connects a configured issue label with the instructions and
harness settings used to implement issues carrying that label. An issue must
match exactly one dispatch route before Dreamcatcher can create an agent
assignment for it. If an issue has no dispatch route then the issue is outside
Dreamcatcher's scope. More than one dispatch route is a routing conflict. The
order of routes in the configuration does not give one route precedence over
another.

### Agent assignment and agent assignment identifier

An **agent assignment** is Dreamcatcher's durable commission to an agent to
implement one issue. It is the central unit of work managed by Dreamcatcher.

An **agent assignment identifier** identifies one agent assignment. It combines
the issue identifier with a timestamp, as in `GH123-20260912-1924`, and is
distinct from the issue identifier because an issue can receive more than one
assignment over its lifetime.

### Pull request

The assignment's **pull request** is both the proposed change and the primary
communication channel between the agent and the user.

### Agent harness and harness session

An **agent harness** is a program, such as Claude Code or Codex, through which
Dreamcatcher runs an agent.

A **harness session** is the continuing conversation maintained by the agent
harness for one agent assignment. The harness supplies its own **harness session
identifier**, which is distinct from Dreamcatcher's agent assignment identifier.

### Agent round

An **agent round** is one bounded activation of an assignment's harness session.
Its core is a contiguous sequence of actions taken by the agent within that
harness session. It begins when Dreamcatcher starts or resumes the harness with
a prompt, and ends when that invocation exits or is interrupted.

An agent round is a Dreamcatcher concept. It is not a model turn, a tool call,
or the harness session itself. An agent round has a number which identifies its
position within one agent assignment.

### Round purpose

Every agent round has one **round purpose** from this set:

- **Implement**: advance an assignment whose pull request is still a draft.
- **Address feedback**: respond after the pull request is ready for the user to
  review.
- **Wind up**: finish an assignment whose pull request has been merged or
  closed.

### Recovery round and round outcome

A **recovery round** is an agent round run because the preceding round was
interrupted or exited with an error. Recovery is a true-or-false property of a
round, independent of its purpose.

An agent round may be:

- **running**;
- **successful**, when its harness invocation exits without an error;
- **errored**, when the invocation exits with an error; or
- **interrupted**, when it was stopped before recording an ending.

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
instance, its issues, and its agent assignments at a particular time. It
replaces the less precise term "board."

An **issue status** is an issue's entry in a status report. It is a derived,
read-only account of several independent facts, not a single lifecycle state.

An **agent assignment status** is an assignment's single summary status in a
status report. It is derived from the assignment record, its rounds, current
process state, and current GitHub state.

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
its pull request is being wound up.

### Completion

An assignment becomes **complete** only when a winding-up agent round exits
successfully. A successful implementation or feedback round does not complete
the assignment.

If the pull request was merged, GitHub closes the issue and there can be no
later assignment for it. If the pull request was closed without being merged,
the issue remains open and may receive another assignment after the previous
assignment has completed.

### Round purpose and recovery

Purpose describes why Dreamcatcher starts a round. It does not describe whether
the round is the first, last, or a recovery. Two or more rounds may have the
same purpose.

The **first round** is simply round number one. The **winding-up round** is a
round whose purpose is to wind up. Neither needs a separate purpose merely
because of its position in the sequence.

Any implementation, feedback, or winding-up round can be a recovery round. An
interruption does not count as an error.

### Issue status and availability

An issue status reports these independent facts, each of which can be true,
false, or unknown:

- **Claimed here**: this Dreamcatcher instance has an open agent assignment for
  the issue.
- **Claimed elsewhere**: the issue has another open linked pull request. When
  there is a local assignment, its own pull request is excluded from this test;
  without a local assignment, any open linked pull request is an external claim.
- **Blocked**: an open issue dependency prevents work from starting.
- **Routing conflict**: the issue matches more than one dispatch route.

These facts can coexist. In particular, an issue may be claimed both here and
elsewhere if somebody opens another pull request after Dreamcatcher creates its
assignment. A claimed issue may also become blocked or develop a routing
conflict.

An issue with a local assignment remains present in the status report even if
its labels, assignee, or route configuration later place it outside the set of
issues Dreamcatcher would consider for a new assignment. Selection governs new
work; it does not make existing work disappear.

An issue is **available for assignment** only when:

- it is open and within the configured issue selection;
- it matches exactly one dispatch route;
- claimed here is known to be false;
- claimed elsewhere is known to be false;
- blocked is known to be false; and
- routing conflict is known to be false.

Availability is derived rather than an independent fact. It is false as soon as
any known fact prevents assignment. If no known fact prevents assignment but a
required fact is unknown, availability is also unknown. A failure to observe
external state can delay work, but must never cause Dreamcatcher to create
duplicate or improperly routed work.

There is no conceptual issue queue. Available issues may be ordered when the
scheduler chooses among them, but that transient ordering does not give an issue
a durable queued state.

### Agent assignment status

An agent assignment has one of these summary statuses in a status report:

- **Working**: an agent round is running.
- **Waiting**: the agent is due to act, but the required round has not started,
  for example because capacity is full or a global cooldown is active.
- **Needs feedback**: the agent has handed control to the user and is waiting
  for a user post, review decision, merge, or closure.
- **Fault**: two consecutive agent rounds for this assignment have exited with
  errors and ordinary recovery has stopped.
- **Complete**: a winding-up round has exited successfully.
- **Unknown**: Dreamcatcher cannot determine the assignment's status from what
  it can currently observe.

These statuses summarize what matters now; they are not a persisted lifecycle or
a substitute for the underlying facts. In particular, pull-request state, round
purpose, whose control it is, and assignment health remain separate concepts
even though they contribute to the summary.

An issue that is claimed here has a corresponding open assignment. That
assignment can have any assignment status except complete.

### Status reports do not control work

A status report may include operational facts such as whether the daemon is
running, when the last scheduler tick occurred, current capacity, and whether a
global cooldown is active. Its issue statuses and agent assignment statuses are
projections derived for a person to read.

The status report never schedules work and is never an input to scheduling.
Scheduling and reporting must nevertheless interpret the same underlying facts
consistently.

## Processes

### Creating an agent assignment

Dreamcatcher creates the branch and worktree, makes and pushes an empty commit,
and opens a linked draft pull request before it asks the agent to do any work.
These steps are part of creating the assignment, not responsibilities delegated
to the agent or to the dispatchable skill. Every recorded agent assignment
therefore already has a pull request.

Starting the first agent round is a separate action. A newly created assignment
with no rounds yet is valid and waits for the scheduler to start its first
implementation round.

### Working through an assignment

An assignment normally progresses as follows:

1. Dreamcatcher opens its pull request as a draft during assignment creation.
2. The agent works on the implementation and may ask the user questions while it
   remains a draft.
3. The agent marks it ready when the work is ready for the user to review.
4. The user may review it and leave feedback over any number of exchanges.
5. The user merges it or closes it without merging.
6. The agent winds the assignment up.
7. A successful winding-up round completes the assignment.

Draft and ready are materially different pull-request states. An open pull
request must not be represented in a way that loses this distinction.

### Passing control between agent and user

The agent and user pass control through the pull request:

- A successful implementation or feedback round normally hands control to the
  user. This can happen while the pull request is still a draft because the
  agent needs a decision, when the agent marks it ready for review, or after the
  agent has addressed review feedback.
- A new user post hands control back to the agent.
- Merging or closing the pull request calls for a winding-up round.
- An errored or interrupted round does not hand control to the user; it calls
  for recovery unless the assignment has entered a fault.

For example, the first implementation round may end after asking the user a
question. Another implementation round continues the work after the user
answers. The second round responds to user input, but its purpose remains
implementation because the pull request is still a draft.

### Scheduling work

Creating an agent assignment and starting an agent round are actions performed
under the scheduler's direction; neither action is itself a durable "dispatch
decision" object.

Existing assignments take precedence over creating new ones. Subject to capacity
and cooldown, the scheduler considers work in this order:

1. recover an interrupted or first-time errored round;
2. wind up an assignment whose pull request has been merged or closed;
3. respond to new user posts on an existing assignment, using an implementation
   round while the pull request is a draft and a feedback round after it is
   ready;
4. start the first implementation round of an assignment that has been created
   but has not begun work;
5. create an assignment for an available issue; and
6. otherwise do nothing.

### Handling errors and global cooldown

A known global error may start a global cooldown immediately.

For errors that cannot be diagnosed reliably, one assignment's first consecutive
error calls for a recovery round and its second places that assignment in fault.
If two assignments enter fault, that is evidence of a shared problem and starts
a global cooldown. When the cooldown ends, Dreamcatcher clears those faults and
permits recovery. This deliberately simple policy prevents one
assignment-specific failure from blocking all other work.

## Terms deliberately avoided

Some earlier terms blurred distinct concepts:

- **Session** on its own is avoided. Harness session is retained for the session
  owned by the harness; agent assignment names Dreamcatcher's durable unit of
  work.
- **Installation** is avoided where the enduring repository-scoped concept is a
  Dreamcatcher instance.
- **Attempt** is not a synonym for agent assignment.
- **Workspace** is avoided where the concrete object is a Git worktree.
- **Board** is replaced by status report.
- **Candidate**, **eligible**, and **queued** are replaced by the precise issue
  facts and the derived phrase available for assignment.
- **Needs you** is replaced by needs feedback.
- **Stuck** is avoided because it does not identify whether the agent is waiting
  normally or has faulted.
- **Awake**, **asleep**, and **wakeup** are avoided because they do not state
  who is due to act or what action is required.
