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
4. **Hold the walk.** The coordinator loops over the assignments itself, skips a
   running one and gives one that needs nothing a "no round required"
   observation. The conversations module does all of that for its own kind, and
   the coordinator calls one function. Accident: nothing says the coordinator
   knows how one kind is inspected and not the other.

What this row points to: one issue listing, called with each kind's routes; one
tick-level inspection per kind with parallel names, each taking the tick's facts
and returning its kind's result, so the coordinator knows neither kind's
internals; and the walk source kept different, citing differ 11.

### Row 2: what each inspection yields

The assignment inspection yields one result per assignment, of three types: a
required round, a faulted assignment, or an observation. The conversation
inspection yields one bundle of candidates, observations and a failure.
Underneath, both kinds produce those same three things.

1. **The bundle.** The conversation side returns candidates, observations and
   failure together. The assignment side has the same three spread over the
   coordinator, which filters the required rounds out of the per-item results
   and turns the rest into observations. Accident: row 1's one inspection per
   kind returns one bundle for both.
2. **Where ranking happens.** Conversation candidates come back ranked by the
   module. Assignment candidates are ranked in the coordinator. The orders
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
route fails to list, the coordinator drops every assignment candidate, including
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
   inspection and carried as a result type, which the coordinator counts. A
   conversation's is derived at inspection, to withhold a candidate, and again
   over every conversation in `scheduler/faults.py` to count. Accident: each
   kind's inspection derives it once and carries it in its bundle, and the
   coordinator sums.
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
   candidate, appended to the list in the coordinator. New conversation work is
   a candidate type holding the issue, its comments and its route, built by the
   inspection. Accident: a new-assignment candidate holds the issue and its
   route, and the assignment inspection builds it where availability is already
   derived.
2. **The route is found twice.** The coordinator digs the label out of the
   observation's nullable label list and looks the route up by name. The
   conversation candidate carries the route. The fallback arm the coordinator
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
   The assignment launch returns nothing, so the coordinator copies the running
   set before the launch, diffs it afterwards to find which identifier appeared,
   filters that candidate out of the inspection results and recomputes the
   assignment observations. That diff is the coordinator's launch chain the
   roadmap names. Accident: a launch returns what it launched, and one helper
   over the base observation type marks the launched work's observation,
   whichever kind it is.
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
assignment creation sits in the coordinator and reads state, config and the
requested harness from itself. Across the whole assignment side the same seven
things are needed; they arrive by three doors. Both protocols describe the one
object, the coordinator. The issue observer has a fourth bundle of its own,
which the roadmap already names as residue.

1. **Three bundles for one set of facts.** The instance's identity and handles
   are what every tick-level operation needs, and they are the same for both
   kinds. Accident: one tick-context value, defined once and passed to each
   kind's inspection and launch and to the issue observer, replacing both
   protocols and the observer's bundle. It is a code shape like the state
   directory, not an ontology concept.
2. **The running set belongs to neither kind.** Both launches write into the
   coordinator's dictionary of running rounds. Row 5 says a launch returns what
   it launched, so the coordinator registers it and neither kind needs the
   dictionary to launch. For inspection, the conversation side reads running
   from the records alone: a round with no ending is running. The assignment
   side checks the dictionary as well, because its round describer treats a
   record with no ending as interrupted. Two conventions for one state. The
   daemon records every stale round as interrupted at startup, before the first
   tick, so while a daemon runs a record with no ending is a running round, as
   the record's own outcome says. Accident: one convention for both kinds inside
   a tick, and the dictionary check goes with it. Status, which may run while no
   daemon does, reads such a record as working when a daemon is alive and as
   left behind when none is, and both kinds read it so.

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
   each kind's status module derives its own summary from its record, its
   observation and the shared tick facts, through parallel functions, and the
   reader holds only what both share, the daemon, the latest scheduler record
   and the clock. That is the status counterpart of row 6's tick context.
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

This part gathers what the seven rows point to into one shape for the scheduler
and status packages. Each section gives the shape, then says what it replaces.
The shape changes no scheduling decision, command or prompt. It changes
persisted documents under the v5 break and status wording under the permission
the roadmap gives, and the lists below name every such change. A name given here
is the name the code uses, so a reader can find each piece from this document.

### The context

Rows 6 and 1 point here.

**Today.** The coordinator, `AgentWorkScheduler` in `scheduler/coordinator.py`,
is a dataclass holding the repository, account, config, state directory,
requested harness, clock, the running set and the agent cap. The per-kind
modules get at those fields three ways:

