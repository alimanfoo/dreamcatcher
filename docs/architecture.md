# Architecture

This document says where each thing lives in the code and how the parts
pass things to each other, while [the ontology](ontology.md) says what
the words mean, [the user stories](stories.md) say what the user does
and sees, and [the standard](standard.md) says how good the work has to
be.

It describes the enduring target architecture for _dreamcatcher_. It
maps the ontology's concepts to code boundaries and states the
responsibilities, interfaces, and encapsulation those boundaries should
provide.

The dated specifications record the design of particular phases. Where
an older design conflicts with this target, this document is
authoritative.

## Architectural aims

The architecture should make the domain visible in the code without
making every domain phrase into a class. In particular, it should:

- give each important decision one owner;
- separate persistent facts, what each tick reads from GitHub, derived
  status, and actions;
- keep scheduling policy out of process supervision and presentation;
- keep GitHub and harness-specific data behind explicit boundaries;
- let an interrupted operation run again without inventing incomplete
  domain objects;
- preserve conservative behavior when an external fact is unknown; and
- use the same interpretation of facts in scheduling and reporting
  without making either subsystem depend on the other's output.

## Principal boundaries

### Daemon lifecycle

`daemon.py` owns the lifetime of the daemon that runs a _dreamcatcher_
instance:

- acquire and release the checkout's daemon lock;
- record the daemon process identifier and the dispatch routes it loaded
  in the daemon run record, whose model `daemon_runs.py` owns, as soon
  as it holds the lock;
- keep the web server inside the established daemon lifetime when `run`
  enables it;
- reconcile round records that an earlier daemon left without an ending
  by ending their recorded process trees at startup, skipping a record
  with no process identifier, then asking the round boundary to record
  them as stopped when the user asked to stop them, and otherwise as
  interrupted;
- call the scheduler repeatedly;
- wait for the daemon run's requested interval between ticks, then check
  that it still holds the daemon lock; and
- stop active child processes during shutdown.

The daemon does not decide which issue, assignment or conversation
deserves work. It knows that scheduling happens, but not the scheduling
priorities.

### Repository setup

`repository_setup.py` owns `dreamcatcher init`, which prepares a main
checkout for a daemon. It checks what a daemon run needs: a main
checkout, the GitHub repository and account, push access, a Git identity
and a fetchable `origin/main`. It writes the default configuration when
the checkout has none. For each harness that the configuration routes
work to, it checks that the harness is installed and signed in, and
installs the dream plugin. Then it creates every route label that the
repository lacks.

The daemon and setup share the checks they both make, because both call
the main-checkout check in `git.py`, the repository and account check in
`github.py`, and the harness check in `harnesses.py`. Every setup step
leaves alone what is already in place. Setup makes no scheduling
decision and starts no agent work.

### Scheduling

The scheduler package owns all decisions about what work starts and
when. The tick in `tick.py` has one path for both kinds of agent work.
Each kind's module, `assignments.py` or `conversations.py`, supplies
only what differs by kind: how it inspects the channel of open work, how
it decides whether a request with no open work may start, and how it
composes a round's plan. `inspection.py` holds the shapes they share:
the scheduling context, the candidate, the round plan and the inspection
of one request. `models.py` holds the scheduler record and its request
rows, and `faults.py` the fault and cooldown rules.

One scheduler tick:

1. reads every piece of agent work from disk, and lists the open issues
   assigned to the signed-in account under each dispatch label;
2. builds the requests from two sources, each dispatch label on each
   listed issue and each piece of open agent work, which names its own
   issue and label;
3. inspects each piece of open work's channel: an assignment's pull
   request and user posts, or a conversation's issue and then its
   comments, ending the conversation if the issue is closed and no round
   of it is running;
4. for each request with no open work, skips an assignment label whose
   issue already has an open assignment, checks for a routing conflict,
   then asks the start-time questions or reads the comments;
5. starts a global cooldown when the counted faults call for one, and
   launches nothing while a cooldown is active;
6. launches candidates until the daemon run's requested capacity is full
   or no candidate remains, open work first in identifier order and then
   new requests in listing order, alternating between the two kinds
   while both have candidates; and
