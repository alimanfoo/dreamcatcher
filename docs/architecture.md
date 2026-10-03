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
- reconcile round records that an earlier daemon left without an ending by
  ending their recorded process trees at startup, then asking the round boundary
  to record them as interrupted;
- call the scheduler repeatedly;
- wait for the run's requested interval between ticks; and
- stop active child processes during shutdown.

The daemon does not decide which issue, assignment or conversation deserves
work. It knows that scheduling happens, but not the scheduling priorities.

### Scheduling

The scheduler package owns all decisions about what work starts and when.

One scheduler tick:

1. observes the relevant local, process, configuration, and GitHub facts;
2. reconciles incomplete assignment setup;
3. applies the run's requested capacity and global-cooldown constraints;
4. finds the highest-priority assignment candidate, considering existing
   assignment rounds before dispatching a new assignment for the oldest
   available issue;
5. finds the highest-priority conversation candidate, ranking recovery before
   the oldest waiting fresh comment;
6. alternates between the two kinds when both have candidates, without changing
   either kind's internal order;
7. performs scheduling actions until capacity is full or no candidate remains;
   and
8. returns a `SchedulerRecord` for operational reporting.

The daemon persists the returned `SchedulerRecord` and reports it in its output.
A scheduler tick that fails before returning one is reported in daemon output
and leaves the last complete scheduler record in place. An invalid scheduler
record ends the daemon because retrying cannot repair the document.

If an issue read fails, the tick records the failure as its hold and prevents
launches in the workflow that depends on those facts. An assignment issue read
does not prevent an issue conversation from starting, and a conversation issue
read does not prevent assignment work from starting. A later tick retries the
failed read.

If a launch fails, the tick keeps every round that it already started and
records the failure as its hold. It starts no lower-priority candidate of the
same kind during that tick, but it may still start ready work of the other kind.

The scheduler uses two distinct lower-level operations: creating an agent
assignment and starting an agent round. When it selects an available issue, it
performs both operations in one scheduling action, starting the first round as
soon as assignment setup succeeds. Keeping the operations separate preserves
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

### Issue conversations

`issue_conversations.py` owns conversation records and their durable operations.
An initial conversation freezes its issue title, body, trusted comment batch and
fetched main revision, then runs in a detached worktree. Conversation worktrees
live outside assignment discovery and never acquire implementation branches or
pull requests.

The signed-in GitHub account identifies trusted issue comments. Marked
Dreamcatcher comments, comments by other accounts and blank comments are
excluded. Each durable round input records the delivered batch, so the newest
comment in the latest input is the delivery position and a batch cannot be
selected again.

The first eligible batch starts one session through the harness selected from
the conversation's configured recipes, with the issue title, body and trusted
comment history. Each later eligible batch resumes that same harness session
with only newly delivered comments. The scheduler first fetches main and resets
the detached worktree to that revision, deleting every local commit and file.
Each round input records its investigated revision. Comments posted while a
round runs remain beyond the latest round input.

A failed or interrupted conversation round is recovered before a fresh batch
while its issue remains eligible. Recovery rereads that round's durable input,
so it uses the same comments and revision without reading new comments, fetching
main or refreshing the worktree. It resumes the recorded harness session with a
recovery prompt. When the first invocation did not record a session identifier,
recovery starts a new session with the configured prompt and the same input. A
selected batch that was never recorded establishes no delivery position and may
be replaced by the next fresh selection.

Fresh-batch candidates are polled before the capacity check.

Conversation harness permissions reinforce the no-implementation boundary while
allowing issue actions that the user requests. Claude allows selected `gh issue`
commands and `gh api` while denying direct editing and Git mutations. Codex runs
in a networked workspace-write sandbox without approval escalation. Each prompt
forbids source changes, Git mutations, pull-request changes and direct reply
posting, and requires the agent marker on every other GitHub post that the agent
makes.

A conversation round posts its own answer. The conversation launcher gives the
round a finisher that posts to the issue, so the shared round runner knows
nothing of GitHub. After the harness exits successfully, the round hands its
final result to that finisher, which posts it with the agent marker, and then
the round records its ending. It therefore keeps its agent slot while it posts,
and no new batch starts until the answer is out. `NO_REPLY` posts nothing. A
missing final result or a failed post makes the round errored. The ending keeps
the harness's clean exit status and gives the failure as its reason, and the
feed notes it too. Failed and interrupted rounds remain visible while ordinary
recovery proceeds, and two consecutive errored rounds place the conversation in
fault.

