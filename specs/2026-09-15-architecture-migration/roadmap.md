# Target architecture migration roadmap

This roadmap describes how to move the working Dreamcatcher implementation to
the domain model in [the ontology](../../docs/ontology.md) and the boundaries in
[the target architecture](../../docs/architecture.md). Read both documents in
full before implementing any stage of this roadmap.

The roadmap is an ordered series of reviewable stages. Each stage will become
one subissue of GH76 and will be delivered by one pull request. The subissues
will be created only after this roadmap has been reviewed and merged.

## Migration rules

Each stage must leave Dreamcatcher in a working state. In particular:

- the daemon and every supported command must work with the state written by
  that stage;
- the complete test suite, branch-coverage gate, static checks, and
  cross-platform checks must pass;
- affected current documentation and the assignment-skill contract must describe
  the implementation at that checkpoint;
- superseded code must be removed as part of the stage which replaces it, so
  there is one implementation of each responsibility; and
- historical dated specifications must not be revised.

Backward compatibility is not required. Nevertheless, a stage must not change a
persisted document, command interface, prompt, scheduling decision, or other
working behaviour merely because a breaking change is permitted. A necessary
break must be identified in that stage's pull request.

The stages are merged in order. A later stage may therefore rely on all earlier
stages, but no pull request should depend on unmerged work from a later stage.

## Behaviour budget

Most of this migration changes names, ownership, dependency direction, and the
representation of existing facts. It must preserve the behaviour of the current
system.

The target design deliberately requires these observable changes:

- Dreamcatcher, rather than the assignment skill, prepares and pushes the branch
  and opens the linked draft pull request before the first agent round;
- an assignment whose creation was interrupted after its durable record was
  written can still receive its missing first round;
- a completed assignment no longer claims its issue, so an issue whose pull
  request closed without merging can receive another assignment; the current
  scheduler treats every stored session as a claim, despite `README.md` saying
  that a closed-unmerged issue is free to dispatch again;
- two consecutive errored rounds place an assignment in fault, and faults in two
  assignments start the agreed global cooldown; and
- the user interface reports issues and agent assignments using the ontology,
  rather than presenting sessions on a board and issues in a queue.

Unless a stage explicitly names one of these changes, it must retain the current
issue-selection scope and ordering, one-action-per-tick rule, capacity handling,
round triggers, prompt contents, user-post delivery protocol, harness output
rendering, live-view behaviour, and conservative response to failed external
reads.

## Starting point

The current implementation already has most of the required mechanisms, but
several boundaries and names do not match the target:

- `daemon.py` owns scheduling policy as well as daemon lifecycle;
- `sessions.py` holds the durable object which will become an agent assignment,
  but the object does not own an already-open pull request or an explicit
  harness session identifier;
- `rounds.py` records a single cause where the target distinguishes purpose,
  recovery, and outcome;
- `eligibility.py` reduces independent issue facts to one obstacle string;
- `wakeups.py` combines observation, scheduling interpretation, and the metaphor
  of waking a session;
- `state.py` owns candidate, waiting, and last-tick models as well as paths;
- `board.py` derives presentation states from scheduler records and presents a
  conceptual queue; and
- `tui.py`, `README.md`, and `CONTRACT.md` expose the current session, board,
  queue, and skill-owned pull-request model.

Other boundaries already largely match the target. `documents.py` owns strict
Dreamcatcher documents and safe writes, `commands.py` is the sole subprocess
boundary, `git.py` contains Git operations, and `feed.py` keeps harness-neutral
plain-text activity. The migration should extend those boundaries only where a
stage needs a missing operation; it should not replace them.

The stages below change those seams without rebuilding mechanisms which already
work.

## Stage 1: Separate scheduling from daemon lifecycle

### Stage 1 Outcome

`scheduler.py` owns the existing scheduling loop, while `daemon.py` owns only
the lifetime of the foreground daemon. This establishes the dependency direction
needed by every later stage without changing what a tick does.

### Stage 1 Work

- Introduce a scheduler object which receives the repository, account,
  configuration, state paths, selected harness, clock, and active-round
  supervision it needs.