7. returns a `SchedulerRecord`, holding one request row per request, for
   operational reporting.

A candidate is open work the tick may start a round for, or a request it
may start work for. It carries a composer that builds the round's plan
once the work exists: the preparation that runs inside the round, the
input prompt, and the finishing step. The tick creates the work of a new
request, then starts the round the plan describes, so creating and
launching are one path for both kinds.

Alternation advances when a kind is selected, including when its start
fails, and begins afresh after a daemon restart.

The daemon persists the returned `SchedulerRecord` and reports it in its
output. A scheduler tick that fails before returning one is reported in
daemon output and leaves the last complete scheduler record in place. A
local record that cannot be read, or a write that fails while open work
is inspected, fails the tick this way whichever work it belongs to. A
conversation's comment cursor is the exception, and its row holds the
failure. An invalid scheduler record ends the daemon because retrying
cannot repair the document, and so does a scheduler record that cannot
be written, because the daemon then has no way to report anything.

If a GitHub read for a request fails, the tick holds the reason in that
request's row and prevents only the launches that depend on what it
would have read. A failed listing is a scheduler failure, because it
belongs to no request, and it starts no work for the issues it would
have listed. Open work is found on disk and reads its own channel, so a
failed listing leaves it inspected. A later tick retries the failed
read.

A launch that fails takes no agent slot. The tick keeps every round that
it already started and goes on to the next candidate. A round that
errored during its preparation or startup is recorded on its agent work,
and the request's row names the round and its reason, which the daemon's
output line repeats. A launch that fails before its round is recorded,
such as a work record that cannot be written or a harness invocation
that cannot be built, is a scheduler failure.

When the tick selects a request, it writes the work record and starts
the first round in the same scheduling action. The record comes first,
before any Git or GitHub step, so the work exists however the round
goes. An assignment without a recorded pull request number is due a
round that opens it, unless its last round is running or it is in fault.
This does not create a separate class of normally scheduled work.

Every new round is given what is past its work's cursor. An assignment
round's input holds the pull request state and head commit, the pull
request signals raised at a head not yet relayed, and the user posts
past the cursor, and a conversation round's input holds the eligible
comments past it. The cursor, the head at which each pull request signal
was last relayed, whether the relay rule withholds a check-failure, and
whether a wrap-up round has been given the finished pull request are
read from the inputs of the rounds that took their turn or are running,
so a round that did not finish has its input given again.

Scheduling should expose pure, read-only functions for interpretations
that status reporting also needs, particularly whether agent work is in
fault and whether its last round did not finish. The status subsystem
may reuse those functions. The scheduler must never consume a status
report or presentation model.

Scheduling priority is derived from current facts rather than persisted
as a queue.

### Issue conversations

`issue_conversations.py` owns a conversation round's input and the
posting of its answer. Creating and ending a conversation go through
`agent_work.py`, and creating one writes its work record and nothing
else. Each round's preparation resets the detached worktree to fetched
main, adding it when it is missing, and freezes the eligible comments
past the cursor and that revision. A conversation's worktree never
acquires an implementation branch or a pull request.

Each tick reads an open conversation's issue before its comments, so
open conversations do not depend on the listing. The tick keeps reading
the issue while a round runs, decides from it whether the conversation
is paused or has ended, and reads its comments only while it is neither.

The relay selects the eligible comments past the cursor. Each durable
round input records the comments it relays, so the newest comment in the
latest input of a round that took its turn or is running is the cursor,
and a comment behind it cannot be selected again. The preparation adds
the issue's title and body to the input of a round that starts a new
harness session, and resetting the worktree deletes every local commit
and file that an earlier round left.

Conversation harness permissions reinforce the no-implementation
boundary while allowing issue actions that the user requests. Claude
allows selected `gh issue` commands and `gh api` while denying direct
editing and Git mutations. Codex runs in a networked workspace-write
sandbox without approval escalation. Each prompt that relays comments
forbids source changes, Git mutations, pull-request changes and direct
reply posting. A new session receives the configured prompt before the
input as well. Every prompt requires the agent marker on every other
GitHub post that the agent makes.

