# Architecture

This document says where each thing lives in the code and how the parts
pass things to each other, while [the concepts page](concepts.md) says
what the words mean, [the user stories](stories.md) say what the user
does and sees, and [the standard](standard.md) says how good the work
has to be.

It describes the enduring target architecture for _dreamcatcher_. It
maps the concepts to code boundaries and states the responsibilities,
interfaces, and encapsulation those boundaries should provide.

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
- record the daemon process identifier, the time the daemon run started,
  which is also the time of its first tick, and the dispatch routes it
  loaded in the daemon run record, whose model `daemon_runs.py` owns, as
  soon as it holds the lock;
- keep the web server inside the established daemon lifetime when `run`
  enables it;
- reconcile round records that an earlier daemon left without an ending
  by ending their recorded process trees at startup, skipping a record
  with no process identifier or one whose round started before the
  machine last booted, then asking the round boundary to record them as
  stopped when the user asked to stop them, and otherwise as
  interrupted;
- call the scheduler repeatedly;
- wait for the daemon run's requested interval between ticks, then check
  that it still holds the daemon lock; and
- stop active child processes during shutdown, which SIGTERM and, on
  POSIX, SIGHUP begin as Ctrl-C does, unless the daemon was started to
  ignore that signal.

The daemon does not decide which issue or piece of agent work deserves a
round. It knows that scheduling happens, but not the scheduling
priorities.

### Repository setup

`repository_setup.py` owns `dreamcatcher init`, which prepares a main
checkout for a daemon. It checks what a daemon run needs: a main
checkout, the GitHub repository and account, push access, a Git identity
and a fetchable default branch. It writes the default configuration when
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
when. The tick in `tick.py` has one path for every kind of agent work.
Each kind's module, `assignments.py`, `campaigns.py` or
`conversations.py`, supplies only what differs by kind: how it inspects
the channel of open work, how it decides whether a request with no open
work may start, and how it composes a round's plan. `conversations.py`
also holds the conversation's lifetime rules and reads eligible
comments. A closed issue ends the conversation after any running round
finishes. The labels, assignee and label applier decide whether it is
held. `scheduler/pull_requests.py` holds the start-time questions and
the pull request activity that can wake assignments and campaigns.
`blockers.py` holds the read of the open issues that block an issue,
which assignment and campaign requests share. `labelling.py` holds the
rule that work starts or resumes only on a dispatch label that the
signed-in account applied, which every kind's requests and open
conversations share. `inspection.py` holds the scheduling context, the
dispatch request, the candidate, the round plan and the inspection of
one request. `models.py` holds the scheduler record and its request
rows, and `faults.py` the fault and cooldown rules.

One scheduler tick:

1. reads every piece of agent work from disk, and lists in one read the
   open issues assigned to the signed-in account, whatever their labels;
2. builds the requests from two sources, each dispatch label on each
   listed issue and each piece of open agent work, which names its own
   issue and label;
3. inspects the assignments and conversations in a first pass, and the
   campaigns in a second pass, so that a campaign can use what the first
   pass found;
4. in each pass, inspects open work's channel first. It reads an
   assignment's pull request and user posts, a conversation's issue and
   eligible comments, or a campaign's pull request and user posts with
   the sub-issue observations from the first pass. The conversation's
   issue and label decide whether it has ended or is held;
5. inspects requests that no open work of the kind answers. It checks
   for a routing conflict and reads who applied the label and when. For
   assignments and campaigns, an application at or before the latest
   recorded GitHub application time for that kind on the issue is
   already consumed. Then a conversation request reads eligible
   comments, and assignment and campaign requests read claims and
   blockers. A clear assignment request checks the parent to select its
   base. A clear campaign request observes the parent's sub-issues;
6. removes the worktree of each piece of work that it sees end, and also
   the local branch for pull request work. Cancelled work keeps both;
