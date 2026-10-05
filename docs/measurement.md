# Measurement

This page holds the latest measurement of Dreamcatcher against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](../specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-06 at `fe427d4`, before v5.0.0.

## Results

| Criterion                              | Measured                                        | Status | Issue                  |
| -------------------------------------- | ----------------------------------------------- | ------ | ---------------------- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility   | met    |                        |
| S2 Functions fit on a screen           | 5 functions over 50 lines, each with its reason | met    |                        |
| S3 Exports are used                    | 30 names without an importer, all permitted     | met    |                        |
| S4 Each thing is done one way          | 8 facts derived twice                           | short  | #379–#380, #421        |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas  | met    |                        |
| C1 One vocabulary                      | 0 disagreements, after this release's fixes     | met    |                        |
| C2 Enduring documents are true         | 0 statements; 2 corrected with this measurement | met    |                        |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                     | met    |                        |
| C4 Formats and contracts are versioned | state format 5, contract 1, both with policy    | met    |                        |
| K1 Structural rules checked by machine | the 4 named rules checked                       | met    | #383                   |
| K2 Suite is fast and speaks plainly    | 23 seconds on a laptop, 100% branch coverage    | met    |                        |
| K3 Tracker is current                  | 0 issues in other words or for done work        | met    |                        |
| K4 Every change reviewed to standard   | 17 of 17 pull requests answered                 | met    |                        |
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
- **E1.** The ledger's entry for a conversation that refuses a leftover worktree
  names a crash as its cause, but the refusal is this project's choice, and an
  assignment setup resumes the same leftover (#418). Four unledgered
  conditionals single out a case: the conversation scheduler's early return when
  no routes are configured, the template's test for the cancel control, the
  web's parsing of "blocked" evidence for issue numbers, and the assignment
  card's comparison with the words "needs user feedback" (#419).
- **E4.** The assignment prompt names, and `StateDirectory.worktrees`, carry no
  kind while the conversation names do (#382). The two kinds create their work
  in different shapes and treat a leftover worktree differently (#418), match
  labels to routes under different names (#420), and decide recovery in
  different ways (#421).

## Notes

- **C1.** The consistency review before this release found about thirty
  disagreements, and #411, #412, #415, #416 and #417 fixed them all, closing
  #381. Users read "update" where the ontology, the architecture and the code
  say "scheduler tick". The ontology states that split, so it is not a
  disagreement.
- **C2.** #348, the previous shortfall, is fixed. This measurement found two
  statements the code had moved past: the standard's C4 bar left out the daemon
  lock and the `.gitignore` that every format shares, and the architecture said
  a conversation's recovery prompt follows the first prompt in a replacement
  session. The release pull request that records this measurement corrects both.
- **K1.** The four rules the standard names are checked. #383 still asks whether
  K1 means the architecture's other checkable rules too.
- **K3.** Triage rewrote nine issues that named code since renamed or removed,
  and closed none, because no issue's work was done. #121 still quotes a feed
  recording in old words, which stays as evidence.
- **K4.** Every pull request merged since the last measurement, from #376 to
  #417, answers the definition of done.
- **E2.** Nine `cast(...)` calls assert that an optional value is present, up
  from eight. The method below does not count them.
- **E3.** Cancelling arrived with its own spec. Harness config, the daemon run
  and the scheduler tick were defined within existing concepts.
- **E4.** #415 removed `is_over` from both kinds at once, so the table of
  parallel operations has 14 rows where it had 15.

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