- Move issue judgement, session judgement, capacity and cooldown checks,
  scheduling priority, and the operations which launch sessions and rounds out
  of `Daemon` and into the scheduler.
- Let the daemon retain startup validation, state bootstrap, repository locking,
  the timed loop, startup recovery of child processes, shutdown of active child
  processes, and reporting of tick failures.
- Move the scheduling tests out of `test_daemon.py`; retain daemon tests for
  startup, locking, timing, failure containment, and shutdown.
- Keep the existing `LastTick`, candidate, waiting, wake-up, session, and round
  interfaces as temporary inputs and outputs of the extracted scheduler.

### Stage 1 Behaviour

This stage is behaviour-preserving. The scheduler must make the same GitHub
reads in the same circumstances, enforce the same capacity cap and current
cooldown, choose the same work in the same order, launch at most one round, and
write the same operational record as the current daemon.

### Stage 1 Working-state checkpoint

The `run` command starts and stops exactly as before. Existing status views can
read the unchanged state documents, and all current daemon and scheduling
scenarios continue to pass with their assertions divided across the new
boundary.

## Stage 2: Establish the agent-assignment boundary

### Stage 2 Outcome

The durable commission currently called a session becomes an `AgentAssignment`,
owned by `agent_assignments.py`. An agent assignment identifier and a harness
session identifier are distinct in every interface, even though explicit harness
session identity is added in a later stage.

### Stage 2 Work

- Replace `sessions.py`, `Session`, `SessionRecord`, `session.key`, and their
  exported operations with descriptive agent-assignment names.
- Keep reading, creation, lookup by issue, record updates, and completion
  queries behind the agent-assignment boundary as those operations are added
  across later stages.
- Rename state paths and owned record names which encode the obsolete session
  concept. Do not otherwise redesign the on-disk representation.
- Rename `HarnessSettings` to `AssignmentRecipe` and `DispatchMapping` to
  `DispatchRoute`. Keep the `dreamcatcher.toml` syntax and recipe-selection
  behaviour unchanged.
- Treat the assignment record's existing label, harness, model, effort, and
  initial prompt as the frozen route and recipe selected at creation. Do not
  introduce a second nested representation of the same facts.
- Update scheduler, round, wake-up, status-view, test, fixture-helper, CLI, and
  documentation references and package metadata to use agent-assignment
  terminology.
- Rename the user-facing `session` command to `assignment`. Preserve its current
  behaviour of selecting the newest assignment for a supplied issue; make that
  selection explicit in its help and output rather than changing how the command
  is addressed.
- Use “harness session” wherever the continuing conversation owned by Claude
  Code or Codex is meant. Do not use bare “session” for an agent assignment.

### Stage 2 Behaviour

Apart from the terminology and corresponding command rename, this stage is
behaviour-preserving. Assignment creation still has its current mechanics,
rounds resume as they do now, and scheduling decisions do not change.

Renaming the persisted assignment directory and record is the one intended
state-format break in this stage. No compatibility layer is required, and no
unrelated record fields or file formats should change.

### Stage 2 Working-state checkpoint

A fresh Dreamcatcher instance can dispatch, resume, display, and wind up agent
assignments through the renamed model. The daemon and views share one
`AgentAssignment` implementation, while the existing scheduling and harness
tests demonstrate that the vocabulary migration did not alter their behaviour.

## Stage 3: Make assignment creation complete and recoverable

### Stage 3 Outcome

Every durable agent assignment has its branch, worktree, pushed empty commit,
and linked draft pull request before its first agent round starts. Dreamcatcher
owns that preparation and can reconcile an interruption without creating a
second assignment or pull request.

### Stage 3 Work

- Add narrow Git operations for making an empty commit and pushing the
  assignment branch. Keep all command execution in `commands.py` and all Git
  knowledge in `git.py`.
- Add GitHub projections and operations for creating a linked draft pull request
  and reading it by its persisted identity. Keep GitHub command and response
  details inside `github.py`.
- Extend the assignment record with its pull-request identity. Continue to read
  mutable draft, ready, merged, and closed state from GitHub rather than caching
  it in the assignment.
