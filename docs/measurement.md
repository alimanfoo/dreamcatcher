# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-27 at `176790cb`, for the v9.4.0 release
preparation. The review covers the two pull requests merged since
v9.3.0: PR #819, which reads who applied a label so that a renamed label
still counts as the user's, and PR #820, which names the default
dispatch labels after the kind of work they ask for. The consistency
review and issue triage ran beside this measurement.

## Results

| Criterion                              | Measured                                                                                                                  | Status | Issue |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------ | ----- |
| S1 Modules are cohesive                | 0 reviewed modules without one nameable responsibility                                                                    | met    |       |
| S2 Functions do one thing              | 0 reviewed functions without one nameable job                                                                             | met    |       |
| S3 Exports are used                    | 32 public definitions without a direct named importer, as at v9.3.0; `github.LabellingEvent` replaces `github.IssueEvent` | met    |       |
| S4 Each thing is done one way          | Who applied a label is still read once, in `github.list_labelling_events`, and judged once, in `scheduler/labelling.py`   | met    |       |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                                                                            | met    |       |
| C1 One vocabulary                      | 2 disagreements found, both corrected in this preparation                                                                 | met    |       |
| C2 Enduring documents are true         | #819 added the rename story and the unrecorded-label fault; the ontology's **Unknown** status widened here to match       | met    |       |
| C3 Documentation by purpose            | Tutorials, task guides, references and explanations remain separate; the configure guide gains a task section             | met    |       |
| C4 Formats and contracts are versioned | State format 8 unchanged since v9.0.0; contract remains 1                                                                 | met    |       |
| K1 Structural rules checked by machine | The 5 named rules remain checked; #811 will move the import rules to import-linter contracts                              | met    |       |
| K2 Suite is fast and speaks plainly    | 40.71 seconds, 1,571 tests passed, 100% statement and branch coverage                                                     | met    |       |
| K3 Tracker is current                  | 12 open issues triaged; 1 body corrected; none ready to close                                                             | met    |       |
| K4 Every change reviewed to standard   | #819 and #820 answer all 7 definition-of-done questions                                                                   | met    |       |
| E1 Rules, not cases                    | 11 ledger entries, unchanged; the one new conditional applies the rule that an unrecorded label cannot yet be judged      | met    |       |
| E2 Invariants by construction          | 72 nullable class fields, unchanged                                                                                       | met    |       |
| E3 Concept economy                     | No domain concept added                                                                                                   | met    |       |
| E4 Symmetry                            | A rename keeps requests and open assignments; open conversations and campaigns pause, as the rename story accepts         | met    |       |

## Deferred work and previous findings

The v9.3.0 measurement left no disagreement open and filed no follow-up.

Since v9.3.0, triage found that GitHub's REST events name a label as it
was called when it was applied, so a renamed dispatch label read as
applied by an unknown account (#818). #819 reads the events through
GraphQL, which names each label as it is called now, and treats a label
whose event GitHub has not yet recorded as one the update cannot tell
about yet. It found that an open conversation or campaign knows its
label by name, so a rename pauses it; the stories accept that, and #821,
which proposed recording a label's identity, was closed as not planned.
PR #820 then renamed the default labels to `agent-conversation`,
`agent-assignment`, `agent-assignment-easy` and `agent-campaign` (#816),
and the configure guide now says to choose between the two assignment
routes by how hard the work is.

Triage in this interval also accepted #811 (import-linter in place of
the architecture test), #813 (titles in place of the standard's codes
and numbers, folding in #807), #814 (drop the typing effect that left
gaps in the feed), #817 (rename the ontology to Concepts) and #822 (a
request row shown beside the work it just started). It closed #812,
keeping the keyword-parameters script. The four triage-outcome labels
now say in their descriptions that they are never applied when filing.

The release triage read all 12 open issues against the ontology and the
code. It corrected one body: #492's example record now names the
`agent-assignment` label. No issue's work is done, so none was closed.

Issues #32, #492, #762, #803, #805, #806, #810, #811, #813, #814, #817
and #822 remain open.

## Notes

- **S1, S2.** The largest modules are `github.py` (931 lines),
  `agent_rounds.py` (785), `status/agent_work.py` (619),
  `scheduler/tick.py` (514) and `agent_work.py` (484). They retain their
  boundary's one responsibility. `github.py` grows by the GraphQL query
  for labelling events and the projection of one page of them. The
  longest functions are those of v9.3.0, with the same jobs.

  | Function                                      | Lines | Its job                                     |
  | --------------------------------------------- | ----: | ------------------------------------------- |
  | `cli._build_cli_parser`                       |   187 | Define the command-line grammar.            |
  | `AgentRound.__init__`                         |    82 | Record and start one round.                 |
  | `DreamcatcherDaemon.run`                      |    82 | Follow the daemon lifecycle.                |
  | `Scheduler.tick`                              |    81 | Follow the scheduler's update sequence.     |
  | `scheduler.assignments._inspect_pull_request` |    66 | Inspect an assignment's channel.            |
  | `scheduler.campaigns._inspect_lead_input`     |    66 | Decide whether a lead round is due.         |
  | `Scheduler._launch`                           |    61 | Create work and start its round.            |
  | `commands.spawn_command`                      |    52 | Start a child and contain its process tree. |

