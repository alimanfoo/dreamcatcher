# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](https://github.com/alimanfoo/dreamcatcher/blob/main/specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-11 at `2d3c972`, with the v5.5.0 release preparation.

## Results

| Criterion                              | Measured                                       | Status | Issue      |
| -------------------------------------- | ---------------------------------------------- | ------ | ---------- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility  | met    |            |
| S2 Functions do one thing              | 0 functions without one nameable job           | met    |            |
| S3 Exports are used                    | 33 names without an importer, all permitted    | met    |            |
| S4 Each thing is done one way          | 2 facts derived more than once                 | short  | #452, #455 |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas | met    |            |
| C1 One vocabulary                      | 2 disagreements                                | short  | #509, #511 |
| C2 Enduring documents are true         | 0 new contradictions                           | met    |            |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                    | met    |            |
| C4 Formats and contracts are versioned | state format 5, contract 1, both with policy   | met    |            |
| K1 Structural rules checked by machine | the 4 named rules checked                      | met    |            |
| K2 Suite is fast and speaks plainly    | 24 seconds on a laptop, 100% branch coverage   | met    |            |
| K3 Tracker is current                  | 42 issues reviewed; 5 corrected, none closed   | met    |            |
| K4 Every change reviewed to standard   | 10 pull requests answered; 7 name no issue     | short  | #510       |
| E1 Rules, not cases                    | 9 ledgered, all external; 4 unledgered         | short  | #419, #457 |
| E2 Invariants by construction          | 61 optional fields, 0 coupled sets             | met    |            |
| E3 Concept economy                     | 21 concepts; none added                        | met    |            |
| E4 Symmetry                            | 14 parallel operations; 1 uneven creation pair | short  | #456       |

## Shortfalls

- **S4.** The terminal and web views still derive issue-row status and evidence
  separately. That work waits on #455, which first settles how both kinds of
  agent work observe an issue. The rule that a round without an ending was
  interrupted once its daemon has gone remains in recovery, status and outcome
  reporting (#452).
- **C1.** The agent-facing contract calls `dream:scout` a conversation skill
  that follows the contract, and the skills guide routes a conversation label to
  a skill. The ontology defines only the assignment skill, and says a
  conversation recipe asks the agent to answer the user (#509).
- **C1.** The home page's terminal illustration writes an issue as `#41`, where
  `dreamcatcher status` writes `GH41`, and shows columns that the status view
  does not print (#511).
- **K4.** #499 to #505 came from one review of the documentation sites. Each
  answers every definition-of-done question, but answers the first with "No
  issue or spec". The standard does not say whether a change may serve neither
  (#510).
- **E1.** Four unledgered conditionals remain. The conversation scheduler
  returns early when no routes are configured, the templates place retry apart
  from the other controls, and the assignment card compares its status with
  display text (#419). The web also parses blocked evidence to recover issue
  numbers (#457).
- **E4.** Assignment creation is a class method, while conversation creation is
  a module function. Giving both creators one shape waits for the record-first
  setup design (#456, blocked by #425).

## Notes

- **Since v5.4.0.** Ten pull requests merged. #491 records which specification
  phases are complete. #497 makes the placeholder commit and push of an
  assignment setup skip the repository's hooks. #499 to #505 introduce dream in
  the documentation, give the site a home page, a dusk scheme and new type, and
  move the skills into a "Customise skills" guide. #507 gives the web nature
  theme a dusk look and a moon when the system is in dark mode. Python source
  changed only in `git.py`.
- **S1, S2.** The largest modules are `github.py` (703 lines), `agent_rounds.py`
  (658) and `web/app.py` (598). They own GitHub projections and operations,
  round supervision, and HTTP routes respectively. `git.py` grew from 210 to 219
  lines and still owns the Git operations. The longest functions are unchanged
  and each does one job:

  | Function                   | Lines | Its one job                                              |
  | -------------------------- | ----: | -------------------------------------------------------- |
  | `cli._build_cli_parser`    |   190 | It holds the complete command-line grammar.              |
  | `read_status_report`       |    97 | It composes the instance's status report.                |
  | `AssignmentCreator.create` |    87 | It follows assignment creation as the ontology lists it. |
  | `AgentRound.__init__`      |    87 | It starts a round as one transaction.                    |
  | `DreamcatcherDaemon.run`   |    76 | It follows the daemon lifecycle in the architecture.     |
  | `Scheduler.tick`           |    55 | It follows the scheduler tick in the architecture.       |

- **S3.** The 33 names without a direct importer are unchanged. Document models,
  callback protocols and domain interfaces account for them.
- **C1.** The new conversation skill wording arrived with #499, whose answer to
  question 4 said it introduced no new term. Every other new word in the
  documentation, such as route, recipe and assignment skill, is the ontology's.
- **C2.** The architecture's account of assignment setup still holds after #497,
  since setup still makes an empty commit and pushes the branch. The known
  window in which a second daemon can run after the lock path is deleted, before
  the first daemon checks it, remains accepted as an edge case. No enduring
  claim newly contradicts the code.
- **C3, C4.** The new "Customise skills" guide sits with the how-to pages, and
  the home page links only user documentation. This release changes neither the
  state format nor the agent contract.
- **K1.** The architecture tests and subprocess lint rule still check the four
  named boundaries. No other rule has failed review more than once.
- **K2.** All 1,198 default tests passed with full branch coverage in 23.66
  seconds. All seven browser tests passed in 7.73 seconds. The new tests name
  behaviours a user sees, such as a placeholder commit that skips failing hooks
  and the moon crossing the dusk sky.
- **K3.** The triage read all 42 open issues against the ontology, and rewrote
  #391, #404, #492, #494 and #496 to its words. #498 carries no type label. No
  open issue's work is complete or obsolete.
- **K4.** All ten pull requests answer the seven definition-of-done questions.
  #491, #497 and #507 each close an issue.
- **E1.** The nature script's day and night ranges and the stylesheet's colour
  scheme query apply general rules. The four previously reported special cases
  remain outstanding.
- **E2.** The count of 61 is unchanged, since no model changed.
- **E3, E4.** The ontology is unchanged. The two creators' shape remains uneven,
  and the existing count of parallel operations stands.

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
