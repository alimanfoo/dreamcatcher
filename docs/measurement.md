# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](https://github.com/alimanfoo/dreamcatcher/blob/main/specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-07 at `a503c8f`, with the v5.3.0 release preparation.

## Results

| Criterion                              | Measured                                       | Status | Issue            |
| -------------------------------------- | ---------------------------------------------- | ------ | ---------------- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility  | met    |                  |
| S2 Functions do one thing              | 0 functions without one nameable job           | met    |                  |
| S3 Exports are used                    | 33 names without an importer, all permitted    | met    |                  |
| S4 Each thing is done one way          | 7 facts derived more than once                 | short  | #379, #452, #455 |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas | met    |                  |
| C1 One vocabulary                      | 2 disagreements after 3 corrections            | short  | #481, #482       |
| C2 Enduring documents are true         | 0 contradictions after 2 corrections           | met    |                  |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                    | met    |                  |
| C4 Formats and contracts are versioned | state format 5, contract 1, both with policy   | met    |                  |
| K1 Structural rules checked by machine | the 4 named rules checked                      | met    |                  |
| K2 Suite is fast and speaks plainly    | 28 seconds on a laptop, 100% branch coverage   | met    |                  |
| K3 Tracker is current                  | 39 issues reviewed; 1 corrected, none closed   | met    |                  |
| K4 Every change reviewed to standard   | all 7 pull requests since v5.2.0 answered      | met    |                  |
| E1 Rules, not cases                    | 9 ledgered, all external; 4 unledgered         | short  | #419, #457       |
| E2 Invariants by construction          | 59 optional fields, 0 coupled sets             | met    |                  |
| E3 Concept economy                     | 21 concepts; none added                        | met    |                  |
| E4 Symmetry                            | 14 parallel operations; 1 uneven creation pair | short  | #456             |

## Shortfalls

- **S4.** The terminal and web views each derive instance facts, issue rows,
  assignment order, round revisions, the recovery marker and whether a kind of
  agent work has anything to show. #379 covers five of these; its issue-row work
  waits for the observation design in #455. The rule that a round without an
  ending was interrupted once its daemon has gone is written in recovery, status
  and outcome reporting (#452).
- **C1.** `init` and the web home page each tell the user how to start work, in
  different words and from different routes. `init` reads the first assignment
  route, which #460 made optional, so it fails on a configuration without one
  (#481). The web names the labels but not the assignment to the signed-in
  account, nor the comment a conversation waits for (#482).
- **E1.** Four unledgered conditionals remain. The conversation scheduler
  returns early when no routes are configured, the templates place retry apart
  from the other controls, and the assignment card compares its status with
  display text (#419). The web also parses blocked evidence to recover issue
  numbers (#457).
- **E4.** Assignment creation is a class method, while conversation creation is
  a module function. Giving both creators one shape waits for the record-first
  setup design (#456, blocked by #425).

## Notes

- **Since v5.2.0.** #460 makes assignment routes optional, as conversation
  routes already were, and has the web home page name the route labels when a
  panel is empty. #464 and #466 change the web header links. #468 has the daemon
  check its lock file after each wait, which closed #41 and the C2 shortfall it
  recorded. #479 and #480 update development dependencies, and #469 sets up
  Dependabot. This release changes S2 to judge a function's job rather than its
  length, as S1 judges a module, and exempts Dependabot's pull requests from K4.
- **S1, S2.** The largest modules are `github.py` (703 lines), `agent_rounds.py`
  (658) and `web/app.py` (608). They own GitHub projections and operations,
  round supervision, and HTTP routes respectively. `lock.py` grew from 85 to 121
  lines and still owns the daemon lock alone. The longest functions each do one
  job:

  | Function                   | Lines | Its one job                                              |
  | -------------------------- | ----: | -------------------------------------------------------- |
  | `cli._build_cli_parser`    |   190 | It holds the complete command-line grammar.              |
  | `AssignmentCreator.create` |    87 | It follows assignment creation as the ontology lists it. |
  | `AgentRound.__init__`      |    87 | It starts a round as one transaction.                    |
  | `DreamcatcherDaemon.run`   |    76 | It follows the daemon lifecycle in the architecture.     |
  | `Scheduler.tick`           |    55 | It follows the scheduler tick in the architecture.       |
  | `compose_home_view`        |    55 | It composes the home page view, one field after another. |

- **S3.** The 33 names are the same as at v5.2.0. The new `WebDaemon` view model
  has an importer, and the lock's held-lock class is private.
- **C1.** The review corrected three claims. The `hold_daemon_lock` docstring
  called the held lock a checker. The `DreamcatcherDaemon.run` docstring left a
  lost lock out of the ways a run ends. The architecture, the command reference
  and the run guide said the web reads local state alone, although the home page
  now reads `dreamcatcher.toml` too. The page's dependence on that file is #483.
- **C2.** The ontology says at most one daemon runs an instance. If someone
  deletes the state directory during a run, a second daemon can still run for up
  to one interval before the first notices its lock has gone. That window is
  accepted as an edge case. The architecture's daemon lifecycle now lists the
  check after each wait, and the web section names the configuration read.
- **C3, C4.** The documentation map still separates the tutorial, task guides,
  command and configuration references, and design explanations. The
  configuration reference marks `assignment` optional. This release changes
  neither the state format nor the contract.
- **K1.** The architecture tests and the subprocess lint rule check all four
  named boundaries. No other rule has failed review more than once.
- **K2.** All 1,184 default tests passed with full branch coverage in 28.01
  seconds. Test names were read for behaviours rather than implementation names.
- **K3.** Triage corrected #379, which named a function that #464 renamed and
  now also lists the duplicated empty-work decision. No issue's requested work
  was wholly done or obsolete.
- **K4.** #460, #462, #464, #466, #468 and #469 each name their issue and answer
  all seven definition-of-done questions. #479 answers all seven too, as a
  dependency update that closes no issue. Dependabot raised #480, which K4
  exempts.
- **E1.** #460 and #468 add no special cases. Since #460 the assignment
  scheduler handles an empty route list without a guard, which makes the
  conversation scheduler's early return in #419 stand out more.
- **E2.** The four new optional fields are the web daemon's version and process
  identifier (#464) and the two empty-panel messages (#460). None forms a
  coupled set.
- **E4.** #460 removes an asymmetry in configuration, because both kinds of
  route are now optional. The count of parallel operations stands.

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