- Read the persisted pull request directly during ordinary assignment work.
  Retain lookup by branch only for reconciling incomplete creation, and remove
  the current rule which chooses among several pull requests on a branch.
- Make `agent_assignments.py` coordinate the complete creation workflow in the
  order specified by the target architecture, writing a valid assignment record
  only after every external artifact exists.
- Enforce that the instance has no open assignment for the issue when creation
  begins.
- Reconcile branch, worktree, remote branch, and pull-request artifacts left by
  an interrupted creation. Use the assignment identifier, branch head, and
  linked pull request as the evidence; do not add a creation journal or a
  partial assignment record.
- Change the scheduler's create-and-start action so a complete assignment with
  no rounds receives its first implementation round before ordinary scheduling
  continues. A failure to start that round must not discard the prepared branch
  or pull request.
- Revise `CONTRACT.md` so an assignment skill adopts the current branch,
  worktree, and already-open draft pull request, uses that pull request to
  communicate, and marks it ready when implementation is ready for review.
- Revise `README.md` to describe the new ownership and recovery behaviour.

### Stage 3 Behaviour

This stage intentionally transfers branch publication and draft-pull-request
creation from the assignment skill to Dreamcatcher. It also replaces the current
irrecoverable “no first round” condition with automatic completion of the
scheduling action.

The configured initial prompt and the way the harness receives it do not change.
Issue selection, scheduling priority, capacity, cooldown, later-round triggers,
and user-post delivery remain unchanged.

### Stage 3 Working-state checkpoint

At every successful dispatch, the agent starts in a clean assignment worktree
whose branch is already visible on GitHub and whose draft pull request already
closes the issue. Failure-injection tests cover interruption after each setup
step and demonstrate that the next tick either reuses or removes the artifacts
without duplicating them. A normally created assignment still starts its first
round in the same tick.

## Stage 4: Establish the agent-round model

### Stage 4 Outcome

`agent_rounds.py` owns the records and supervised process lifetime of an
`AgentRound`. Round number, purpose, recovery, and outcome are represented
independently, using the terms established by the ontology.

### Stage 4 Work

- Replace `rounds.py`, `Round`, `RoundRecord`, `Cause`, and `Workspace` with
  descriptive agent-round types and operations. Name the round's file collection
  as paths or files; the shared execution location remains the assignment's
  worktree.
- Give every new round one purpose: implement, address feedback, or wrap up.
  Give it an independent recovery flag derived from the preceding round.
- Persist the round's assignment-scoped number in its record as well as using
  that number for its directory and display.
- Represent running, successful, errored, and interrupted outcomes without
  reducing them to a generic complete-or-failed flag. Retain the observed exit
  status and ending time where they exist.
- Reconcile a recorded running round whose process no longer exists as
  interrupted. Keep the existing process-tree termination and stream-draining
  behaviour.
- Extend the pull-request projection with GitHub's draft/ready value. Map the
  existing triggers onto purposes: a draft pull request calls for
  implementation, a ready pull request calls for addressing feedback, and a
  merged or closed pull request calls for wrap up.
- Derive purpose and recovery independently for every new round. A preceding
  interruption or error makes the round a recovery round, while the current
  pull-request state determines its purpose. The same purpose may repeat while
  the pull-request state remains unchanged.
- Derive assignment completion from a successful wrap-up round. Treat only
  assignments without such a round as open when determining whether an issue is
  claimed here.
- Update adapters, scheduler, temporary wake-up and board models, feeds, views,
  state readers, test helpers, and fixtures to consume the new round record.

### Stage 4 Behaviour

The new representation must not change when work starts, which harness command
runs, what prompt it receives, how output is streamed, or how user posts are
delivered. An interrupted or first-time errored round continues to receive the
same recovery opportunity as before.

The intended semantic correction is that only a successful wrap-up completes an
assignment. Consequently, a completed assignment no longer claims an issue whose
pull request closed without merging.

The round-record schema and the wording of round metadata shown in feeds and
views may change to express the ontology. No compatibility layer for old round
records is required.

### Stage 4 Working-state checkpoint