- The conversation functions in `scheduler/conversations.py` take a `scheduler`
  argument typed as `_ConversationScheduler`, a protocol listing seven of the
  coordinator's attributes. The coordinator passes itself.
- The assignment launch in `scheduler/assignments.py` takes a `scheduler`
  argument typed as `_AssignmentRoundScheduler`, a protocol listing two
  attributes, clock and the running set. The assignment inspection takes
  `repository` and `account` as plain parameters instead.
- The issue observer in `scheduler/issues.py` builds its own private bundle,
  `_IssueObservationContext`, from the repository, account, config, the open
  assignments and the incomplete setups.

Both protocols describe the same object. Every operation needs the same six
facts about the instance and this run.

**The shape.** One frozen dataclass, `SchedulerContext`, holds those six facts:
repository, account, config, state directory, requested harness and clock. Every
tick-level operation takes it as its first keyword argument, `context`. Nothing
else carries those facts. The running set is not in it; the next section says
where that goes.

**The edits.**

1. Add `scheduler/context.py` with `SchedulerContext`, a frozen keyword-only
   dataclass of the six fields, and a docstring saying it is what every
   scheduling operation knows about the instance and this run.
2. Give `AgentWorkScheduler` a `context` field in place of the six fields it
   holds today, and have the daemon and CLI build the context when they build
   the scheduler. The agent cap and the running set stay on the coordinator.
3. Change every conversation function that takes `scheduler` to take `context`,
   and read `context.repository` and so on where it read `scheduler.repository`.
   Delete `_ConversationScheduler`.
4. Change the assignment launch to take `context`, and the assignment inspection
   to take `context` in place of `repository` and `account`. Delete
   `_AssignmentRoundScheduler`.
5. Change `observe_issues` to take `context` plus the open assignments and the
   incomplete setups, and pass those three to its helpers in place of the
   bundle. Delete `_IssueObservationContext`.

It is a code shape like the state directory, not an ontology concept, so E3 has
nothing to say.

### The running set and the meaning of "no ending"

Row 6 points here, with row 5.

**Today.** The coordinator keeps a dictionary of running rounds keyed by agent
work identifier. Two things in the per-kind modules touch it:

- Each launch writes into it. `_start_assignment_round` and
  `_start_prepared_conversation_round` both end with
  `scheduler.rounds[identifier] = start_agent_round(...)`.
- The assignment inspection reads it. `_inspect_assignments` in the coordinator
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

**The shape.** The dictionary belongs to the coordinator alone. A launch returns
the `AgentRound` it started and the coordinator registers it. No inspection
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
3. Make each launch return the round instead of writing it into the dictionary.
   Have the coordinator write `self.rounds[identifier] = round` after a launch
   returns. The round has to say which work it belongs to, so give `AgentRound`
   the agent work identifier from its launch request.
4. Delete the coordinator's copy-and-diff of the dictionary that discovers what
   launched, which the launch section covers.

### Listing issues

`list_route_issues`, in `scheduler/issues.py`, lists the open issues assigned to
the account that carry any of the routes it is given, one call per route, merged
by issue number and sorted by creation time then number. A route that fails to
list contributes its failure and the other routes are still listed; the failures
join into one. It returns the issues and the joined failure. The assignment side
calls it with the assignment routes and the conversation side with the
conversation routes. It replaces the two near-copies.

The hold both kinds record for a failed listing has one wording, given in the
list of changed words below.

### Inspecting each kind

Each kind has one tick-level inspection with a parallel name, taking the context
and the tick's facts and returning one bundle:

- `inspect_agent_assignments`, in `scheduler/assignments.py`, takes the open
  assignments, the issue observations and the time the last cooldown ended. It
  walks the open assignment records, as differ 11 requires, skipping any whose
  latest record has no ending, and reads each one's pull request. It also turns
  each available issue observation into a candidate for a new assignment.
- `inspect_issue_conversations`, in `scheduler/conversations.py`, takes the
  saved conversations, the previous tick's conversation observations and the
  time the last cooldown ended. It lists the conversation routes' issues and
  walks the listed eligible issues, as differ 11 requires, finding the record
  for each.

