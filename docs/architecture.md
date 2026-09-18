# Dreamcatcher target architecture

This document describes the enduring target architecture for Dreamcatcher. It
maps the concepts in [the ontology](ontology.md) to code boundaries and states
the responsibilities, interfaces, and encapsulation those boundaries should
provide.

The dated specifications record the design of particular phases. Where an older
design conflicts with this target, this document is authoritative.

## Architectural aims

The architecture should make the domain visible in the code without making every
domain phrase into a class. In particular, it should:

- give each important decision one owner;
- separate persistent facts, live observations, derived status, and actions;
- keep scheduling policy out of process supervision and presentation;
- keep GitHub and harness-specific data behind explicit boundaries;
- make interrupted operations recoverable without inventing incomplete domain
  objects;
- preserve conservative behavior when an external fact is unknown; and
- use the same interpretation of facts in scheduling and reporting without
  making either subsystem depend on the other's output.

## Principal boundaries

### Daemon lifecycle

`daemon.py` owns the lifetime of the daemon that runs a Dreamcatcher instance:

- acquire and release the repository lock;
- record the daemon process identifier;
- perform startup recovery of child processes;
- call the scheduler repeatedly;
- wait between ticks; and
- stop active child processes during shutdown.

The daemon does not decide which issue or assignment deserves work. It knows
that scheduling happens, but not the scheduling priorities.

### Scheduling

`scheduler.py` owns all decisions about what work starts and when.

One scheduler tick:

1. observes the relevant local, process, configuration, and GitHub facts;
2. reconciles incomplete assignment creation and round processes, including
   recognizing interrupted rounds;
3. applies capacity and global-cooldown constraints;
4. finds the highest-priority existing assignment that requires an agent round,
   considering recovery need, a terminal pull request, and unrelayed user posts
   in that order;
5. otherwise finds the oldest issue available for an agent assignment;
6. performs at most one scheduling action; and
7. when the look completes, records a concise account of what happened for
   operational reporting.

A look that fails before producing that account is reported in daemon output and
leaves the last complete scheduler record in place. An invalid scheduler record
ends the daemon because retrying cannot repair the document.

The scheduler uses two distinct lower-level operations: creating an agent
assignment and starting an agent round. When it selects an available issue, it
performs both operations in one scheduling action, starting the first round as
soon as assignment creation succeeds. Keeping the operations separate preserves
clear ownership. If the combined action is interrupted between the operations,
the complete assignment record shows that its first round is missing, and the
scheduler finishes the action before ordinary scheduling. This does not create a
separate class of normally scheduled work.

For every new round, the scheduler derives purpose and recovery independently. A
terminal pull request requires wrap up; otherwise a draft pull request calls for
implementation and a ready pull request calls for addressing feedback. The
recovery flag is true when the preceding round was interrupted or exited with an
error and the assignment does not currently have fault status. A recovery round
can therefore have any purpose.

Scheduling should expose pure, read-only functions for interpretations that
status reporting also needs, particularly whether an issue is available for an
agent assignment and what round an assignment requires next. The status
subsystem may reuse those functions. The scheduler must never consume a status
report or presentation model.

Scheduling priority is derived from current facts rather than persisted as a
queue.

### Agent assignments

`agent_assignments.py` owns the durable representation and lifecycle operations
of an agent assignment. It should provide cohesive operations to:

- create an assignment while enforcing that its issue has no open local
  assignment;
- read existing assignments;
- find the open assignment for an issue;
- update the harness session identifier and user-post delivery cursor; and
- recognize completion after a successful wrap-up round.

Assignment creation coordinates lower-level Git, GitHub, configuration, and
document operations. As one recoverable workflow it:

1. allocates the agent assignment identifier;
2. fetches the current main branch;
3. creates the assignment branch and worktree;
4. makes an empty commit and pushes the branch;
5. opens a linked draft pull request;
6. writes the complete assignment record atomically;
7. returns the newly created assignment to the scheduler so it can start the
   first round immediately.

An interruption can leave external setup artifacts, but not a valid partial
assignment record. The assignment identifier determines the branch and worktree
identities, and the pull request identifies that branch as its head. Recovery
can therefore recognize artifacts belonging to the same assignment. Repeating or
recovering creation must reuse or remove those artifacts as appropriate and must
not create a second branch or pull request. If the complete assignment record
already exists, the scheduler continues to the first round instead of recreating
the assignment.

