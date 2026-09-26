# Design: issue conversations

_Revised on 2026-09-24, after stage 3 of the roadmap landed. The roadmap's
[revision after stage 3](roadmap.md#revision-after-stage-3) says what changed
and why._

## What we're building

An issue conversation is a saved harness session dedicated to discussing one
GitHub issue. The user invites it by adding a configured conversation label and
assigning the issue to themselves. Dreamcatcher supplies their comments, runs an
round of that conversation, and posts the final answer on the issue.

This is not an assignment. An assignment takes an issue to a pull request; a
conversation helps the user understand and explore it. Neither owns, blocks, or
coordinates with the other. They share execution machinery, not a lifecycle.

Implementation starts after the web UI work under
[GH153](https://github.com/alimanfoo/dreamcatcher/issues/153), specified in
`specs/2026-09-17-web-ui/`, has landed. Conversations extend its shared
reporting and feed models; the terminal and web remain separate presentation
layers over the same local data.

## How it works

### One conversation from question to answer

The user posts a question on GH58, labels it for conversation, and assigns it to
themselves. On its next observation, Dreamcatcher discovers the open issue. It
reads its title, body, and ordinary issue comments, filtering comments before
any are supplied to the agent. Only comments from the signed-in user, without
Dreamcatcher's agent-comment marker, survive.

Dreamcatcher creates a conversation record and a detached worktree at current
`origin/main`. When an agent slot is available, it saves the input batch and
starts the configured harness with the issue conversation instructions. The
agent reads code, investigates the question, and returns Markdown ready to post.
When the round ends, it posts that final answer as one marked comment on GH58.
The process ends; the harness session and worktree remain available.

A later question starts another round in the same session. Before that new
batch, Dreamcatcher refreshes the worktree to current main and records the
investigated revision. The resumed transcript already contains the earlier issue
text and revisions, so the new input carries only the new comments and current
revision. Questions arriving while a round runs wait for the next batch.
Recovery continues the unfinished batch in the same session and at the same code
revision.

### Invitation and discovery

Add an optional conversation configuration, separate from implementation
dispatch routes. It supplies one label and, as a dispatch route does, a block
per harness holding the model, effort and initial instructions. The daemon's
requested harness chooses between the blocks by the dispatch route's rule, so a
configuration with one block runs that harness whatever the daemon names.
Multiple conversation types are not part of this design. Save the chosen
settings when a conversation starts; neither a configuration change nor a
different requested harness switches an existing conversation to a different
harness.

Conversation discovery asks for open issues bearing that label and assigned to
the signed-in GitHub user. That same account supplies the permitted comment
author. Do not inherit a different configured implementation assignee: the
invitation and the trusted commenter must refer to the same person.

An open implementation assignment, linked PR, dependency blocker, or
implementation dispatch label is irrelevant to conversation eligibility. The
conversation path does not call assignment availability or creation.

Keep at most one conversation per repository issue. Store conversation records
in their own namespace under the existing repository-local state directory.
Rediscovery uses the saved record rather than creating a second session.

Only currently eligible issues have their comments polled. Closing the issue,
removing the label, or removing the user as assignee stops new input collection.
There is no separate poll of previously eligible or closed issues. Restoring
eligibility makes the issue appear in the normal discovery query again.

Eligibility controls taking new batches, not cancelling a running round: a round
that has started finishes and posts its answer after the issue becomes
ineligible. An interrupted or errored round recovers only while the issue is
eligible, as an assignment recovers only while its pull request is open, and
restoring eligibility lets the recovery go ahead. Retain the session, cursor,
worktree and round records while the issue is ineligible. No automatic expiry or
cleanup policy is added here.

### Input and comment delivery

Use an issue-comment reader, not the existing three-endpoint PR-feedback reader.
Read paginated ordinary issue comments, then apply the author and marker filters
before writing an inbox or prompt. Comments by other accounts never become agent
context. The issue's title and body are still supplied; they describe the issue
even when another agent or person raised it.

The label and assignment enable watching; they do not themselves start a round.
Every new batch, including the first, requires at least one eligible,
undelivered comment. If there are none after filtering, wait without launching
the agent. The issue title and body alone do not trigger a round.

On the first round, supply the eligible existing history and ask the agent to
answer outstanding questions. Do not build a question detector or an answered
question ledger. The agent decides whether the supplied comments need a response
and can return `NO_REPLY`.

Later rounds receive only newly posted eligible comments. Edits to already
delivered comments do not trigger another round. Comments posted while an issue
was inactive are included after it becomes eligible again. Supply current issue
title and body with each new batch, but an issue-body edit alone is not a
follow-up trigger.

Order a batch by comment creation time and ID. Persist a delivery cursor with
both values, rather than a timestamp alone, so comments created in the same
second have a tie-break. This records delivery, not whether individual questions
were answered. Reuse the existing marker spelling, `<!-- dreamcatcher -->`.
Dreamcatcher adds it when publishing, so its own comments do not start a loop
even though they are posted under the user's account.

Freeze the batch before launch and save it as round input. After launch, record
its delivery position. An interrupted or failed round is resumed before any new
batch is accepted. Its saved input and harness context are sufficient; recovery
does not reread GitHub to reconstruct questions or reconcile replies. A crash at
the launch/persistence boundary can repeat input. Exactly-once delivery is not a
requirement. Input saved without a round record belongs to a batch that never
started. The delivery position comes from the latest recorded round, so the next
batch collects those comments again and overwrites the file. That input is not
recovered.

### Worktree and issue conversation contract

Each conversation has a dedicated detached Git worktree in Dreamcatcher's
managed worktree area, under a conversation-specific namespace excluded from
assignment discovery and incomplete-assignment recovery. The existing assignment
discovery scans `GH*-*` worktrees, so conversation paths must not match that
convention. Dreamcatcher creates and refreshes the worktree; the agent does not
create a branch, commit, push, or perform other Git mutations. Reuse the
low-level worktree operations, adding a detached path rather than going through
assignment setup with its branch and draft PR.

Before each new batch, fetch main and update the idle worktree to that fetched
revision. A failed fetch or update prevents the round; do not silently answer
against stale main. Do not refresh a running or recovering round. Save its
revision with its input, and tell the agent which revision it is investigating.
When the revision changes between batches, the agent checks earlier conclusions
where relevant. No separate change-summary service is needed.

Reset tracked files and remove untracked and ignored files before moving the
worktree to fetched main. The conversation agent is forbidden to edit the
worktree, so anything it nevertheless leaves there is disposable investigation
state and must not make the user repair a managed worktree.

The new issue conversation skill contract says: no implementation in this
session. Read source and Git history, run code, and reproduce bugs as needed; do
not edit project source or mutate Git or GitHub. Use agent-managed scratch space
when investigation needs temporary files. Dreamcatcher does not provision or
maintain a separate scratch directory.

The agent answers from the supplied issue input and local investigation. It must
not fetch issue comments itself or post its own replies. Receiving and
publishing comments belong to Dreamcatcher. Use conversation-specific harness
permissions instead of the assignment permissions that allow implementation and
GitHub mutations, on first, resumed, and recovery rounds.

These are task instructions reinforced by practical harness permissions, not a
universal security sandbox. Do not add containers, credential isolation, or a
cross-platform sandbox system to this feature. In particular, denying editing
tools does not prove that arbitrary reproduction code cannot write files. The
user explicitly accepted this boundary.

### Final answer and publication

The final output is Markdown ready to post, or exactly `NO_REPLY`. Compare the
whole trimmed final output with that sentinel. Do not use JSON or a response
schema, and do not ask the skill to quote every question or produce separate
replies for each question. One batch produces at most one comment in the normal
case, or none.

Only publish the final output of a successful round. Intermediate messages, tool
output, and reasoning remain in the local feed. Extract the actual final answer
at the harness boundary, not by scraping the human-readable feed: Claude's
successful result carries its result text; Codex provides a last-message output
file. Preserve the raw stream for diagnosis and session-ID recovery. Ensure
final-output capture has completed before posting; process exit alone is not
proof that stream readers have finished. Missing final text is a round failure,
not an implicit `NO_REPLY`.

The round publishes its own answer. `NO_REPLY` finishes the batch without a
GitHub call. Otherwise the round appends Dreamcatcher's marker and posts an
issue comment before it records its ending, so the round keeps its agent slot
while it posts and no new batch starts until the answer is out. The shared round
runner knows nothing of GitHub: the conversation launcher gives it a callback
that posts to the issue. A failed post makes the round errored, with the failure
as its reason and noted in its feed, and recovery runs it again like any other
errored round. If the daemon dies between the harness exiting and the post, the
round is interrupted and recovers the same way. There is no saved reply record
and no retry of the post on later ticks.

GitHub may accept a post before Dreamcatcher loses the response or crashes.
Recovering the round can then duplicate the comment. Accept that rare duplicate;
do not add remote reply reconciliation, per-question acknowledgements, or an
exactly-once publication protocol.

### Sessions, recovery, and capacity

A conversation record holds issue identity, chosen launch settings, and the
harness session ID. Its issue number derives the worktree's location in managed
state. Numbered round records hold process identity and outcome; their durable
inputs hold each saved comment batch, its investigated revision, and the prior
round's revision. The round directory also holds its prompt, raw output, feed
and final output. Use the existing atomic document writers and validated
document models.

The harness owns the conversation transcript. Every later invocation resumes
that session. Recover an interrupted or failed round by asking it to continue
the unfinished work, retaining its input and code revision. No separate summary
memory, answer ledger, or transcript reconstruction is needed. A harness that
cannot resume reports a normal failure; do not silently replace the session. A
conversation whose harness never reported a session identifier has no session to
resume or replace. Its recovery is a new first round, in a fresh session, with
the first-round prompt, including the configured instructions, and the saved
input.

Reuse process supervision, session-ID capture, shutdown, and orphan recovery.
Extend these mechanics to conversation-owned rounds without pretending their
owner is an assignment. Do not introduce a broad workflow framework merely to
share a process runner.

At most one round runs per conversation. Running conversation and implementation
rounds count against the same configured concurrency cap; idle sessions consume
no agent slot. Among conversations awaiting a new round, take the oldest waiting
comment first, batching the other waiting comments on that issue. The same
ordering applies to initial and later batches; an issue with no eligible,
undelivered comments is not a candidate for a new batch. Recovery takes
precedence over every fresh batch, including one waiting at another
conversation.

When both an implementation candidate and a conversation candidate are ready,
alternate which kind receives the next free slot. When only one kind is ready,
it can use the available capacity. Keep each kind's internal selection rules;
this shared turn-taking rule prevents either from starving the other. It needs
no durable queue or persisted turn-taking state across daemon restarts.

Conversations join the assignment fault rules rather than copying them. Two
consecutive errored rounds since the latest retry or cooldown end put a
conversation in fault, and automatic recovery stops. Interrupted rounds are not
errors. A failure before the process starts, including a refused or unavailable
session resume, goes into the scheduler hold and is tried again on the next
tick, as it is for an assignment; it is not a round and does not count toward a
fault. `dreamcatcher retry GH123` clears whatever is in fault at that issue: its
newest assignment, its conversation or both. It refuses only when nothing there
is in fault. The global cooldown counts faulted assignments and conversations
together, and its start, its expiry and a lone fault work as they do for
assignments. There is no per-conversation timer or special rate-limit
classifier.

Do not add a special missing-session recovery mechanism.

Status and logs distinguish conversations from assignments, but a conversation
uses the assignment status words wherever they mean the same thing. Each status
says whose move it is and whether anything is happening, and the detail line
gives the reason.

| Conversation status | Meaning                                                                                                                                                                                                       | Assignment counterpart |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| Working             | A round is running.                                                                                                                                                                                           | Working                |
| Waiting             | A round is due but has not started: comments wait to be answered, the first batch included, or an interrupted or errored round waits to be recovered. A free agent slot, or the end of a cooldown, starts it. | Waiting                |
| Idle                | No round is due: the latest answer is posted, or the user has not commented yet.                                                                                                                              | Needs user feedback    |
| Fault               | Two consecutive rounds have errored, and automatic recovery has stopped until the user retries or a cooldown ends.                                                                                            | Fault                  |
| Unknown             | Dreamcatcher cannot tell whether the issue is eligible or whether comments wait.                                                                                                                              | Unknown                |

Idle differs from needs user feedback on purpose. An assignment at rest has a
pull request waiting for review, so it asks something of the user. A
conversation at rest has already posted its answer, so it asks nothing. A
conversation has no complete status: removing the label, unassigning the user or
closing the issue takes the conversation off the status report instead.

Every eligible issue appears as a conversation from the first tick that sees it,
whether or not a conversation record exists yet. So a conversation has no
counterpart to an available issue, and blocked issues and failed setups do not
apply to it. Once the issue is ineligible, the conversation appears only while a
round is running, and its detail view shows it as idle with the reason. The
scheduler reads each eligible issue's comments on every tick, whether or not an
agent is free, so status can tell waiting from idle. Conversations are listed as
fault, working, waiting, unknown and then idle, since idle is not a call to
action. Show the issue and latest failure where relevant. Reporting reads local
records and scheduler observations rather than polling GitHub.

From the first usable delivery, include conversations in `dreamcatcher status`,
add `dreamcatcher conversation GH123` as the detail view analogous to
`dreamcatcher assignment GH123`, and provide a live conversation feed. The
detail view shows the issue, chosen harness settings, saved session identifier,
worktree, and round history with code revisions and outcomes. This gives later
acceptance tests a place to verify session continuity, code freshness, and
recovery without reading state files by hand.

The feed shows the agent's actions and output from its saved rounds, using the
existing local feed machinery. Select its owner explicitly with
`dreamcatcher feed GH123 --conversation` or
`dreamcatcher feed GH123 --assignment`. Require exactly one of these mutually
exclusive selectors so an issue carrying both kinds of work is unambiguous.

The web overview also shows conversations from the first usable delivery. Each
links to a conversation page combining its detail view and live feed, analogous
to the web assignment page without assignment-only facts such as a branch or PR.
When conversations exist, the home page keeps Assignments on the left and
Conversations on the right. The Assignments panel also holds failed assignment
setups, available issues and blocked issues, so every stage of assignment work
stays together. Both presentations read the same status and feed models and ask
GitHub nothing. Use the landed web UI's rendering, polling and tail boundaries;
keep conversation lifecycle decisions in the shared reporting layer rather than
either presenter.

As later stages add round and lifecycle behaviour, extend both presentations
alongside it. Most UI wiring belongs to the first stage; later stages mainly
supply additional rounds, code revisions, recovery outcomes and fault states to
those views. Do not defer web visibility to a final integration stage.

## What changes, and what goes away

Add conversation configuration, records, input, prompts, and scheduling. Extend
GitHub access with ordinary issue-comment reading and host-owned reply posting.
Extend Git helpers with detached-worktree creation and idle refresh. Teach the
harness boundary about conversation permissions and final-answer capture. Extend
terminal and web status, detail views, live feed, retry, and startup/shutdown
handling to conversation records. The web UI prerequisite's historical
specifications remain unchanged.

The current round launch request names an assignment, and its inbox and round
purposes are implementation-specific. Separate those assumptions from the shared
process runner. Keep conversation and assignment input types distinct; do not
fabricate PR state or run conversation input through assignment feedback and
wrap-up purposes. Assignment lifecycle behaviour remains unchanged; shared
capacity selection and cooldown fault counting gain conversation participants.

The conversation path has no branch creation, empty commit, push, draft PR,
ownership claim, dependency check, or wrap-up round. Leaving these out removes
the implementation lifecycle entirely rather than disabling pieces of it.

There is no agent-managed polling loop: a round exits, and the daemon watches
for new input. There is no managed scratch directory, fixed lifetime code
snapshot, question decomposition service, response schema, per-question answer
tracking, reply reconciliation, or coordination with an implementation agent.

Update the current requirements to distinguish eligibility for new input from
already-started work, clarify new-batch freshness versus recovery, and remove
the remaining term "conversation assignment". Document the separate conversation
contract and vocabulary alongside the existing assignment contract. Leave
historical specs and assignment semantics alone. GH196, the existing assignment
inbox-field mismatch, remains a separate issue, not a dependency of this
feature.

## Why it's this and not something else

An assignment with a different prompt would still bring branch, PR, ownership,
and completion rules. A separate conversation lifecycle avoids those rules while
sharing the worktree and harness mechanics that are actually useful.

A detached worktree supplies local code and history without a private clone or
an implementation branch. Refreshing between batches keeps answers relevant;
holding the revision during recovery lets the agent continue the same work.

Host-owned posting makes the skill simpler and keeps intermediate output off the
issue. A Markdown answer or `NO_REPLY` is enough. Rare duplicate posts are
cheaper to tolerate than a reconciliation protocol.

The issue conversation contract is not a hard isolation guarantee. Building a
new cross-platform sandbox would outweigh this feature; use the harness controls
where practical and be honest about their limits.

## What's still open

No design choices remain open. Independent reviews found no further cuts or
blocking buildability gaps, and the worktree-discovery clarification is included
above. The revision after stage 3 replaced the earlier rule for failures before
launch with the assignment path's scheduler hold.
