# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](https://github.com/alimanfoo/dreamcatcher/blob/main/specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-07 at `0c37c52`, with the v5.2.0 release preparation.

## Results

| Criterion                              | Measured                                          | Status | Issue            |
| -------------------------------------- | ------------------------------------------------- | ------ | ---------------- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility     | met    |                  |
| S2 Functions fit on a screen           | 5 functions over 50 lines, each with its reason   | met    |                  |
| S3 Exports are used                    | 33 names without an importer, all permitted       | met    |                  |
| S4 Each thing is done one way          | 6 facts derived more than once                    | short  | #379, #452, #455 |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas    | met    |                  |
| C1 One vocabulary                      | 0 disagreements after 2 docstring corrections     | met    |                  |
| C2 Enduring documents are true         | 1 guarantee broken after state-directory deletion | short  | #41              |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                       | met    |                  |
| C4 Formats and contracts are versioned | state format 5, contract 1, both with policy      | met    |                  |
| K1 Structural rules checked by machine | the 4 named rules checked                         | met    |                  |
| K2 Suite is fast and speaks plainly    | 34 seconds on a laptop, 100% branch coverage      | met    |                  |
| K3 Tracker is current                  | 39 issues reviewed; 10 corrected, none closed     | met    |                  |
| K4 Every change reviewed to standard   | all 12 pull requests since v5.1.0 answered        | met    |                  |
| E1 Rules, not cases                    | 9 ledgered, all external; 4 unledgered            | short  | #419, #457       |
| E2 Invariants by construction          | 55 optional fields, 0 coupled sets                | met    |                  |
| E3 Concept economy                     | 21 concepts; none added without a case            | met    |                  |
| E4 Symmetry                            | 14 parallel operations; 1 uneven creation pair    | short  | #456             |

## Shortfalls

- **S4.** The terminal and web views each derive instance facts, issue rows,
  assignment order, round revisions and the recovery marker. #379 covers four of
  these; its issue-row work waits for the observation design in #455. The rule
  that a round without an ending was interrupted once its daemon has gone is
  written in recovery, status and outcome reporting (#452).
- **C2.** The ontology says at most one daemon runs an instance. Deleting the
  state directory during a run removes the shared lock file while the first
  daemon continues; a second daemon can then acquire a new lock file (#41).
- **E1.** Four unledgered conditionals remain. The conversation scheduler
  returns early when no routes are configured, the templates place retry apart
  from the other controls, and the assignment card compares its status with
  display text (#419). The web also parses blocked evidence to recover issue
  numbers (#457).
- **E4.** Assignment creation is a class method, while conversation creation is
  a module function. Giving both creators one shape waits for the record-first
  setup design (#456, blocked by #425).

## Notes

- **Since v5.1.0.** `init` adds a repository-setup boundary and shares the main
  checkout, GitHub identity and harness checks with `run`. #443 gives claimed
  here and awaiting recovery one derivation for scheduling and status. #451
  makes prompt and worktree names parallel, #447 makes route matching parallel,
  and #453 makes both creators reuse leftover worktrees. These changes remove
  the shortfalls previously tracked in #380, #382, #418, #420 and #421.
- **S1, S2.** The largest modules are `github.py` (703 lines), `agent_rounds.py`
  (658) and `web/app.py` (602). They own GitHub projections and operations,
  round supervision, and HTTP routes respectively. The five long functions
  retain the reasons reported by `tools/measure_source.py`:

  | Function                   | Lines | Reason it stays whole                                    |
  | -------------------------- | ----: | -------------------------------------------------------- |
  | `cli._build_cli_parser`    |   190 | It holds the complete command-line grammar.              |
  | `AssignmentCreator.create` |    87 | It follows assignment creation as the ontology lists it. |
  | `AgentRound.__init__`      |    87 | It starts a round as one transaction.                    |
  | `DreamcatcherDaemon.run`   |    73 | It follows the daemon lifecycle in the architecture.     |
  | `Scheduler.tick`           |    55 | It follows the scheduler tick in the architecture.       |

- **S3.** The 33 names are document models or parts of interfaces the
  architecture names, including callback protocols, scheduling candidates and
  interpretations, durable delivery-position readers, and command entry points.
  No view-model field or public name was counted as unused merely because a
  template reads it.
- **C1.** The consistency review corrected two unsupported docstring claims. The
  startup sweep described its stale-PID window as the same window as live round
  teardown, although it can span the interval between daemon runs (#61). The
  Codex item reader said a todo list was the only unhandled item a round sends,
  although collaboration items are also omitted (#97). The docstrings now
  describe the current limits; those issues remain open for their behaviour
  changes. No other vocabulary or symbol-contract disagreement was supported.
- **C3, C4.** The documentation map still separates the tutorial, task guides,
  command and configuration references, and design explanations. `init` is in
  the command reference. The compatibility policy, state format and agent
  contract agree, and this release changes neither version.
- **K1.** #446 brought the K1 bar into line with the standard's rule for
  admitting a machine check. The architecture tests and subprocess lint rule
  check all four named boundaries; no additional rule was found that meets the
  admission rule and lacks a check.
- **K2.** All 1,175 default tests passed with full branch coverage in 34.11
  seconds. A first run alongside the repository checks took 61.02 seconds, so
  the final measurement ran without those checks in parallel. Test names were
  read for behaviours rather than implementation names.
- **K3.** Triage corrected product-name casing in #109, #113, #125 and #188, the
  remaining conditional count in #419, the leftover-worktree description in
  #425, the mutable-container example in #44, and the command list in #119. #61
  and #97 now distinguish the corrected documentation from their outstanding
  behaviour changes. No issue's requested work was wholly done or obsolete.
- **K4.** #436–#439, #441, #443, #446–#449, #451 and #453 each name their issue
  or spec and answer all seven definition-of-done questions.
- **E1.** #453 removed the ledger's internal-cause entry for refusing a leftover
  conversation worktree. All nine remaining entries have external causes.
- **E2, E4.** The optional-field audit found no coupled sets. Thirteen casts
  were reviewed separately and are not included in that count. The namespace map
  confirms the parallel operations, with the creation-shape difference above.
  The observation design in #455 remains a question to settle; the existing
  differences in eligibility and observation content are named by the ontology.

## Method

- **S1, S2.** `tools/measure_source.py` reports module and function line counts,
  and the reason each long function stays whole. Review names each module's
  responsibility, largest first.
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
