# Design for the state format 6 phase

This design answers the brief in `requirements.md` and builds on the reading in
`reading-guide.md`, both in this folder. Read the brief first.

## What we're building

The model is small enough to say in one paragraph, and everything below is that
paragraph worked out.

The agent is a collaborator on GitHub. You ask it for help by putting a dispatch
label on an issue. That label on that issue is a **request**. There are two
kinds of help, and the kind is fixed by the label: a conversation, where the
agent answers you in comments on the issue, and an assignment, where the agent's
answer is a pull request. Once dreamcatcher takes a request on, it creates a
piece of **agent work** for it, and the work has a **channel**, the GitHub
object the agent and you talk through: the issue for a conversation, the pull
request for an assignment. The agent takes a turn whenever something new for it
appears in the channel, and each turn is a **round**. dreamcatcher remembers,
per piece of work, only three things that GitHub cannot tell it: where the
agent's memory is (the harness session), where it works (the worktree), and how
far through the channel the agent has read (the **cursor**). Everything else is
read from GitHub each time it is needed.

That is the whole thing. The rest of this document says how each word in it
works, what has to change in the code to make it so, and what goes away.

### The words, one at a time

A **request** is one dispatch label on one issue. It exists while the label is
on the issue, and it is withdrawn by taking the label off. One issue with two
labels is two requests. A request has at most one live piece of agent work.
Nothing is stored for a request; the scheduler reads the labels fresh each tick,
and the work a request led to is what is stored. A request is new to the
ontology, and it is the name for something every label on an issue has always
meant.

**Agent work** is an assignment or a conversation, as today. Each piece of work
is created from one request and records the issue and the label it came from.
The two kinds differ in exactly two places: which channel they talk through, and
so what counts as new in it, and how they end. Everything else, the tick, the
rounds, the cursor, the fault rule, the status, the storage, is one piece of
code for both.

A **channel** is the pull request for an assignment and the issue for a
conversation. An assignment's channel does not exist until the assignment's
first round opens it, and the assignment exists before that. The brief says
this: once the assignment record exists, the request is actioned and we are
committed, and taking the label off the issue has no effect.

A **round** is one attempt to take a turn in the channel. It holds everything
the attempt does: the preparation before the harness runs, which for an
assignment's first round means making the branch, worktree and pull request; the
harness invocation itself; and whatever has to happen after, such as posting a
conversation's answer. The harness is one step of a round, not the round itself.
A round's record is written when the attempt begins, before any of those steps,
so an attempt that fails in its preparation is a round that errored, the same as
one whose harness crashed.

A **signal** is something new in the channel that calls for a turn. For a
conversation there is one kind: a comment by you, after the cursor. For an
assignment there are four: a post by you after the cursor; the pull request
being ready for review and behind or conflicting with main at a head commit the
agent has not been told about; a finished check having failed at a head the
agent has not been told about; and the pull request having been merged or closed
without the agent having had its final turn.

The **cursor** is what the agent has been shown of the channel. It is not a file
of its own. It is read from the input of the latest round that finished, where
finished means ended successful or stopped. For a conversation that is the
newest comment delivered. For an assignment it is the newest post delivered, the
head at which "behind or conflicting" was last relayed, the head at which a
check failure was last relayed, and whether a round has been given the merged or
closed state. Anything past the cursor is new. A round that errored or was
interrupted did not finish, so what it was given is still past the cursor and is
given again. That is what recovery means here, and it needs no flag and no
separate path.

## How it works

### One assignment, start to finish

Here is one real case walked through, so that each part below can be placed in
the whole.

You label issue 20, "Add CSV export", with `dream:smith`, an assignment label,
and assign the issue to yourself.

The next tick lists the issues under each route and finds a request: issue 20,
`dream:smith`. No live work names that request, so the tick asks the two
start-time questions through GitHub: does an open pull request already claim
issue 20, and does an open issue block it? Neither, so the request is a
candidate to start. There is capacity, so the tick writes the assignment's
record, `work/GH20-20261017-091500-assignment/work.json`, naming the issue, the
label, the kind, the title, and the harness settings the route's recipe gives.
From this moment the assignment exists, and the label no longer matters to it.