7. starts a global cooldown when the counted faults call for one, and
   launches nothing while a cooldown is active;
8. launches candidates until the daemon run's requested capacity is full
   or no candidate remains, open work first in identifier order and then
   new requests in listing order, the kinds taking free slots in
   rotation in the order assignment, campaign, conversation, and a kind
   with no candidate giving up its place; and
9. returns a `SchedulerRecord`, holding one request row per request, for
   operational reporting.

A candidate is open work the tick may start a round for, or a request it
may start work for. It carries a preparation step that runs inside the
round and supplies its input, prompt and any finishing step. The tick
creates the work from the dispatch request, which carries the label
application time for an assignment or campaign and the base branch when
one was selected. It then starts the candidate's round.

`assignments.py` owns the base choice. The first pass builds its
assignment request inspector from all saved work, including ended
campaigns. The inspector looks up the direct parent and considers only a
parent in this repository. It uses the newest saved campaign by label
application time. With no campaign on record, it reads the parent's
labels if the daemon has a campaign route. It shares the base decision
across the parent's sub-issues and the pull request observation with the
campaign pass for the same tick. A failed read leaves the base unknown
and prevents a launch. An open or cancelled campaign supplies its branch
while its pull request is open. A campaign's sub-issue with no available
campaign pull request is held with a finding that names the parent.

Alternation advances when a kind is selected, including when its start
fails, and begins afresh after a daemon restart.

The daemon persists the returned `SchedulerRecord` and reports it in its
output. A scheduler tick that fails before returning one ends the daemon
run through the shutdown that an interrupt takes, so the daemon ends its
rounds and its web server, `cli.main` prints the failure, and the last
complete scheduler record stays in place. A local record that cannot be
read, or a write that fails while open work is inspected, fails the tick
this way whichever work it belongs to, and so does a scheduler record
that cannot be read or written.

If a GitHub read for a request fails, the tick holds the reason in that
request's row and prevents only the launches that depend on what it
would have read. A failed listing is a scheduler failure, because it
belongs to no request, and it starts no new work of any kind. Open work
is found on disk and reads its own channel, so a failed listing leaves
it inspected. A later tick retries the failed read.

The listing holds at most 500 issues, counted over every open issue
assigned to the signed-in account, whether or not a dispatch label is on
it. An account assigned more than 500 open issues may therefore have a
labelled issue left out of a tick.

A round that errors during its preparation or startup takes no agent
slot, and the tick goes on to the next candidate. The round is recorded
on its agent work, and the request's row names the round and its reason,
which the daemon's output line repeats. A launch that fails before its
round is recorded, such as a work record that cannot be written, fails
the tick and so ends the daemon.

A tick sees work end when the work was open when the tick read it, or
when the daemon held a round of it that the tick has just forgotten. It
removes nothing while the daemon still holds a round of the work, so a
later tick sees that work end once it forgets the round. No other tick
sees the work end, so a worktree or branch that Git will not remove is a
scheduler failure that no later tick tries again. For the same reason,
work that ended while no daemon ran keeps its worktree, and so does work
whose wrap-up round ended just before the daemon stopped.

When the tick selects a request, it writes the work record and starts
the first round in the same scheduling action. The record comes first,
before any Git or GitHub step, so the work exists however the round
goes. Pull request work without a recorded pull request number is due a
round that opens it, unless its last round is running or it is in fault.
This does not create a separate class of normally scheduled work.

Every new round is given what is past its work's cursor. A pull request
round's input holds the pull request number, state and head commit, the
pull request signals raised at a head not yet relayed, and the user
posts past the cursor, and a conversation round's input holds the
eligible comments past it. The cursor, the head at which each pull
request signal was last relayed, whether the relay rule withholds a
check-failure, and whether a wrap-up round has been given the finished
pull request are read from the inputs of the rounds that consumed their
input or are running, so a round that did not finish has its input given
again.

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
else. Each round's preparation resets the detached worktree to the
fetched default branch, adding it when it is missing, and freezes the
eligible comments past the cursor and that revision. A conversation's
worktree never acquires an implementation branch or a pull request.

