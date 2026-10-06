# Measurement

This page holds the latest measurement of Dreamcatcher against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](https://github.com/alimanfoo/dreamcatcher/blob/main/specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-06 at `14b26af`, before v5.1.0.

## Results

| Criterion                              | Measured                                        | Status | Issue                  |
| -------------------------------------- | ----------------------------------------------- | ------ | ---------------------- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility   | met    |                        |
| S2 Functions fit on a screen           | 5 functions over 50 lines, each with its reason | met    |                        |
| S3 Exports are used                    | 30 names without an importer, all permitted     | met    |                        |
| S4 Each thing is done one way          | 8 facts derived twice                           | short  | #379–#380, #421        |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas  | met    |                        |
| C1 One vocabulary                      | 11 disagreements; 9 fixed with this measurement | short  | #429, #430             |
| C2 Enduring documents are true         | 0 statements; 1 corrected with this measurement | met    |                        |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                     | met    |                        |
| C4 Formats and contracts are versioned | state format 5, contract 1, both with policy    | met    |                        |
| K1 Structural rules checked by machine | the 4 named rules checked                       | met    | #383                   |
| K2 Suite is fast and speaks plainly    | 26 seconds on a laptop, 100% branch coverage    | met    |                        |
| K3 Tracker is current                  | 0 issues in other words or for done work        | met    |                        |
| K4 Every change reviewed to standard   | 3 of 3 pull requests answered                   | met    |                        |
| E1 Rules, not cases                    | 10 ledgered, 1 internal cause; 4 unledgered     | short  | #418, #419             |
| E2 Invariants by construction          | 55 optional fields, 0 coupled sets              | met    |                        |
| E3 Concept economy                     | 21 concepts; none added without a case          | met    |                        |
| E4 Symmetry                            | 14 parallel operations; 4 uneven sets           | short  | #382, #418, #420, #421 |

## Shortfalls

- **S4.** The terminal and web views each derive instance facts, issue rows,
  assignment order, round revisions and the recovery marker (#379). The
  scheduler and status each derive "claimed here" and "awaiting recovery"
  (#380). Each kind of agent work decides in its own way whether its last round
  needs recovery (#421).
- **C1.** The web writes an issue number as `#50` where the ontology and the
  terminal write `GH50` (#429). The product name is spelled both "dreamcatcher"
  and "Dreamcatcher" (#430). Each needs a decision before the words can agree.
- **E1.** The ledger's entry for a conversation that refuses a leftover worktree
  names a crash as its cause, but the refusal is this project's choice, and an
  assignment setup resumes the same leftover (#418). Four unledgered
  conditionals single out a case: the conversation scheduler's early return when
  no routes are configured, the templates' tests that place retry apart from the
  other controls, the web's parsing of "blocked" evidence for issue numbers, and
  the assignment card's comparison with the words "needs user feedback" (#419).
- **E4.** The assignment prompt names, and `StateDirectory.worktrees`, carry no
  kind while the conversation names do (#382). The two kinds create their work
  in different shapes and treat a leftover worktree differently (#418), match
  labels to routes under different names (#420), and decide recovery in
  different ways (#421).

## Notes

- **Since v5.0.0.** Two pull requests merged: the documentation site (#424) and
  the move of the stop and cancel controls (#427). Neither changed Python under
  `src` beyond docstrings, so S1 to S3, S5, E2 and E4 read as they did at
  v5.0.0. The measurement read them again rather than carry them over.
- **C1.** The consistency review found eleven disagreements. The release pull
  request that records this measurement fixes nine: "agent cap" for agent
  capacity, "dashboard" for the web home page, "ticks" in the contract, the web
  heading "Conversations", the contract's plural title, "session" for harness
  session in the `conversation` help, the `assignment` help's claim that the
  view ends while the assignment is in fault, a stale comment on that help, and
  the architecture's claim below. Users still read "update" where the ontology,
  the architecture and the code say "scheduler tick", which the ontology states.
- **C2.** The architecture said an assignment stays open until a successful
  wrap-up round, but a cancel also ends it. The release pull request corrects
  it.
- **C3.** The documentation is now a site built from `docs/`. It publishes the
  developer pages in a Development section of their own, and no user page links
  to one.
- **K3.** Triage rewrote six issues and closed none. #68 named a test helper
  since renamed, #382 the contract's old path, and #419 a template #427 removed.
  #109, #113 and #125 said "repository" for the Dreamcatcher instance. #119 and
  #425 got smaller corrections outside K3.
- **K4.** Every pull request merged since the last measurement, #422, #424 and
  #427, answers the definition of done.
- **E1.** #427 removed the cancel-only confirmation test by taking each
  control's confirmation from one table, and added the retry placement tests in
  its place, so the count of unledgered conditionals is unchanged.
- **E2.** Nine `cast(...)` calls assert that an optional value is present, as at
  v5.0.0. The method below does not count them.

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
- **C2.** Read the ontology, the architecture and the standard against the code.
- **K2.** Time the default run on a laptop.
- **E1.** Read every conditional that names a particular situation against
  [the ledger](special-cases.md).
- **E2.** Count the class-level annotated fields, in dataclasses and pydantic
  models under `src`, whose type admits `None`. Read them for coupled sets.
- **E4.** Read the parallel names and the standing asymmetries in
  `specs/2026-09-30-engineering-standard/agent-work-shape.md` against the
  namespace map.