The tick then starts round one. It writes `rounds/1/round.json` with the number
and start time and no process id, because nothing has been spawned yet. Round
one's preparation runs: fetch main, add the worktree on a new branch, make the
empty commit, push, open the draft pull request with "Closes #20", and write
`pull-request-observation.json` with the pull request's number, which is the
only thing that file ever holds. Each step does nothing if its result already
exists. Then the round writes its prompt, the recipe's first-round prompt,
spawns the harness with the prompt on stdin, writes the process id into the
round record, and from then on behaves as a round does today. The agent
implements the issue, pushes, marks the pull request ready, and ends its turn.
The round records a successful ending.

Next tick. The assignment is live and has a channel, so the tick reads the pull
request once, asking for its state, draft flag, mergeable state, head commit and
checks, and reads its posts. The cursor says no posts have been delivered and no
signal has been relayed. The pull request is ready, mergeable, green and has no
posts from you, so nothing is past the cursor. The row for this request in
`scheduler.json` says: live work `GH20-...-assignment`, pull request #88, ready,
nothing new. The home page shows the assignment as idle, "ready for review",
reading the pull request's state from the row.

You review and request changes. Next tick, the posts read returns your review,
which is after the cursor. That is a signal. The tick starts round two: its
input file holds the pull request state, your posts, the current head, and no
relayed signals; its prompt is the user-posts prompt naming the file. The agent
addresses the review and pushes. Round two ends successful. The cursor has moved
past your review.

Meanwhile someone merges another pull request into main, and the repository
requires branches to be up to date before merging. Next tick, the pull request
read says the pull request is behind main, at head commit B, and the cursor says
"behind or conflicting" has never been relayed. That is a signal. Round three's
input records head B and that it relayed "out of date"; its prompt is the
user-posts prompt with one extra line saying the pull request is behind or
conflicts with its base and the agent should merge main in, resolve anything,
and push. The agent does, and pushes head C. Round three ends successful.

Next tick, the checks at head C are still running. Nothing is past the cursor:
no post, no finished failed check, and "out of date" was relayed at head B and
the pull request is now mergeable anyway. The row says idle, "checks running". A
tick later the checks finish red. That is a check failure at head C, which the
cursor has never seen. Round four is woken for it, with the prompt saying the
checks failed, the agent fixes the test and pushes head D. If D comes back red
too, that is a second consecutive check-failure signal at a new head, and the
relay rule declines to wake the agent a third time: the row says idle, "checks
failing after two attempts", and the next thing that wakes the assignment is a
post from you.

D is green. You merge. Next tick, the pull request read says merged, and the
cursor says no round has been given a non-open state. That is the final-turn
signal. Round five's input says `MERGED`, its prompt is the same user-posts
prompt, and the agent winds up as its skill says. When the harness exits
successfully, the round's finishing step sees that its input carried a non-open
state and writes `ended.json` with the reason "completed". The assignment is no
longer live. The next tick does not read its pull request, and the home page
shows it under the ended fold.

Had round one failed at the push, say because a commit hook refused the empty
commit, the round would have recorded an errored ending with the hook's output
as the reason, and no process id. The next tick finds an assignment whose last
round did not finish, so round two runs the same preparation again, finds the
worktree and commit already there, and tries the push again. A second failure
puts the assignment in fault, the row says so with the reason, and you retry or
cancel it. Nothing about that is a special path.

### The tick

The scheduler runs one tick per interval, as today, and the tick has one shape
for both kinds of work.

First, it reads every piece of agent work from disk, and lists the open issues
assigned to you under each route's label, one `gh issue list` per route as
today. A listing that fails is recorded as a scheduler failure and means no new
work starts for that route this tick, but live work is still inspected, because
live work is found on disk, not in the listing.

Second, it builds the set of requests. A request comes from two sources: each
route label on each listed issue, and each live piece of work, which names its
own issue and label. The second source is what lets a conversation whose label
has been removed still appear, as paused, and what lets an assignment be
inspected whatever its labels now say.