Each tick reads an open conversation's issue before its comments, so
open conversations do not depend on the listing. The tick keeps reading
the issue while a round runs, decides from it whether the conversation
is held back or has ended, and reads its comments only while it is
neither. While no round runs, a conversation that nothing else holds
back is also held back when an account other than the signed-in one
applied its label, which the tick reads from the issue's events.

The relay selects the eligible comments past the cursor. Each durable
round input records the comments it relays, so the newest comment in the
latest input of a round that consumed its input or is running is the
cursor, and a comment behind it cannot be selected again. The
preparation adds the issue's title and body to the input of a round that
starts a new harness session, and resetting the worktree deletes every
local commit and file that an earlier round left.

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
streams. Claude supplies the answer in the last result event that has
text, which the round reads once Claude's output stream ends, or after a
short bound when a process the harness left behind holds the stream
open. For a Codex conversation, the adapter gives `codex exec` the
round's `final.md` path as its last-message output file on first and
resumed invocations. The path is relative to the worktree that Codex
runs in. The worktree and the work's directory both sit in the state
directory, so the command line never carries the checkout's own path.

### Campaigns

`campaigns.py` owns a lead round's input and the comparison of the
sub-issues. Once the work record exists, the opening round opens the
campaign's draft pull request through `pull_request_work.py`. It cuts
the campaign branch from the default branch and uses GitHub's closing
keyword for the parent. The worktree starts on the campaign branch and
keeps the checkout the lead left between rounds. The opening input
carries the new pull request number, its initial state and the head of
the worktree that was pushed, along with the sub-issues and assignment
routes. An opening round that adopts an existing pull request relays
GitHub's current observation and uses it to choose the input prompt. A
merged or closed pull request calls for wrap-up.

`scheduler/campaigns.py` asks the shared start-time questions after the
label checks clear a campaign request. A claim, a blocker or a failed
read holds the request before any sub-issues are observed. Once the
campaign exists, the parent supplies the sub-issue list and the pull
request drives the campaign's rounds.

Each tick then observes a campaign's sub-issues, for an open campaign
and for a campaign request that nothing blocks. It lists the parent's
direct sub-issues and matches each to the newest assignment at its
issue, ended ones included, and to what the tick's first pass found of
that assignment or of the assignment request at the issue.
`campaigns.py` owns the snapshot that results, one `CampaignChild` per
sub-issue in GitHub's order: the sub-issue's number, title and state,
whether it is settled, and where its newest assignment stands. A
sub-issue is settled when no assignment round of it is running and the
first pass made none due, where a request that may start an assignment
counts as a round due. Its assignment's entry names the assignment, its
pull request, what the first pass read of that pull request, the newest
round that consumed its input, its ending and whether it is in fault. An
assignment that has ended or is in fault keeps its pull request's
number, but the first pass read nothing of it. No sub-issue's pull
request is read a second time. The observation fails when the sub-issue
read fails, when a sub-issue is in another repository, whose work this
daemon never sees, when the first pass could not read a sub-issue's
assignment or assignment request, or when the listing failed and a
sub-issue has no open assignment. A failed observation holds no partial
picture.

For an open campaign with a complete sub-issue observation, the tick
reads its pull request activity through `scheduler/pull_requests.py`.
`compare_campaign_children` compares the current sub-issues with the
newest picture delivered to the lead, and names the changes that warrant
a notification. Pull request activity, an unfinished round or a
sub-issue notification can make a round due. An open pull request ready
for review also wakes the lead through the shared out-of-date and
check-failure relay rules. Its round receives the finishing input prompt
with the same signal lines an assignment receives. An open draft
receives the coordinating prompt. Both prompts direct the lead to read
the pull request's state first and wrap up if it is merged or closed. A
campaign in fault still shows the sub-issues the tick can observe. An
incomplete observation prevents a round. The tick compares sub-issues
each time, and records the notifications only in the input of a round
that starts.