A conversation round posts its own answer. The conversation's round plan
gives the round a finishing step that posts to the issue, so the shared
round runner knows nothing of GitHub. After the harness exits
successfully, the round hands its final output to that finishing step,
which posts it with the agent marker, and then the round records its
ending. It therefore keeps its agent slot while it posts, and no new
batch starts until the answer is out. `NO_REPLY` posts nothing. A
missing final output or a failed post makes the round errored. The
ending keeps the harness's clean exit status and gives the failure as
its reason, and the feed notes it too.

Harness adapters expose final output separately from their progress
streams. Claude supplies the answer in its successful result event. For
a Codex conversation, the adapter gives `codex exec` the round's
`final.md` path as its last-message output file on first and resumed
invocations.

### Agent assignments

`agent_assignments.py` owns what only an assignment records and does. It
should provide cohesive operations to:

- open the assignment's pull request, as the preparation of a round
  whose assignment has none, with `agent_assignment_pull_requests.py`
  finding or creating the pull request on the branch;
- name the assignment's branch from its identifier;
- read its pull request number;
- read the cursor, the pull request state last relayed, the head at
  which each pull request signal was last relayed, whether the relay
  rule withholds, and whether a wrap-up round has been given the
  finished pull request, from recorded round inputs;
- complete an assignment as its wrap-up round finishes; and
- cancel an assignment.

`agent_work.py` owns what both kinds of agent work share: the work
record, the agent work identifier, creating work of either kind from its
dispatch route, and the one reader through which the scheduler, status,
the commands and the views list agent work of either kind. It also
records the facts that change later for both kinds: the harness session
identifier, when the user retries work after resolving a fault, and when
and why the work ended.

Creating an assignment writes its work record and nothing else. The
preparation step of a round whose assignment has no recorded pull
request number coordinates lower-level Git, GitHub and document
operations. It:

1. fetches the current main branch;
2. adds the assignment's worktree on its branch, unless it is already
   there;
3. makes an empty commit, unless the branch already has one, and pushes
   the branch;
4. adopts the pull request already on the branch, whatever its state, or
   opens a linked draft pull request; and
5. writes the pull request's number to `pull-request.json`.

Each step does nothing when its result already exists, and a worktree
that cannot be added is removed with its branch. The assignment
identifier names the branch and worktree, so a round that follows a
failed one finds what the earlier attempt made and never makes a second
branch or pull request.

A wrap-up round records the assignment's ending with the reason
"completed" in its finishing step, after its harness exits successfully.

The assignment module coordinates the workflow but does not implement
Git commands, parse GitHub responses, launch harnesses, or choose when
work should run.

### Agent rounds

`agent_rounds.py` owns agent-round records and the supervised lifetime
of a round process for both assignments and conversations. Before
anything is recorded, it asks a harness adapter to build the round's
invocation, so a failure there is a scheduler failure. It should then
provide operations to:

- record the round, with the next number that its work allocated, before
  anything else happens;
- run the preparation step that the work's kind supplies, which readies
  what the round needs and returns any input to relay;
- write the prompt and any input;
- start the invocation in the work's worktree, and record its process
  id;
- record an errored ending with a reason and no exit status when
  preparation, the spawn or the record of the spawned process fails;
- stream and render its output, and keep the final output the harness
  reports;
- run the finishing step of a round whose harness succeeded, before the
  ending;
- record a successful ending, an errored ending with the exit status of
  a harness that failed, or an errored ending with the reason its
  finishing step failed;
- interrupt the process tree safely;
- record an interruption, or a stop when the user asked for one, when
  the daemon finds a round record that an earlier daemon left without an
  ending; and
- interpret a round with no ending as running while a daemon runs it and
  as interrupted once that daemon has gone, for scheduling and status
  alike, without claiming that its harness has exited.