The daemon can start, observe, stop, resume, and display every kind of agent
round. Tests cover all combinations which affect scheduling: each purpose,
ordinary and recovery rounds, every outcome, recovery of a wrap-up round, and
completion after a successful wrap up. Existing harness-stream and process
supervision tests continue to pass against the renamed boundary.

## Stage 5: Establish the user-post relay boundary

### Stage 5 Outcome

GitHub contributions from the user are represented as `UserPost` values, and
`relay.py` owns the act of selecting posts which have not yet been delivered.
There is no durable inbox domain entity; the existing round input remains a
transport document owned by the agent round.

### Stage 5 Work

- Replace the generic `Post` and `AnyPost` names in the GitHub boundary with a
  harness-neutral `UserPost` representation covering conversation comments,
  review bodies, speaking review verdicts, and inline review comments.
- Keep GitHub pagination, ordering, filtering of non-speaking reviews, and
  tolerant response projections unchanged.
- Rename the assignment's watermark concept to its user-post delivery cursor.
  Keep it as a one-value text document unless a structured model provides
  additional meaning.
- Keep relay responsible only for comparing normalized user posts with that
  cursor and returning the undelivered posts. It must not decide whether or when
  an agent round runs.
- Remove `Inbox` from the relay's domain interface. Let the agent-round boundary
  own the transport document containing pull-request state and delivered user
  posts.
- Advance the delivery cursor at the same durable point as the current
  implementation: after the round has started successfully. A failed launch must
  leave the posts available for the next tick.
- Update the assignment-skill contract to use “user post” and “feedback” while
  retaining its existing instructions for reading and acting on the delivered
  JSON document.

### Stage 5 Behaviour

This stage is behaviour-preserving. It must retain the existing transport JSON,
the prompt which points the agent to it, the definition and ordering of new
posts, and the marker used to distinguish the user's contributions from the
agent's own. Posts made while a round is running remain beyond the cursor and
cause a later round.

### Stage 5 Working-state checkpoint

Conversation comments, reviews, verdicts, and inline comments still reach the
agent once and in order. A batch whose round cannot start is offered again, and
a later post is not lost when an earlier batch is already being handled. Tests
exercise those behaviours through `UserPost`, relay, assignment cursor, and
agent-round interfaces rather than through an `Inbox` domain object.

## Stage 6: Make harness sessions explicit

### Stage 6 Outcome

Every agent assignment records the identifier of the continuing harness session
created by its first agent round. Every later round resumes that specific
harness session rather than whichever conversation happens to be the latest in
the worktree.

### Stage 6 Work

- Replace the ambiguous `Launch.session` interface with names which distinguish
  the Dreamcatcher assignment identifier from the harness session identifier.
- Make each adapter construct a new-session invocation and an
  explicitly-identified resume invocation for its harness.
- Let adapters recognize the harness session identifier in the harness's
  existing event stream without exposing Claude- or Codex-specific event shapes
  outside the adapter boundary.
- Persist the identifier on the assignment as soon as the first round reports
  it. Continue to render the corresponding harness event in the feed as today.
- Recover an identifier from the first round's durable raw stream when the
  process reported it but Dreamcatcher was interrupted before updating the
  assignment record.
- Refuse to resume when no identifier can be established. Report the condition
  in the existing operational path rather than guessing “last”, starting a
  second harness session, or producing an unhandled traceback.
- Make the hand-resume command refer to the explicit harness session where the
  harness supports doing so.
- Test new and resumed invocations for both Claude Code and Codex, including
  interruption between observing and recording the identifier.

### Stage 6 Behaviour

Normal assignments continue through the same harness conversation in the same
worktree with the same model, effort, permissions, prompt, and event rendering.
The intentional correction is that an unrelated conversation created in that
worktree can no longer capture a resumed agent round.

### Stage 6 Working-state checkpoint

Before any later round can start, its assignment either holds a valid harness
session identifier or carries a reportable reason why Dreamcatcher cannot resume
it. Restarting the daemon and manually resuming an assignment both select the
same harness conversation, and no supported path depends on an implicit
“continue” or “last” lookup.

## Stage 7: Derive issue availability from independent facts

### Stage 7 Outcome