Harness adapters expose final answers separately from their progress streams.
Claude supplies the answer in its successful result event. For a Codex
conversation, the adapter gives `codex exec` the round's `final.md` path as its
last-message output file on first and resumed invocations.

### Agent assignments

`agent_assignments.py` owns the durable representation and lifecycle operations
of an agent assignment. It should provide cohesive operations to:

- create an assignment while enforcing that its issue has no open local
  assignment;
- read existing assignments;
- find the open assignment for an issue;
- allocate the next round number within an assignment;
- update the harness session identifier;
- read the user-post delivery position from recorded round inputs;
- record when the user requests another recovery attempt after resolving a
  fault; and
- recognize completion after a successful wrap-up round.

Assignment setup coordinates lower-level Git, GitHub, configuration, and
document operations. As one recoverable workflow it:

1. allocates the agent assignment identifier;
2. fetches the current main branch;
3. creates the assignment branch and worktree;
4. makes an empty commit and pushes the branch;
5. opens a linked draft pull request;
6. writes the complete assignment record atomically;
7. returns the newly created assignment to the scheduler so it can start the
   first round immediately.

An interruption can leave an incomplete assignment setup: a worktree and branch
without a valid assignment record. On a later tick, the assignment module checks
whether it can safely resume the assignment setup. If it cannot, it returns the
reason. The scheduler records that reason as evidence that claimed elsewhere is
unknown, unless an open linked pull request already proves the claim true. The
assignment identifier determines the branch and worktree identities, and the
pull request identifies that branch as its head. Recovery can therefore
recognize artifacts belonging to the same assignment. Repeating or recovering
the assignment setup must reuse or remove those artifacts as appropriate and
must not create a second branch or pull request. If the complete assignment
record already exists, the scheduler continues to the first round instead of
recreating the assignment.

The assignment remains open until the module recognizes a successful wrap-up
round. A merged or closed pull request calls for wrap up but does not by itself
complete the assignment.

The assignment module coordinates the workflow but does not implement Git
commands, parse GitHub responses, launch harnesses, or choose when work should
run.

### Agent rounds

`agent_rounds.py` owns agent-round records and the supervised lifetime of a
round process for both assignments and conversations. It should provide
operations to:

- record the next number that its owner allocated;
- record the round's purpose and whether it is recovery;
- write the prompt and any delivered input;
- ask a harness adapter to build the invocation;
- start that invocation in its owner's worktree;
- stream and render its output, and keep the final result the harness reports;
- let its owner finish a round whose harness succeeded, before the ending;
- record a successful or errored ending;
- interrupt the process tree safely; and
- record an interruption when the daemon finds a round record that an earlier
  daemon left without an ending.

`agent_assignments.py` owns `AssignmentRoundInput`, the pull request state and
relayed user posts that a resumed assignment round receives beside its prompt.
`issue_conversations.py` owns `ConversationInput`, which freezes the issue,
trusted comments and investigated revision for a conversation round. The round
runner writes whichever input the owner delivers without reading it, and it
hands the final result to the owner's finisher without knowing what the owner
does with it.

The scheduler decides which purpose and recovery flag a new round has. The round
boundary executes and records that decision; it does not inspect the pull
request or select later work.

A round is running while it has no terminal outcome and its process is alive.
Successful, errored, and interrupted are terminal outcomes.

A round may have an internal collection of file paths, but its owner remains the
domain object shared across boundaries.

### GitHub

`github.py` is the only boundary that knows GitHub response shapes or constructs
GitHub commands. It owns projections and operations for:

- repository and account identity;
- issue title, state, assignees, labels, and dependencies;
- linked pull requests;
- pull-request identity, draft state, readiness, and terminal state;
- creating the linked draft pull request; and
- reading ordinary issue comments and posting a conversation answer; and
- reading and normalizing user posts from comments, reviews, verdicts, and
  inline comments.

An agent assignment persists its pull-request identity and, separately, the
latest state and draft flag that a scheduler tick observed for reporting.
Scheduling does not read that observation. It reads the current state from
GitHub when it needs it.

GitHub owns its documents and may add fields, so its responses remain tolerant
projections. Documents owned by Dreamcatcher remain strict.