The lead publishes its own messages, and its final output stays in the
feed. The shared wrap-up finisher records a completed campaign. Claude
gives a lead the assignment allow list, including `gh pr ready`, plus
the tools to dispatch sub-issues, review and merge their pull requests,
and check out the commits it reviews. Claude approves a shell call by
these rules only when every command in it matches one, and its auto mode
classifier refuses any other call that merges a pull request that no
person approved, so the campaign input prompt asks the lead to run each
`gh pr merge` on its own in both phases. Codex runs campaign and
assignment rounds under its own reviewer because fetching writes outside
the worktree. On both harnesses the coordinating prompt defers the
lead's edits, commits and pushes until it judges every sub-issue done.
The shared campaign prompt leaves the campaign's own merge to the user.
Every prompt requires the agent marker on every GitHub post that the
lead makes, except feedback that it gives a sub-issue's assignment on
that assignment's pull request. `compose_round_prompt` in `prompts.py`
chooses those words by the kind of work. The ordinary assignment relay
then gives the unmarked feedback to the assignment's agent as a user
post, so the lead reaches an assignment's agent through the same channel
as the user, and no campaign code relays it.

### Pull request work

`pull_request_work.py` names the branch, opens and records the pull
request, closes issues for merges into alternate bases, completes the
work after wrap-up, and removes the worktree and local branch for
assignments and campaigns. It also cancels either kind of work.

`agent_work.py` owns what every kind of agent work shares: the work
record, the agent work identifier, creating work of any kind from its
dispatch route, and the one reader through which the scheduler, status,
the commands and the views list agent work of any kind. It also records
the facts that change later for every kind: the harness session
identifier, when the user retries work after resolving a fault, and when
and why the work ended. It removes an ended piece of work's worktree and
keeps its records.

Creating pull request work writes its work record. The preparation step
of a round whose work has no recorded pull request number coordinates
lower-level Git, GitHub and document operations. It:

1. looks up a pull request on the work's branch and adopts it if found,
   whatever its state;
2. for a branch with no pull request, fetches the recorded base branch,
   or the current default branch when the record leaves the base empty;
3. adds the work's worktree on its branch, unless it is already there;
4. makes an empty commit if the branch has no commits beyond its base,
   then pushes the branch;
5. opens a draft pull request into the fetched base branch; and
6. writes the pull request's number to `pull-request.json`.

Adoption works even after the original base branch is gone. A worktree
that cannot be added is removed with its branch. The work identifier
names the branch and worktree, so a round that follows a failed one
finds what the earlier attempt made and never makes a second branch or
pull request.

For open work whose pull request merged and whose record names a base
other than the default, preparation closes the issue as completed before
it builds the wrap-up input. The closing comment names the pull request
and carries the agent marker. GitHub failures during closure error the
round during preparation. A retry leaves a closed issue alone and reuses
a closing comment already posted for that merge. A wrap-up round records
the work's ending with the reason "completed" in its finishing step,
after its harness exits successfully.

`pull_request_work.py` also models what a tick observed of a pull
request. The scheduler's pull request finding extends that model, and a
campaign holds it for each sub-issue's assignment.

The pull request work module coordinates the workflow but does not
implement Git commands, parse GitHub responses, launch harnesses, or
choose when work should run.

### Agent rounds

`agent_rounds.py` owns agent-round records and the supervised lifetime
of a round process for every kind of agent work. Before anything is
recorded, it asks a harness adapter to build the round's invocation.
Every value in the invocation is a name that dreamcatcher chose, a
setting that was checked when the configuration file was read, or a
harness session identifier that was checked when it was recorded, so
building it cannot fail. It should then provide operations to:

- record the round, with the next number that its work allocated, before
  anything else happens;
