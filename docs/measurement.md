# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-23 at `9cae9cde`, for the v9.0.0 release
preparation. The review covers the 23 pull requests merged since v8.0.0,
with particular attention to the shared issue listing, ended worktree
removal, harness feeds, round inputs and status reporting. The
consistency review and issue triage ran beside this measurement.

## Results

| Criterion                              | Measured                                                                                                                   | Status  | Issue      |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------- | ---------- |
| S1 Modules are cohesive                | 0 reviewed modules without one nameable responsibility                                                                     | met     |            |
| S2 Functions do one thing              | 0 reviewed functions without one nameable job                                                                              | met     |            |
| S3 Exports are used                    | 31 public definitions without a direct named importer; each is a model, protocol, entry point or part of a named interface | met     |            |
| S4 Each thing is done one way          | Previous round-input and GitHub identity findings resolved; no new duplicate derivation established                        | met     |            |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                                                                             | met     |            |
| C1 One vocabulary                      | Previous vocabulary findings resolved; 2 supported symbol-contract disagreements remain                                    | not met | #757, #758 |
| C2 Enduring documents are true         | 1 stale architecture sentence corrected; cancellation and conversation-answer promises have known counterexamples          | not met | #757, #758 |
| C3 Documentation by purpose            | Tutorial, task guides, references and explanations remain separate; no new page                                            | met     |            |
| C4 Formats and contracts are versioned | State format 8 requires v9.0.0; contract remains 1; breaking entry and upgrade instructions present                        | met     |            |
| K1 Structural rules checked by machine | The 5 named rules remain checked                                                                                           | met     |            |
| K2 Suite is fast and speaks plainly    | 57.57 seconds, 1,519 tests passed, 100% statement and branch coverage                                                      | met     |            |
| K3 Tracker is current                  | 15 open issues triaged; 4 bodies corrected; none ready to close                                                            | met     |            |
| K4 Every change reviewed to standard   | All 23 merged PRs answer all 7 definition-of-done questions                                                                | met     |            |
| E1 Rules, not cases                    | 11 ledger entries with external causes; no unsupported new case found                                                      | met     |            |
| E2 Invariants by construction          | 68 nullable class fields inspected; previous round-input defensive raises moved into model validation                      | met     |            |
| E3 Concept economy                     | No domain concept added; existing concepts gain more precise descriptions                                                  | met     |            |
| E4 Symmetry                            | Shared input validation and worktree removal cover all applicable kinds; cancellation retains its documented difference    | met     |            |

## Deferred work and previous findings

All five findings from the v8.0.0 measurement have fixes merged: #712
and #713 through #745 and #746, #714 through #747, #715 through #748,
and #716 through #749. Round-input validation now belongs to the models,
unused readers and package exports are gone, GitHub label and login
comparisons each have one home, the web feed uses position, and the
fault flag is `is_in_fault` throughout the code. The campaign input
keeps its contract's `is_fault` spelling through a serialization alias.