The scheduler represents claimed here, claimed elsewhere, blocked, and routing
conflict as independent three-valued facts and derives whether an issue is
available. Candidate, eligibility, obstacle, and queue concepts no longer
control scheduling.

### Stage 7 Work

- Extend GitHub issue projections only as needed to observe issue state,
  assignees, labels, dependencies, and linked pull requests. Preserve tolerant
  projection of documents owned by GitHub.
- Replace `CandidateIssue` and `eligibility.py` with structured issue
  observations and pure interpretation functions owned by the scheduling
  boundary.
- Let `config.py` identify which observed labels are configured dispatch labels.
  Leave the scheduler to interpret zero, one, or several matches.
- Represent each independent fact as true, false, or unknown. Preserve the
  reason supplied by a failed external read as diagnostic evidence without
  turning that reason into the fact itself.
- Derive claimed here from open local assignments. Derive claimed elsewhere from
  open linked pull requests other than the local assignment's persisted pull
  request, if it has one. Allow both facts to be true.
- Derive blocked from open issue dependencies and routing conflict from more
  than one configured dispatch label. Do not give configuration order precedence
  when labels conflict.
- Implement the ontology's availability rule exactly, including false as soon as
  a known fact prevents assignment and unknown when no fact prevents it but a
  required observation is unknown.
- Continue to consider the same open, assigned, dispatch-labelled issues for new
  work and to choose the oldest available issue.
- Observe issues with open local assignments even when their current state,
  assignee, labels, or route configuration exclude them from consideration for
  new work. Record those observations for reporting, but never use them to
  abandon the existing assignment.
- Replace persisted candidate rows with the observations needed for later
  operational reporting. Let the existing board adapt those observations for
  presentation until the status-report stage removes the board.
- Add focused truth-table tests for availability and integration tests for the
  GitHub observations which supply it.

### Stage 7 Behaviour

This stage is behaviour-preserving for dispatch. Issues which Dreamcatcher can
currently prove dispatchable remain dispatchable in the same order, and a failed
read still causes conservative inaction for every issue whose safety depends on
that read. No issue acquires a durable queue position or queued state.

The richer representation may reveal that an issue is simultaneously claimed
here and elsewhere, blocked, or in routing conflict. Those facts do not create a
second assignment while claimed here is true.

### Stage 7 Working-state checkpoint

The scheduler can explain every considered issue through independent facts and
derive availability without presentation models. The daemon still dispatches at
most the same issue it would have selected before this stage, and the temporary
board remains usable from the new operational observation record.

## Stage 8: Complete the target scheduling policy

### Stage 8 Outcome

The scheduler derives the next required agent round directly from assignment,
round, pull-request, user-post, process, capacity, and cooldown facts. Wake-up,
waiting-session, stuck, and blanket single-error cooldown concepts no longer
control work.

### Stage 8 Work

- Replace `wakeups.py`, `Wakeup`, `Finding`, and `WaitingSession` with a pure
  interpretation of whether an assignment requires a round and, if so, its
  purpose, recovery flag, unrelayed user posts, and explanatory evidence.
- Preserve the established priority among runnable work: recover an interrupted
  or first-time errored round, wrap up a terminal pull request, start a round
  for new user posts, then create an assignment for the oldest available issue.
  Continue to perform at most one scheduling action per tick.
- Keep scheduling priority separate from round purpose. In particular, a
  highest-priority recovery round may have implementation, feedback, or wrap-up
  as its purpose according to the pull request's current state.
- Treat a complete assignment as requiring no work. Treat a complete assignment
  whose pull request closed without merging as no longer claiming its still-open
  issue.
- Derive fault when an assignment has two consecutive errored rounds since the
  most recent global cooldown ended. Do not count an interruption as an errored
  round.
- Replace the current cooldown after every failed round with a global cooldown
  triggered when two assignments are in fault. During the cooldown, continue
  observing and reporting but start no assignment or round. Retain the current
  fifteen-minute duration.
- Persist the active cooldown and the time the most recent cooldown ended in an
  instance-wide scheduler record. Once the cooldown ends, ignore earlier errors
  when deriving fault and permit the affected assignments to recover.