Both return `AgentWorkInspection`, one generic dataclass in
`scheduler/models.py` with four fields: `candidates`, ranked, in the kind's
candidate type; `observations`, in the kind's observation type; `fault_count`,
the faults this kind contributes to the cooldown; and `failure`, the joined
reason the kind's reads failed, or none. Each inspection derives fault once per
item with the shared derivation, withholds a candidate for a faulted item and
counts it, with the conversation side counting only conversations whose issue
has no known routing conflict, as differ 10 says. The coordinator sums the two
counts.

This replaces the three-way assignment result type, the faulted assignment type,
the conversation candidate result, the conversation inspection type, the
conversation fault count in `scheduler/faults.py`, the observation list builder,
and the coordinator's loop over assignments.

The issue observer keeps its own result, the issue observations and their
listing failure, because it observes issues rather than agent work. It now calls
`list_route_issues` and takes the context.

### Candidates

A candidate carries the facts a launch needs and nothing prepared. Each kind's
candidate types follow its ranking list in the ontology, which is differ 9, and
what starts each kind, which is differ 2:

- Assignment: `NewAgentAssignmentCandidate`, the issue, its title and its route,
  built from an available issue observation;
  `FirstAgentAssignmentRoundCandidate`, an assignment whose record has no
  rounds, which is the ontology's rule for finishing an interrupted creation and
  reads no pull request, as today; and `AgentAssignmentRoundCandidate`, an
  assignment with its pull request, its undelivered posts and the reason its
  last round needs recovery, or none.
- Conversation: `IssueConversationBatchCandidate`, an eligible issue with its
  route, its waiting comments and its record if one exists, since a first and a
  later batch are one thing to the ontology; and
  `IssueConversationRecoveryCandidate`, a conversation whose latest round
  errored or was interrupted.

The counts differ, three against two, and the ontology names why: a
conversation's start is a batch and nothing else, and a conversation recovery
reuses its saved input where an assignment recovery reads the pull request
afresh. The ranking functions take parallel names,
`rank_agent_assignment_candidate` and `rank_issue_conversation_candidate`, and
each inspection sorts by its own.

This replaces the required round, which carried a prepared plan and prompt; the
issue observation pressed into service as a candidate; and the coordinator's
lookup of the route by label.

### Observations and the scheduler record

One observation type carries the one fact both kinds share.
`AgentWorkObservation`, in `scheduler/models.py`, holds the agent work
identifier, the issue and `requires_round`, an `IssueFact` whose value is true,
false or unknown with its evidence. The ontology's phrase is "whether an
assignment requires an agent round", and the name follows it. Status reads this
fact one way for both kinds: unknown gives unknown with the evidence, true gives
waiting, false gives the resting status.

`IssueConversationObservation` extends it with the title, because a conversation
is observed before any record holds one, which is differ 7, and with
`routing_conflict`, which differ 8 puts on the conversation and nowhere else.
The assignment observation is the base type itself.

The evidence has one wording for both kinds. A faulted item's observation says
false, "in fault". Work whose round the tick launched says false, "round N
started". Work the tick could not read says unknown with the failure. Work that
needs nothing says false, "no round required". Work that needs a round says true
with the need: the posts or comments to answer, the pull request state, the
round to recover, or that no round has run yet.

The scheduler record keeps its two observation lists, assignment and
conversation, and loses nothing else. Every open work item the tick inspected
has an observation in it, launched or not. The capacity hold no longer rewrites
observation reasons, because status never showed them.

This is the v5 shape of the scheduler record. The assignment observation's
reason, is-known and is-round-required fields go, replaced by the one fact. The
conversation observation's has-comments-to-answer becomes `requires_round` and
gains the identifier.

### Delivery position

The delivery position of either kind is read from its recorded rounds' inputs
and nowhere else. `read_user_post_delivery_cursor`, in `agent_assignments.py`,
returns the newest post among the inputs of recorded rounds, scanning back past
the first and recovery rounds that carry none. It is the counterpart of
`read_issue_comment_delivery_cursor`, which reads the latest recorded input,
since every conversation round carries one. Differ 4 names that difference.

The assignment's cursor file goes, with the function that advanced it, the
callback that recorded a session before advancing it, and the field on the
assignment that read it. The relay takes the position as it does today. This is
the second change the v5 break carries, and the reasoning on the one edge it
touches is under row 5.

### Launching

Each kind has one launch with a parallel name,
`launch_agent_assignment_candidate` and `launch_issue_conversation_candidate`,
taking the context and one candidate and returning the `AgentRound` it started.
A round names the work it belongs to, so the coordinator can register it. A
launch of a new-work candidate creates the record first and starts the first
round in the same call, for both kinds, as the ontology's processes say.