Two remaining disagreements, described below, already have issues. A
wrap-up can overwrite a cancellation and allow the worktree to be
removed (#757). A recorded Claude stream contains intermediate and empty
result events that the adapter treats as final answers (#758). Neither
is a quick documentation repair, and this preparation does not change
their implementation. The release checklist permits tracked shortfalls
while requiring every test and check to pass.

The triage read all 15 open issues against the ontology and current
code. It corrected #492's removed `Assignment` properties and earlier
state-format reference, #594's claim that the teammate story endorses
collaborator dispatch, #728's spelling of sub-issues, and #731's removed
listing field. No issue's requested work is complete. In particular,
issue #728 still asks why assignment requests first appear at different
updates; #739 fixed only the lag of an assignment card once work starts.

Other deferred work includes read-only collection fields on frozen
dataclasses (#731), duplicated test helpers (#735), slow macOS test
server construction (#755), failed-update reporting (#756), and unused
recorded-feed goldens (#759). The presentation questions remain open:
issues #733, #734, #736 and #737. Issues #32 and #594 also remain open.
The journal proposal #492 remains a design question rather than
completed work.

## Notes

- **S1, S2.** The largest modules are `github.py` (863 lines),
  `agent_rounds.py` (772), `status/agent_work.py` (575),
  `scheduler/tick.py` (512), `agent_work.py` (478), `web/app.py` (467)
  and `status/report.py` (464). They retain their boundary's one
  responsibility. The tick grows to remove ended worktrees and assemble
  the scheduler record once, after launches. Status owns the new trigger
  descriptions and section guidance; presentation consumes those values.

  | Function                                      | Lines | Its job                                     |
  | --------------------------------------------- | ----: | ------------------------------------------- |
  | `cli._build_cli_parser`                       |   187 | Define the command-line grammar.            |
  | `Scheduler.tick`                              |    84 | Follow the scheduler's update sequence.     |
  | `DreamcatcherDaemon.run`                      |    83 | Follow the daemon lifecycle.                |
  | `AgentRound.__init__`                         |    82 | Record and start one round.                 |
  | `scheduler.assignments._inspect_pull_request` |    66 | Inspect an assignment's channel.            |
  | `scheduler.campaigns._inspect_lead_input`     |    66 | Decide whether a lead round is due.         |
  | `Scheduler._launch`                           |    58 | Create work and start its round.            |
  | `commands.spawn_command`                      |    52 | Start a child and contain its process tree. |

- **S3, S4.** An AST inventory finds 31 public class or function
  definitions without a direct named import from another source module.
  Review also accounts for imports through module objects, package
  exports, document and view models, callback protocols and the console
  entry point. It establishes no unused public function. This count
  excludes constants and aliases, and is not a measure of unused code.
  Conversation and campaign readers now use their models' one validation
  rule. Login and label comparisons use `is_login_of_account` and
  `identify_label` in the scheduler and at their other callers.
- **S5, K1.** The three coverage pragmas remain at `teardown.py:20`,
  `teardown.py:110` and `commands.py:270`, all platform arms. The
  architecture tests and lint rules pass, with no suppression added.
- **C2.** The review compares the changed listing, worktree,
  round-input, feed and status paths with all four enduring documents.
  The architecture still said campaign cards used the assignment matched
  by the tick; #739 instead selects the newest local assignment. This
  preparation corrects that sentence. The two known story contradictions
  remain tracked below rather than weakening the stories to accept them.
- **C3, C4.** The documentation map retains pages by reader purpose.
  State format 8 records update completion and daemon-run start times;
  the compatibility opening already names v9.0.0 and format 8. Its
  upgrade instructions explain the fresh start, stopped views and
  retained older state. The agent contract remains version 1.
- **K2.** The default suite passed twice with 1,519 tests, one
  platform-only skip, and 100% statement and branch coverage. The first
  run took 71.82 seconds while the repository checks also ran. A repeat
  with those checks finished took 57.57 seconds. Its slowest test was
  `test_a_closed_parent_ends_the_campaign_once_its_round_finishes`, at
  21.92 seconds. The separate browser and read-only GitHub integration
  groups passed together: 36 tests, one platform-only skip, 24.17
  seconds. Every pre-commit check passed. Local timing does not
  establish timing on the other platforms; CI covers their behaviour.
- **K4.** The reviewed PRs are #725, #726, #727, #729, #730, #732, #738,
  #739, #740, #741, #742, #743, #744, #745, #746, #747, #748, #749,
  #750, #751, #752, #753 and #754. Each explains the change, links its
  issue and answers all seven questions. No Dependabot PR merged in this
  interval.
- **E1.** The ledger now has 11 entries. It removes subagent text
  suppression and adds Claude's handback-report fallback and Codex's
  collaboration-item start event. These have external protocol causes.
  Worktree removal, label identity, input order, hidden successful
  outcomes and unrouted guidance apply the documented general rules.
- **E2, E3, E4.** The nullable-field inventory is a prompt for review,
  not a target count. No new defensive raise for an impossible internal
  combination was established. Ordered comments and nonempty
  conversation input are validated at construction. Conversation and
  campaign inputs share that ordering rule; all kinds share
  ended-worktree removal, and only assignments remove a branch.
  Cancelled assignments keep their worktrees, subject to #757. No new
  domain concept is required.

## Semantic Consistency Review

### Scope

The namespace, source stubs, changed symbol contracts, enduring and user
documents, recorded feeds, templates and open issues were reviewed,
weighted to changes since v8.0.0. Formatting and design preferences are
excluded. Existing issues are reused for supported findings.

### Summary

The previous vocabulary disagreements are resolved. Two supported
symbol-contract disagreements remain, both already tracked.

### Vocabulary findings

No supported vocabulary disagreement remains after the tracker edits.
The campaign input's wire alias is intentional compatibility, not a
second meaning for fault.

### Symbol-contract findings

#### 1. A write-once document can replace its earlier value

**Claim A** — `src/dreamcatcher/documents.py` ·
`WriteOnceDreamcatcherDocument` · docstring

> Model a document that dreamcatcher writes at most once.

**Claim B** — `src/dreamcatcher/documents.py` · `write_text` · body

> `lock = _hold_document_lock(path=path) if is_replaceable else nullcontext()`
>
> `staged.replace(path)`

**How they differ:** The write-once flag skips locking but does not
prevent replacement. A later ending can replace a cancellation (#757).

**Why these should agree:** `end_agent_work` constructs an
`AgentWorkEnding`, a write-once model, and `write_json` passes its
`is_replaceable` flag to this writer.

#### 2. Claude result events need not close the round

**Claim A** — `src/dreamcatcher/claude.py` · `_read_round_result` ·
docstring

> Return the usage, outcome, and final text that close the round.

**Claim B** — `tests/fixtures/claude/subagents.jsonl` · first result at
line 38 · recorded output

> Both subagents are still running, so I'll wait for their reports.

**How they differ:** Five result events follow the background subagents,
including waiting messages and empty results. The adapter exposes each
as final output, although an earlier one does not close the round
(#758).

**Why these should agree:** This is the recorded Claude event stream
that the adapter reads, and a conversation posts the adapter's final
output as its answer.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- AST inventories over `src` count public definitions without direct
  named importers and class fields whose own annotation admits `None`.
  Package exports and module-object callers are reviewed separately.
- The namespace and stubs guide targeted body reads and the diff from
  v8.0.0. The docs map guides the documentation review.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the tracker triage.
