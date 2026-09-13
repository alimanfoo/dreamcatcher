# Dreamcatcher target architecture

This document describes the enduring target architecture for Dreamcatcher. It
maps the concepts in [the ontology](ontology.md) to code boundaries and states
the responsibilities, interfaces, and encapsulation those boundaries should
provide.

It intentionally does not describe how to migrate the current code. Migration
will be planned only after the ontology and target architecture have been
reviewed and accepted.

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

`daemon.py` owns the lifetime of the foreground service:

- acquire and release the repository lock;
- record the daemon process identifier;
- perform startup recovery of child processes;
- call the scheduler repeatedly;
- wait between ticks; and
- stop active child processes during shutdown.

The daemon does not decide which issue or assignment deserves work. It knows
that scheduling happens, but not the scheduling priorities.

### Scheduling

`scheduler.py` owns all decisions about what work starts and when. It absorbs
the policy currently spread across the daemon, eligibility checks, and wakeup
logic.

One scheduler tick:

1. observes the relevant local, process, configuration, and GitHub facts;
2. reconciles newly completed or interrupted rounds;
3. applies capacity and global-cooldown constraints;
4. finds the highest-priority existing assignment that requires a recovery,
   winding-up, user-post response, or first implementation round;
5. otherwise finds the oldest issue available for assignment;
6. performs at most one scheduling action; and
7. records a concise account of what happened for operational reporting.

The scheduler directs two distinct actions: creating an agent assignment and
starting an agent round. Creating an assignment does not implicitly start its
first round. Normally that new assignment becomes the work selected by a later
tick.

Scheduling should expose pure, read-only functions for interpretations that
status reporting also needs, particularly whether an issue is available for
assignment and what round an assignment requires next. The status subsystem may
reuse those functions. The scheduler must never consume a status report or
presentation model.

There is no persisted queue and no wakeup object. Priority is a scheduling
decision over current facts.

### Agent assignments

`agent_assignments.py` owns the durable representation and lifecycle operations
of an agent assignment. It should provide cohesive operations to:

- create an assignment;
- read existing assignments;
- find the open assignment for an issue;
- update the harness session identifier and relayed-user-post cursor; and
- recognize completion after a successful winding-up round.

Assignment creation coordinates lower-level Git, GitHub, configuration, and
document operations. As one recoverable workflow it:

1. allocates the agent assignment identifier;
2. fetches the current main branch;
3. creates the assignment branch and worktree;
4. makes an empty commit and pushes the branch;
5. opens a linked draft pull request;
6. writes the complete assignment record atomically; and
7. returns the newly created assignment without starting an agent round.

An interruption can leave external setup artifacts, but not a valid partial
assignment record. Repeating or recovering creation must recognize artifacts
belonging to the same assignment identifier and must not create a second branch
or pull request accidentally.

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
- record a successful or errored ending; and
- interrupt the process tree safely.

The scheduler decides which purpose and recovery flag a new round has. The round
boundary executes and records that decision; it does not inspect the pull
request or select later work.

The current exported idea of a round "workspace" should disappear. A round may
have an internal collection of file paths, but the domain object shared across
boundaries is the assignment's Git worktree.

### GitHub

`github.py` is the only boundary that knows GitHub response shapes or constructs
GitHub commands. It owns projections and operations for:

- repository and account identity;
- issue selection and issue dependencies;
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
round should run. The scheduler determines that new feedback requires work; the
relay prepares the user posts, and the assignment records the newest post
accepted for delivery at the appropriate durable point.

### Harness adapters

`adapters.py` and `harnesses.py` form the harness boundary. An adapter knows:

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
containing service facts, `IssueStatus` entries, and `AgentAssignmentStatus`
entries.

Status construction may read:

- assignment and round records;
- current child-process state;
- the latest scheduler-tick record;
- configuration and route matches;
- current GitHub issue, dependency, and pull-request facts; and
- the latest rendered feed output needed for a useful summary.

It may call the scheduler's pure interpretation functions, but it cannot invoke
a scheduling action, mutate an assignment, relay a user post, or start a
process. Status values are always derived; they are not written back as domain
state.

`tui.py` renders status reports and feeds with Rich. It owns presentation only.
It should not rediscover status, scheduling, or lifecycle rules while choosing
headings and colors.

### Configuration and dispatch routes

`config.py` owns the strict model for `dreamcatcher.toml`. A configured
`DispatchRoute` replaces the current dispatch-mapping terminology. The module
validates route structure and harness settings and can report which routes an
issue's labels match.

Configuration establishes matches; it does not silently resolve multiple matches
by list order. The scheduler interprets exactly one match as routable, more than
one as a conflict, and none as outside scope.

### State and documents

`state.py` owns the paths within `.dreamcatcher/` and the mechanics required to
bootstrap that directory. It should become deliberately small. It must not
contain candidate issues, waiting assignments, scheduling decisions, or status
projections.

The on-disk layout follows ownership:

- service-wide operational records live at the state-directory root;
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
available.

### Git, commands, prompts, and feeds

`git.py` owns Git operations and worktree mechanics. It does not know why an
assignment was selected or what GitHub reports about it.

`commands.py` remains the sole subprocess boundary. Higher-level modules ask it
to run or spawn already-constructed commands; no other module imports the
subprocess library.

`prompts.py` composes prompts from an explicit round purpose, recovery flag,
assignment context, and optional user posts. It does not infer why a round is
being run.

`feed.py` owns the harness-neutral activity representation and rendering of
parsed harness events into plain-text records. Rich presentation remains in the
TUI boundary.

## Persistent and derived information

The architecture persists facts needed to recover identity, ownership, and
acknowledged work.

An assignment record persists:

- the issue and assignment identifiers;
- the frozen dispatch route and harness settings selected at creation;
- branch and worktree identity;
- pull-request identity;
- harness identity and, once known, its harness session identifier; and
- the cursor identifying the latest user post accepted for delivery.

A round record persists:

- its assignment-scoped number;
- purpose and recovery flag;
- start time and process identifier;
- end time, exit status, and outcome when it ends; and
- the durable files containing its prompt, delivered posts, and output.

The following are derived rather than persisted as authoritative state:

- whether an issue is claimed here or elsewhere;
- whether an issue is blocked, conflicted, or available for assignment;
- whether an assignment is complete or in fault;
- which side is due to act;
- what round purpose is required next; and
- every issue and assignment status shown in a status report.

Mutable external facts, including issue state, dependencies, pull-request
draft/readiness/terminal state, and user posts, are read from GitHub. A failed
read produces an unknown fact and conservative inaction rather than a guessed
answer.

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

The dispatchable-skill contract is a third enduring design document alongside
this architecture and the ontology. It should describe the protocol between
Dreamcatcher and an agent skill, not implementation history.

The existing root `CONTRACT.md` still reflects the earlier responsibility split
in which the skill opens the draft pull request. Once the ontology and target
architecture are accepted, that contract should move into `docs/` and be revised
so that:

- Dreamcatcher provides the issue, branch, worktree, and already-open draft pull
  request;
- the skill adopts those resources rather than creating them;
- the agent uses the pull request for questions and feedback;
- the agent marks the pull request ready when implementation is ready for
  review;
- resumed rounds act on relayed user posts; and
- winding-up rounds distinguish a merged pull request from one closed without
  merging.

That contract revision belongs after review of these two documents, not inside
the migration plan and not as an implicit side effect of this architecture
draft.
