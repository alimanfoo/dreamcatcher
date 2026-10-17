# Architecture

This document describes the enduring target architecture for _dreamcatcher_. It
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

`daemon.py` owns the lifetime of the daemon that runs a _dreamcatcher_ instance:

- acquire and release the checkout's daemon lock;
- record the daemon process identifier and the dispatch routes it loaded in the
  daemon run record as soon as it holds the lock;
- keep the web server inside the established daemon lifetime when `run` enables
  it;
- reconcile round records that an earlier daemon left without an ending by
  ending their recorded process trees at startup, skipping a record with no
  process identifier, then asking the round boundary to record them as stopped
  when the user asked to stop them, and otherwise as interrupted;
- call the scheduler repeatedly;
- wait for the daemon run's requested interval between ticks, then check that it
  still holds the daemon lock; and
- stop active child processes during shutdown.

The daemon does not decide which issue, assignment or conversation deserves
work. It knows that scheduling happens, but not the scheduling priorities.

### Repository setup

`repository_setup.py` owns `dreamcatcher init`, which prepares a main checkout
for a daemon. It checks what a daemon run needs: a main checkout, the GitHub
repository and account, push access, a Git identity and a fetchable
`origin/main`. It writes the default configuration when the checkout has none.
For each harness that the configuration routes work to, it checks that the
harness is installed and signed in, and installs the dream plugin. Then it
creates every route label that the repository lacks.

The daemon and setup refuse a checkout for the same reasons, because both call
the main-checkout check in `git.py`, the repository and account check in
`github.py`, and the harness check in `harnesses.py`. Every setup step leaves
alone what is already in place. Setup makes no scheduling decision and starts no
agent work.

### Scheduling

The scheduler package owns all decisions about what work starts and when.

One scheduler tick:

1. observes the relevant local, process, configuration, and GitHub facts;
2. ranks the assignment candidates, considering existing assignment rounds
   before dispatching a new assignment for the oldest available issue;
3. ranks the conversation candidates by their oldest waiting comment;
4. starts a global cooldown when the counted faults call for one, and launches
   nothing while a cooldown is active;
5. alternates between the two kinds when both have candidates, without changing
   either kind's internal order;
6. performs scheduling actions until the daemon run's requested capacity is full
   or no candidate remains; and
7. returns a `SchedulerRecord` for operational reporting.

The daemon persists the returned `SchedulerRecord` and reports it in its output.
A scheduler tick that fails before returning one is reported in daemon output
and leaves the last complete scheduler record in place. An invalid scheduler
record ends the daemon because retrying cannot repair the document.

If an issue read fails, the tick records the failure and prevents only the
launches that depend on those facts. A later tick retries the failed read. New
conversation rounds launch in order of their oldest waiting comment across all
issues, so a failed read for any conversation that awaits new comments prevents
every new conversation round in that tick. A round that gives a conversation the
input of one that did not finish does not depend on that order, so it still
launches.

A launch that fails takes no agent slot. The tick records the failure, keeps
every round that it already started, and goes on to the next candidate. A round
that errored before its harness ran is recorded on its agent work, and the
failure names that work and the round.

The scheduler uses two distinct lower-level operations: creating an agent
assignment and starting an agent round. When it selects an available issue, it
writes the assignment's work record and starts the first round in the same
scheduling action. The record comes first, before any Git or GitHub step, so the
assignment exists however the round goes. An assignment without a pull request
observation is due a round that opens it, unless its last round is running or it
is in fault. This does not create a separate class of normally scheduled work.

Every new round is given the input that past rounds have not yet relayed. An
assignment round's input holds the pull request state and the user posts after
the delivery position, and a conversation round's input holds the comments after
it. The delivery position and whether the final turn has been taken are read
from the inputs of the rounds that did not error or get interrupted, so a round
that did not finish has its input given again. Existing work with something new
to relay, or whose last round errored or was interrupted, is a candidate unless
its last round is running or it is in fault.

Scheduling should expose pure, read-only functions for interpretations that
status reporting also needs, particularly whether an issue is available for an
agent assignment and what round an assignment requires next. The status
subsystem may reuse those functions. The scheduler must never consume a status
report or presentation model.