Third, for each request with live work, it inspects the work's channel. A
conversation reads its issue first; one whose label is not on the issue, whose
issue is no longer assigned to you, or whose issue carries a second conversation
label, is paused, and its comments are not read. For everything else:

- An assignment whose pull request exists: one `gh pr view` for the state, draft
  flag, mergeable state, head commit and checks, and the posts read as today.
  Nothing is written to the assignment's directory; the request row carries what
  the views need.
- An assignment whose pull request does not exist yet, because round one has not
  finished: nothing is read. Round one is due unless it is running or the
  assignment is in fault.
- A conversation: one read of the issue itself, for its state, labels and
  assignees, and one paged read of its comments, as today. The issue read is
  what tells a closed issue from a removed label or an unassigned issue, and it
  means a live conversation does not depend on the listing at all. A failed
  listing therefore affects only new requests, and the path that carried
  observations across a failed listing has nothing to carry.

From what it read and the cursor, the tick works out the signals. If the last
round is running, there is no candidate. If the work is in fault, there is no
candidate. Otherwise a candidate exists when there is at least one signal, or
when the last round did not finish.

Fourth, for each request with no live work, it decides whether to start some. If
the issue already has live work of the same kind, from another label, or carries
another label of the same kind, nothing starts: at most one piece of work of
each kind is live on an issue, and that is checked from the request rows,
locally, before anything is read. For an assignment label, the tick asks GitHub
the two start-time questions, open linked pull requests and open blockers, and
starts only when both come back empty. For a conversation label, it reads the
comments and starts only when there is at least one comment by you. These are
the only reads made for an issue that has no work, and they are never made for
an issue that has.

Fifth, it ranks and launches. Candidates for existing work come before new
requests, and within each the order is identifier order for existing work and
listing order for new. The tick alternates between kinds when both have
candidates, as today. A global cooldown is started when two pieces of work are
in fault, and nothing launches while one is active, as today. A launch that
fails is a round that errored, and the tick goes on to the next candidate.

Sixth, it writes the scheduler record: one row per request, the cooldown, the
listing failures, and the identifiers it launched.

### What a round does

A round is started by the tick, for one piece of work, with the signals the tick
found. Its steps, in order:

1. Write the round record: number and start time. No process id yet.
2. Prepare the channel. The kind supplies this step as a callback, in the same
   shape as the finisher, so the round module stays clear of Git and GitHub and
   the kind's own module owns what the step writes. For an assignment whose pull
   request observation does not exist yet, which is what "the channel does not
   exist" means on disk: fetch main, add the worktree on the assignment's
   branch, make the empty commit, push, find or create the draft pull request on
   that branch, and write the pull request observation, which holds the pull
   request's number and nothing else. A pull request found on the assignment's
   own branch is adopted whatever its state. Round one looks at no other pull
   request: the start-time question already asked whether one claims the issue,
   and once the assignment exists its issue is ignored. For every conversation
   round: fetch main and reset the detached worktree to it, adding the worktree
   if it is missing, as today's refresh does. For an assignment whose pull
   request exists: nothing. Each step does nothing when its result already
   exists, so a round that follows a failed one re-runs the step and finds most
   of it done.
3. Write the input file, when there is anything to deliver, and the prompt. The
   prompt depends on whether there is a harness session to resume, not on the
   round number. With no session, the round starts a new one with the recipe's
   first prompt, which for a conversation is the instructions followed by the
   input prompt naming the file, and for an assignment is the recipe prompt
   alone, followed by the input prompt when there is an input. A conversation's
   input includes the issue title and body when there is no session, since a new
   session has not seen them. With a session, the prompt is the input prompt for
   its kind, naming the file. In either case one line is prefixed per
   circumstance: the previous round was stopped by you; the previous round did
   not finish; the pull request is behind or conflicts with main; the checks
   failed.
4. Spawn the harness, resuming the recorded session when there is one and
   starting a new one otherwise, and write the process id into the round record.
   From here the round runs on its own threads exactly as today.
5. Finish. When the harness exits successfully, a conversation round posts the
   answer, and an assignment round whose input carried a merged or closed state
   writes `ended.json` with the reason "completed". A finishing step that fails
   makes the round errored with a reason, as today.