`agent_assignments.py` owns `AssignmentRoundInput`, the pull request
state and head commit, the relayed pull request signals and the relayed
user posts that an assignment round receives beside its prompt once its
pull request exists. `issue_conversations.py` owns
`ConversationRoundInput`, which freezes the issue, eligible comments and
investigated revision for a conversation round. The round runner writes
whichever input the preparation returns without reading it, and it hands
the final output to the finishing step without knowing what that step
does with it. The round module therefore stays clear of Git and GitHub,
and each kind's own module owns what its steps write.

The scheduler decides the input and the prompt a new round has. The
round boundary executes and records that decision; it does not inspect
the pull request or select later work.

A round may have an internal collection of file paths, but its agent
work remains the domain object shared across boundaries.

### GitHub

`github.py` is the only boundary that knows GitHub response shapes or
constructs GitHub commands. It owns projections and operations for:

- repository and account identity, and whether the account can push;
- the repository's labels, and creating a label;
- issue title, state, assignees, labels, and dependencies;
- linked pull requests;
- pull-request identity, draft state, readiness, terminal state, merge
  state, head commit, and what its checks add up to;
- creating the linked draft pull request;
- reading ordinary issue comments and posting a conversation answer; and
- reading and normalizing user posts from comments, reviews, verdicts,
  and inline comments.

An agent assignment persists its pull request's number and nothing else
about it. Scheduling reads the current state from GitHub when it needs
it, and the request row carries what the tick read to the views. An
assignment the tick read nothing for shows the merged or closed state
its newest relayed round input carried, if any.

GitHub owns its documents and may add fields, so its responses remain
tolerant projections. Documents owned by _dreamcatcher_ remain strict.

### Relay

`relay.py` owns what is past a piece of agent work's cursor in its
channel, for both kinds. For an assignment it selects the user posts
past the cursor, oldest first, by comparing normalized user posts from
the GitHub boundary with the assignment's cursor, read from the newest
input that contains posts among the rounds that took their turn or are
running. It raises the pull request signals of a pull request that is
open and ready for review, each at a head other than the one at which it
was last relayed, and leaves out a check-failure that the relay rule
withholds. For a conversation it selects the eligible issue comments
past the conversation's cursor, oldest first. One rule decides, for both
channels, which posts are the user's to relay. Each kind's own module
reads its cursor from the round inputs that it owns.

Relay does not define a separate inbox domain entity and does not decide
when a round should run. The scheduler determines whether posts,
comments or other signals require work; the relay selects them, the
scheduler places them in the round's input, and the round input records
the posts and pull request signals it relays, with the head they were
raised at, before its process starts. Posts made while a round is
running remain past the cursor and are available to a later round.

### Harness adapters

`harness_adapters.py` and `harnesses.py` form the harness boundary, with
`claude.py` and `codex.py` providing its two concrete adapters. A
harness adapter knows:

- how to start a new harness session;
- how to resume an identified harness session;
- which model and effort arguments its harness needs, and which harness
  config it takes;
- how to find the harness session identifier in output;
- how to parse the harness's event stream; and
- how to check that its harness is signed in, and how to install a
  plugin for the user.

An adapter does not know about issues, pull requests, dispatch routes,
assignment status, scheduling priorities, or status reports. It receives
an invocation request and returns the command, prompt behavior, and
parsed events needed by the round runner.

The code should always name a harness session explicitly when that is
what an identifier or operation refers to. A bare `session` name is not
part of this interface.

### Status reporting

Status reporting owns the read-only status model and constructs a
`DreamcatcherStatusReport` containing the repository identity, instance
and daemon facts, an `AgentWorkStatus` for every piece of agent work,
and a `RequestStatus` for every request with no open work.

Status construction may read:

- agent work and round records;
- raw harness output and the matching harness adapter when it must find
  a harness session identifier or build a hand-resume command;
- current child-process state;
- the instance's repository record and daemon-run record;
- the scheduler record, with its request rows, the active global
  cooldown, and the latest tick;
- the latest rendered feed output needed for a useful summary.

It may call the scheduler's pure interpretation functions, but it cannot
invoke a scheduling action, mutate an assignment, relay a user post, or
start a process. In the code, those functions and records are the
scheduler's `models` and `faults` modules, and status imports no other
scheduler module. Status values are always derived; they are not written
back as domain state.