- Do not attempt to classify a harness failure as globally shared without a
  reliable signal. The ontology permits an immediately recognized global error,
  but defining such signals is not part of this migration.
- Replace `LastTick` with an operational scheduler record containing the tick
  time, action taken, active hold or cooldown, and observations needed by the
  local views. Keep issue and assignment status derived rather than persisted.
- Move scheduling documents out of `state.py`; leave that module responsible for
  their paths and bootstrap mechanics.
- Adapt the existing board to the new record until the following stage replaces
  it with status reporting.

### Stage 8 Behaviour

Round and assignment selection retains its existing priority and capacity rules.
The deliberate change is error handling: one errored round receives an ordinary
recovery opportunity without stopping unrelated work; two consecutive errors
fault that assignment; and a second fault supplies evidence for a global
cooldown.

### Stage 8 Working-state checkpoint

The daemon remains able to dispatch new work while one assignment is in fault,
stops all launches when two assignments fault, and resumes recovery after the
cooldown. Tests cover interrupted rounds, one and two consecutive errors,
successful rounds which break an error sequence, faults on different
assignments, cooldown persistence across daemon restarts, and fault clearing at
the cooldown boundary. Existing priority, capacity, pull-request, and user-post
scenarios continue to pass.

## Stage 9: Replace the board with status reporting

### Stage 9 Outcome

`status.py` constructs a read-only `StatusReport` containing instance and daemon
facts, an `IssueStatus` for each relevant issue, and an `AgentAssignmentStatus`
for each assignment. `tui.py` renders those models and feeds without deriving
lifecycle or scheduling decisions.

### Stage 9 Work

- Replace `board.py`, `Board`, `QueuedIssue`, `SessionRow`, and
  `SessionStanding` with the status-report model and constructor described by
  the target architecture.
- Include instance-wide facts such as daemon state, latest scheduler tick,
  capacity, and active global cooldown.
- Give each issue status independent claimed-here, claimed-elsewhere, blocked,
  and routing-conflict facts and a derived availability value. Include every
  issue considered for new work and every issue with an open local assignment,
  even when its current labels, assignee, or route no longer select it.
- Give each assignment one derived summary status: working, waiting, needs user
  feedback, fault, complete, or unknown. Reuse the scheduler's pure issue and
  required-round interpretations rather than restating their rules.
- Derive status from assignment and round records, process state, configuration,
  scheduler observations, and latest feed output. Report when the external facts
  were observed. Continue to use GitHub facts observed by the daemon and
  recorded locally; the view commands must not acquire network access or mutate
  external state.
- Replace the `board` command with `status`. Present issues and assignments as
  distinct concepts and remove queue position, “needs you”, “stuck”, “awake”,
  and “asleep” language.
- Keep the `assignment` and `feed` views, including selection of the newest
  assignment for an issue and selection of a numbered agent round. Make labels
  distinguish issue identifiers, agent assignment identifiers, and harness
  session identifiers wherever more than one appears.
- Preserve terminal watching, alternate-screen handling, non-terminal one-shot
  rendering, feed streaming, and the rules for when assignment and round views
  finish.
- Remove remaining status projections from `state.py`, leaving only state paths
  and bootstrap mechanics there.
- Replace board and session golden fixtures with status and assignment fixtures
  produced by the new view. Do not edit raw harness recordings.
- Rewrite the relevant `README.md` command and operations sections to describe
  the status report rather than a board or queue.

### Stage 9 Behaviour

This stage intentionally changes status terminology and organization. It does
not change scheduling, GitHub observations, assignment or round lifecycles, feed
contents, or the mechanics of watching a running instance.

### Stage 9 Working-state checkpoint

The user can run `status`, `assignment`, and `feed` against a running or stopped
instance and obtain a coherent local view. Truth-table tests show that status
and scheduling interpret the same underlying facts consistently, while
dependency tests ensure that scheduling never consumes a `StatusReport` and the
TUI never performs domain decisions.

## Stage 10: Complete the descriptive-symbol audit

### Stage 10 Issue

Use existing issue GH71 for this stage.

### Stage 10 Outcome