6. Record the ending: successful, errored, interrupted or stopped, as today.

A failure in step 2 or 3 records an errored ending with the reason and no
process id, and that is the whole of what "a launch failed" now means. An
errored ending therefore carries an exit status only when a process ran, and the
views word a round that never ran as "errored: reason" without an exit status.
The daemon's startup sweep, which ends the process tree of every round left
without an ending, skips the kill for a record with no process id and still
records the interruption.

### The cursor and the signals, exactly

Each round's input records what it delivered. For an assignment the input holds
the pull request state, the posts delivered, the head commit at the time, and
the list of signals relayed, which can include "out of date" and "check
failure". For a conversation it holds the comments delivered and the revision,
as today.

The cursor is read from the latest round whose ending is successful or stopped.
A round that errored or was interrupted does not advance it. So:

- The delivery position for posts or comments is the newest one in that round's
  input, or the newest in the latest finished input that held any.
- The head at which "out of date" was last relayed is the head recorded by the
  latest finished round whose input relayed it, and likewise for "check
  failure".
- The final turn has been taken when the latest finished round's input carried a
  non-open pull request state.

Given the current channel facts, the signals are:

- Posts after the delivery position. Comments after it, for a conversation.
- Out of date: the pull request is open, not a draft, its merge state is behind
  or dirty, and its head differs from the head at which "out of date" was last
  relayed. A draft is left alone because the agent has not finished.
- Check failure: the pull request is open, not a draft, a finished check at the
  current head has failed, its head differs from the head at which "check
  failure" was last relayed, and the relay rule below allows it.
- Final turn: the pull request is merged or closed and the final turn has not
  been taken.

The relay rule for check failures is what stops an agent that keeps pushing red.
A check failure is not relayed when the last two rounds both relayed a check
failure. A round woken by anything else, a post or a merge, breaks the run. So
the agent gets two attempts at a red build on its own, and then waits for you.
The row says why, and a post from you wakes it again. This is a rule about what
to relay, not a new kind of failure, so the fault rule, the cooldown and the
retry are untouched by it.

A stopped round counts as finished, so what it was given is not given again, and
the next round's prompt says you stopped the previous one. That is today's
behaviour for both kinds.

### Faults

The fault rule does not change. A piece of work is in fault when its last two
rounds both ended errored, and both endings are at or after the later of your
last retry request and the end of the last global cooldown. A retry writes a
timestamp and nothing else. A piece of work in fault starts no round. Two pieces
of work in fault start a global cooldown. All as today.

What changes is only what can be an errored round: now also a first round that
failed to make its channel, and a conversation round that could not refresh its
worktree. Those used to be launch failures recorded on the scheduler, and now
they are rounds, so the fault rule covers them with no new clause.

### Ending, cancelling and pausing

A piece of work is live until `ended.json` exists in its directory. The file
holds the time and the reason. Three things write it:

- An assignment's final round, in its finishing step, with the reason
  "completed", when its input carried a merged or closed state and the harness
  exited successfully.
- The tick, with the reason "issue closed", when it reads a conversation's issue
  and finds it closed.
- The `cancel` command and the web cancel control, with the reason "cancelled",
  for an assignment, after asking any running round to stop, as the cancel does
  today.

Ended work is not inspected and its channel is not read. It shows under the
ended fold on the home page and in the terminal count, for both kinds. An ended
assignment's request, if the label is still on the issue, is a request with no
live work again, and the start-time questions decide whether a new assignment
starts. Nothing can tell a label that stayed on from one that was taken off and
put back, so the label is a standing request, and if you do not want the agent
back you take it off.

A conversation is paused while its label is off the issue or the issue carries a
second conversation label. Paused is derived, not written: the tick reads a live
conversation's issue, finds the label gone, the issue unassigned, or a second
conversation label on it, and leaves the conversation alone. Put the label back,
or remove the second one, and the next tick inspects it as before and it carries
on in the same harness session. The issue read that every live conversation
makes each tick is what tells the cases apart: a closed issue ends it, a removed
label or an unassigned issue leaves it paused.

