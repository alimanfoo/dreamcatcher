# Roadmap: issue conversations

Every session that implements a stage should correct the specifications as
details change and say on its pull request what it corrected. It may change how
it delivers the stage when earlier work or implementation discoveries justify
that change. It should raise any change to the roadmap's stages, boundaries,
order or dependencies with the user instead of restructuring the roadmap itself.

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
agent input. Freeze the eligible existing history as the initial batch; an
invitation without comments may still start a round. Do not apply assignment
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
author/marker filtering, the no-comment invitation, namespace separation,
initial worktree revision, final-result readiness, `NO_REPLY`, missing or failed
results, and completion without repeated launch. Exercise a failed post followed
by success and prove the harness runs only once. Cover ordinary process cleanup
without resumption, both owner selectors, and both presentations from the same
fabricated states, including a failed initial attempt and pending publication.
Existing assignment behaviour remains covered by its regression tests.

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
delivered comments. Supply current issue title/body with each batch, but do not
make an issue-body edit alone a trigger. Marker filtering prevents answers from
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
oldest waiting input first; an initial conversation without comments uses issue
age. No durable scheduling queue is added.

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
worktree to that revision. Record the revision with the batch and tell the agent
the previous and current revisions so it can revisit relevant earlier findings.
Keep the session; replace neither its transcript nor its identity. A running
round's checkout does not move.

Report failed refreshes rather than answer against stale main, and do not force
away unexpected local changes. Show the investigated revision for each round in
both detail views and identify revision changes in the feed.

**Change surface.** Extend `git.py` with safe detached-worktree refresh and call
it from conversation preparation before accepting a new batch. Extend the round
input and prompt with previous/current revision context. Add the corresponding
shared reporting facts and small terminal/web presentation changes. No change to
comment routing or assignment worktree handling is needed.

**Acceptance test.** Ask about a small function in the test repository, merge a
change to that function on main, then ask the same conversation, "Does your
answer still hold?" Both overview UIs show another round. Both detail views
retain the session ID and show the new round's changed revision; the feed names
the previous and current revisions and shows investigation of the change. The
GitHub answer reflects the new behaviour and explains its effect on the earlier
answer.

**Automated proof.** Cover changed and unchanged main, fetch/update failure,
unexpected local changes without destructive cleanup, and no refresh while a
round runs. Verify that the saved input and both presentations report the exact
revision investigated, not a later moving remote ref.

**Deferral.** Recovering interrupted or failed work; conversation fault/retry
handling; Codex conversations.

**Dependency.** Stage two supplies the successful follow-up path to prepare
against a newer revision.

## Stage 4: Continue interrupted work

**Delivery.** Resume interrupted or failed issue conversation rounds in their
existing sessions, with the saved batch and code revision. Do not fetch main,
collect a new batch, or reconstruct earlier replies to recover an unfinished
round. Eligibility loss does not cancel already-started work or its eventual
reply. Recovery takes precedence over fresh input for that conversation.

Two consecutive errored attempts put a conversation in fault. Include failures
before process launch in that accounting; interruption is not an error. Extend
manual retry so it can explicitly select the conversation when the issue also
has an assignment. Reuse one global cooldown: any two faulted assignments or
conversations trigger it, no rounds start during it, and expiry clears all
faults for retry while retaining their history. A lone fault still needs manual
retry unless another fault triggers cooldown. Do not add per-conversation
timers, rate-limit classification or a special replacement-session mechanism.

Extend both UIs with recovery outcomes, faults and their reasons, and shared
cooldown state. Keep the saved session and revision inspectable while the daemon
is stopped. Normal saved-answer publication retries remain the stage-one path,
not extra agent rounds.

**Change surface.** Extend conversation inspection and attempt recording,
recovery prompt composition, and the daemon's orphan reconciliation/resumption
path. Extend fault derivation and the scheduler's existing global cooldown to
include conversation faults, and extend the retry command's target selection.
Add recovery/fault facts to the shared status/detail models and render them in
the existing terminal and web views. Preserve assignment lifecycle semantics.

**Acceptance test.** Start an issue conversation round and stop the daemon while
its feed shows the agent working. With the daemon stopped, inspect the
conversation in the terminal and browser: its interrupted round, session ID and
code revision remain visible. Restart the daemon. Both overviews show it running
again, both detail views identify the recovery round with the same session and
revision, and the feeds show continued work. The question receives its answer on
GitHub without being posted again by the user.

**Automated proof.** Cover daemon shutdown and orphan reconciliation,
same-session recovery, frozen input/revision despite changed main, queued
comments not overtaking recovery, and recovery after eligibility loss. Cover
errored and interrupted attempts, pre-launch failures, manual retry targeting,
two conversations or a conversation plus assignment triggering the same
cooldown, expiry clearing all faults, and the lone-fault caveat. Retain the
ordinary publication-failure tests rather than requiring manual fault injection
for acceptance. Check both UIs against the resulting saved states.

**Deferral.** Codex conversations.

**Dependency.** Stage two provides session resumption and stage one provides
saved attempts and process cleanup. Recovery itself does not require stage
three; placing it afterwards also verifies that the normal refresh path is
skipped during recovery.

## Stage 5: Conversations with Codex

**Delivery.** The complete conversation lifecycle works with Codex as well as
Claude. Add Codex's issue conversation launch settings and final-answer capture
for first, resumed and recovery rounds. Capture its final message separately
from progress, apply the same Markdown/`NO_REPLY` protocol, and use the existing
conversation publisher and lifecycle rather than duplicating them.

New conversations use their configured harness. Existing conversations retain
their recorded harness and settings. Both UIs show the correct harness, session
identity and feed through the presentation paths already built.

**Change surface.** Extend `codex.py` and the necessary adapter/launch boundary
for conversation permissions and final-message capture; remove the temporary
conversation-only support restriction from stage one. Extend harness contract
tests and any presenter cases that expose a harness-specific assumption. The
conversation scheduler, worktree lifecycle and publisher remain shared.

**Acceptance test.** Configure Codex for new conversations. On a fresh eligible
issue, ask a question and then post a contextual follow-up after the first
answer. Both overviews identify a Codex conversation. The terminal and web
detail views show two rounds using the same Codex session, and the feeds show
both rounds. GitHub contains the initial answer and a contextual follow-up. Use
a fresh issue so a saved Claude session is not being asked to change harness.

**Automated proof.** Exercise the same conversation contract with Codex: initial
and resumed output capture, `NO_REPLY`, failed or missing final output, issue
conversation settings on every launch path, preserved session and revision
during recovery, and publication without relaunch. Existing Claude conversations
and implementation assignments through either harness remain covered. Confirm
the real CLI's first/resume final-output behaviour during adapter verification;
do not change recorded harness fixtures by hand.

**Deferral.** None of the agreed design.

**Dependency.** Its adapter work could begin after stage one, but this stage is
deliberately last so its acceptance and automated tests establish parity against
the lifecycle delivered by stages two through four, not a second moving target.