### User-post relay

`relay.py` owns the act of selecting user posts not yet delivered to the agent
and preparing them as input to an agent round. It compares normalized user posts
from the GitHub boundary with the assignment's delivery position, read from the
newest recorded round input that contains posts.

Relay does not define a separate inbox domain entity and does not decide when a
round should run. The scheduler determines whether unrelayed user posts require
work; the relay prepares the posts, and the round input records the newest post
accepted for delivery before its process starts. Posts made while a round is
running remain beyond that position and are available to a later round.

### Harness adapters

`harness_adapters.py` and `harnesses.py` form the harness boundary, with
`claude.py` and `codex.py` providing its two concrete adapters. A harness
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

Status reporting owns the read-only status model and constructs a
`DreamcatcherStatusReport` containing the repository identity, instance and
daemon facts, failed-setup, available and blocked `IssueObservation` entries,
`ConversationStatus` entries, and `AssignmentStatus` entries.

Status construction may read:

- assignment and round records;
- conversation and conversation-round records;
- raw harness output and the matching harness adapter when it must recover a
  harness session identifier or build a hand-resume command;
- current child-process state;
- the instance's repository record and daemon-run record;
- scheduler records, including issue observations, assignment and conversation
  observations, the active global cooldown, and the latest tick;
- the latest rendered feed output needed for a useful summary.

It may call the scheduler's pure interpretation functions, but it cannot invoke
a scheduling action, mutate an assignment, relay a user post, or start a
process. In the code, those functions and records are the scheduler's `models`
and `faults` modules, and status imports no other scheduler module. Status
values are always derived; they are not written back as domain state.

An `IssueObservation` represents claimed here, claimed elsewhere, blocked, and
routing conflict as independent facts which may each be true, false, or unknown;
its availability is derived from those facts together with whether the issue is
open, assigned to the instance's user, and carries exactly one assignment label.
The report includes available issues in the scheduler's dispatch order. It also
includes issues with known open blockers, together with the scheduler's recorded
blocker evidence. An `AssignmentStatus` is one summary status from the ontology.

The report includes an issue observation among failed setups while the latest
tick records a setup failure, independently of whether the issue is available or
a linked pull request proves that it is claimed elsewhere.

An `AgentWorkObservation` records the tick's interpretation of one open work
item. It carries the agent work identifier, issue and one `IssueFact` saying
whether it requires a round and why. Status reads this observation because view
commands cannot reach GitHub. It is the last tick's interpretation kept as
operational evidence, not authoritative state.

The scheduler record holds one `ConversationObservation`, extending
`AgentWorkObservation`, for each open, assigned issue that carries at least one
configured conversation label. Each observation additionally records:

- the issue and its title;
- an `IssueFact` that says whether more than one conversation route matches.

The tick observes a matching issue even when it has no conversation record yet.
So status lists a conversation from the first tick that sees its issue, and
reports a routing conflict before any round starts.

An issue with no observation is not eligible. Status stops listing its
conversation once no round runs for it.

If the tick cannot list the matching issues, it copies the previous tick's
observations and marks each fact unknown.

A `ConversationStatus` is one summary status from the ontology.

The scheduler record also names every assignment or conversation whose round the
tick launched, in launch order. Alternation advances when a kind is selected,
including when its start fails, and begins afresh after a daemon restart. Each
launched work item keeps an observation whose `requires_round` fact is false and
says which round started. If that round ends after the scheduler record, status
reports that the work is waiting for the next update. An ending that predates
the record should already have been observed, so an unexplained absence remains
unknown.

### TUI

The TUI renders status reports and feeds with Rich. It owns presentation only.
It should not rediscover status, scheduling, or lifecycle rules while choosing
headings and colors.

### Web

The web interface renders status reports and feeds as HTML. It owns presentation
only and depends on the status and feed models; neither model depends on it. It
should not rediscover status, scheduling, or lifecycle rules while choosing
markup and styles.

The web process can ask a running round to stop. It writes a same-origin stop
request through the agent-round boundary, into that round's own directory. The
daemon still owns the live process and lifecycle transition: the round watches
the request, kills its harness process tree, and records its stopped ending.

### Configuration, dispatch labels, and routes

`config.py` owns the strict model for `dreamcatcher.toml`. A `DispatchRecipe`
supplies the model, effort, and initial prompt used to start agent work through
one harness. A `DispatchRoute` maps one dispatch label to one recipe per harness
that the route configures.