An assignment does not pause. Once its record exists, its labels are not
consulted again.

### Storage

Under `.dreamcatcher/v6/`:

```text
daemon.json          process id, harness, version, capacity, interval, and now
                     the routes: each label and its kind
repository
scheduler.json       one row per request, the cooldown, listing failures,
                     launched identifiers
work/<identifier>/
    work.json        issue, label, kind, title, harness, model, effort,
                     harness config, prompt; branch for an assignment
    pull-request-observation.json
                     assignment only, written once by round one: the pull
                     request's number
    harness-session.json
    retry-request.json
    ended.json       time and reason, once ended
    rounds/<n>/      round.json, prompt.txt, round-input.json, raw.jsonl,
                     feed.txt, final.md, stop-request, as today
worktrees/<identifier>/
```

The identifier is `GH<n>-<timestamp>-<kind>` for both kinds, as in
`GH20-20261017-091500-assignment` or `GH15-20261017-093000-conversation`. The
kind is in the name for the person reading a directory listing, a daemon line or
a web address, and the record says it too, as the issue number is in both today;
nothing cross-checks them. The assignment's branch carries the same name after
its prefix. Two collections replace four, one record name replaces two, and
`cancel.json` is absorbed into `ended.json`. Nothing under `rounds/` changes
except that `round.json` loses its purpose and recovery fields and its process
id becomes absent until the harness is spawned, and `round-input.json` for an
assignment gains the head commit and the relayed signals.

The purpose of a round, implement, address feedback, wrap up or discuss, and
whether it followed a round that did not finish, are worked out where they are
shown, from the round's input and the previous round's ending, rather than
stored. The feed's round boundary line and the views print the same words as
today from that derivation.

### The scheduler record

One row per request the tick saw, from either source. A row holds the issue
number, its title, the label, the kind, and the identifier of the live work if
any. Beside that it holds what the tick found, as typed values:

- For live work with a channel: what was new, as the count of posts or comments
  and the list of signals; the number of the round the tick started for it, when
  it started one; and the channel facts the views need, the pull request number,
  state, draft flag, mergeable state, head and check result for an assignment.
- For a paused conversation: that it is paused, and why: label removed, or the
  conflicting labels.
- For a request with no work: why nothing started: the open linked pull
  requests, the open blocking issues, the conflicting labels, or that no comment
  is waiting; or that it was started this tick.
- For any read that failed: the failure reason, in place of the facts it would
  have given.

No row holds a sentence meant for a person. The terminal and web views compose
their words from the values, so the two can share one row type and nothing
parses text to recover a number.

### Status

There is one status derivation for both kinds of work, in this order:

1. Ended, when `ended.json` exists, with its reason. An ended assignment's pull
   request state is the one its last round's input carried.
2. Working, when the last round has no ending and the daemon is running.
3. Fault, when the fault rule says so.
4. Unknown, when there is no scheduler record, or the row's read failed.
5. Waiting, when the row found a signal and the round it started, if any, has
   ended since the tick, so the next tick has not yet looked; or the last round
   did not finish, which includes a round with no ending while no daemon runs;
   or no round has run yet.
6. Idle, otherwise, with a detail from the row: ready for review, answered,
   checks running, checks failing after two attempts, conflicts with main,
   paused because the label was removed, paused by a routing conflict.

That is the chain both of today's readers compute, in one place. The words
"needs user feedback" and "routing conflict" go as status values; the first
becomes idle with "ready for review", the second becomes either a paused
conversation's idle detail or a request row's reason.

A request with no live work is a row of its own on the home page and in the
terminal, with its reason: blocked by these issues, claimed by these pull
requests, conflicting labels, waiting for a comment. The views link the issue
and pull request numbers because they have them as numbers.

### The daemon record and the views

The daemon writes the routes it loaded into its run record at startup. The
status report reads the labels from there for its "label an issue with X"
guidance and never opens `dreamcatcher.toml`. A broken or missing file fails the
daemon at its next start and leaves the views showing what the last daemon
recorded.