Scheduling priority is derived from current facts rather than persisted as a
queue.

### Issue conversations

`issue_conversations.py` owns the durable operations of issue conversations.
Creating a conversation writes its work record and nothing else. Each round's
preparation resets the detached worktree to fetched main, adding it when it is
missing, and freezes the trusted comment batch and that revision. A
conversation's worktree never acquires an implementation branch or a pull
request.

The signed-in GitHub account identifies trusted issue comments. Marked
_dreamcatcher_ comments, comments by other accounts and blank comments are
excluded. Each durable round input records the delivered batch, so the newest
comment in the latest input of a round that did not error or get interrupted is
the delivery position, and a batch that such a round received cannot be selected
again.

The first eligible batch starts one session through the harness selected from
the conversation's configured recipes, with the issue title, body and trusted
comment history. Each later eligible batch resumes that same harness session
with only newly delivered comments. Resetting the worktree deletes every local
commit and file. Each round input records its investigated revision. Comments
posted while a round runs remain beyond that round's input.

A failed or interrupted conversation round established no delivery position, so
the next round is given its comments again, together with any that arrived
since, against a freshly reset worktree, and its prompt says that the previous
round did not finish. It resumes the recorded harness session, or starts a new
session with the configured prompt and the issue's title and body when no
session identifier was recorded.

Fresh-batch candidates are polled before the capacity check.

Conversation harness permissions reinforce the no-implementation boundary while
allowing issue actions that the user requests. Claude allows selected `gh issue`
commands and `gh api` while denying direct editing and Git mutations. Codex runs
in a networked workspace-write sandbox without approval escalation. Each prompt
that delivers a comment batch forbids source changes, Git mutations,
pull-request changes and direct reply posting. A new session receives the
configured prompt before the input as well. Every prompt requires the agent
marker on every other GitHub post that the agent makes.

A conversation round posts its own answer. The conversation launcher gives the
round a finisher that posts to the issue, so the shared round runner knows
nothing of GitHub. After the harness exits successfully, the round hands its
final output to that finisher, which posts it with the agent marker, and then
the round records its ending. It therefore keeps its agent slot while it posts,
and no new batch starts until the answer is out. `NO_REPLY` posts nothing. A
missing final output or a failed post makes the round errored. The ending keeps
the harness's clean exit status and gives the failure as its reason, and the
feed notes it too. Failed and interrupted rounds remain visible while later
rounds are given their input again, and two consecutive errored rounds place the
conversation in fault.

Harness adapters expose final output separately from their progress streams.
Claude supplies the answer in its successful result event. For a Codex
conversation, the adapter gives `codex exec` the round's `final.md` path as its
last-message output file on first and resumed invocations.

### Agent assignments

`agent_assignments.py` owns the durable representation and lifecycle operations
of an agent assignment. It should provide cohesive operations to:

- create an assignment by writing its work record;
- open the assignment's pull request, as the preparation of a round whose
  assignment has none;
- name the assignment's branch from its identifier;
- read and record its pull request observation;
- read the user-post delivery position, and whether the final turn has been
  taken, from recorded round inputs;
- complete an assignment as its wrap-up round finishes; and
- cancel an assignment.

`agent_work.py` owns what both kinds of agent work share: the work record, the
agent work identifier, and the one reader through which the scheduler, status,
the commands and the views list agent work of either kind. It also records the
facts that change later for both kinds: the harness session identifier, when the
user retries work after resolving a fault, and when and why the work ended.

Creating an assignment writes its work record and nothing else. The preparation
step of a round whose assignment has no pull request observation coordinates
lower-level Git, GitHub and document operations. It:

1. fetches the current main branch;
2. adds the assignment's worktree on its branch, unless it is already there;
3. makes an empty commit, unless the branch already has one, and pushes the
   branch;
4. adopts the pull request already on the branch, whatever its state, or opens a
   linked draft pull request; and
5. writes the pull request observation.