The assignment remains open until the module recognizes a successful wrap-up
round. A merged or closed pull request calls for wrap up but does not by itself
complete the assignment.

The assignment module coordinates the workflow but does not implement Git
commands, parse GitHub responses, launch harnesses, or choose when work should
run.

### Agent rounds

`agent_rounds.py` owns agent-round records and the supervised lifetime of a
round process. It should provide operations to:

- allocate the next number within an assignment;
- record the round's purpose and whether it is recovery;
- write the prompt and any relayed user posts;
- ask a harness adapter to build the invocation;
- start that invocation in the assignment's worktree;
- stream and render its output;
- record a successful or errored ending;
- interrupt the process tree safely; and
- recognize and record an interruption when a previously running process is no
  longer present without a recorded ending.

The scheduler decides which purpose and recovery flag a new round has. The round
boundary executes and records that decision; it does not inspect the pull
request or select later work.

A round is running while it has no terminal outcome and its process is alive.
Successful, errored, and interrupted are terminal outcomes. Reconciliation
records interrupted when a round has no recorded ending and its process is no
longer alive.

A round may have an internal collection of file paths, but the domain object
shared across boundaries is the assignment's Git worktree.

### GitHub

`github.py` is the only boundary that knows GitHub response shapes or constructs
GitHub commands. It owns projections and operations for:

- repository and account identity;
- issue state, assignees, labels, and dependencies;
- linked pull requests;
- pull-request identity, draft state, readiness, and terminal state;
- creating the linked draft pull request; and
- reading and normalizing user posts from comments, reviews, verdicts, and
  inline comments.

An agent assignment persists its pull-request identity, not a cached copy of
mutable pull-request state. Scheduling and reporting read that state from GitHub
when they need it.

GitHub owns its documents and may add fields, so its responses remain tolerant
projections. Documents owned by Dreamcatcher remain strict.

### User-post relay

`relay.py` owns the act of selecting user posts not yet delivered to the agent
and preparing them as input to an agent round. It compares normalized user posts
from the GitHub boundary with the assignment's delivery cursor.

Relay does not define a separate inbox domain entity and does not decide when a
round should run. The scheduler determines whether unrelayed user posts require
work; the relay prepares the posts, and the assignment records the newest post
accepted for delivery at the appropriate durable point. Posts made while a round
is running remain beyond that cursor and are available to a later round.

### Harness adapters

`harness_adapters.py` and `harnesses.py` form the harness boundary. A harness
adapter knows:

- how to start a new harness session;
- how to resume an identified harness session;
- which model and effort arguments its harness needs;
- how to recover the harness session identifier from output; and
- how to parse the harness's event stream.

An adapter does not know about issues, pull requests, dispatch routes,
assignment status, scheduling priorities, or status reports. It receives an
invocation request and returns the command, prompt behavior, and parsed events
needed by the round runner.

The code should always name a harness session explicitly when that is what an
identifier or operation refers to. A bare `session` name is not part of this
interface.

### Status reporting

`status.py` owns the read-only status model and constructs a `StatusReport`
containing instance and daemon facts, `IssueStatus` entries, and
`AgentAssignmentStatus` entries.

Status construction may read:

- assignment and round records;
- current child-process state;
- scheduler records, including the active global cooldown and latest tick;
- configuration, dispatch labels, and routes;
- current GitHub issue, dependency, and pull-request facts; and
- the latest rendered feed output needed for a useful summary.

It may call the scheduler's pure interpretation functions, but it cannot invoke
a scheduling action, mutate an assignment, relay a user post, or start a
process. Status values are always derived; they are not written back as domain
state.

An `IssueStatus` represents claimed here, claimed elsewhere, blocked, and
routing conflict as independent facts which may each be true, false, or unknown;
availability is derived from those facts together with whether the issue is
open, assigned to the instance's user, and carries exactly one dispatch label.
An `AgentAssignmentStatus` is one summary status from the ontology. The report
includes every issue considered for a new assignment and every issue with an
open local assignment, even if later changes to GitHub state or configuration
would prevent a new assignment for that issue.

### TUI

`tui.py` renders status reports and feeds with Rich. It owns presentation only.
It should not rediscover status, scheduling, or lifecycle rules while choosing
headings and colors.

### Configuration, dispatch labels, and routes

`config.py` owns the strict model for `dreamcatcher.toml`. A `DispatchRoute`
maps one dispatch label to one or more harness-specific `AssignmentRecipe`
objects. Each recipe supplies the model, effort, and initial prompt used to
start agent work through that harness. The initial prompt normally invokes an
assignment skill.