The web page for any piece of work is `/work/<identifier>`. The home page is one
row per request plus the ended fold. The commands take `GH<n>`, meaning the
newest work at that issue of the selected kind, as today, and the kind selector
stays on the commands that have it. The conversation page and command lose
nothing but their issue-number key.

### The agent's side

The assignment input file gains two keys, the head commit and the relayed
signals, which an assignment skill may ignore. The prompt gains two possible
lines, for out of date and for check failures, in the same place the stopped
line goes. The contract page documents the keys and the lines. An agent asked to
fix a red build has to read the check output, so the assignment harness
permissions gain the gh commands that read checks and runs; today Claude's
assignment allow list has neither.

## What changes, and what goes away

What goes, and what each deletion buys.

- The leftover-setup path: `_find_incomplete_assignment_identifiers`,
  `_find_incomplete_assignment`, `inspect_incomplete_assignment_setups`,
  `_inspect_incomplete_assignment_setup`, `_check_worktree_branch`,
  `validate_assignment_pull_request_setup`, `_adopt_pull_request`, the
  `incomplete_setups` argument through `observe_issues`, the setup cases in
  `_observe_external_claim`, `IssueObservation.setup_failure`, the failed-setups
  section in the report, the terminal and the web, and its template partial. It
  buys the absence of a second way for an assignment to exist, and two or three
  GitHub reads per leftover per tick.
- `IssueObservation`, `ObservedIssueDetails`, `ObservedFact`, `Truth`,
  `derive_issue_availability`, `_find_preventing_fact`, `observe_claimed_here`
  and the whole of `scheduler/issues.py` as it stands. Replaced by the request
  row and the start-time questions. It buys one shape for what the tick records,
  three or four GitHub reads per open assignment per tick, and the end of
  sentences parsed for numbers, which closes #457.
- `ConversationObservation`, `AgentWorkObservation`, `mark_round_started`,
  `_carry_forward_unlisted_observations` and
  `_count_carried_conversation_faults`. Replaced by the request row, which
  exists only for work that exists or a request that does not. It buys the end
  of a conversation being observed before it exists, and of a second path across
  a failed listing.
- The two inspect paths, the five candidate types, and the two rank functions in
  `scheduler/assignments.py` and `scheduler/conversations.py`. Replaced by one
  inspect over requests and one candidate type, which carries the work and its
  signals or the request to start. It buys the symmetry the standard asks for
  and halves the scheduler.
- `AssignmentCreator.create` as a thing the scheduler calls before a round. Its
  body becomes round one's preparation, without the refusal of a linked pull
  request on another branch, which the start-time question already covers. It
  buys record-first and one conditional.
- `record_pull_request_observation` and the state, draft flag and time in
  `PullRequestObservation`. The observation holds the number, written once. It
  buys one write per state change per assignment per tick and one fewer place
  the pull request's state is stored.
- The round record's purpose and recovery fields, `AssignmentRoundPurpose`,
  `ConversationRoundPurpose`, `AgentRoundPlan.is_recovery`,
  `derive_round_purpose`, `ASSIGNMENT_RECOVERY_PROMPT` and
  `CONVERSATION_RECOVERY_PROMPT` as separate prompts. The words are derived
  where shown, and the did-not-finish line joins the stopped line as a prefix.
  It buys two fewer stored facts that had to agree with facts stored elsewhere,
  and the end of recovery as a path.
- `is_awaiting_recovery` as a scheduler rule. "The last round did not finish" is
  one of the things that make a candidate, read from the ending.
- `cancel.json` and `Assignment.is_complete`, `ended_at` and `is_open` as
  derivations over rounds. Replaced by `ended.json` and one rule: live until
  ended. It buys one way for work of either kind to end, and ended conversations
  in the views.
- `compose_conversation_identifier`, `read_conversation` by issue, the
  `conversations/` and `conversation-worktrees/` collections, the
  `/conversations/<issue>` routes, and the check that a conversation's directory
  name matches its issue. It buys the label in the key, which closes #393.