Each launch prepares an `AgentRoundStartRequest`, the type the round boundary
already takes, from the candidate's facts. The two rules both kinds share from
same 3 live once, in `scheduler/models.py`: a later round with no recorded
session cannot resume and raises, naming the work; a recovery with no recorded
session starts a new session with the configured prompt. The conversation launch
keeps its finisher and its narrower permissions, which differ 5 and differ 1
name.

This replaces the two launch functions with different returns, the bare tuple
the assignment side prepared into, the conversation's prepared-round type, the
two copies of the no-session rules with their shared error sentence, and the
coordinator's diff of the running set to discover what launched.

### The tick

The coordinator's tick reads as the architecture lists it. It builds the
context, forgets ended rounds, reads the records, observes issues, inspects each
kind, sums the fault counts and starts a cooldown if required, writes the
record, and then launches. Launching alternates between the kinds as the
ontology says, pops the next candidate of the chosen kind, calls that kind's
launch, registers the round, marks the launched work's observation with one
helper over the base observation type, and appends the identifier to the record.
A launch that raises adds its reason to the hold and clears that kind's
remaining candidates, as today. A full running set with candidates left sets the
capacity hold and nothing else.

The coordinator knows the two kinds' names and nothing of their internals.

### Status

Status takes the same two-level shape: shared facts read once, and each kind
deriving its own summary.

`StatusContext`, in `status/context.py`, holds the state directory, the time,
the daemon's process identifier, the latest scheduler record and the two
observation maps. It replaces the reader, whose per-kind methods move to the
kind's module.

Each kind has one derivation with a parallel name:
`derive_agent_assignment_status`, in `status/assignments.py`, taking the context
and an assignment; and `derive_issue_conversation_status`, in
`status/conversations.py`, taking the context, the issue, the title and the
conversation if one is saved. Each derives in the same order, with the steps a
named difference gives to one kind marked:

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
7. Otherwise the observation's `requires_round` decides: unknown, waiting, or
   the kind's resting status, needs user feedback or idle.

The shared steps come in the same order for both kinds, and each kind's own
steps sit where today's code has them, so no status value changes except where
the list of changed words says.

The two status types keep their fields. Both gain `is_over`, whether nothing
more happens until the user acts, as a property: fault or complete for an
assignment, and fault, routing conflict or not listed for a conversation. The
TUI's constant for ending a view goes, and the TUI reads the property.

`status/rounds.py` holds what both kinds say about a round: the running detail,
the ending detail that fault and recovery share, which round can take a stop
request, and whether a round ended after a time. The conversation summary type
goes, and each kind composes its status directly.

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

| Operation          | Assignment                                           | Conversation                                           |
| ------------------ | ---------------------------------------------------- | ------------------------------------------------------ |
| Inspect for a tick | `inspect_agent_assignments`                          | `inspect_issue_conversations`                          |
| Result             | `AgentWorkInspection`                                | `AgentWorkInspection`                                  |
| Candidates         | three types, by the ranking list                     | two types, by the ranking list                         |
| Rank               | `rank_agent_assignment_candidate`                    | `rank_issue_conversation_candidate`                    |
| Launch             | `launch_agent_assignment_candidate`                  | `launch_issue_conversation_candidate`                  |
| Observation        | `AgentWorkObservation`                               | `IssueConversationObservation`, adds two facts         |
| Delivery position  | `read_user_post_delivery_cursor`                     | `read_issue_comment_delivery_cursor`                   |
| Session identifier | `find_agent_assignment_harness_session_identifier`   | `find_issue_conversation_harness_session_identifier`   |
| Record session     | `record_agent_assignment_harness_session_identifier` | `record_issue_conversation_harness_session_identifier` |
| Retry              | `request_agent_assignment_retry`                     | `request_issue_conversation_retry`                     |
| Status             | `derive_agent_assignment_status`                     | `derive_issue_conversation_status`                     |
| Over               | `is_over`                                            | `is_over`                                              |

The baseline counted twelve symbols for conversations against nine for
assignments in the scheduler. The remeasurement counts these pairs and lists
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

- **A candidate protocol with a launch method**, so the coordinator launches
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
- Row 6, item 2 said a record with no ending means running. It means running
  while a daemon lives, and status, which may run when none does, reads it as
  left behind otherwise. Both kinds use those two readings.