Each step does nothing when its result already exists, and a worktree that
cannot be added is removed with its branch. The assignment identifier names the
branch and worktree, so a round that follows a failed one finds what the earlier
attempt made and never makes a second branch or pull request.

The assignment remains open until its ending is recorded. A wrap-up round, one
whose input carries a merged or closed pull request, records the ending with the
reason "completed" in its finishing step, after its harness exits successfully.
A cancel records it with the reason "cancelled". A merged or closed pull request
calls for wrap up but does not by itself complete the assignment.

The assignment module coordinates the workflow but does not implement Git
commands, parse GitHub responses, launch harnesses, or choose when work should
run.

### Agent rounds

`agent_rounds.py` owns agent-round records and the supervised lifetime of a
round process for both assignments and conversations. It should provide
operations to:

- record the round, with the next number that its owner allocated, before
  anything else happens;
- run its owner's preparation step, which readies the worktree and returns any
  input to deliver;
- write the prompt and any delivered input;
- ask a harness adapter to build the invocation;
- start that invocation in its owner's worktree, and record its process id;
- record an errored ending with a reason and no exit status when preparation or
  the spawn fails;
- stream and render its output, and keep the final output the harness reports;
- let its owner finish a round whose harness succeeded, before the ending;
- record a successful or errored ending;
- interrupt the process tree safely; and
- record an interruption, or a stop when the user asked for one, when the daemon
  finds a round record that an earlier daemon left without an ending.

`agent_assignments.py` owns `AssignmentRoundInput`, the pull request state and
relayed user posts that an assignment round receives beside its prompt once its
pull request exists. `issue_conversations.py` owns `ConversationRoundInput`,
which freezes the issue, trusted comments and investigated revision for a
conversation round. The round runner writes whichever input the owner's
preparation returns without reading it, and it hands the final output to the
owner's finisher without knowing what the owner does with it. The round module
therefore stays clear of Git and GitHub, and each kind's own module owns what
its steps write.

The scheduler decides the input and the prompt a new round has. The round
boundary executes and records that decision; it does not inspect the pull
request or select later work.

A round is running while it has no terminal outcome. Successful, errored,
interrupted, and stopped are terminal outcomes.

A round may have an internal collection of file paths, but its owner remains the
domain object shared across boundaries.

### GitHub

`github.py` is the only boundary that knows GitHub response shapes or constructs
GitHub commands. It owns projections and operations for:

- repository and account identity, and whether the account can push;
- the repository's labels, and creating a label;
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
projections. Documents owned by _dreamcatcher_ remain strict.

### User-post relay

`relay.py` owns the act of selecting user posts not yet delivered to the agent,
oldest first. It compares normalized user posts from the GitHub boundary with
the assignment's delivery position, read from the newest recorded round input
that contains posts.

Relay does not define a separate inbox domain entity and does not decide when a
round should run. The scheduler determines whether unrelayed user posts require
work; the relay selects the posts, the scheduler places them in the round's
input, and the round input records the newest post accepted for delivery before
its process starts. Posts made while a round is running remain beyond that
position and are available to a later round.

### Harness adapters

`harness_adapters.py` and `harnesses.py` form the harness boundary, with
`claude.py` and `codex.py` providing its two concrete adapters. A harness
adapter knows:

- how to start a new harness session;
- how to resume an identified harness session;
- which model and effort arguments its harness needs, and which harness config
  it takes;
- how to recover the harness session identifier from output;
- how to parse the harness's event stream; and
- how to check that its harness is signed in, and how to install a plugin for
  the user.

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
daemon facts, `IssueObservation` entries, `ConversationStatus` entries, and
`AssignmentStatus` entries.

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

Status reads the dispatch labels from the daemon run record, never from
`dreamcatcher.toml`, and describes whether each kind of agent work has a section
to show, the section's heading, and any guidance for an empty section. The
presentations make none of those choices themselves.

An `IssueObservation` represents claimed here, claimed elsewhere, blocked, and
routing conflict as independent facts which may each be true, false, or unknown;
its availability is derived from those facts together with whether the issue is
open, assigned to the instance's user, and carries exactly one assignment label.
The report includes available issues in the scheduler's dispatch order. It also
includes issues with known routing conflicts or open blockers, together with the
scheduler's recorded evidence. An `AssignmentStatus` is one summary status from
the ontology.

