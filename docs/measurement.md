# Measurement

This page holds the latest measurement of Dreamcatcher against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](../specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-04 at `5c96e41`, before v5.0.0.

## Results

| Criterion                              | Measured                                        | Status | Issue     |
| -------------------------------------- | ----------------------------------------------- | ------ | --------- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility   | met    |           |
| S2 Functions fit on a screen           | 5 functions over 50 lines, each with its reason | met    |           |
| S3 Exports are used                    | 31 names without an importer, all permitted     | met    |           |
| S4 Each thing is done one way          | 9 facts derived twice                           | short  | #378–#380 |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas  | met    |           |
| C1 One vocabulary                      | 11 disagreements                                | short  | #381      |
| C2 Enduring documents are true         | 1 statement the code contradicts                | short  | #348      |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                     | met    |           |
| C4 Formats and contracts are versioned | state format 5, contract 1, both with policy    | met    |           |
| K1 Structural rules checked by machine | the 4 named rules checked                       | met    | #383      |
| K2 Suite is fast and speaks plainly    | 21 seconds on a laptop, 100% branch coverage    | met    |           |
| K3 Tracker is current                  | 0 issues in other words or for done work        | met    |           |
| K4 Every change reviewed to standard   | 1 of 1 pull requests answered                   | met    |           |
| E1 Rules, not cases                    | 10 ledgered cases; 2 unledgered, internal cause | short  | #378      |
| E2 Invariants by construction          | 71 optional fields, 0 coupled sets              | met    |           |
| E3 Concept economy                     | 21 concepts; none added without a case          | met    |           |
| E4 Symmetry                            | 15 parallel operations; 1 uneven set of names   | short  | #382      |

## Shortfalls

- **S4.** The terminal and web views each derive instance facts, issue rows,
  assignment order, field labels, round revisions and the recovery marker
  (#379). The scheduler and status each derive "claimed here" and "awaiting
  recovery" (#380). The web reads capacity out of the scheduler hold's text
  (#378).
- **C1.** Seven disagreements change words a user sees, such as "idle" on an
  assignment that needs user feedback and four names for a dispatch recipe. Four
  are in the code alone, such as "delivery cursor" against the documents'
  "delivery position" (#381).
- **C2.** The ontology says an existing assignment's rounds depend only on its
  pull request, while a failed issue listing drops them (#348).
- **E1.** The web hides a hold that starts with `"at cap:"`, and the daemon
  rewrites one that starts with `"global cooldown"`. Both parse the scheduler
  hold's free text (#378).
- **E4.** The assignment prompt names carry no kind and the conversation names
  do (#382).

## Notes

- **K1.** The four rules the standard names are checked. The architecture states
  six more that a test could check, and the standard's admission rule for checks
  argues against adding them until one fails review. #383 asks which reading K1
  means.
- **K3.** #121 quotes a feed recording that uses old words. The recording is
  evidence, so it stays as it is.
- **K4.** #377 was the first pull request after the definition-of-done section
  became required.
- **E2.** Eight `cast(...)` calls assert that an optional value is present. The
  method below does not count them.
- **E3.** "Assignment route" was added and "dispatch recipe" renamed since the
  baseline. Both name concepts the code already had, and both predate the E3
  question in the definition of done.

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