Status reads the dispatch labels from the daemon run record, never from
`dreamcatcher.toml`, and describes whether each kind of agent work has a
section to show, the section's heading, and any guidance for an empty
section. The presentations make none of those choices themselves.

The scheduler record holds one `RequestRow` for each request the tick
saw. A row names the issue, its title, the dispatch label, the kind, and
the identifier of the open agent work, if any, with that work's latest
round when it had ended as the tick read the work. It holds what the
tick found as a typed finding:

- for an assignment whose pull request the tick read, the pull request's
  number, state, draft flag, merge state and check result, the count of
  user posts and the pull request signals past the cursor, and whether
  the relay rule withheld a check-failure;
- for a conversation whose comments the tick read, the count of comments
  past the cursor;
- for an assignment request with no open work, the open linked pull
  requests and the open blocking issues, as numbers;
- for a request or an open conversation whose issue carries two labels
  of its kind, those labels;
- for a conversation paused for any other reason, the cause;
- for a read that failed, the reason, in place of what it would have
  found.

A row has no finding when the tick found nothing to record for it, as
for an assignment in fault, an unpaused conversation in fault, a
conversation whose issue it found closed, or an assignment whose pull
request no round has opened yet. A running round does not prevent the
tick from recording a finding, but it prevents the finding from making
the work a candidate for another round. A row also names the round the
tick started for it and, when that round errored during its preparation
or startup, the reason. Apart from those reasons for a failure, no row
holds a sentence meant for a person. Status composes the words from
these values once, and keeps the issue and pull request numbers as
numbers, so both presentations link them and neither parses text.

`AgentWorkStatus` is one summary status from the ontology, derived in
one chain for both kinds of agent work. `RequestStatus` gives a request
with no open work its request status and its reasons, each as words with
the issues or pull requests it names.

Status tells whether the scheduler record read the work after its latest
round ended from the round that the work's row names as ended, not from
the times of the record and the ending. A round that took its turn after
the tick read the work leaves it idle and awaiting the next update,
unless the record found input that the round did not consume. The
earlier finding still supplies the assignment's last observed pull
request summary. A missing row says nothing about what the tick read, so
the work remains unknown.

A round that did not finish leaves the work waiting until a row names it
as ended. For a conversation, that row's count of comments then decides,
so a conversation whose comments the user deleted is idle. An
assignment's unfinished round is always given again, so the assignment
stays waiting.

### TUI

The TUI renders status reports and feeds with Rich. It owns presentation
only. It should not rediscover status, scheduling, or lifecycle rules
while choosing headings and colors.

### Web

The web interface renders status reports and feeds as HTML. It owns
presentation only and depends on the status and feed models; neither
model depends on it. It should not rediscover status, scheduling, or
lifecycle rules while choosing markup and styles.

`dreamcatcher run` serves the web interface by default. The web server
starts after the daemon's startup checks pass and stops when the daemon
ends. `dreamcatcher web` serves the same interface by itself for manual
control.

Every piece of agent work, of either kind, has its page at
`/work/<identifier>`, and its feed tail and controls below that address.
A conversation the tick has found but not yet saved has no page.

The web interface can ask a running round to stop. It writes a
same-origin stop request through the agent-round boundary, into that
round's own directory. The daemon still owns the live process and
lifecycle transition: the round watches the request, kills its harness
process tree, and records its stopped ending.

The web interface and the `cancel` command can cancel an assignment. A
cancel goes through the agent-assignment boundary, which records the
assignment's ending, with the reason "cancelled", and then writes a stop
request for any round that has no ending. The scheduler starts no
further rounds for the assignment. A round that it starts as the cancel
lands is stopped too, because the scheduler reads the ending again once
that round's record exists.

The web interface can also request a retry for agent work that status
derives as in fault. It writes the retry request time into the directory
of the assignment or conversation. The scheduler reads the request on a
later tick, so the daemon still decides when the work's next round
starts.

### Configuration, dispatch labels, and routes

