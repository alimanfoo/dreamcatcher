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
scheduling change, outside this stage's budget.