- run the preparation step that the work's kind supplies, which readies
  what the round needs and returns its prompt, any input to relay and
  any finishing step;
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

`pull_request_work.py` owns `PullRequestRoundInput`, the pull request
number, state and head commit, the relayed signals and the user posts.
`issue_conversations.py` owns `ConversationRoundInput`, which freezes
the issue, eligible comments and investigated revision for a
conversation round. `campaigns.py` owns `CampaignRoundInput`, which
extends the pull request input with sub-issues, notifications and
assignment routes for a campaign round. The round runner writes
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
- the events that applied a label to an issue, with the account and
  application time;
- a parent issue's direct sub-issues, with their titles and states;
- an issue's direct parent and its repository, including an explicit
  answer when the issue has no parent;
- linked pull requests;
- pull-request identity, draft state, readiness, terminal state, merge
  state, head commit, what its checks add up to, and whether any of them
  still runs;
- creating the draft pull request with a closing keyword for its issue;
- reading and posting ordinary issue comments, and closing an issue as
  completed with a closing comment; and
- reading and normalizing user posts from comments, reviews, verdicts,
  and inline comments.

The pull request record for an assignment or campaign holds its pull
request's number. Scheduling reads the current state from GitHub, and
the request row carries the observation to the views. Work with no
current observation shows the merged or closed state its newest relayed
round input carried, if any.

GitHub owns its documents and may add fields, so its responses remain
tolerant projections. Documents owned by _dreamcatcher_ remain strict.

GitHub matches a login in any case. `is_login_of_account` is the one
comparison of a login with the signed-in account, both for the author of
a post and for an assignee of an issue.

### Relay

`relay.py` owns what is past a piece of agent work's cursor. For pull
request work it selects user posts oldest first, identifying posts in
the last relayed second by kind and id, and raises pull request signals
for a head where they have yet to be relayed, under the relay rule. It
validates each recorded input against the work kind's full model and
uses the shared fields for the post cursor, signal memory and wrap-up.
For a conversation it selects eligible issue comments oldest first and
owns `IssueCommentCursor`, which marks a position in issue comments. One
eligibility rule selects user posts in both channel shapes.

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
and a `RequestStatus` for every request with no open work. The scheduler
record names the open work for each request that the tick saw, but the
tick writes that record only as it finishes, after it has started work.
So status also asks each work record whether it answers a request,
through `AgentWork.answers_request`, which the tick uses too.

Status construction may read:

- agent work and round records;
- raw harness output and the matching harness adapter when it must find
  a harness session identifier or build a hand-resume command;
- current child-process state;
- the instance's repository record and daemon-run record;
- the scheduler record, with its request rows, the active global
  cooldown, and when the latest tick finished;
- the latest rendered feed output needed for a useful summary.

It may call the scheduler's pure interpretation functions, but it cannot
invoke a scheduling action, mutate an assignment, relay a user post, or
start a process. In the code, those functions and records are the
scheduler's `models` and `faults` modules, and status imports no other
scheduler module. Status values are always derived; they are not written
back as domain state.

Status reads the dispatch labels from the daemon run record, never from
`dreamcatcher.toml`, and describes the section that every kind of agent
work has: its heading, and the guidance for a section with nothing
active once a daemon run is recorded. The guidance names the kind's
labels, or, when the daemon run routes none, says how to route the kind
and links the documentation that shows how. The presentations make none
of those choices themselves.

The scheduler record holds one `RequestRow` for each request the tick
saw. A row names the issue, its title, the dispatch label, the kind, and
the identifier of the open agent work, if any, with that work's latest
round when it had ended as the tick read the work, and the issue's state
when the tick read the issue: the listing reads it for every request,
and the tick reads it again for an open conversation. It holds what the
tick found as a typed finding:

- for work whose pull request the tick read, the pull request's number,
  state, draft flag, merge state, head and check result, whether any
  check still runs, the count of user posts and the pull request signals
  past the cursor, and whether the relay rule withheld a check-failure.
  A campaign finding also counts sub-issues with notifications;
- for a conversation whose comments the tick read, the count of comments
  past the cursor;
- for an assignment or campaign request with no open work, the open
  linked pull requests, as numbers, and the open blocking issues, each
  as a number with its repository when that is another one;
- for a request or an open conversation whose issue carries two labels
  of its kind, those labels;
- for a request, or an open conversation, whose label an account other
  than the signed-in one applied, that account;
- for an assignment or campaign request already consumed by earlier
  work, a consumed request finding;
- for a conversation that the user paused, the cause;
- for a read that failed, the reason, in place of what it would have
  found.

A row has no finding when the tick found nothing to record for it, as
for pull request work in fault or with no pull request yet, or for a
conversation in fault or whose issue is closed. A running round does not
prevent the tick from recording a finding, but it prevents the finding
from making the work a candidate for another round. A row also names the
round the tick started for it and, when that round errored during its
preparation or startup, the reason. Apart from those reasons for a
failure, no row holds a sentence meant for a person. Status composes the
words from these values once, and keeps the issue and pull request
numbers as numbers, so both presentations link them and neither parses
text.

A campaign's row also holds the parent's sub-issues as the tick observed
them, beside its finding, so they stay current while the lead is in
fault. The row omits the sub-issues when the tick skips observation or
cannot observe them all. Status gives an active campaign those
sub-issues and the words that count its closed sub-issues out of the
total, or says that its sub-issues are unknown. The status report gives
each sub-issue the status of its newest local assignment, so a new
assignment shows before the next tick records it on the campaign, the
request statuses of its assignment labels that have no open work, and
whether its issue is open or closed, as the tick observed it. The status
report also summarises the sub-issues on one line: the count of closed
sub-issues, then one count for each word that the chips of the nested
assignment cards and request cards show: the statuses of open work in
attention order, then the ending words, then the words that only a
request shows. The web home page puts an active campaign's lead card and
the expandable block of its sub-issues side by side in one wrapper, so
the latest output of a sub-issue's card is never read as the lead's. The
block stays in place, holding only its count while the sub-issues are
unknown or there are none, so a refresh keeps it open through a failed
observation. Each card in that block takes the campaign's identifier as
a prefix to its HTML identifier, so it differs from the same card on the
Assignments tab. A request card's identifier holds its label
percent-encoded, so two distinct labels on one issue never share one.

`AgentWorkStatus` is one summary status from the concepts page, derived
in one chain for every kind of agent work. `RequestStatus` gives a
request with no open work its request status, the facts that GitHub
holds about its issue, each as words with the issues or pull requests it
names, and any detail: what _dreamcatcher_ found, or what the user has
to do.

Status tells whether the scheduler record read the work after its latest
round ended from the round that the work's row names as ended, not from
the times of the record and the ending. A round that consumed its input
after the tick read the work leaves it idle and awaiting the next
update, unless the record found input that the round did not consume.
The earlier finding still supplies the assignment's last observed pull
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

Every piece of agent work, of any kind, has its page at
`/work/<identifier>`, and its feed tail and controls below that address.
Every kind of work shares one page layout, which opens with the work's
card. One macro renders a card's rows both there and on the home page,
from the same view model, so the two cannot drift apart. The page's tail
renders the card again, so the card keeps the pull request's state, the
issue's state, the status and the detail current. A conversation the
tick has found but not yet saved has no page.

The home page shows each kind of work on a tab of its own. The address's
fragment names the selected tab, as in `/#campaign`, so the browser's
back and forward buttons move between tabs. A work page links home to
the tab of its kind.