`config.py` owns the strict model for `dreamcatcher.toml`. A
`DispatchRecipe` supplies the model, effort, and initial prompt used to
start agent work through one harness. A `ClaudeRecipe` and a
`CodexRecipe` each add the harness config that their adapter takes,
which is none for Claude. A `DispatchRoute` maps one dispatch label to
one recipe per harness that the route configures.

An `AssignmentRoute` specializes a dispatch route for assignments, and
its prompt normally invokes an assignment skill. A `ConversationRoute`
specializes a dispatch route for issue conversations, and its prompt
normally invokes a conversation skill. Both kinds use the same
harness-selection rule: the preferred harness wins when the route has a
recipe for it, while the sole recipe wins when only one exists.

The repository configuration carries choices that everyone working in
the repository shares. The daemon interval and agent capacity belong to
one person's run, so the `run` command receives them instead.

The default configuration is `default_config.toml` in the package. The
configuration module writes it for `init`, with the recipes of each
harness that is not installed commented out, and the configuration
reference includes the same file.

The configuration module validates labels, routes, and recipes. Each
dispatch label belongs to one route, so a label cannot configure both
kinds of agent work. Given an issue's labels, the module identifies the
matching routes. It does not silently resolve multiple labels by list
order. The scheduler applies the routing rules to the routes it returns.

### State and documents

`state.py` owns the top-level paths within `.dreamcatcher/` and the
mechanics required to bootstrap that directory. The modules that own
agent work and rounds name the files within their own directories. A
state-format constant selects the versioned root, currently
`.dreamcatcher/v7/`, so one format never reads another format's files.
The shared `.dreamcatcher/daemon.lock` stays outside that root, so
daemons using different formats from v5 on use the same lock. The daemon
acquires an operating-system lock on that empty file before it starts
work. After every wait, the daemon verifies that the path still names
the file that it acquired and stops before another tick when it does
not. A reader asks whether the lock is held. The kernel releases the
lock when the daemon's process ends, so neither a reused PID nor a clock
change can make a dead daemon look live. A v4 daemon takes no such lock.
It writes its PID to `.dreamcatcher/daemon.pid` and treats that file as
a mutex, so it does not see this lock. The module should remain
deliberately small. It must not contain collections of issues or
assignments selected for work, scheduling decisions, or status
projections.

The on-disk layout follows ownership:

- instance-wide operational records live at the versioned root;
- each piece of agent work, of either kind, owns a directory under
  `work/` named by its identifier, holding its durable record, a file
  for each fact that changes after its creation, and numbered round
  records;
- each round owns its prompt, raw output, rendered feed, final output
  when the harness reports one, and any input it relays; and
- each piece of agent work's worktree lives under `worktrees/`, named by
  the same identifier.

`documents.py` remains the only way _dreamcatcher_ reads and writes
documents it owns. Every structured document has a strict model and
every replacement write is atomic. A read of a replaceable document and
the replacement step of its write hold a persistent `<document>.lock`
sidecar, so readers close the document before a writer replaces it
across threads and processes. A writer stages and closes a file that no
other write shares before it takes the lock, so writes that race each
other each land whole. Static TOML and append-only streams need no
document lock. These short document locks are distinct from the daemon
lock held for a daemon run. A one-value process file may remain simple
text where a model would add no meaning.

State-directory objects provide paths and document access. They do not
answer domain questions such as whether an assignment has ended or a
request may start.

### Git, commands, prompts, and feeds

`git.py` owns Git operations and worktree mechanics. It does not know
why an assignment was selected or what GitHub reports about it.

`commands.py` remains the sole subprocess boundary. Higher-level modules
ask it to run or spawn already-constructed commands; no other module
imports the subprocess library.

`prompts.py` owns the construction of the prompts passed to agent
harnesses. It receives the information required to construct each
prompt, including how the previous round ended, and opens the input of a
round that follows a stopped, errored or interrupted one with a line
saying so. It does not infer why an agent round is being run or make
scheduling decisions.

`feed.py` owns the harness-neutral activity representation and rendering
of parsed harness events into plain-text records. Rich presentation
remains in the TUI boundary.

## Persistent and derived information

The architecture persists facts needed to recover identity, ownership,
and acknowledged work.