- The two status readers' chains and the `ROUTING_CONFLICT` and
  `NEEDS_USER_FEEDBACK` values. Replaced by one chain. The issue-row logic in
  `tui/status.py` and `web/views.py`, including `_ISSUE_REFERENCE_PATTERN`.
  Replaced by rendering the request row.
- The status report's read of `dreamcatcher.toml`. Replaced by the routes in the
  daemon record, which closes #483.
- `AgentWorkScheduler.resolve_harness_session` as a separate decision. A round
  resumes the recorded session when there is one and starts afresh otherwise;
  the case it refused, a non-recovery round with no session, cannot arise when a
  round that did not finish is simply re-delivered.

What changes but stays:

- `github.py`: the pull request read asks for the mergeable state, head and
  checks as well, and the projection grows to hold them. Everything else in it
  stays.
- `agent_rounds.py`: the round record is written before preparation, the process
  id is written after spawn, and a preparation step runs between. The threads,
  the streams, the stop watcher, the finisher and the endings stay.
- `agent_assignments.py` and `issue_conversations.py` shrink to the parts of the
  work record and channel each kind owns, and the shared parts move to
  `agent_work.py`, which already holds the session and retry records.
- `relay.py` grows from posts to all four assignment signals, or a sibling does
  the same for the issue channel; either way one module answers "what is past
  the cursor" for a channel.
- `prompts.py` gains two lines and loses two prompts.
- `daemon_runs.py` gains the routes. `daemon.py` writes them.
- `status/`: one reader, one status type, one row type for requests.
- `tui/` and `web/`: one row renderer each, one work page each, and ended
  conversations shown.
- `cli.py`: `retry`, `stop`, `cancel`, `assignment`, `conversation` and `feed`
  find work by issue and kind as today; nothing user-visible changes except that
  a conversation's page address carries an identifier.
- `docs/ontology.md`, `docs/architecture.md` and `docs/contract.md` change to
  say the above: request, channel, cursor, signal and the new meaning of a
  round, and the removal of issue observation, routing conflict as a status,
  recovery round, and incomplete setup.

## Why it's this and not something else

Two kinds of work with a shared key, rather than one kind with a channel, was
the smaller change and was dropped because it keeps two inspect paths and two
status chains that differ only in words, and every issue in the batch is a
symptom of that doubling.

A failure recorded against the work as a thing of its own, rather than as a
round that errored before its process started, was dropped because it adds a
record and a rule where loosening the round record's process id adds neither.

A fault clause for the agent that keeps pushing red was replaced by a relay
rule, because the natural way out of a red loop is a post from you rather than a
retry, and because a red build is not evidence of a shared harness problem and
should not start a cooldown.

Keeping assignment completion derived from rounds, rather than writing
`ended.json`, was dropped because a conversation's end is a GitHub fact that has
to be written down anyway, and one way to end is simpler than two.

Reading the two start-time facts for every issue every tick, to keep one
observation shape, was dropped because those facts decide only whether work may
start, and the brief now says an assignment's issue needs no further
observation.

Ending a conversation when its label is removed, rather than pausing it, would
have avoided the paused state and the per-conversation issue read, and was
dropped because the brief says a conversation resumes where it left off.

## What's still open

1. The contract version. The input file's two new keys are additive and the
   prompt's two new lines are instructions in words, so a version 1 skill still
   works. Whether to call that version 2 is a documentation decision.
2. The assignment harness permissions need the commands that read check output.
   Which ones, for Claude and for Codex, is for the build.
3. Issues #550, #551 and #425 need amending to match the brief and this design,
   and #455, #393 and #457 should close in favour of them.
4. Whether an errored round counts towards the two-round relay limit is for the
   build. How `gh pr view --json statusCheckRollup` reports checks was checked
   on this repository: each entry is a `CheckRun` with a `status` of `COMPLETED`
   or `IN_PROGRESS` and a `conclusion` that is `SUCCESS` when done and empty
   while running, or an older status context reporting a `state`. A finished
   check has failed when its status is completed and its conclusion is anything
   but success, neutral or skipped. While required checks run the merge state is
   `BLOCKED`, so "out of date" tests for `BEHIND` and `DIRTY` only, and a merged
   pull request reports `UNKNOWN`.