The home page gives each theme a motif, drawn by the macros in
`templates/partials/motifs.html`. The home view carries the count of
running agents, the macros give each motif its place and timing, and
each theme's stylesheet gives it its look. A working motif's place is a
distance from the window's edge in the mockup, and the stylesheet scales
each horizontal place and movement to the gutter between the window and
the content's text, including the theme's side padding. It keeps the
motif's fixed size and preserves the mockup's places at 1440px. The home
page's refresh redraws the motifs with the page, so the count stays true
without a script of their own. Nature draws both a seed and a firefly
for each motif, and its stylesheet shows the seeds on a light page and
the fireflies on a dark one, so the motif always suits the sky behind
it.

`home.js` observes the site header's rendered height and writes it to
the shared stylesheet variable, so the fixed working-motif layer begins
beneath the header without a height duplicated in each theme. The home
page's refresh morphs the header in place, so the observer stays with
it.

The web interface can ask a running round to stop. It writes a
same-origin stop request through the agent-round boundary, into that
round's own directory. The daemon still owns the live process and
lifecycle transition: the round watches the request, kills its harness
process tree, and records its stopped ending.

The web interface and the `cancel` command cancel an assignment or
campaign through `pull_request_work.py`. The operation records the
work's ending with the reason "cancelled", then writes a stop request
for any round that has no ending. If an ending already exists, the
operation keeps it and the command reports that the work has already
ended. The scheduler starts no further rounds for that work. A round
that starts as the cancel lands is stopped too, because the scheduler
reads the ending again once that round's record exists.

The web interface and the `retry` command can also request a retry for
agent work that status derives as in fault. Each writes the retry
request time into the directory of the work. The scheduler reads the
request on a later tick, so the daemon still decides when the work's
next round starts.

### Configuration, dispatch labels, and routes

`config.py` owns the strict model for `dreamcatcher.toml`. A
`DispatchRecipe` supplies the model, effort, and initial prompt used to
start agent work through one harness. A `ClaudeRecipe` and a
`CodexRecipe` each add the harness config that their adapter takes,
which is none for Claude. A `DispatchRoute` maps one dispatch label to
one recipe per harness that the route configures.

An `AssignmentRoute` specializes a dispatch route for assignments, and
its prompt normally invokes an assignment skill. A `CampaignRoute`
specializes a dispatch route for campaigns, and its prompt normally
invokes a campaign skill. A `ConversationRoute` specializes a dispatch
route for issue conversations, and its prompt normally invokes a
conversation skill. Every kind uses the same harness-selection rule: the
preferred harness wins when the route has a recipe for it, while the
sole recipe wins when only one exists.

The repository configuration carries choices that everyone working in
the repository shares. The daemon interval and agent capacity belong to
one person's run, so the `run` command receives them instead.

The default configuration is `default_config.toml` in the package. The
configuration module writes it for `init`, with the recipes of each
harness that is not installed commented out, and the configuration
reference includes the same file.

The configuration module validates labels, routes, and recipes. Each
dispatch label belongs to one route, so a label configures one kind of
agent work. Given an issue's labels, the module identifies the matching
routes. It does not silently resolve multiple labels by list order. The
scheduler applies the routing rules to the routes it returns.

GitHub matches label names in any case. `identify_label` gives each
label name its identity. Every comparison of two label names compares
their identities, and every sorted list of label names is in the order
of their identities.

### State and documents

`state.py` owns the top-level paths within `.dreamcatcher/` and the
mechanics required to bootstrap that directory. The modules that own
agent work and rounds name the files within their own directories. A
state-format constant selects the versioned root, currently
`.dreamcatcher/v9/`, so one format never reads another format's files.
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
- each piece of agent work, of any kind, owns a directory under `work/`
  named by its identifier, holding its durable record, a file for each
  fact that changes after its creation, and numbered round records;
- each round owns its prompt, raw output, rendered feed, final output
  when the harness reports one, and any input it relays; and
- each piece of agent work's worktree lives under `worktrees/`, named by
  the same identifier, until the scheduler removes it after the work
  ends. Cancelled pull request work keeps its worktree.