Creation writes the work record, `work.json`, once, and nothing writes
it again. The same record serves both kinds of agent work. It persists:

- the issue identifier, while the agent work identifier names the
  directory that holds the record and the worktree;
- the issue title captured at creation;
- the dispatch label and the kind of agent work;
- the selected harness, model, effort and harness config;
- the work's instructions, which are the recipe's prompt with the issue
  filled in.

An assignment's branch is named from its identifier, and its pull
request number is in `pull-request.json`.

Every fact that changes later has a file of its own beside the record.
Each write replaces that file whole and merges nothing into it, so the
daemon, the web interface and a command can each record a fact at the
same moment without erasing another's. These files persist:

- for an assignment, once the round that opens its pull request has done
  so, that pull request's number, written once;
- the harness session identifier, once known;
- the time of the user's latest retry request, when one has been made;
- the time and the reason the work ended, once it has ended.

A round record persists:

- its number within its work and its start time, written before anything
  else;
- its process identifier, once the harness is spawned;
- its terminal outcome, when known, any observed end time and exit
  status, and the reason it could not prepare, start or finish; and
- the durable files containing its prompt, input, output, and any final
  output the harness reports.

Each kind of errored ending has its own type in `agent_rounds.py`, and
the exit status in a saved ending selects the type when the record is
read. An absent status means the round's preparation or startup failed
and no exit status was recorded, a nonzero status means its harness
failed, and a zero status means its finishing step failed.

An assignment round input that carries user posts puts the cursor at its
newest post, and one that carries a pull request signal records the head
at which it was relayed. The assignment reads the cursor by scanning the
recorded inputs of its rounds that took their turn or are running, from
newest to oldest. What woke a round is read from its input rather than
recorded.

A conversation's harness session identifier and latest user retry
request each have a file of their own beside its record, as an
assignment's do. Its route and recipe stay frozen for its life. Each
round input persists its investigated revision and the eligible comments
it relays; the input of a round that starts a new harness session also
persists the issue title and body.

Instance records persist the repository identity and the most recent
daemon run's preferred harness, _dreamcatcher_ version, capacity,
interval, and the dispatch routes it loaded, each as a dispatch label
and its kind of agent work. An instance-wide scheduler record persists
the last tick's result, including its failures, its request rows, the
active global cooldown, and the time at which the most recent cooldown
ended. Its rows preserve operational evidence of what the tick read
rather than authoritative state. Assignments and conversations persist
the time of their latest user retry request. These boundaries allow
fault to remain a derived status: ending a cooldown or requesting a
retry changes which round errors count towards fault rather than writing
a lifecycle status.

The following are derived rather than persisted as authoritative state:

- which requests exist, and whether a request with no open work may
  start;
- whether either kind of agent work is in fault;
- whether agent work requires a round;
- what input the next round is given; and
- every agent work status and request status shown in a status report.

Mutable external facts, including issue state, assignees, labels,
dependencies, linked pull requests, pull-request
draft/readiness/terminal state, merge state, head commit and checks, and
user posts, are read from GitHub. A failed read produces an unknown fact
and conservative inaction rather than a guessed answer.

## Dependency direction

The important dependency rules are:

- the daemon depends on the scheduler, never the reverse;
- the scheduler may direct assignment and round operations;
- assignment and round modules depend on narrow Git, GitHub, document,
  harness, prompt, and command boundaries, not on the scheduler;
- status reporting may reuse pure scheduling interpretations but may not
  call scheduling actions;
- the TUI depends on status and feed models, while neither depends on
  the TUI;
- GitHub and harness adapters expose projections to the domain and never
  import presentation or scheduling policy; and
- state and document modules know storage mechanics, not domain policy.

These rules keep the scheduling loop imperative and straightforward
without turning every possible action into an abstract command
hierarchy.

`tests/test_architecture.py` checks each rule here that keeps one module
from reaching another through its imports, directly or through another
module. It checks the status rule on the scheduler modules that status
imports directly.

## Agent-facing contract

The [agent-facing contract](contract.md) describes the protocols between
_dreamcatcher_ and assignment and conversation skills. It records each
side's responsibilities, not implementation history.
