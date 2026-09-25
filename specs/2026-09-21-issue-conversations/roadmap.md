# Roadmap: issue conversations

Every session that implements a stage should correct the specifications as
details change and say on its pull request what it corrected. It may change how
it delivers the stage when earlier work or implementation discoveries justify
that change. It should raise any change to the roadmap's stages, boundaries,
order or dependencies with the user instead of restructuring the roadmap itself.

The design was revised after stage 3 landed. Read the
[revision after stage 3](#revision-after-stage-3) before working on stage 4
or 5.

## Stage 1: A visible first answer with Claude

**Delivery.** Post a question, add the conversation label, and assign the issue
to yourself. Dreamcatcher runs the first round of an issue conversation with
Claude and publishes its final answer on that issue. This stage delivers the
initial exchange described in `design.md`, not a preliminary refactor or a
separate demonstration command.

This stage starts after the web UI work under
[GH153](https://github.com/alimanfoo/dreamcatcher/issues/153) has landed. Read
the landed implementation before changing either presentation. The issue
conversation reading guide describes the earlier code; it is a navigation aid,
not a substitute for checking what the web UI work changed.

Add the separate conversation configuration and discover open labelled issues
assigned to the signed-in account. Read the issue title and body plus ordinary
issue comments, filtering other authors and marked agent comments before writing
agent input. The label and assignment enable watching, not an agent round. Only
start the first round when at least one eligible, undelivered comment exists;
otherwise wait. Freeze the eligible existing history as the initial batch. The
issue title and body alone do not trigger a round. Do not apply assignment
ownership, PR, dependency or dispatch-conflict gates.

Create one conversation record and a detached worktree in a namespace excluded
from assignment discovery. Fetch main for this initial round and record its
revision. Retain the chosen settings, saved input, session identifier, round
outcome and final answer. Keep enough delivery state for stage two to continue
without resending the initial batch. Respect the existing shared agent cap and
active global cooldown, but leave fair selection between the two workflows to
stage two.

Provide the issue conversation contract and prompts, with the practical
conversation permissions in the design. Claude returns final Markdown or
`NO_REPLY`. Capture the final result separately from progress output and wait
for capture to finish before publication. Dreamcatcher saves the answer, appends
its marker, posts it, and records that it was posted. On later ordinary ticks, a
saved unposted answer is tried again without another agent invocation. This is
part of publishing, not a separate retry service or roadmap stage. Accept the
design's rare duplicate after an uncertain post outcome.

An initial exchange is not repeated merely because the issue remains eligible.
Agent failures and interruptions are recorded and visible, but are not
automatically resumed in this stage. Keep normal process containment and daemon
shutdown/startup cleanup; deferring recovery must not leave orphan processes
running. Do not create implementation branches, commits or pull requests.

Deliver visibility with the feature. `dreamcatcher status` includes
conversations; `dreamcatcher conversation GH123` shows the chosen settings,
session ID, worktree, code revision and round outcome; and
`dreamcatcher feed GH123 --conversation` follows its activity. Add the explicit
`--assignment` alternative to the feed command and require exactly one owner
selector. The web home page shows a conversation entry linking to a page with
the same detail and live feed. Both UIs read the shared local status/feed data,
work when the daemon is stopped, and do not contact GitHub. Show the initial
round's finished state without pretending follow-ups are supported yet.

**Change surface.** Extend configuration and GitHub projections/readers in
`config.py` and `github.py`; introduce conversation-owned records and operations
alongside, not inside, `agent_assignments.py`. Add paths in `state.py` and
detached-worktree preparation in `git.py`. Adapt `agent_rounds.py`,
`harness_adapters.py`, `claude.py` and prompt composition only as needed by this
real second caller. Wire its initial candidate into `scheduler.py` and process
cleanup into `daemon.py`. Extend the shared status/feed models, `cli.py`,
`tui.py`, and the landed `web.py` routes/templates. Update the public contract,
ontology, architecture and command documentation. No broad workflow framework or
unrelated assignment refactor is called for.

**Acceptance test.** In a test repository, configure Claude conversations and
run the daemon. Post a straightforward code question on a fresh issue, assign
yourself and add the conversation label. Watch that conversation start in both
the terminal status view and web overview. Open its terminal detail/feed and web
conversation page: both should show the same session and revision, with the
agent's activity arriving live. One answer appears on GitHub, both UIs show that
the round finished, and no implementation PR is created. Leave the daemon
running through another tick: there is no second round or duplicate answer.

**Automated proof.** Cover eligibility and independence from assignment gates,
author/marker filtering, no launch without eligible comments, namespace
separation, initial worktree revision, final-result readiness, `NO_REPLY`,
missing or failed results, and completion without repeated launch. Exercise a
failed post followed by success and prove the harness runs only once. Cover
ordinary process cleanup without resumption, both owner selectors, and both
presentations from the same fabricated states, including a failed initial
attempt and pending publication. Existing assignment behaviour remains covered
by its regression tests.

**Deferral.** Follow-up batches and session resumption; refreshing main after
the initial round; automatic recovery, fault counting and conversation manual
retry; fair admission between workflows; Codex conversations. Existing Codex
assignments still work. Until stage five, selecting Codex for a new conversation
must report that it is unsupported, not silently choose another harness.

## Stage 2: Follow-up questions in the same session

**Delivery.** A newly posted comment starts another round in the existing Claude
session. Batch all currently waiting eligible comments, with at most one round
running per conversation. Comments arriving during a round wait for the next
batch. Do not accept another batch while the preceding answer is unposted.

Use the design's creation-time-and-ID delivery cursor and ignore edits to
delivered comments. Supply issue title/body to the first batch; resumed rounds
retain them in the harness transcript and receive only new comments. Do not make
an issue-body edit alone a trigger. Marker filtering prevents answers from
triggering new rounds. Never refresh the worktree in this stage: follow-ups use
its initial revision until stage three.

Closing the issue, removing its label, or unassigning the user stops new comment
collection, not a round already started. Preserve its records and session.
Rediscovery after eligibility returns supplies comments posted during
inactivity. Do not poll inactive issues' comments or treat another workflow's
ownership as a conversation gate. An interrupted or failed batch remains held
for stage four's recovery rather than being overtaken by new input.

Add fair admission at the point that selects a new agent round: alternate
conversation and implementation candidates when both are ready, keeping each
workflow's internal selection rules and the shared cap. Conversation batches use
oldest waiting input first, for initial and later batches alike. Issues without
eligible, undelivered comments are not candidates for new batches. No durable
scheduling queue is added.

Both UIs show further rounds in the existing conversation and keep the session
identity visible. Feeds retain earlier output and follow across idle gaps. An
inactive conversation remains inspectable; it is not a completed assignment.

**Change surface.** Extend conversation batch selection, delivery persistence
and prompt composition from stage one. Use resumed launch through the shared
round boundary and Claude adapter. Extend the scheduler's conversation candidate
selection and shared admission decision. Extend status/detail/feed projections
and the two presenters for waiting and inactive conversations and subsequent
rounds; the routes, commands and feed infrastructure already exist.

**Acceptance test.** After stage one's answer, post a follow-up referring to it,
such as asking what evidence supports the explanation. Both overview UIs show
another round on the existing conversation. The terminal and web detail views
show two rounds with the same harness session ID; their feeds retain the first
round and append the second. GitHub receives a contextual follow-up answer,
without repeating the original response.

**Automated proof.** Cover comments queued during a round, cursor ties,
non-redelivery, comment edits, agent markers, no concurrent rounds for one
conversation, and pending publication blocking new input. Cover each loss of
eligibility and rediscovery with undelivered comments, without polling inactive
comments. Verify fair admission, the shared cap, and unchanged assignment
selection within its own candidates. Both presentations follow multiple rounds
without duplicating feed lines.

**Deferral.** Updated main between batches; recovery and conversation
fault/retry handling; Codex conversations.

**Dependency.** Stage one supplies the saved session, initial delivery position,
round runner, publisher and presentation surfaces this stage continues.

## Stage 3: Follow changes on main

**Delivery.** Before a new batch, fetch main and update the idle conversation
worktree to that revision. Record the revision with the batch. The resumed
transcript already holds the revision from earlier rounds. Keep the session;
replace neither its transcript nor its identity. A running round's checkout does
not move.

Discard tracked, untracked and ignored local changes before moving to fetched
main rather than asking the user to repair a managed worktree. Show the
investigated revision for each round in both detail views and identify revision
changes in the feed.

**Change surface.** Extend `git.py` with safe detached-worktree refresh and call
it from conversation preparation before accepting a new batch. Extend the round
input with current revision context. Add the corresponding shared reporting
facts and small terminal/web presentation changes. No change to comment routing
or assignment worktree handling is needed.

**Acceptance test.** Ask about a small function in the test repository, merge a
change to that function on main, then ask the same conversation, "Does your
answer still hold?" Both overview UIs show another round. Both detail views
retain the session ID and show the new round's changed revision; the feed names
the previous and current revisions and shows investigation of the change. The
GitHub answer reflects the new behaviour and explains its effect on the earlier
answer.

**Automated proof.** Cover changed and unchanged main, fetch/update failure,
cleanup of tracked, untracked and ignored local changes, and no refresh while a
round runs. Verify that the saved input and both presentations report the exact
revision investigated, not a later moving remote ref.

**Deferral.** Recovering interrupted or failed work; conversation fault/retry
handling; Codex conversations.

**Dependency.** Stage two supplies the successful follow-up path to prepare
against a newer revision.

## Revision after stage 3

On 2026-09-24, after stage 3 landed, we paused and revised the design before
starting stage 4. Testing the delivered stages showed that the conversation path
had grown its own versions of things the assignment path already does, and that
they made a conversation harder to follow than an assignment. The revision
brings conversations back in line with assignments wherever a conversation has
no need to differ.

Stages 1 to 3 are left as they were written. They record what those stages set
out to do, and parts of them no longer describe the design. Where one of them
disagrees with `design.md`, `requirements.md` or stages 4 and 5, the later text
wins. Stages 4 and 5 were rewritten in this revision, and `design.md` and
`requirements.md` were corrected to match. So there is a deliberate break
between stages 3 and 4: stage 4 does not build on everything stages 1 to 3
describe.

The revision changes four things:

- **The round posts its own answer.** A conversation round posts its final
  answer when it ends, and a failed post makes the round errored. There is no
  saved reply, no retry of the post on later ticks and no awaiting-publication
  status. [GH250](https://github.com/alimanfoo/dreamcatcher/issues/250) makes
  this change.
- **Conversation statuses match assignment statuses.** A conversation is
  working, waiting, idle, fault or unknown, and appears as soon as its issue is
  eligible. Once the issue is ineligible, it appears only while a round is
  running. [GH254](https://github.com/alimanfoo/dreamcatcher/issues/254) makes
  this change.
- **Recovery, faults, retry and the cooldown follow the assignment rules.** A
  failure before a round's process starts goes into the scheduler hold, as it
  does for an assignment, rather than counting as an errored attempt. An
  unfinished round recovers only while the issue is eligible, as an assignment
  recovers only while its pull request is open. `dreamcatcher retry GH123`
  clears whatever is in fault at the issue. Stage 4 makes this change.
- **The conversation config has a block per harness,** as a dispatch route does,
  and the daemon's `--harness` chooses between them by the same rule. Stage 5
  makes this change.

GH250 and GH254 are not roadmap stages. They land in that order before stage 4,
and stage 4 depends on both.

## Stage 4: Continue interrupted work

_Rewritten in the [revision after stage 3](#revision-after-stage-3). Read that
section first._

**Delivery.** Resume an interrupted or errored conversation round in its
existing session, with that round's saved input and code revision, as an
assignment recovers its unfinished round. Do not fetch main, collect a new batch
or reconstruct earlier replies to recover. Recovery takes precedence over fresh
input for that conversation. It happens only while the issue is eligible, and
restoring eligibility lets it go ahead. Give conversations their own recovery
prompt: the assignment's `RECOVERY_PROMPT` tells the agent how to mark its own
GitHub posts, and a conversation agent posts nothing.

A failed post of a round's answer makes the round errored (GH250), so recovery
runs the round again with the same input and posts again.

Two cases need no recovery machinery of their own. A conversation whose harness
never reported a session identifier, because its first round stopped before it
could, has no session to resume or replace. Its recovery is a new first round,
in a fresh session, with the first-round prompt, including the conversation's
configured instructions, and the saved input. The recovery prompt is only for a
resumed session. Input saved without a round record belongs to a batch that
never started. The delivery position comes from the latest recorded round, so
the next batch collects the same comments again and overwrites the file. That
input is not recovered, and it is not reported as a problem.

Conversations join the assignment fault rules. Two consecutive errored rounds
since the latest retry or cooldown end put a conversation in fault, and
automatic recovery stops. An interrupted round is not an error. A failure before
the process starts goes into the scheduler hold and is tried again on the next
tick, as it is for an assignment; it is not a round and does not count toward a
fault. `dreamcatcher retry GH123` clears whatever is in fault at that issue: its
newest assignment, its conversation or both. It refuses only when nothing there
is in fault. The global cooldown counts faulted assignments and conversations
together, and otherwise works as it does today.

The statuses from GH254 already cover this. A round waiting to be recovered
makes the conversation waiting, with a detail such as "round 2 interrupted, will
resume" or "round 2 failed, will retry", and two errors in a row make it a
fault. The round history marks recovery rounds.

**Change surface.** Generalize `derive_assignment_fault` so that it covers a
conversation's rounds and retry time too, rather than copying it, and add a
retry time to the conversation record. Extend the scheduler's conversation
inspection to require a recovery round, `_start_cooldown_if_required` to count
conversation faults, and the retry command to find what is in fault at the
issue. Add the conversation recovery prompt. Remove the check in
`_list_comments_to_answer` that makes a conversation unknown when it has input
without a round record. The daemon's orphan sweep already marks unfinished
conversation rounds interrupted.

**Acceptance test.** Start an issue conversation round and stop the daemon while
its feed shows the agent working. With the daemon stopped, inspect the
conversation in the terminal and browser: its interrupted round, session ID and
code revision remain visible. Restart the daemon. Both overviews show it working
again, both detail views identify the recovery round with the same session and
revision, and the feeds show continued work. The question receives its answer on
GitHub without being posted again by the user.

**Automated proof.** Cover same-session recovery after orphan reconciliation,
input and revision held despite a changed main, queued comments not overtaking
recovery, and no recovery while the issue is ineligible. Cover errored and
interrupted rounds, a failed post counting as an errored round, and a failure
before launch going to the scheduler hold. Cover a first round that stopped
before its harness reported a session identifier recovering as a new first round
with the configured instructions, and input without a round record being
replaced by the next batch. Cover retry clearing a conversation's fault, an
assignment's or both, two conversations or a conversation and an assignment
starting the same cooldown, and expiry clearing all faults. Check both UIs
against the resulting saved states.

**Deferral.** Codex conversations.

**Dependency.** GH250 and GH254. Stage two provides session resumption, and
stage one provides saved rounds and process cleanup.

## Stage 5: Conversations with Codex

_Rewritten in the [revision after stage 3](#revision-after-stage-3). Read that
section first._

**Delivery.** The whole conversation lifecycle works with Codex as well as
Claude. Give the conversation config a block per harness, as a dispatch route
has. `[conversation]` keeps its `label`, and `[conversation.claude]` and
`[conversation.codex]` each hold a prompt, model and effort. The daemon's
`--harness` chooses between them by the rule a dispatch route uses, so a config
with one block runs that harness whatever the daemon names. A conversation
records its harness when it is created and keeps it, since a session cannot move
between harnesses.

Add Codex's conversation permissions and final-answer capture for first, resumed
and recovery rounds. Capture the final message separately from progress, apply
the same Markdown and `NO_REPLY` protocol, and post through the same
round-ending callback as Claude (GH250).

**Change surface.** Replace the `harness` field of `IssueConversationConfig`
with per-harness blocks, reusing the dispatch route's recipe model and
`choose_harness` rule rather than copying them, and remove the Claude-only
restriction on conversations. Update this repository's `dreamcatcher.toml`.
Extend `codex.py` with conversation permissions and final-message capture.
Choose the Codex sandbox and approval settings that come closest to the Claude
conversation permissions, and say on the pull request what they allow. Codex
resume already works for assignments. Extend the harness contract tests and any
presenter cases that assume Claude.

**Acceptance test.** Configure both harness blocks and run the daemon with
`--harness codex`. On a fresh eligible issue, ask a question and then post a
follow-up that refers to the first answer. Both overviews identify a Codex
conversation. The terminal and web detail views show two rounds using the same
Codex session, and the feeds show both rounds. GitHub holds the first answer and
a follow-up answer that uses its context. A conversation started earlier with
Claude keeps using Claude.

**Automated proof.** Exercise the conversation contract with Codex: first and
resumed output capture, `NO_REPLY`, failed or missing final output, conversation
permissions on every launch path, and session and revision held during recovery.
Cover harness choice for a config with one block and with two, and an existing
conversation keeping its recorded harness. Existing Claude conversations and
implementation assignments through either harness remain covered. Confirm the
real CLI's first and resumed final-output behaviour during adapter verification,
and do not change recorded harness fixtures by hand.

**Deferral.** None of the agreed design.

**Dependency.** Stage 4. This stage is deliberately last, so its tests establish
parity against the whole lifecycle rather than a moving target.