The configuration module validates labels, routes, and recipes and, given an
issue's observed labels, identifies which are configured dispatch labels. It
does not silently resolve multiple labels by list order. The scheduler
interprets exactly one dispatch label as routable, more than one as a routing
conflict, and none as outside scope.

### State and documents

`state.py` owns the paths within `.dreamcatcher/` and the mechanics required to
bootstrap that directory. It should become deliberately small. It must not
contain collections of issues or assignments selected for work, scheduling
decisions, or status projections.

The on-disk layout follows ownership:

- instance-wide operational records live at the state-directory root;
- each assignment owns its durable record, delivery cursor, and numbered round
  records;
- each round owns its prompt, raw output, rendered feed, and any delivered user
  posts; and
- worktrees live in a separate collection keyed by assignment identifier.

`documents.py` remains the only way Dreamcatcher reads and writes documents it
owns. Every structured document has a strict model and every replacement write
is atomic. One-value process or cursor files may remain simple text where a
model would add no meaning.

State-directory objects provide paths and document access. They do not answer
domain questions such as whether an assignment is complete or an issue is
available for an agent assignment.

### Git, commands, prompts, and feeds

`git.py` owns Git operations and worktree mechanics. It does not know why an
assignment was selected or what GitHub reports about it.

`commands.py` remains the sole subprocess boundary. Higher-level modules ask it
to run or spawn already-constructed commands; no other module imports the
subprocess library.

`prompts.py` owns the construction of the prompts passed to agent harnesses. It
receives the information required to construct each prompt. It does not infer
why an agent round is being run or make scheduling decisions.

`feed.py` owns the harness-neutral activity representation and rendering of
parsed harness events into plain-text records. Rich presentation remains in the
TUI boundary.

## Persistent and derived information

The architecture persists facts needed to recover identity, ownership, and
acknowledged work.

An assignment record persists:

- the issue and assignment identifiers;
- the frozen dispatch route and assignment recipe selected at creation;
- branch and worktree identity;
- pull-request identity;
- harness identity and, once known, its harness session identifier; and
- the cursor identifying the latest user post accepted for delivery.

A round record persists:

- its assignment-scoped number;
- purpose and recovery flag;
- start time and process identifier;
- its terminal outcome, when known, and any observed end time and exit status;
  and
- the durable files containing its prompt, delivered posts, and output.

An instance-wide scheduler record persists an active global cooldown and the
time at which the most recent cooldown ended. This allows fault to remain a
derived status: ending a cooldown changes which round errors count towards fault
rather than writing an assignment status.

The following are derived rather than persisted as authoritative state:

- whether an issue is claimed here or elsewhere;
- whether an issue is blocked, has a routing conflict, or is available for an
  agent assignment;
- whether an assignment is complete or in fault;
- whether an assignment requires an agent round or needs user feedback;
- what round purpose and recovery flag are required next; and
- every issue and assignment status shown in a status report.

Mutable external facts, including issue state, assignees, labels, dependencies,
linked pull requests, pull-request draft/readiness/terminal state, and user
posts, are read from GitHub. A failed read produces an unknown fact and
conservative inaction rather than a guessed answer.

## Dependency direction

The important dependency rules are:

- the daemon depends on the scheduler, never the reverse;
- the scheduler may direct assignment and round operations;
- assignment and round modules depend on narrow Git, GitHub, document, harness,
  prompt, and command boundaries, not on the scheduler;
- status reporting may reuse pure scheduling interpretations but may not call
  scheduling actions;
- the TUI depends on status and feed models, while neither depends on the TUI;
- GitHub and harness adapters expose projections to the domain and never import
  presentation or scheduling policy; and
- state and document modules know storage mechanics, not domain policy.

These rules keep the scheduling loop imperative and straightforward without
turning every possible action into an abstract command hierarchy.

## Agent-facing contract

The assignment-skill contract is a third enduring design document alongside this
architecture and the ontology. It should describe the protocol between
Dreamcatcher and an assignment skill, not implementation history.

The contract should establish that:

- Dreamcatcher provides the issue, branch, worktree, and already-open draft pull
  request;
- the assignment skill adopts those resources rather than creating them;
- the agent uses the pull request for questions and feedback;
- the agent marks the pull request ready when implementation is ready for
  review;
- resumed rounds act on relayed user posts; and
- wrap-up rounds distinguish a merged pull request from one closed without
  merging.
