# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](https://github.com/alimanfoo/dreamcatcher/blob/main/specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-08 at `ec15db5`, with the v5.4.0 release preparation.

## Results

| Criterion                              | Measured                                       | Status | Issue      |
| -------------------------------------- | ---------------------------------------------- | ------ | ---------- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility  | met    |            |
| S2 Functions do one thing              | 0 functions without one nameable job           | met    |            |
| S3 Exports are used                    | 33 names without an importer, all permitted    | met    |            |
| S4 Each thing is done one way          | 2 facts derived more than once                 | short  | #452, #455 |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas | met    |            |
| C1 One vocabulary                      | 0 disagreements after 1 correction             | met    |            |
| C2 Enduring documents are true         | 0 new contradictions                           | met    |            |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                    | met    |            |
| C4 Formats and contracts are versioned | state format 5, contract 1, both with policy   | met    |            |
| K1 Structural rules checked by machine | the 4 named rules checked                      | met    |            |
| K2 Suite is fast and speaks plainly    | 39 seconds on a laptop, 100% branch coverage   | met    |            |
| K3 Tracker is current                  | 39 issues reviewed; 3 corrected, none closed   | met    |            |
| K4 Every change reviewed to standard   | all 5 pull requests since v5.3.0 answered      | met    |            |
| E1 Rules, not cases                    | 9 ledgered, all external; 4 unledgered         | short  | #419, #457 |
| E2 Invariants by construction          | 61 optional fields, 0 coupled sets             | met    |            |
| E3 Concept economy                     | 21 concepts; none added                        | met    |            |
| E4 Symmetry                            | 14 parallel operations; 1 uneven creation pair | short  | #456       |

## Shortfalls

- **S4.** The terminal and web views still derive issue-row status and evidence
  separately (#455). The rule that a round without an ending was interrupted
  once its daemon has gone remains in recovery, status and outcome reporting
  (#452). #488 removed the other five duplicated facts previously tracked by
  #379.
- **E1.** Four unledgered conditionals remain. The conversation scheduler
  returns early when no routes are configured, the templates place retry apart
  from the other controls, and the assignment card compares its status with
  display text (#419). The web also parses blocked evidence to recover issue
  numbers (#457).
- **E4.** Assignment creation is a class method, while conversation creation is
  a module function. Giving both creators one shape waits for the record-first
  setup design (#456, blocked by #425).

## Notes

- **Since v5.3.0.** #488 moves shared daemon facts, instance facts, agent-work
  ordering and sections, round revisions and recovery wording into status. #486
  completes the empty-panel guidance, #487 fixes `init` without assignment
  routes, #489 reports failed home refreshes, and #485 corrects the release-note
  heading instructions. The default `dream:less` recipes use medium effort after
  commit `2aa4d8b`.
- **S1, S2.** The largest modules are `github.py` (703 lines), `agent_rounds.py`
  (658) and `web/app.py` (598). They own GitHub projections and operations,
  round supervision, and HTTP routes respectively. `status/report.py` grew to
  522 lines as shared status derivations moved there. Its responsibility remains
  composing the read-only status report. The longest functions each do one job:

  | Function                   | Lines | Its one job                                              |
  | -------------------------- | ----: | -------------------------------------------------------- |
  | `cli._build_cli_parser`    |   190 | It holds the complete command-line grammar.              |
  | `read_status_report`       |    97 | It composes the instance's status report.                |
  | `AssignmentCreator.create` |    87 | It follows assignment creation as the ontology lists it. |
  | `AgentRound.__init__`      |    87 | It starts a round as one transaction.                    |
  | `DreamcatcherDaemon.run`   |    76 | It follows the daemon lifecycle in the architecture.     |
  | `Scheduler.tick`           |    55 | It follows the scheduler tick in the architecture.       |

- **S3.** The 33 names without a direct importer are unchanged. Document models,
  callback protocols and domain interfaces account for them. The added status
  models have production importers; the old web-only daemon model is removed.
- **C1.** The consistency review found that `read_status_report`'s docstring
  named local state alone although the function now reads the current route
  configuration too. The release preparation corrects that summary. The setup
  guidance disagreements recorded at v5.3.0 are resolved by #486 and #487. No
  supported vocabulary disagreement remains after issue triage.
- **C2.** The architecture now assigns the current route read and section
  descriptions to status. The known window in which a second daemon can run
  after the lock path is deleted, before the first daemon checks it, remains
  accepted as an edge case. No enduring claim newly contradicts the code.
- **C3, C4.** The documentation map separates the tutorial, task guides, command
  and configuration references, and design explanations. This release changes
  neither the state format nor the agent contract.
- **K1.** The architecture tests and subprocess lint rule still check the four
  named boundaries. No other rule has failed review more than once.
- **K2.** All 1,196 default tests passed with full branch coverage in 39.05
  seconds. All six browser tests passed in 12.84 seconds. Test names describe
  behaviours, including failed refreshes and route-dependent setup guidance.
- **K3.** Triage changed #404's terminology from work item to agent work,
  updated #455's remaining issue-row work after #488 closed #379, and extended
  #483 to cover terminal status, which now reads the configuration too. #489
  resolved the silent-refresh failure that #483 referenced. No open issue's work
  was wholly complete or obsolete.
- **K4.** #485, #486, #487, #488 and #489 each name the issue or release
  procedure they serve and answer all seven definition-of-done questions.
- **E1.** The new status branches apply general rules for known facts,
  configured or recorded work, and optional presentation values. The failed
  refresh warning applies to every reportable home refresh failure. The four
  previously reported special cases remain outstanding.
- **E2.** The count rises from 59 to 61 after the status section models replace
  separate web empty-panel messages. The optional fields introduce no coupled
  set requiring a defensive check.
- **E4.** The shared status sections and round descriptions remove presentation
  duplication. The two creators' shape remains uneven, and the existing count of
  parallel operations stands.

## Method

- **S1, S2.** `tools/measure_source.py` reports module line counts and the ten
  longest functions. Review names each module's responsibility, largest first,
  and each long function's job, longest first.
- **S3.** Parse every module under `src`. Collect each module-level class,
  function, assignment and type alias whose name has no leading underscore.
  Remove a name when another source module imports it directly. Classify what
  remains as a document model, a view model a template consumes, or an interface
  the architecture names.
- **S4, C1.** Run the `uncoded-consistency-review` skill over the source, the
  enduring documents, the user documentation and the output a user sees.
- **C2.** Read the ontology, the architecture and the standard against the code,
  including recorded failure cases in open issues.
- **K2.** Time the default run on a laptop.
- **E1.** Read every conditional that names a particular situation against
  [the ledger](special-cases.md).
- **E2.** Count the class-level annotated fields, in dataclasses and pydantic
  models under `src`, whose type admits `None`. Read them for coupled sets.
- **E4.** Read the parallel names and the standing asymmetries in
  `specs/2026-09-30-engineering-standard/agent-work-shape.md` against the
  namespace map.