An `AgentWorkObservation` records the tick's interpretation of one open work
item. It carries the agent work identifier, issue and one `ObservedFact` saying
whether it requires a round and why. A conversation the tick observes before it
is saved has no identifier yet. Status reads this observation because view
commands cannot reach GitHub. It is the last tick's interpretation kept as
operational evidence, not authoritative state.

The scheduler record holds one `ConversationObservation`, extending
`AgentWorkObservation`, for each open, assigned issue that carries at least one
configured conversation label. Each observation additionally records:

- the issue and its title;
- an `ObservedFact` that says whether more than one conversation route matches.

The tick observes a matching issue even when no conversation's work record
exists for it yet. So status lists a conversation from the first tick that sees
its issue, and reports a routing conflict before any round starts.

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

`dreamcatcher run` serves the web interface by default. The web server starts
after the daemon's startup checks pass and stops when the daemon ends.
`dreamcatcher web` serves the same interface by itself for manual control.

Every piece of agent work, of either kind, has its page at `/work/<identifier>`,
and its feed tail and controls below that address. A conversation the tick has
found but not yet saved has no page.

The web interface can ask a running round to stop. It writes a same-origin stop
request through the agent-round boundary, into that round's own directory. The
daemon still owns the live process and lifecycle transition: the round watches
the request, kills its harness process tree, and records its stopped ending.

The web interface and the `cancel` command can cancel an assignment. A cancel
goes through the agent-assignment boundary, which records the assignment's
ending, with the reason "cancelled", and then writes a stop request for any
round that has no ending. The scheduler starts no further rounds for the
assignment. A round that it starts as the cancel lands is stopped too, because
the scheduler reads the ending again once that round's record exists.

The web interface can also request a retry for agent work that status derives as
in fault. It writes the retry request time into the directory of the assignment
or conversation. The scheduler reads the request on a later tick, so the daemon
still decides when the work's next round starts.

### Configuration, dispatch labels, and routes

`config.py` owns the strict model for `dreamcatcher.toml`. A `DispatchRecipe`
supplies the model, effort, and initial prompt used to start agent work through
one harness. A `ClaudeRecipe` and a `CodexRecipe` each add the harness config
that their adapter takes, which is none for Claude. A `DispatchRoute` maps one
dispatch label to one recipe per harness that the route configures.

An `AssignmentRoute` specializes a dispatch route for assignments, and its
prompt normally invokes an assignment skill. A `ConversationRoute` specializes a
dispatch route for issue conversations, and its prompt normally invokes a
conversation skill. Both kinds use the same harness-selection rule: the
preferred harness wins when the route has a recipe for it, while the sole recipe
wins when only one exists.

The repository configuration carries choices that everyone working in the
repository shares. The daemon interval and agent capacity belong to one person's
run, so the `run` command receives them instead.

The default configuration is `default_config.toml` in the package. The
configuration module writes it for `init`, with the recipes of each harness that
is not installed commented out, and the configuration reference includes the
same file.

The configuration module validates labels, routes, and recipes. Each dispatch
label belongs to one route, so a label cannot configure both kinds of agent
work. Given an issue's observed labels, the module identifies the matching
routes. It does not silently resolve multiple labels by list order. The
scheduler interprets exactly one route of either kind as routable, more than one
of that kind as a routing conflict, and none as outside that kind of agent work.
One route of each kind may match at the same time.

### State and documents

`state.py` owns the top-level paths within `.dreamcatcher/` and the mechanics
required to bootstrap that directory. The modules that own agent work and rounds
name the files within their own directories. A state-format constant selects the
versioned root, currently `.dreamcatcher/v6/`, so one format never reads another
format's files. The shared `.dreamcatcher/daemon.lock` stays outside that root,
so daemons using different formats from v5 on use the same lock. The daemon
acquires an operating-system lock on that empty file before it starts work.
After every wait, the daemon verifies that the path still names the file that it
acquired and stops before another tick when it does not. A reader asks whether
the lock is held. The kernel releases the lock when the daemon's process ends,
so neither a reused PID nor a clock change can make a dead daemon look live. A
v4 daemon takes no such lock. It writes its PID to `.dreamcatcher/daemon.pid`
and treats that file as a mutex, so it does not see this lock. The module should
remain deliberately small. It must not contain collections of issues or
assignments selected for work, scheduling decisions, or status projections.