An `AssignmentRoute` specializes a dispatch route for assignments, and its
prompt normally invokes an assignment skill. A `ConversationRoute` specializes a
dispatch route for issue conversations. Both kinds use the same
harness-selection rule: a configured requested harness wins, while the sole
recipe wins when only one exists.

The repository configuration carries choices that everyone working in the
repository shares. The daemon interval and agent cap belong to one person's run,
so the `run` command receives them instead.

The configuration module validates labels, routes, and recipes. Each dispatch
label belongs to one route, so a label cannot configure both kinds of agent
work. Given an issue's observed labels, the module identifies the matching
routes. It does not silently resolve multiple labels by list order. The
scheduler interprets exactly one route of either kind as routable, more than one
of that kind as a routing conflict, and none as outside that workflow. One route
of each kind may match at the same time.

### State and documents

`state.py` owns the paths within `.dreamcatcher/` and the mechanics required to
bootstrap that directory. A state-format constant selects the versioned root,
currently `.dreamcatcher/v5/`, so one format never reads another format's files.
The shared `.dreamcatcher/daemon.pid` lock stays outside that root, so daemons
using different formats still cannot run against one checkout together. It is a
strict document containing the daemon's PID and process start time. A reader
accepts it only while both values still identify the same live process, so a PID
that the operating system has reused does not make a dead daemon look live. The
module should remain deliberately small. It must not contain collections of
issues or assignments selected for work, scheduling decisions, or status
projections.

The on-disk layout follows ownership:

- instance-wide operational records live at the versioned root;
- each assignment owns its durable record and numbered round records;
- each conversation owns its durable record and numbered round records;
- each round owns its prompt, raw output, rendered feed, final output when the
  harness reports one, and any delivered input; and
- assignment and conversation worktrees live in separate collections under the
  versioned root.

`documents.py` remains the only way Dreamcatcher reads and writes documents it
owns. Every structured document has a strict model and every replacement write
is atomic. A one-value process file may remain simple text where a model would
add no meaning.

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
- the issue title captured during assignment setup;
- the dispatch label and selected harness, model, effort and prompt, plus its
  harness session identifier once known;
- branch and worktree identity;
- pull-request identity;
- the latest observed pull-request state, draft flag, and observation time;
- the time of the user's latest retry request, when one has been made.

A round record persists:

- its owner-scoped number;
- purpose and recovery flag;
- start time and process identifier;
- its terminal outcome, when known, any observed end time and exit status, and
  the reason an owner could not finish it; and
- the durable files containing its prompt, delivered input, output, and any
  final result the harness reports.

An assignment round input that carries user posts establishes the delivery
position at its newest post. The assignment reads that position by scanning its
recorded round inputs from newest to oldest; no separate cursor file exists.

A conversation record persists its issue and title, chosen dispatch label and
harness settings, harness session identifier and latest user retry request. The
route and recipe remain frozen when a different configured conversation label
later makes the issue eligible. The issue derives the managed worktree path.
Each round input persists its investigated revision and the trusted comments
accepted for delivery; the first also persists the issue title and body.

Instance records persist the repository identity and the most recent daemon
run's harness, Dreamcatcher version, and capacity. An instance-wide scheduler
record persists the last tick's result, including its hold, issue, assignment
and conversation observations, active global cooldown, and the time at which the
most recent cooldown ended. Its per-work observations preserve operational
evidence of the tick's interpretation rather than authoritative state.
Assignment and conversation records persist the time of their latest user retry
request. These boundaries allow fault to remain a derived status: ending a
cooldown or requesting a retry changes which round errors count towards fault
rather than writing a lifecycle status.

The following are derived rather than persisted as authoritative state:

- whether an issue is claimed here or elsewhere;
- whether an issue is blocked, has an assignment or conversation routing
  conflict, or is available for an agent assignment;
- whether an assignment is complete or either kind of agent work is in fault;
- whether an assignment requires an agent round or needs user feedback;
- what round purpose and recovery flag are required next; and
- every issue conversation and agent assignment status shown in a status report.

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

`tests/test_architecture.py` checks each rule here that keeps one module from
reaching another through its imports, directly or through another module.

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
- a wrap-up round acts on the merged or closed state carried in its round input.