Every surviving symbol describes its value or action clearly at the point of
use, including when an exported name is imported without its module qualifier.
The audit confirms the target architecture rather than introducing another round
of structural change.

### Stage 10 Work

- Review every source module systematically after the preceding migrations,
  following definitions and references rather than searching only for a list of
  known vague words.
- Give functions and methods verb phrases which say what they do.
- Give booleans names which state the question they answer.
- Give exported classes, functions, and values enough context to remain clear
  when imported bare.
- Distinguish issue, agent assignment, agent round, harness session, scheduler,
  status, and user-post concepts consistently. Retain “session” only where it
  specifically means a harness session.
- Replace remaining vague names such as generic findings, looks, launches,
  endings, holders, or abbreviated local names when the surrounding code does
  not make their meaning immediate.
- Update tests and current documentation for renamed public symbols. Do not
  rewrite historical specifications or alter text inside recorded harness output
  fixtures.

### Stage 10 Behaviour

This stage is behaviour-preserving. It must not change persistence, commands,
prompts, scheduling policy, status derivation, or process supervision while
renaming symbols.

### Stage 10 Working-state checkpoint

The complete suite proves that each rename preserves behaviour, and a final
reference scan finds no stale imports or uses. A reader can follow each target
architectural boundary without translating old domain names or guessing what an
exported symbol means.

## Stage 11: Rewrite the docstrings

### Stage 11 Issue

Use existing issue GH65 for this stage.

### Stage 11 Outcome

The final codebase explains itself in direct, natural language which uses the
ontology consistently and accurately describes each symbol's actual
responsibility.

### Stage 11 Work

- Review every source module, class, function, and method rather than limiting
  the pass to docstrings already known to be difficult.
- Rewrite indirect, literary, or implementation-first explanations as plain
  descriptions of who performs an action, what it does, when it does it, and why
  that matters to a caller.
- Keep summaries concise, but include operational details where they define a
  contract, recovery rule, conservative failure, or cross-platform guarantee.
- Make every docstring agree with its symbol name and signature and with the
  ownership assigned by the target architecture.
- Use issue, agent assignment, agent round, round purpose, recovery, user post,
  harness session, scheduler, and status-report terms with their defined
  meanings.
- Remove claims about superseded session, wake-up, queue, board, stuck, and
  blanket-cooldown behaviour.
- Leave historical specifications and recorded harness output unchanged.

### Stage 11 Behaviour

This stage changes prose only. It must not alter executable statements,
persistence, commands, prompts, scheduling, rendering, or tests merely to make a
docstring easier to write.

### Stage 11 Working-state checkpoint

All documentation and code-quality checks pass, the complete test suite remains
green, and a final source review finds no docstring which describes a different
name, decision owner, state, or behaviour from the code beneath it.

## Completion criteria

The migration is complete when:

- the principal modules and dependency direction match the target architecture;
- every concept represented in code, current documentation, package metadata,
  and user-facing output uses the ontology consistently;
- `sessions.py`, `rounds.py`, `eligibility.py`, `wakeups.py`, and `board.py` no
  longer exist, and their responsibilities each have one target owner;
- `state.py` contains paths and bootstrap mechanics rather than scheduling or
  status models;
- Dreamcatcher-owned structured documents remain strict and atomically written,
  GitHub responses remain tolerant projections, and subprocesses still run only
  through `commands.py`;
- no prompt, transport format, command behaviour, scheduling decision, or view
  mechanic has changed except where the behaviour budget permits it;
- `README.md`, `CONTRACT.md`, `docs/ontology.md`, and `docs/architecture.md`
  agree with the implementation; and
- the full test and check suite passes on Windows, macOS, and Linux.

## Preparing the implementation issues

After this roadmap is merged, create one GH76 subissue for each of Stages 1–9.
Use existing issues GH71 and GH65 for Stages 10 and 11. Each issue should link
to its roadmap section and treat it as the accepted scope rather than repeating
or elaborating the design independently.

Make each stage depend on the preceding stage, including making GH71 depend on
Stage 9 and GH65 depend on GH71. This preserves the reviewed merge order while
leaving every issue and pull request independently understandable.