The on-disk layout follows ownership:

- instance-wide operational records live at the versioned root;
- each piece of agent work, of either kind, owns a directory under `work/` named
  by its identifier, holding its durable record, a file for each fact that
  changes after its creation, and numbered round records;
- each round owns its prompt, raw output, rendered feed, final output when the
  harness reports one, and any delivered input; and
- each piece of agent work's worktree lives under `worktrees/`, named by the
  same identifier.

`documents.py` remains the only way _dreamcatcher_ reads and writes documents it
owns. Every structured document has a strict model and every replacement write
is atomic. Each write stages in a file that no other write shares, so writes
that race each other each land whole. A one-value process file may remain simple
text where a model would add no meaning.

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

Creation writes the work record, `work.json`, once, and nothing writes it again.
The same record serves both kinds of agent work. It persists:

- the issue identifier, while the agent work identifier names the directory that
  holds the record and the worktree;
- the issue title captured at creation;
- the dispatch label and the kind of agent work;
- the selected harness, model, effort, harness config and prompt.

An assignment's branch is named from its identifier, and its pull request number
is in its pull request observation.

Every fact that changes later has a file of its own beside the record. Each
write replaces that file whole and merges nothing into it, so the daemon, the
web interface and a command can each record a fact at the same moment without
erasing another's. These files persist:

- for an assignment, once its first round has opened its pull request, that pull
  request's number and latest observed state, draft flag, and observation time;
- the harness session identifier, once known;
- the time of the user's latest retry request, when one has been made;
- the time and the reason the work ended, once it has ended.

A round record persists:

- its owner-scoped number and start time, written before anything else;
- its process identifier, once the harness is spawned;
- its terminal outcome, when known, any observed end time and exit status, and
  the reason it could not prepare, start or finish; and
- the durable files containing its prompt, delivered input, output, and any
  final output the harness reports.

An assignment round input that carries user posts establishes the delivery
position at its newest post. The assignment reads that position by scanning the
recorded inputs of its rounds that did not error or get interrupted, from newest
to oldest. What woke a round is read from its input rather than recorded.

A conversation's harness session identifier and latest user retry request each
have a file of their own beside its record, as an assignment's do. The route and
recipe remain frozen when a different configured conversation label later makes
the issue eligible. Each round input persists its investigated revision and the
trusted comments accepted for delivery; the input of a round that starts a new
harness session also persists the issue title and body.

Instance records persist the repository identity and the most recent daemon
run's harness, _dreamcatcher_ version, capacity, interval, and the dispatch
routes it loaded, each as a dispatch label and its kind of agent work. An
instance-wide scheduler record persists the last tick's result, including its
failures, issue, assignment and conversation observations, active global
cooldown, and the time at which the most recent cooldown ended. Its per-work
observations preserve operational evidence of the tick's interpretation rather
than authoritative state. Assignments and conversations persist the time of
their latest user retry request. These boundaries allow fault to remain a
derived status: ending a cooldown or requesting a retry changes which round
errors count towards fault rather than writing a lifecycle status.

The following are derived rather than persisted as authoritative state:

- whether an issue is claimed here or elsewhere;
- whether an issue is blocked, has an assignment or conversation routing
  conflict, or is available for an agent assignment;
- whether either kind of agent work is in fault;
- whether an assignment requires an agent round or needs user feedback;
- what input the next round is given; and
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
reaching another through its imports, directly or through another module. It
checks the status rule on the scheduler modules that status imports directly.

## Agent-facing contract

The [agent-facing contract](contract.md) describes the protocols between
_dreamcatcher_ and assignment and conversation skills. It records each side's
responsibilities, not implementation history.