- **S3, S4.** An AST inventory finds 32 public class or function
  definitions without a direct named import from another source module,
  the same count as at v9.3.0. `github.LabellingEvent`, which
  `list_labelling_events` returns, replaces `github.IssueEvent`. Review
  also accounts for imports through module objects, package exports,
  document and view models, callback protocols and the console entry
  point. It establishes no unused public function.
- **S5, K1.** The three coverage pragmas remain at `teardown.py:20`,
  `teardown.py:110` and `commands.py:270`, all platform arms. The
  architecture tests and lint rules pass, with no suppression added.
- **C1, C2.** The consistency review below found two disagreements, both
  about the label whose event GitHub has not yet recorded, and both are
  corrected here. #819 corrected the stories in the same change, and
  #820 every page that named a default label. Every `dream:*` name left
  in the documents, the source and the documentation home page names a
  skill, not a label.
- **C3, C4.** The documentation map retains pages by reader purpose. The
  configure guide gains "Match the recipe to how hard the work is", a
  task section. State format 8 and the agent contract's version 1 are
  unchanged. The default configuration that `init` writes changes, but
  `init` leaves an existing `dreamcatcher.toml` alone, and the changelog
  says how to switch.
- **K2.** The default suite passed with 1,571 tests, one platform-only
  skip, and 100% statement and branch coverage, in 40.71 seconds. Its
  slowest test was
  `test_a_closed_parent_ends_the_campaign_once_its_round_finishes`, at
  21.00 seconds. The separate browser and read-only GitHub integration
  groups passed together: 46 tests, one platform-only skip, 21.29
  seconds. The new integration test reads a real renamed label, on #638.
  Every pre-commit check passed. Local timing does not establish timing
  on the other platforms; CI covers their behaviour.
- **K4.** #819 and #820 each explain the change, link their issue and
  answer all seven questions. The maintainer reviewed both before they
  merged, and ran the integration tests for #819, which CI leaves out.
  No commit reached main outside a pull request.
- **E1.** The ledger keeps its 11 entries, none added or removed. The
  one new conditional, in `find_label_applied_by_other`, applies the
  rule that a read which cannot tell who applied a label starts nothing,
  as a failed read starts nothing.
- **E2, E3, E4.** The nullable-field inventory is unchanged. No domain
  concept is added: the new default labels use the ontology's words for
  the kinds of work. A rename treats requests and open assignments
  alike, because both are judged by the label as it is called now. Open
  conversations and campaigns differ, because each records its label by
  name when it starts, and the rename story names that difference.

## Semantic Consistency Review

### Scope

The namespace, the whole diff from v9.3.0, the source, templates,
enduring and user documents, the agent guide, the documentation home
page and the output a user sees were reviewed. Each change was checked
against the other claims about its concept: who applied a label and how
it is read, the request statuses, the read-failure finding, the default
labels and every remaining `dream:*` name. Formatting and design
preferences are excluded.

### Summary

Two disagreements were found, and both were corrected in this
preparation.

### Vocabulary findings

#### 1. What "unknown" means

**Claim A** — `docs/stories.md` · "GitHub cannot be reached"

> An update that reads in between cannot tell who applied it, so it
> starts nothing for that label, and the row says that it cannot tell.

**Claim B** — `docs/ontology.md` · request statuses, and
`docs/run-and-monitor.md`

> **Unknown**: a read that decides whether work may start failed.

**How they differ:** A label whose event GitHub has not yet recorded
comes from a read that succeeded, yet its row is unknown. The ontology,
the guide and the `ReadFailureFinding` docstring now also name a read
that could not yet tell.

### Symbol-contract findings

#### 2. What an empty applier means

**Claim A** — `src/dreamcatcher/scheduler/models.py` ·
`LabelAppliedByOtherFinding`

> An empty applier is an account that GitHub no longer names, or none at
> all when no event records the label being applied.

**Claim B** — `src/dreamcatcher/scheduler/labelling.py` ·
`find_label_applied_by_other`, which answers a label with no recorded
event with a `ReadFailureFinding`.

**How they differ:** An empty applier now means only a deleted account.
The docstring now says so, as `describe_label_applier` already did.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- AST inventories over `src` count public definitions without direct
  named importers and class fields whose own annotation admits `None`.
  Package exports and module-object callers are reviewed separately. The
  same inventories over v9.3.0 give the changes since then.
- The namespace and stubs guide targeted body reads and the diff from
  v9.3.0. The docs map guides the documentation review.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the tracker triage.