`documents.py` remains the only way _dreamcatcher_ reads and writes
documents it owns. Every structured document has a strict model and
every replacement write is atomic. A read of a replaceable document and
the replacement step of its write hold a persistent `<document>.lock`
sidecar, so readers close the document before a writer replaces it
across threads and processes. A writer stages and closes a file that no
other write shares before it takes the lock, so writes that race each
other each land whole. A work's ending checks for an ending and moves
its staged write into place under that same lock, so when endings race,
the first to take the lock lands and the others change nothing. Static
TOML and append-only streams need no document lock. These short document
locks are distinct from the daemon lock held for a daemon run. A
one-value process file may remain simple text where a model would add no
meaning.

State-directory objects provide paths and document access. They do not
answer domain questions such as whether an assignment has ended or a
request may start.

### Git, commands, prompts, and feeds

`git.py` owns Git operations and worktree mechanics. Fetching the
default branch refreshes `origin/HEAD` from the remote. Fetching a named
branch refreshes its remote-tracking ref even when the checkout's fetch
configuration omits that branch. The module takes a base ref for
creating a worktree on a branch and for counting commits beyond its
base.

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
it again. The same record serves every kind of agent work. It persists:

- the issue identifier, while the agent work identifier names the
  directory that holds the record and the worktree;
- the issue title captured at creation;
- the dispatch label and the kind of agent work;
- the GitHub application time of the label that started an assignment or
  campaign;
- the selected harness, model, effort and harness config;
- the base branch for pull request work, when explicitly selected;
- the work's instructions, which are the recipe's prompt with the issue
  filled in.

The branch of pull request work is named from its identifier, and its
pull request number is in `pull-request.json`.

Every fact that changes later has a file of its own beside the record.
Each write replaces that file whole and merges nothing into it, so the
daemon, the web interface and a command can each record a fact at the
same moment without erasing another's. These files persist:

- for pull request work, once the round that opens its pull request has
  done so, that pull request's number, written once;
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

A pull request round input that carries user posts puts the cursor at
its newest post, and one that carries a pull request signal records the
head at which it was relayed. The relay reads the cursor by scanning the
recorded inputs of its rounds that consumed their input or are running,
from newest to oldest. What woke a round is read from its input rather
than recorded.

A conversation's harness session identifier and latest user retry
request each have a file of their own beside its record, as an
assignment's do. Its route and recipe stay frozen for its life. Each
round input persists its investigated revision and the eligible comments
it relays; the input of a round that starts a new harness session also
persists the issue title and body. A conversation's input requires some
eligible comments, oldest first and each once. A campaign's input adds
the sub-issues, their notifications and the assignment routes to its
pull request round input.

Instance records persist the repository identity and the most recent
daemon run's start time, preferred harness, _dreamcatcher_ version,
capacity, interval, and the dispatch routes it loaded, each as a
dispatch label and its kind of agent work. An instance-wide scheduler
record persists the last tick's result, including when it started and
finished, its failures, its request rows, the active global cooldown,
and the time at which the most recent cooldown ended. Its rows preserve
operational evidence of what the tick read rather than authoritative
state. Agent work of every kind persists the time of its latest user
retry request. These boundaries allow fault to remain a derived status:
ending a cooldown or requesting a retry changes which round errors count
towards fault rather than writing a lifecycle status.

The following are derived rather than persisted as authoritative state:

- which requests exist, and whether a request with no open work may
  start;
- whether agent work of any kind is in fault;
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

An import-linter contract in `pyproject.toml` checks each rule here that
keeps one module from reaching another through its imports, directly or
through another module. The status rule's contract checks the scheduler
modules that status imports directly. The `lint-imports` commit hook
runs every contract.

## Agent-facing contract

The [agent-facing contract](contract.md) says what an assignment,
campaign or conversation skill must say and must not say.
