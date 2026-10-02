# One shape for the two kinds of agent work

Stage 3 of [the roadmap](roadmap.md) asks for one shape for the two kinds of
agent work, designed with the user before any code is written. This document is
that design. It grows in three parts, in the order the work is done.

1. What the ontology says: where the two kinds are the same and where they
   differ, each line citing the ontology.
2. What the code does: each difference the scheduler and status splits made
   visible, held against part 1 and marked as following from a named difference
   or as an accident.
3. The shape: what the accidents resolve to, and what changes.

The ontology stays the authority. This document reads it; it does not repeat it
as a second source. A line below that could not be cited was a gap in the
ontology, and the pull request that wrote the line filled the gap, so each line
now has its citation.

## What the ontology says

### Same

1. Both are agent work with an agent work identifier.
   ([Agent work and agent work identifier](../../docs/ontology.md#agent-work-and-agent-work-identifier))
2. Both run numbered rounds, each with a purpose, a recovery flag and an
   outcome. ([Agent round](../../docs/ontology.md#agent-round),
   [Describing an agent round](../../docs/ontology.md#describing-an-agent-round))
3. Both normally share one harness session across rounds, and recovery without a
   recorded harness session identifier starts a new one.
   ([Agent harness and harness session](../../docs/ontology.md#agent-harness-and-harness-session),
   [Agent work composition](../../docs/ontology.md#agent-work-composition))
4. Both recover an errored or interrupted round automatically, and two
   consecutive errors put the work in fault.
   ([Recovery round](../../docs/ontology.md#recovery-round),
   [Handling errors and global cooldown](../../docs/ontology.md#handling-errors-and-global-cooldown))
5. Both share the daemon's capacity and the global cooldown, and a user retry
   clears a fault the same way for each.
   ([Starting an issue conversation](../../docs/ontology.md#starting-an-issue-conversation),
   [Handling errors and global cooldown](../../docs/ontology.md#handling-errors-and-global-cooldown))
6. Both have a summary status with shared meanings for working, waiting, fault
   and unknown, and each has a resting status that is the other's counterpart.
   ([Agent assignment status](../../docs/ontology.md#agent-assignment-status),
   [Issue conversation status](../../docs/ontology.md#issue-conversation-status))
7. Both are selected through one dispatch label, which belongs to one route,
   which supplies one recipe.
   ([Dispatch labels and routes](../../docs/ontology.md#dispatch-labels-and-routes))
8. Both have a stop rule with the same shape: a stopped round is not recovered,
   and the next ordinary round's prompt says the user stopped the last one.
   ([Scheduling rounds in response to events](../../docs/ontology.md#scheduling-rounds-in-response-to-events),
   [Starting an issue conversation](../../docs/ontology.md#starting-an-issue-conversation))
9. A round's input is a frozen batch of user input from the work's communication
   channel: posts on the pull request for an assignment, comments on the issue
   for a conversation.
   ([Agent assignment composition](../../docs/ontology.md#agent-assignment-composition),
   [Issue conversation composition](../../docs/ontology.md#issue-conversation-composition))

### Differ

1. An assignment owns a branch, worktree and pull request, so the pull request
   is its communication channel with the user. A conversation owns a detached
   worktree and nothing else, so the issue is its communication channel with the
   user. ([Pull request](../../docs/ontology.md#pull-request),
   [Agent assignment composition](../../docs/ontology.md#agent-assignment-composition),
   [Issue conversation composition](../../docs/ontology.md#issue-conversation-composition))
2. An assignment is created by a scheduling action from an available issue. A
   conversation starts from an eligible comment batch, and a bare labelled issue
   starts nothing.
   ([Creating an agent assignment](../../docs/ontology.md#creating-an-agent-assignment),
   [Starting an issue conversation](../../docs/ontology.md#starting-an-issue-conversation))
3. An assignment round's purpose comes from pull request state. A conversation
   round is always a discussion.
   ([Round purpose](../../docs/ontology.md#round-purpose))
4. Beside the batch, an assignment round's input carries the pull request state,
   which a wrap-up round acts on. A conversation round's input carries the main
   revision it investigates, and the first one also carries the issue title and
   body.
   ([Agent assignment composition](../../docs/ontology.md#agent-assignment-composition),
   [Issue conversation composition](../../docs/ontology.md#issue-conversation-composition))
5. A conversation round must post its answer before it ends successfully. An
   assignment round ends when the harness exits.
   ([Starting an issue conversation](../../docs/ontology.md#starting-an-issue-conversation))
6. An assignment can complete. A conversation never does, and is kept after the
   issue stops being eligible.
   ([Completing an assignment](../../docs/ontology.md#completing-an-assignment),
   [Issue conversation composition](../../docs/ontology.md#issue-conversation-composition),
   [Issue conversation status](../../docs/ontology.md#issue-conversation-status))
7. The tick observes every labelled issue of either kind before any work exists.
   For an assignment the observation says whether the issue is available, so it
   is a place in the queue. For a conversation it says whether comments wait, so
   it is a status, idle until the user comments.
   ([Issue observations and availability](../../docs/ontology.md#issue-observations-and-availability),
   [Issue conversation status](../../docs/ontology.md#issue-conversation-status))
8. Availability for an assignment reads claimed here, claimed elsewhere, blocked
   and routing conflict. Conversation eligibility reads none of those, only its
   own routing conflict and whether comments wait.
   ([Issue observations and availability](../../docs/ontology.md#issue-observations-and-availability),
   [Starting an issue conversation](../../docs/ontology.md#starting-an-issue-conversation))
9. Assignment ranking is recovery, wrap up, new posts, then oldest available
   issue. Conversation ranking is recovery, then oldest waiting comment.
   ([Scheduling work](../../docs/ontology.md#scheduling-work))
10. A conversation in fault counts towards the cooldown only when its issue has
    no known routing conflict. An assignment in fault always counts.
    ([Handling errors and global cooldown](../../docs/ontology.md#handling-errors-and-global-cooldown))
11. Each kind lives by its channel. An assignment recovers and takes new work
    only while its pull request is open, and reads nothing else about its issue
    once created. A conversation does so only while its issue stays eligible:
    open, assigned, with exactly one conversation label.
    ([Scheduling rounds in response to events](../../docs/ontology.md#scheduling-rounds-in-response-to-events),
    [Starting an issue conversation](../../docs/ontology.md#starting-an-issue-conversation))

Differences 8, 10 and 11 are one difference seen three times. A conversation's
eligibility plays the part an assignment's open pull request plays: it bounds
when work starts and when recovery runs, and a fault that cannot recover says
nothing about a shared problem. Each conflict is reported differently today.
[Issue 346](https://github.com/alimanfoo/dreamcatcher/issues/346) records that
as an accident outside this stage's budget.

### Gaps the list found

Two lines could not be cited when first written, and the ontology grew in the
same pull request so that they could.

- Same 9 and differ 4 say what an assignment round's input holds. The ontology
  said this of a conversation round's input and nothing of an assignment's.
  "Agent assignment composition" now says it.
- Differ 11 says an assignment reads nothing about its issue once created. The
  ontology said what ends a conversation's eligibility and nothing of what an
  assignment stops reading. "Scheduling rounds in response to events" now says
  it.

## What the code does

The Stage 2 review listed six differences the scheduler split made visible, one
per row. Each row below is read against part 1. A difference that part 1 names
stands, and the row says which line names it. A difference that part 1 does not
name is an accident, and part 3 resolves it.

### Row 1: how existing work is examined

Each tick examines each kind in four steps, and the difference is in where each
step lives.

1. **List the labelled issues.** Both kinds list issues by route label and
   assignee, one call per route, merged by issue number. The assignment listing
   is in `scheduler/issues.py` and the conversation listing in
   `scheduler/conversations.py`, and they are near-copies. The assignment one
   stops at the first route that fails to list; the conversation one carries on
   and joins the failures. Accident: same 7 says both kinds are selected by one
   label per route, and nothing says the listing differs.
2. **Observe each listed issue.** An assignment observation carries the
   availability facts. A conversation observation carries routing conflict and
   whether comments wait. Named: differ 7 says both kinds are observed before
   any work exists, and differ 8 says what each observation reads.
3. **Inspect existing work.** Assignments are inspected by walking the open
   assignment records and reading each one's pull request. Conversations are
   inspected by walking the listed eligible issues and finding the record for
   each. A conversation whose issue is not listed is never inspected; an
   assignment is inspected whatever its issue does. Named: differ 11.
4. **Hold the walk.** The scheduler loops over the assignments itself, skips a
   running one and gives one that needs nothing a "no round required"
   observation. The conversations module does all of that for its own kind, and
   the scheduler calls one function. Accident: nothing says the scheduler knows
   how one kind is inspected and not the other.

What this row points to: one issue listing, called with each kind's routes; one
tick-level inspection per kind with parallel names, each taking the tick's facts
and returning its kind's result, so the scheduler knows neither kind's
internals; and the walk source kept different, citing differ 11.

### Row 2: what each inspection yields

The assignment inspection yields one result per assignment, of three types: a
required round, a faulted assignment, or an observation. The conversation
inspection yields one bundle of candidates, observations and a failure.
Underneath, both kinds produce those same three things.

1. **The bundle.** The conversation side returns candidates, observations and
   failure together. The assignment side has the same three spread over the
   scheduler, which filters the required rounds out of the per-item results and
   turns the rest into observations. Accident: row 1's one inspection per kind
   returns one bundle for both.
2. **Where ranking happens.** Conversation candidates come back ranked by the
   module. Assignment candidates are ranked in the scheduler. The orders
   themselves are differ 9 and stand. Where they are applied is an accident.
3. **What a candidate carries.** An assignment candidate is a prepared round:
   purpose, recovery flag, input and prompt, composed at inspection. A
   conversation candidate is the facts, the issue, its comments and its route,
   and the round is prepared at launch. Preparing a conversation round fetches
   main and resets the worktree, which differ 4 names, so it can only happen for
   the candidate that launches. Preparing an assignment round has no side
   effect. Accident, resolved towards the conversation side: a candidate of
   either kind carries facts, and the launch prepares the round.
4. **Two observation documents say one thing in two shapes.** The assignment
   observation has a reason and two booleans, is-known and is-round-required.
   The conversation observation has one tri-state fact with evidence,
   has-comments-to-answer. Status reads them identically: unknown gives unknown
   with the evidence, false gives the resting status, true gives waiting. That
   is one fact, whether the work needs a round and why, and the conversation
   side already has the type for it. Accident, and an E2 finding, since two
   booleans and a string can say what one fact cannot. Both observations are
   persisted in the scheduler record, so this is one of the changes the stage's
   format break to v5 carries.

What this row points to: each kind's inspection returns one bundle of ranked
candidates, observations and a failure; a candidate carries the facts a launch
needs and nothing prepared; and one observation type, keyed by the work and
holding one fact for whether a round is needed, with the conversation's routing
conflict beside it where differ 8 puts it.

A behaviour asymmetry this row found, outside its business. When one assignment
route fails to list, the scheduler drops every assignment candidate, including
recovery rounds for existing assignments. When one conversation route fails to
list, the module keeps recovery candidates from the routes that listed and drops
only fresh batches. Differ 11 says an assignment's pull request governs it, so
the assignment side is more cautious than the ontology asks. Healing it is a
scheduling change, outside this stage's budget, and
[issue 348](https://github.com/alimanfoo/dreamcatcher/issues/348) records it.

### Row 3: what a fault is

The derivation is already one function for both kinds, as same 4 asks. What
differs is how each kind carries the answer and what it says about it.

Two differences are named. Which faults count towards the cooldown is differ 10:
a conversation's counts only when its issue has no known routing conflict.
Status shows a conversation's fault only while its issue is eligible, and an
assignment's always, which is differ 11.

1. **Derived once or twice.** An assignment's fault is derived once at
   inspection and carried as a result type, which the scheduler counts. A
   conversation's is derived at inspection, to withhold a candidate, and again
   over every conversation in `scheduler/faults.py` to count. Accident: each
   kind's inspection derives it once and carries it in its bundle, and the
   scheduler sums.
2. **What the record says about a faulted item.** The assignment observation
   says "two consecutive rounds failed" with round-required true, the default.
   The conversation observation says comments-to-answer false, "no comments to
   answer", though no comments were read. Status reads neither: it derives the
   fault again from the rounds. Accident, in two shapes: with one observation
   type, a faulted item's observation says it is in fault as its evidence. This
   goes in the v5 break with row 2's item 4.
3. **Two words for one thing.** The assignment fault says "failed", in the
   scheduler and in status. The conversation fault says "errored", in status.
   The ontology's word is errored. The scheduler's string is a status phrase
   that nothing shows. Accident, under S4 and C1: the word lives in status,
   once.
4. **Two fault details.** An assignment's detail is the last feed line, else the
   reason and the feed path. A conversation's is the unfinished round's
   description, "round N errored" with its reason. Both status types carry the
   latest output, and nothing in the ontology says the detail differs by kind.
   Accident: one detail, in the status rounds module both share.

Items 3 and 4 change text a user sees. The roadmap's Stage 3 permits that where
one wording wins and says more, and part 3 lists each string that changes.

### Row 4: where new work comes from

An assignment is created by a scheduling action from an available issue, and a
conversation starts from an eligible batch, which is differ 2. Both kinds create
the record at launch when there is none and start the first round in the same
action, which the ontology says of each process. Assignment setup has more
steps, branch, commit, push and pull request, so it alone has an incomplete
setup to resume, which follows from differ 1.

1. **The candidate is a persisted document.** New assignment work is the issue
   observation itself, a scheduler-record document pressed into service as a
   candidate, appended to the list in the scheduler. New conversation work is a
   candidate type holding the issue, its comments and its route, built by the
   inspection. Accident: a new-assignment candidate holds the issue and its
   route, and the assignment inspection builds it where availability is already
   derived.
2. **The route is found twice.** The scheduler digs the label out of the
   observation's nullable label list and looks the route up by name. The
   conversation candidate carries the route. The fallback arm the scheduler
   keeps for a missing list defends a state that availability already rules out,
   which is an E2 finding. Accident: same 7 says one label selects one route, so
   the candidate carries it.
3. **The candidate types partition differently.** Assignment candidates divide
   by whether a record exists: an issue observation for new work, and a required
   round for everything else, the first round of a just-created assignment
   included. Conversation candidates divide by recovery: one type for a first or
   later batch, with the record created at launch if absent, and one for
   recovery. The two cuts follow each kind's ranking list in the ontology, which
   is differ 9, so they stand; part 3 says why. What was accidental is item 1,
   the issue observation serving as a candidate. The assignment side's rank that
   puts a first round before everything is the ontology's rule for finishing an
   interrupted creation, and survives either cut.

A note for the E1 ledger, not a verdict. Both kinds meet an unrecorded worktree
at creation. An assignment resumes it, because its branch and pull request may
already exist, which differ 1 explains. A conversation refuses it with an error.
Its own creation removes the worktree when the record write fails, so the branch
guards a state the code already cleans up, unless that removal failed.

### Row 5: how launching works

Both launches do the same four things: resolve the harness session and the
prompt, start the round, register it in the running set, and tell the tick's
record that the launched work no longer waits.

Two differences are named. The conversation launch hands the round a finisher
that posts the answer and the assignment launch hands none, which is differ 5.
The conversation launch marks its request as conversation work, so the harness
gets the narrower permissions, which follows from differ 1.

1. **Finding out what launched.** The conversation launch returns a new
   scheduler record with its own observation patched to "no comments to answer".
   The assignment launch returns nothing, so the scheduler copies the running
   set before the launch, diffs it afterwards to find which identifier appeared,
   filters that candidate out of the inspection results and recomputes the
   assignment observations. That diff is the launch chain the roadmap names.
   Accident: a launch returns what it launched, and one helper over the base
   observation type marks the launched work's observation, whichever kind it is.
2. **The prepared round.** The conversation side prepares into a named type
   holding the conversation, input, prompt, session identifier and recovery
   flag. The assignment side prepares into a bare tuple of three unnamed values.
   Inside both sit the same two rules from same 3: a later round with no
   recorded session cannot resume and raises, and a recovery with no recorded
   session starts a new session with the configured prompt. The rules are
   written twice, with the same error sentence in two files. Accident: one
   prepared-round shape, and the two rules in one place. The assignment launch
   also writes a session identifier it recovered from raw output back into the
   record, and the conversation launch does not.
3. **Two delivery cursors.** A conversation's delivery position is the newest
   comment in the latest recorded round's input; there is no other file, and the
   ontology states that rule in those words. An assignment's position is a
   separate cursor file, written after the round starts, though the same posts
   sit in the round's input. Two persisted facts that must agree, which is S4
   and E2 at once. Accident: the position of either kind is read from its
   recorded inputs, and the cursor file goes in the v5 break.

Item 3 changes one edge. Today an assignment recovery that starts a fresh
session with posts advances its cursor only once the new session reports its
identifier, so a lost identifier redelivers the posts. Reading the position from
recorded inputs counts them delivered when the round is recorded, as a
conversation does. The edge is narrower than it looks. A recovery with an open
pull request carries no posts, so the case needs a merged or closed pull request
and no identifier from any round. Both harnesses report the identifier in their
first event, before any work, and the scheduler recovers it from any round's raw
output, so no identifier means no round ever got past starting its harness.
Nothing was done and nothing can be resumed, and the wrap-up round is a fresh
session with the pull request in front of it either way. The change is neutral
for robustness, removes the write window between the round start and the cursor
write, and leaves one delivery rule for both kinds.

### Row 6: how the scheduler is passed to each kind

No line of part 1 names anything in this row. It is code shape alone.

The conversation functions take the scheduler through a protocol of seven
attributes: repository, account, config, state, requested harness, clock and the
running set. The assignment functions take it through a protocol of two, clock
and the running set, and take repository and account as plain parameters, while
assignment creation sits in the scheduler and reads state, config and the
requested harness from itself. Across the whole assignment side the same seven
things are needed; they arrive by three doors. Both protocols describe the one
object, the scheduler. The issue observer has a fourth bundle of its own, which
the roadmap already names as residue.

1. **Three bundles for one set of facts.** The instance's identity and handles
   are what every tick-level operation needs, and they are the same for both
   kinds. Accident: the facts become attributes again, on one base class that
   both kinds extend, replacing both protocols and the observer's bundle. Part 3
   gives the two classes.
2. **The running set belongs to neither kind.** Both launches write into the
   scheduler's dictionary of running rounds. Row 5 says a launch returns what it
   launched, so the scheduler registers it and neither kind needs the dictionary
   to launch. For inspection, the conversation side reads running from the
   records alone: a round with no ending is running. The assignment side checks
   the dictionary as well, because its round describer treats a record with no
   ending as interrupted. Two conventions for one state. The daemon records
   every stale round as interrupted at startup, before the first tick, so while
   a daemon runs a record with no ending is a running round, as the record's own
   outcome says. Accident: one convention for both kinds inside a tick, and the
   dictionary check goes with it. Status, which may run while no daemon does,
   reads such a record as working when a daemon is alive and as left behind when
   none is, and both kinds read it so.

### Row 7: how status summarises each kind

The Stage 2 review named status's own asymmetry beside the scheduler's: the
reader holds both kinds of agent work, and the two kinds are summarised in
different places. Status answers one question for both kinds, what is happening
with this work now, and most of the differences are in where the answer is
worked out and how it is packaged.

Five differences are named. A conversation status exists before any record, so
it carries the issue, the title and an optional record where the assignment
status carries the record alone: differ 7. A conversation drops off the report
when its issue stops being eligible unless a round runs, which its listed flag
carries: differ 11. A conversation's fault is shown only while eligible:
differ 11. A conversation's round list shows the main revision each round
investigated: differ 4. An assignment's running detail names the round's purpose
and a conversation's does not, since a conversation round is always a
discussion: differ 3.

1. **Two homes for one derivation.** The assignment summary is worked out in
   eight methods on the reader. The conversation summary is worked out partly in
   functions in `status/conversations.py`, through an intermediate summary type
   the assignment side lacks, and partly in six more reader methods. Accident:
   one base reader holds what both kinds share, the daemon, the latest scheduler
   record and the time, and one subclass per kind derives its own statuses from
   its records and observations. That is the status counterpart of row 6's two
   classes.
2. **Running detail written twice.** The round number, how long it has run and
   how long since its last output are composed once for assignments and once for
   conversations, with the purpose the only difference. Accident: one
   composition in `status/rounds.py`, which both share.
3. **Stop eligibility written twice.** Which round can take a stop request is
   one rule written in both status types. Accident.
4. **"Over" derived in two places.** Whether nothing more happens until the user
   acts is a property on the conversation status. For assignments the TUI
   derives it, twice, from a constant the status package exports for the
   purpose. Accident under S4: one property on both.
5. **Two readings of the gap after a round ends.** When an assignment's round
   ends after the latest tick, status says waiting, "awaiting next update",
   because the scheduler has not yet looked at the pull request. When a
   conversation's round ends after the latest tick, status says idle and
   answered, though comments may have arrived while the round ran and the
   scheduler has not yet looked. The architecture states the assignment rule and
   is silent on conversations. Accident: work whose round ended after the latest
   tick is waiting for the next update, whichever kind it is. This changes one
   status a user sees, within what the roadmap permits.
6. **Hand-resume for one kind only.** The assignment status offers the session
   identifier and the command to resume the session by hand, and both views show
   it. The conversation status offers neither, though it finds the same
   identifier for its own stop check. Nothing in the ontology says only an
   assignment can be picked up by hand. Accident, but adding a section to the
   conversation view and page is more than settling words, so it stays out of
   this stage and
   [issue 349](https://github.com/alimanfoo/dreamcatcher/issues/349) records it.

## The shape

This part is the migration plan. It takes what the seven rows point to and turns
it into one shape for the scheduler and status packages, section by section, in
the order the work is best done. Each section has the same three parts.
**Today** says what the code has now, naming files and symbols and passing no
judgement. **The shape** says what it becomes. **The edits** list the changes in
the order a developer would make them. Where a move needs a reason beyond the
row that points to it, the section gives it.

Two rules hold throughout. The shape changes no scheduling decision, command or
prompt. It changes persisted documents only under the v5 break, and status
wording only under the permission the roadmap gives, and the lists at the end of
this part name every such change. A name given here is the name the code uses,
so a reader can find each piece from this document.

### The two kinds as classes

Rows 6 and 1 point here.

**Today.** The scheduler's one class, `AgentWorkScheduler` in
`scheduler/coordinator.py`, is a dataclass holding the repository, account,
config, state directory, requested harness, clock, the running set and the agent
cap. Before Stage 2, the two kinds' scheduling code was methods on that one
class and read those fields as `self.repository` and so on. The split moved the
code into `scheduler/assignments.py` and `scheduler/conversations.py` as free
functions, and then had to hand them the object they used to be methods on. It
did that three ways:

- The conversation functions take a `scheduler` argument typed as
  `_ConversationScheduler`, a protocol listing seven of the scheduler's
  attributes. The scheduler passes itself.
- The assignment launch takes a `scheduler` argument typed as
  `_AssignmentRoundScheduler`, a protocol listing two attributes, clock and the
  running set. The assignment inspection takes `repository` and `account` as
  plain parameters instead.
- The issue observer in `scheduler/issues.py` builds its own private bundle,
  `_IssueObservationContext`, from the repository, account, config, the open
  assignments and the incomplete setups.

Both protocols describe the same object, and every operation needs the same six
facts about the instance and this run.

**The shape.** The two kinds are two classes with one base, and the facts are
attributes again.

- `AgentWorkScheduler`, in `scheduler/agent_work.py`, is a frozen keyword-only
  dataclass holding the six facts: repository, account, config, state directory,
  requested harness and clock. It declares three abstract methods that every
  kind implements with the same signature: `inspect`, `rank` and `launch`, which
  the sections below define. It holds the code both kinds share: listing a set
  of routes' issues, and the harness session rule. It is generic over the kind's
  candidate and observation types, so the two implementations agree in shape
  while differing in type.
- `AssignmentScheduler`, in `scheduler/assignments.py`, and
  `ConversationScheduler`, in `scheduler/conversations.py`, extend it. Every
  helper that took `scheduler` or `repository` becomes a method, or a function
  that takes the scheduling object, and reads `self.repository` and so on.
- The scheduler holds one instance of each, built from the same six facts, and
  calls `self.assignments.inspect(...)` and `self.conversations.launch(...)`.
  The running set, the agent cap and the alternation stay on the scheduler.

The names follow the ontology. Agent work is either an assignment or a
conversation, so `AgentWorkScheduler` is what the two kinds' schedulers share,
and the class that runs the tick, which is the ontology's one scheduler, becomes
`Scheduler`. Stage 2 called that class the scheduler, after its module; the
ontology never does, and this design stops. The base makes the symmetry
structural: two subclasses of one base must implement the same methods with the
same signatures, which the type checker holds, so E4 stops being a convention a
reviewer rechecks. Shared code has an obvious home. And it is the codebase's own
precedent: `AgentAssignmentCreator` and `StatusReportReader` are small classes
holding their handles with a method or two. It stops there. One base, two
subclasses, no deeper; the kind objects hold handles, not mutable state; and no
candidate launches itself, so the scheduling loop stays imperative as the
architecture asks.

**The edits.**

1. Add `scheduler/agent_work.py` with `AgentWorkScheduler`: the six fields, the
   three abstract methods, and the two shared methods the listing and launching
   sections define.
2. In `scheduler/assignments.py`, add `AssignmentScheduler` extending it. Turn
   each function that took `scheduler`, `repository` or `account` into a method.
   Delete `_AssignmentRoundScheduler`.
3. In `scheduler/conversations.py`, add `ConversationScheduler` extending it.
   Turn each function that took `scheduler` into a method. Delete
   `_ConversationScheduler`.
4. Change `observe_issues` and its helpers in `scheduler/issues.py` to take the
   scheduling object, the open assignments and the incomplete setups, and delete
   `_IssueObservationContext`.
5. Rename `AgentWorkScheduler` to `Scheduler`, since the base takes its old
   name, and its module from `scheduler/coordinator.py` to `scheduler/tick.py`,
   since the tick is all it holds. Give it two fields, `assignments` and
   `conversations`, in place of the six facts. Have the daemon and CLI build the
   two kind objects when they build it. The rename touches the daemon, the
   package face, the measurement's list of functions that stay whole, and three
   test files.

### The running set and the meaning of "no ending"

Row 6 points here, with row 5.

**Today.** The scheduler keeps a dictionary of running rounds keyed by agent
work identifier. Two things in the per-kind modules touch it:

- Each launch writes into it. `_start_assignment_round` and
  `_start_prepared_conversation_round` both end with
  `scheduler.rounds[identifier] = start_agent_round(...)`.
- The assignment inspection reads it. `_inspect_assignments` in the scheduler
  skips an assignment when its identifier is in the dictionary and its latest
  round has no ending. It needs that check because
  `AgentAssignment.describe_unfinished_round` calls a round with no ending
  "interrupted", so without the check a running assignment would be scheduled
  for recovery.

The conversation side reads nothing from the dictionary. Its inspection treats a
latest round with no ending as running by the record alone: it is not errored or
interrupted, so it is not recovered, and `is_issue_conversation_ready_for_input`
says no new batch.

The two kinds therefore read a record with no ending two ways: running, on the
conversation side, and interrupted, on the assignment side. The conversation
reading is the safe one inside a tick, because the daemon records every round an
earlier daemon left as interrupted before its first tick, in
`DreamcatcherDaemon.run`. Status is different: it may run while no daemon does,
so for status a record with no ending means working when a daemon is alive and
left behind when none is. Both kinds already read it that way in status, and
that stays.

**The shape.** The dictionary belongs to the scheduler alone. A kind's `launch`
returns the `AgentRound` it started and the scheduler registers it. No `inspect`
reads the dictionary: both kinds treat a latest round with no ending as running,
by the record. The assignment describer stops calling such a record interrupted.

**The edits.**

1. Change `describe_unfinished_round` on `AgentAssignment` to return `None` when
   the latest round has no ending, and keep its two descriptions for the
   interrupted and errored endings. Check its callers in status: the step that
   decides working or waiting from the daemon's presence stays, and is written
   once for both kinds in the status section below.
2. Remove the dictionary check from the assignment inspection. Skip an
   assignment whose latest round has no ending, as the conversation inspection
   already does by its outcome checks.
3. Make each `launch` return the round instead of writing it into the
   dictionary. Have the scheduler write `self.rounds[identifier] = round` after
   a launch returns. The round has to say which work it belongs to, so give
   `AgentRound` the agent work identifier from its launch request.
4. Delete the scheduler's copy-and-diff of the dictionary that discovers what
   launched, which the launch section covers.

### Listing issues

Row 1, step 1, points here.

**Today.** Each kind lists the issues that carry its labels, and the two
listings are near-copies.

- `_list_considered_issues` in `scheduler/issues.py` loops over the assignment
  routes, calls `list_issues` once per route with the route's label and the
  account as assignee, and merges the results by issue number. If a route fails
  to list, it stops there and returns what it has with that failure. The
  scheduler later prefixes the failure with "could not refresh issues".
- `_list_conversation_route_issues` in `scheduler/conversations.py` does the
  same for the conversation routes, with two differences. A route that fails
  does not stop it: it records "could not list issue conversations for LABEL:
  REASON" and carries on with the other routes, joining the failures at the end.
  And it sorts the merged issues by creation time, then number.

Notice that the two differences are not decisions anybody made about assignments
or conversations. They are two people writing the same loop on different days.

**The shape.** One method on the base, `list_route_issues`, takes a list of
routes and returns a `RouteIssueListing`: the merged issues, sorted by creation
time then number, and one joined failure or none. A route that fails to list
contributes its failure and the other routes are still listed. The failure reads
"could not list issues for LABEL: REASON" for either kind. Each kind calls it
with its own routes.

The conversation side's behaviour wins because it loses less: when one route
fails, the issues on the other routes are still observed, so the status report
stays as complete as it can be. Nothing is launched on a failed listing either
way, so no scheduling decision moves.

**The edits.**

1. Add `RouteIssueListing`, a frozen dataclass of `issues` and `failure`, to
   `scheduler/agent_work.py`, and `list_route_issues` as a method on the base,
   built from the conversation version's loop with the new failure wording.
2. Change `observe_issues` to call it on the scheduling object with the
   assignment routes, and delete `_list_considered_issues` and
   `_ConsideredIssueResult`. The observer keeps its own sort of the finished
   observations, because it adds issues it read one by one after the listing.
3. Change the conversation inspection to call it with the conversation routes,
   and delete `_list_conversation_route_issues` and `_ConversationRouteListing`.
4. Remove the "could not refresh issues" prefix from the scheduler. The
   listing's own wording is the hold.

### Inspecting each kind

Rows 1, 2 and 3 point here. This is the largest move, so here is the idea before
the detail. Every tick, for each kind, the scheduler has to answer three
questions: what work is ready to launch, in what order; what did I find out
about each piece of work, for the status report; and did anything I needed to
read fail. Today the assignment side answers them in several places and the
conversation side in one. The shape makes each kind answer all three in one
method, returning one bundle of the same type.

**Today.**

- For assignments, the scheduler's own method `_inspect_assignments` loops over
  the open assignments, skips a running one, and calls
  `inspect_agent_assignment` in `scheduler/assignments.py` for each. That
  function returns one of three things: a `RequiredAgentRound` when a round is
  needed, a `FaultedAgentAssignment` when the assignment is in fault, an
  `AgentAssignmentObservation` when the pull request or posts could not be read,
  or `None` when nothing is needed, which the scheduler turns into a "no round
  required" observation. The scheduler then does the rest itself: counts the
  faulted results for the cooldown, converts every result into an observation
  with `list_assignment_observations`, filters the required rounds out and ranks
  them with `prioritize_required_rounds`, and appends the available issues from
  the issue observations as candidates for new assignments. If the issue listing
  failed, it returns no assignment candidates at all. The issue observation
  itself, with the incomplete setups it needs and the recording of missing
  titles, is also the scheduler's work, done before the loop.
- For conversations, `list_issue_conversation_candidates` in
  `scheduler/conversations.py` does all of that inside the module and returns an
  `IssueConversationCandidateResult` holding the ranked candidates, the
  observations and the joined failure. One thing it leaves out: the fault count.
  The scheduler calls `count_observed_conversation_faults` in
  `scheduler/faults.py`, which runs the fault derivation over every conversation
  a second time.

**The shape.** `inspect` is the first abstract method on the base. Its signature
is the same for both kinds: it takes the previous tick's scheduler record, or
none, and the tick's time, and returns the kind's bundle. Each kind reads its
own records from `self.state` inside it.

- `AssignmentScheduler.inspect` reads the assignments and the incomplete setups,
  observes the issues, records missing titles, walks the open assignment
  records, as differ 11 requires, skipping any whose latest record has no
  ending, reads each one's pull request, and turns each available issue
  observation into a candidate for a new assignment.
- `ConversationScheduler.inspect` reads the conversations, takes the previous
  observations from the previous record, lists the conversation routes' issues,
  and walks the listed eligible issues, as differ 11 requires, finding the
  record for each.

Both return `AgentWorkInspection`, one generic frozen dataclass in
`scheduler/models.py` with four fields:

- `candidates`: the work ready to launch, already ranked, in the kind's own
  candidate types. Only candidates it is safe to launch are here. When the
  kind's listing failed, the assignment bundle holds none and the conversation
  bundle holds recoveries only, exactly as the scheduler decides today.
- `observations`: one per piece of work the tick looked at, in the kind's own
  observation type, for the scheduler record and the status report.
- `fault_count`: how many of this kind's work items are in fault and count
  towards the global cooldown. Each inspection derives fault once per item,
  gives a faulted item no candidate, and counts it. The conversation side counts
  only conversations whose issue has no known routing conflict, which differ 10
  names.
- `failure`: the joined reason this kind's reads failed, or none.

The assignment bundle, `AssignmentInspection`, extends it with
`issue_observations`, the issue observations the tick made, which the record
persists and the report shows. That extension is named by the ontology: issue
observations and availability are how an assignment starts, which is differ 2
and 7, and a conversation has no counterpart to an available issue.

The scheduler calls both inspections, adds the two fault counts, and puts the
issue observations, the two observation lists and the joined failures in the
record. It never looks inside a candidate.

**The edits.**

1. Add `AgentWorkInspection` to `scheduler/models.py`, generic over the
   candidate and observation types, and `AssignmentInspection` extending it in
   `scheduler/assignments.py`.
2. In `scheduler/assignments.py`, implement `inspect`. Move the reading of
   assignments and incomplete setups, the call to `observe_issues` and the
   recording of missing titles from the scheduler's `tick` into it. Move the
   loop from the scheduler's `_inspect_assignments` into it, dropping the
   running-set check in favour of skipping a latest round with no ending. Inside
   the loop, derive fault with `derive_agent_work_fault` and, when true, count
   it and record an observation saying so. Otherwise read the pull request and
   posts as `_inspect_assignment_pull_request` does today, and build a candidate
   or an observation. After the loop, add a new-assignment candidate for each
   available issue observation, rank all candidates with `self.rank`, and return
   the bundle with the issue listing's failure. Delete
   `inspect_agent_assignment`, `AssignmentInspectionResult`,
   `FaultedAgentAssignment`, `list_assignment_observations`,
   `compose_assignment_observation` and `prioritize_required_rounds`.
3. In `scheduler/conversations.py`, turn `list_issue_conversation_candidates`
   into `inspect`, reading the conversations and the previous observations
   itself and returning the shared bundle. Count faults where
   `_inspect_conversation_recovery` already derives them, so the second pass
   goes. Apply the recoveries-only rule on a failed listing here. Delete
   `IssueConversationCandidateResult`.
4. Delete `count_observed_conversation_faults` from `scheduler/faults.py`.
5. In the scheduler, delete `_inspect_assignments`,
   `_list_ready_assignment_candidates`, `_list_ready_conversation_candidates`
   and `_list_available_issues`, and have `tick` call the two inspections and
   add their fault counts.

### Candidates

Rows 2 and 4 point here.

**Today.** The two kinds describe ready work with different kinds of object.

- An assignment that needs a round is a `RequiredAgentRound`, which carries the
  assignment, a complete `AgentRoundPlan` with purpose, recovery flag and input,
  a reason and the prompt text. Everything the launch needs is prepared at
  inspection.
- An issue that needs a new assignment is the `IssueObservation` itself, the
  document the scheduler record persists, used as a candidate because it happens
  to hold the issue number and labels. At launch the scheduler reads
  `assignment_labels[0]` out of it, with a fallback for a missing list that
  availability already rules out, and looks the route up by name.
- A conversation that needs a round is a `NewIssueConversationRoundCandidate`,
  holding the issue, its waiting comments, its record if one exists, and its
  route, or an `IssueConversationRecoveryCandidate` holding the conversation.
  Nothing is prepared; the launch does that.

**The shape.** A candidate carries the facts a launch needs and nothing
prepared, for both kinds. Each kind's candidate types follow its ranking list in
the ontology, which is differ 9, and what starts each kind, which is differ 2.

- Assignment, three types in `scheduler/assignments.py`:
  `NewAssignmentCandidate`, the issue number, its title and its route, built
  from an available issue observation; `FirstAssignmentRoundCandidate`, an
  assignment whose record has no rounds, which the ontology's rule for finishing
  an interrupted creation needs, and which reads no pull request, as today; and
  `AssignmentRoundCandidate`, an assignment with its pull request, its
  undelivered posts, and the reason its last round needs recovery, or none.
- Conversation, two types in `scheduler/conversations.py`:
  `ConversationBatchCandidate`, the renamed batch candidate, since a first and a
  later batch are one thing to the ontology; and
  `ConversationRecoveryCandidate`, today's `IssueConversationRecoveryCandidate`
  renamed.

Why three against two, when the point is one shape? Because the ontology's
ranking lists differ: an assignment can need a first round, a recovery, a
wrap-up, new posts or creation, and a conversation can need a recovery or a
batch. The types follow the lists. What was accidental was never the cut; it was
using a persisted document as a candidate, and preparing one kind's round at
inspection and the other's at launch.

`rank` is the second abstract method on the base: it takes one candidate and
returns its sort key, and each kind's `inspect` sorts by it. The assignment
order is the one the scheduler produces today: first rounds, then recoveries,
then wrap-ups, then posts, then new assignments in the issue observations'
order. The conversation order is recoveries, then batches by their oldest
waiting comment.

**The edits.**

1. Add the three assignment candidate dataclasses to `scheduler/assignments.py`
   and implement `rank` on `AssignmentScheduler`. Delete `RequiredAgentRound`
   and `_rank_required_round`. The three functions that composed a required
   round, `compose_initial_round_requirement`,
   `_compose_recovery_round_requirement` and
   `_compose_resumed_round_requirement`, move to the launch, which the launch
   section covers.
2. Rename `NewIssueConversationRoundCandidate` to `ConversationBatchCandidate`
   and `IssueConversationRecoveryCandidate` to `ConversationRecoveryCandidate`,
   and turn `_rank_issue_conversation_candidate` into `rank` on
   `ConversationScheduler`.
3. Delete the scheduler's `_AssignmentCandidate` alias and its route lookup by
   label.

### Observations and the scheduler record

Rows 2 and 3 point here. This is the first of the two changes the v5 break
carries.

**Today.** The scheduler record, `SchedulerRecord` in `scheduler/models.py`,
holds two observation lists, and the two kinds' observations have different
shapes for the same job.

- `AgentAssignmentObservation` has the assignment identifier, the issue, a
  `reason` string, and two booleans, `is_known` and `is_round_required`.
- `IssueConversationObservation` has the issue, the title, and two `IssueFact`s:
  `has_comments_to_answer` and `routing_conflict`. An `IssueFact` is a value,
  true, false or unknown, with its evidence.

Look at how status reads them. For an assignment: not known gives unknown with
the reason; not required gives needs user feedback; required gives waiting. For
a conversation: comments unknown gives unknown with the evidence; false gives
idle; true gives waiting. That is the same three-way reading of one fact, does
this work need a round and why, with the conversation side already using the
type built for it.

Two more things the record carries that nobody reads. When the tick is at
capacity, the scheduler rewrites every required assignment's reason to the
capacity hold, but status never shows that reason. And a faulted assignment's
observation says "two consecutive rounds failed" with round-required true, while
a faulted conversation's says comments false, and status derives the fault from
the rounds and reads neither.

**The shape.** One base type carries the one shared fact.

- `AgentWorkObservation`, in `scheduler/models.py`, holds `identifier`, the
  agent work identifier; `issue`; and `requires_round`, an `IssueFact`. The name
  follows the ontology's phrase, "whether an assignment requires an agent
  round".
- `ConversationObservation`, today's `IssueConversationObservation` renamed,
  extends it with `title`, because a conversation is observed before any record
  holds one, which is differ 7, and `routing_conflict`, which differ 8 puts on
  the conversation alone.
- The assignment observation is the base type itself.

The evidence words are the same for both kinds. True carries the need: "N new
posts to answer", "N comments to answer", "the pull request is merged", "round N
errored, to recover", or "no round has run yet". False carries why not: "no
round required", "in fault", or "round N started" for work the tick launched.
Unknown carries the failure. Every open work item the tick inspected has an
observation, launched or not, and the capacity hold rewrites nothing.

**The edits.**

1. In `scheduler/models.py`, add `AgentWorkObservation`, rename
   `IssueConversationObservation` to `ConversationObservation` and make it
   extend the base: rename `has_comments_to_answer` to `requires_round` and add
   `identifier`. Delete `AgentAssignmentObservation` and type the record's
   `assignment_observations` as a list of the base.
2. In the assignment inspection, compose observations with the shared words,
   including one for a faulted assignment and one for each launched one.
3. In the conversation inspection, give each observation its identifier,
   composed as `IssueConversation.identifier` composes it, and say "round N
   errored, to recover" rather than "no comments to answer" for a recovery.
4. In the scheduler, delete the capacity rewrite in `_hold_for_capacity` and the
   removal of a launched assignment's observation.
5. In status, read `requires_round` in the one way for both kinds, which the
   status section covers.

### Delivery position

Row 5 points here. This is the second change the v5 break carries.

**Today.** The two kinds record which user input has been delivered to the agent
in different ways.

- A conversation's position is the newest comment in its latest recorded round's
  input. `read_issue_comment_delivery_cursor` in `issue_conversations.py` reads
  it from the input file, and no other file exists. The ontology states this
  rule.
- An assignment's position is a separate one-line file, named by
  `USER_POST_DELIVERY_CURSOR_NAME`, read into
  `AgentAssignment.user_post_delivery_cursor` when the assignment is loaded.
  `advance_user_post_delivery_cursor` writes it after a round with posts starts.
  One case is special: a recovery that starts a fresh session with posts writes
  it only once the session identifier arrives, through
  `_record_session_before_advancing_user_post_cursor`. Yet the same posts are in
  the round's input file, written when the round starts.

So the assignment side keeps two facts that must agree, the cursor file and the
latest input's posts, and nothing checks that they do.

**The shape.** Either kind's position is read from its recorded rounds' inputs
and from nowhere else. `read_user_post_delivery_cursor` in
`agent_assignments.py` scans the rounds newest first, reads each one's input
file if there is one, and returns the newest post's time from the first input
that holds posts, or the empty string when none does, which is today's
beginning-of-time cursor. It is the counterpart of the conversation's reader,
scanning back because first and recovery rounds carry no input, which the
ontology now says.

The one edge this touches, and why it is safe, is under row 5.

**The edits.**

1. Add `read_user_post_delivery_cursor` to `agent_assignments.py`.
2. Make `user_post_delivery_cursor` on `AgentAssignment` a property that calls
   it, so the relay's caller in the assignment inspection reads as today.
3. Delete `USER_POST_DELIVERY_CURSOR_NAME`, `_read_user_post_delivery_cursor`,
   `advance_user_post_delivery_cursor` and
   `_record_session_before_advancing_user_post_cursor`, and the branch in the
   launch that chose between them.

### The format break

Both changes above alter a persisted document, so the state format version moves
from 4 to 5.

**The edits.**

1. Set `STATE_FORMAT_VERSION` in `state.py` to 5. The versioned root becomes
   `.dreamcatcher/v5/`, and the daemon lock stays outside it, shared by every
   format, as the architecture says.
2. Correct the README's state format section and the architecture's state and
   documents section to say v5, and say in the README that version 5 starts with
   empty local state, as version 4 did.
3. Update the test fabrications that build scheduler records and assignment
   directories.

### Launching

Row 5 points here, with row 4.

**Today.** The two launches have different shapes, and the scheduler does part
of one kind's launching itself.

- `launch_required_round` in `scheduler/assignments.py` takes the scheduler and
  a `RequiredAgentRound` and returns nothing. It resolves the session with
  `_prepare_assignment_resume`, which returns a bare tuple of three values,
  writes a recovered session identifier back to the record, chooses between two
  cursor-advancing callbacks, starts the round, and writes it into the running
  set.
- A new assignment is launched by the scheduler's `_launch_assignment`, which
  creates the assignment with `AgentAssignmentCreator` and then calls
  `launch_required_round` with the first round's requirement.
- `launch_issue_conversation_round` in `scheduler/conversations.py` takes the
  scheduler, the scheduler record and a candidate, prepares a
  `_PreparedIssueConversationRound` with `_prepare_issue_conversation_round` or
  `_prepare_issue_conversation_recovery`, creating the conversation record first
  if there is none, starts the round, writes it into the running set, and
  returns a new scheduler record with the conversation's observation patched.

Inside both sit the same two rules from same 3, written twice with the same
error sentence: a later round with no recorded session cannot resume and raises,
and a recovery with no recorded session starts a new session with the configured
prompt.

**The shape.** `launch` is the third abstract method on the base. It takes one
candidate and the tick's time, and returns the `AgentRound` it started.

- `AssignmentScheduler.launch`: for a new-assignment candidate it creates the
  assignment with the candidate's route and the tick's time, then starts the
  first round, in one call. For a first-round candidate it starts the first
  round. For a round candidate it derives the purpose from the pull request with
  `derive_round_purpose`, builds the plan with the input, composes the prompt,
  resolves the session and starts the round.
- `ConversationScheduler.launch`: today's launch with the record patching
  removed and the round returned.

Each launch prepares an `AgentRoundStartRequest`, the type the round boundary
already takes, from the candidate's facts, and hands it to `start_agent_round`.
The two session rules live once on the base as `resolve_harness_session`, which
takes the work identifier, whether it has rounds, its recorded session
identifier, whether this is a recovery, and the two prompts, and returns a
`HarnessSessionResumption` of the identifier to resume, or none, and the prompt
to use, or raises the one error sentence. The conversation launch keeps its
finisher and its narrower permissions, which differ 5 and differ 1 name.

**The edits.**

1. Add `HarnessSessionResumption` to `scheduler/agent_work.py` and
   `resolve_harness_session` as a method on the base, from the two copies.
2. In `scheduler/assignments.py`, implement `launch`. Move `_launch_assignment`
   from the scheduler into its new-assignment arm. Turn the three former
   requirement composers into the preparation of the first-round and round arms.
   Delete `launch_required_round`, `_prepare_assignment_resume` and
   `_start_assignment_round`.
3. In `scheduler/conversations.py`, turn `launch_issue_conversation_round` into
   `launch`, return the round, and delete
   `_record_conversation_comments_delivered`. Replace the session logic in
   `_prepare_issue_conversation_round` and
   `_prepare_issue_conversation_recovery` with calls to
   `resolve_harness_session`. `_PreparedIssueConversationRound` becomes an
   `AgentRoundStartRequest`.
4. Give `AgentRound` an `agent_work_identifier` property from its launch
   request, so the scheduler can register what a launch returns.

### The tick

Rows 1, 5 and 6 point here. With the pieces above in place, the scheduler
shrinks to the steps the architecture lists.

**Today.** `AgentWorkScheduler.tick` reads the previous record, forgets ended
rounds, reads the records, observes issues, inspects assignments through its own
loop, lists conversation candidates, counts faults two ways, starts a cooldown
if required, builds the record, and then either holds for the cooldown, holds
for capacity with the reasons rewritten, or calls `_launch_available_work`. That
method builds a `_ReadyAgentWork` from the two candidate lists and runs
`_launch_ready_candidates`, a loop that chooses the kind with
`_choose_next_work_kind` and calls `_launch_next_candidate`, which copies the
running set, calls `_try_launch_candidate` to dispatch on the kind and catch a
`ReportableError`, diffs the running set to discover what launched, removes the
launched assignment's observation, and clears the kind's candidates on a
failure. `_hold_for_capacity` then rewrites observations again.

**The shape.** `Scheduler`, in `scheduler/tick.py`, holds `assignments`,
`conversations`, the running set, the agent cap and the alternation state.
`tick` reads as the eight steps in the architecture: forget ended rounds, read
the previous record, inspect each kind, add the fault counts and start a
cooldown if required, write the record, launch. The launch loop alternates
between the kinds as the ontology says and, for each free slot: pops the next
candidate of the chosen kind, calls that kind's `launch`, registers the returned
round, marks the launched work's observation with `mark_round_started`, one
function in `scheduler/models.py` over the base observation type, and appends
the identifier to the record. A launch that raises adds its reason to the hold
and clears that kind's remaining candidates, as today. A full running set with
candidates left sets the capacity hold and nothing else.

The scheduler knows the two kinds by name and nothing of their internals.

**The edits.**

1. Add `mark_round_started` to `scheduler/models.py`.
2. Rewrite `tick` and the launch loop as above. Keep `_choose_next_work_kind`
   and the alternation state. Delete `_launch_available_work`,
   `_launch_next_candidate`, `_try_launch_candidate`,
   `_launch_next_assignment_candidate`, `_launch_assignment`,
   `_hold_for_capacity`'s rewrite and `_ReadyAgentWork`'s readiness flags,
   keeping only the two candidate lists.

### Status

Row 7 points here. The status package gets the same shape as the scheduler: one
base holding the facts both kinds share, and one subclass per kind deriving its
own statuses.

**Today.** `StatusReportReader` in `status/reader.py` reads the daemon's process
identifier, the latest scheduler record and the two observation maps in its
constructor, and then holds fourteen methods that derive the two kinds'
statuses: eight for assignments, which do all of that kind's work, and six for
conversations, which share the work with three functions and an intermediate
`ConversationSummary` type in `status/conversations.py`. Three pieces of text
are composed twice, once per kind: the running detail, the fault detail and
which round can take a stop request. Whether a view can stop refreshing is a
property, `is_over`, on the conversation status, and for assignments a constant,
`STATUSES_THAT_END_A_VIEW`, that the TUI applies itself in two places.

So the reader is already nearly the shape we want. It holds the shared facts and
both kinds' derivations. What it lacks is the line between the two kinds.

**The shape.**

- `AgentWorkStatusReader`, in `status/agent_work.py`, is a frozen dataclass
  holding the state directory, the time, the daemon's process identifier and the
  latest scheduler record. It declares one abstract method, `list_statuses`,
  which takes nothing and returns the kind's statuses in the order the report
  needs, and holds the derivation steps both kinds share, such as whether a
  round ended after the latest tick.
- `AssignmentStatusReader`, in `status/assignments.py`, extends it with the
  assignment observation map, `list_statuses`, and `derive`, which takes an
  assignment. `ConversationStatusReader`, in `status/conversations.py`, extends
  it with the conversation observation map, `list_statuses`, and `derive`, which
  takes the issue, the title and the conversation if one is saved. The two
  `derive` methods differ in what they take, which differ 7 names, so
  `list_statuses` is the abstract one.
- `status/rounds.py` holds what both kinds say about a round: the running
  detail, the ending detail that fault and recovery share, and which round can
  take a stop request.
- Both status types gain `is_over` as a property: fault or complete for an
  assignment, and fault, routing conflict or not listed for a conversation.
- `status/report.py` reads the four shared facts once, builds one reader of each
  kind from them, and asks each for its statuses.

Both `derive` methods walk the same order, read top to bottom. A step marked for
one kind is a named difference, and the row says which.

1. A latest round with no ending while a daemon lives is working, with the
   shared running detail.
2. For a conversation: no scheduler record is unknown; no observation is idle,
   because its issue is not eligible, which is differ 11; and an observation
   with a known or unknown routing conflict gives that status, which is
   differ 8.
3. Two consecutive errored rounds is fault, with the shared ending detail.
4. A latest round that errored or was interrupted, short of fault, is waiting
   for recovery, with the shared ending detail.
5. For an assignment: a successful wrap-up round is complete, which is differ 6;
   a record with no rounds is waiting for its first round, which is the
   ontology's rule for an interrupted creation; and no scheduler record is
   unknown.
6. A latest round that ended after the latest tick is waiting, "awaiting next
   update", because the scheduler has not yet looked at the work.
7. Otherwise the observation's `requires_round` decides: unknown with its
   evidence, waiting with the kind's detail, or the kind's resting status, needs
   user feedback or idle, with the kind's detail.

The shared steps come in the same order for both kinds, and each kind's own
steps sit where today's code has them, so no status value changes except where
the list of changed words says.

**The edits.**

1. Add `status/agent_work.py` with `AgentWorkStatusReader`, from the reader's
   constructor, with the shared steps as methods.
2. Add the three shared helpers to `status/rounds.py`, from the assignment and
   conversation versions.
3. Add `AssignmentStatusReader` to `status/assignments.py`. Move the reader's
   assignment methods into its `derive` and `list_statuses`, following the order
   above.
4. Add `ConversationStatusReader` to `status/conversations.py`. Move the
   reader's conversation methods and the three functions into its `derive` and
   `list_statuses`, following the order above. Delete `ConversationSummary`.
5. Add `is_over` to `AgentAssignmentStatus`. Delete `STATUSES_THAT_END_A_VIEW`
   and have the TUI read the property in both places.
6. Delete `status/reader.py` and point `status/report.py` at the two readers.

### The order of the work

The roadmap's Stage 3 lists the work in the order to do it, one sub-issue and
one pull request per item, each blocked by the one before. Items 2, 3, 5, 6 and
7 of that list carry this design: the two classes and the running set;
inspection and candidates; the observations and the delivery position, in the v5
break; launching and the tick; and status. The rename comes first so that every
pull request after it is written in the final names, and the E2 audit comes
before the v5 break so that the break carries every persisted change at once.

### Words a user sees that change

Each is one wording that two kinds or two presentations gave two ways, or a
status one kind gave and the other did not.

1. Fault detail, both kinds: "round N errored (exit S)", followed by the
   ending's reason when the owner gave one, with the round's last feed line as
   the latest output. It replaces the assignment's last feed line as detail and
   "two consecutive rounds failed (path)" when there was none, and the
   conversation's "round N errored: reason" and "two consecutive rounds
   errored".
2. Running detail, conversation: gains the purpose word, "round N, discuss,
   running 3m, last output 10s ago", matching the assignment's form.
3. A conversation whose round ended after the latest tick: waiting, "round N
   ended, awaiting next update", where today it reads idle and answered.
4. The hold for a failed listing, both kinds: "could not list issues for LABEL:
   REASON", replacing "could not refresh issues: REASON" and "could not list
   issue conversations for LABEL: REASON".
5. Waiting for recovery, assignment: the ending detail, "round N errored (exit
   S)" or "round N interrupted", replacing "next round, PURPOSE (recovery)", so
   that the detail says what went wrong, as the conversation's already does.

### Enduring documents to correct

- Architecture, status reporting: what the two observation types record; that
  launched work keeps an observation saying its round started; that a round
  ended after the latest tick is waiting for the next update, for either kind.
- Architecture, agent assignments and user-post relay: the delivery position is
  read from recorded round inputs, and no cursor file exists. Five sentences
  name the cursor today.
- Architecture, state and documents: the versioned root is `.dreamcatcher/v5/`.
- README: the state format section names v5 and its break.

### Parallel names

The operations each kind has after the change, read in pairs. Where a pair
differs in shape, the line names the difference.

| Operation          | Assignment                                      | Conversation                                     |
| ------------------ | ----------------------------------------------- | ------------------------------------------------ |
| Scheduler class    | `AssignmentScheduler`                           | `ConversationScheduler`                          |
| Inspect for a tick | `inspect`                                       | `inspect`                                        |
| Result             | `AssignmentInspection`, adds issue observations | `AgentWorkInspection`                            |
| Candidates         | three types, by the ranking list                | two types, by the ranking list                   |
| Rank               | `rank`                                          | `rank`                                           |
| Launch             | `launch`                                        | `launch`                                         |
| Observation        | `AgentWorkObservation`                          | `ConversationObservation`, adds two facts        |
| Delivery position  | `read_user_post_delivery_cursor`                | `read_issue_comment_delivery_cursor`             |
| Session identifier | `find_assignment_harness_session_identifier`    | `find_conversation_harness_session_identifier`   |
| Record session     | `record_assignment_harness_session_identifier`  | `record_conversation_harness_session_identifier` |
| Retry              | `request_assignment_retry`                      | `request_conversation_retry`                     |
| Status class       | `AssignmentStatusReader`                        | `ConversationStatusReader`                       |
| Statuses           | `list_statuses`                                 | `list_statuses`                                  |
| Derive one         | `derive`, from an assignment                    | `derive`, from an issue and its record if saved  |
| Over               | `is_over`                                       | `is_over`                                        |

A name in the table that exists today under a longer form is renamed to this
one. The ontology uses "assignment" and "conversation" as the short forms of its
two terms, and the names follow it; "agent work" stays whole because it has no
short form. The baseline counted twelve symbols for conversations against nine
for assignments in the scheduler. The remeasurement counts these pairs and lists
every symbol one kind has without a counterpart, with the line of part 1 that
names it.

### Asymmetries that stand

Each of these is named by part 1 and stays, recorded here so the remeasurement
can find it.

- Which records are walked, and what each kind reads: differ 8 and 11.
- Candidate types, three against two: differ 2 and 9.
- The conversation observation's title and routing conflict: differ 7 and 8.
- A conversation's fault counted only without a routing conflict: differ 10.
- The finisher and the narrower permissions: differ 5 and 1.
- The conversation's status existing without a record, dropping off the report
  when ineligible, and showing each round's revision: differ 7, 11 and 4.
- `find_open_agent_assignments_by_issue` with no counterpart: an issue can carry
  many assignments over time and one open, and at most one conversation, so
  there is nothing on the conversation side to filter.
- How a failed listing is filled in: the assignment side reads each locally
  known issue on its own, and the conversation side carries the previous tick's
  observations forward as unknown. The architecture names the conversation's
  rule. Giving both one rule changes which GitHub reads a tick makes, so it
  waits for a stage with a behaviour budget.

### Alternatives considered

- **A context dataclass passed to free functions**, which an earlier draft of
  this part proposed. It tidied the protocols the Stage 2 split had needed
  without asking why free functions needed them. Two classes with one base give
  the same facts as attributes, make the parallel methods a fact the type
  checker holds, give shared code a home, and follow the codebase's own small
  classes. The dataclass is withdrawn.
- **A candidate protocol with a launch method**, so the scheduler launches
  without knowing the kind. The architecture rules this out in words: the
  scheduling loop stays imperative rather than becoming an abstract command
  hierarchy. Two named launches and a dispatch on kind keep it so.
- **One candidate cut for both kinds**, as row 4 first asked. Forcing the
  conversation's cut on assignments puts the first round, which reads no pull
  request, into a type with an optional pull request, which E2 forbids. Forcing
  the assignment's cut on conversations separates a first batch from a later
  one, which the ontology treats as one thing. The cuts the ontology's ranking
  lists give are the honest ones, and row 4 is corrected below.
- **One observation list with a kind field.** The identifier already says the
  kind by its prefix, and status reads the two kinds' observations by different
  keys, so one list would need a discriminator to deserialise and gain nothing.
  Two lists of one base type stay.
- **Reading a first assignment round's pull request**, so that the first and
  later round candidates could be one type. It adds a GitHub read and lets the
  first round's purpose follow a pull request the user changed before the round
  ran, which is a scheduling change. It waits.
- **Keeping the prepared plan on the assignment candidate**, as the required
  round has today. It costs nothing in side effects, but it leaves the two kinds
  preparing at different moments and the launch of one kind trivial and of the
  other heavy. Preparing at launch for both is the one shape.

### Corrections to part 2

Drafting the shape changed three verdicts in part 2, and the rows are corrected
in place so this document reads true.

- Row 4, item 3 said part 3 would pick one cut for both kinds. The ontology's
  ranking lists name each kind's cut, so the cuts differ and stand. What was
  accidental was the issue observation serving as a candidate.
- Row 5, item 1 said each kind's bundle marks its own observation. One helper
  over the base observation type marks either kind's.
- Row 6, item 1 and row 7, item 1 first pointed at a context value passed to
  free functions. The shape gives the facts as attributes on one base class per
  package instead, and the rows now say so.
- Row 6, item 2 said a record with no ending means running. It means running
  while a daemon lives, and status, which may run when none does, reads it as
  left behind otherwise. Both kinds use those two readings.
