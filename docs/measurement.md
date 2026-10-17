# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](https://github.com/alimanfoo/dreamcatcher/blob/main/specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-17 at `64ae1b4`, with the v6.0.0 release preparation.

## Results

| Criterion                              | Measured                                       | Status | Issue |
| -------------------------------------- | ---------------------------------------------- | ------ | ----- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility  | met    |       |
| S2 Functions do one thing              | 0 functions without one nameable job           | met    |       |
| S3 Exports are used                    | 30 names without an importer, all permitted    | met    |       |
| S4 Each thing is done one way          | 1 fact derived more than once                  | short  | #452  |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas | met    |       |
| C1 One vocabulary                      | 1 disagreement left; every other one settled   | short  |       |
| C2 Enduring documents are true         | 0 contradictions left                          | met    |       |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                    | met    |       |
| C4 Formats and contracts are versioned | state format 6, contract 1, both with policy   | met    |       |
| K1 Structural rules checked by machine | the 4 named rules checked                      | met    |       |
| K2 Suite is fast and speaks plainly    | 25 seconds on a laptop, 100% branch coverage   | met    |       |
| K3 Tracker is current                  | 47 issues reviewed; 5 to close, 20 to rewrite  | short  |       |
| K4 Every change reviewed to standard   | 17 pull requests answered; 3 name no issue     | short  |       |
| E1 Rules, not cases                    | 9 ledgered, all external; 0 unledgered         | met    |       |
| E2 Invariants by construction          | 54 optional fields, 1 coupled set              | short  |       |
| E3 Concept economy                     | 22 concepts; 2 added, 2 removed                | met    |       |
| E4 Symmetry                            | 14 parallel operations; 1 uneven pair          | short  |       |

## Shortfalls

- **S4.** The rule that a round without an ending was interrupted once its
  daemon has gone is still written in three places: the scheduler's unfinished
  round check, status's round outcome, and status's check that a round is
  working (#452).
- **C1.** A conversation whose last round errored reads as waiting, but when the
  comments that round was given have since been deleted, nothing is past its
  cursor and the scheduler starts no round.
- **K3.** The triage found 5 open issues whose work is done or no longer
  applies, 20 that name a concept by a word the ontology no longer uses or
  describe code that has since gone, and 1 without a type label. The proposals
  are on #573 for the maintainer to apply.
- **K4.** #536 and #540 prepared v5.6.1 and v5.6.2, and #541 limited the CI
  token. None names an issue or a spec, and the standard still does not say
  whether a change may serve neither.
- **E2.** An errored round ending's exit status and reason are both optional,
  and a validator requires one of them, where two ending types, one with each,
  would make the empty case unrepresentable.
- **E4.** The terminal's detail commands list the older assignments at an issue
  but select only the newest conversation. An issue can now hold several
  conversations, one for each conversation label, so an older or other-label
  conversation has no detail view or feed command there.

An issue is filed for each shortfall that names none when #573 merges.

## Notes

- **Since v5.6.0.** Seventeen pull requests merged, besides two from Dependabot.
  #525, #528, #534, #539 and #543 restyle the web interface's themes, #531
  shares the web controls between the two kinds of agent work, #544 derives
  status classes from status values, #530 bounds K4 to the pull requests since
  the last major or minor release, and #536 and #540 prepared v5.6.1 and v5.6.2.
  #552 specified the state format 6 phase, and its five stages #561, #562, #565,
  #568 and #571 move the state format to 6. #573 prepares v6.0.0.
- **S1, S2.** The largest modules are `github.py` (792 lines), `agent_rounds.py`
  (705) and `tui/views.py` (532). `github.py` grew by 89 lines, as the pull
  request read took on the merge state, the head commit and the checks, and it
  still owns the GitHub boundary alone. `web/app.py` shrank from 635 to 455
  lines once both kinds of agent work shared one page route. The longest
  functions each do one job:

  | Function                                      | Lines | Its one job                                          |
  | --------------------------------------------- | ----: | ---------------------------------------------------- |
  | `cli._build_cli_parser`                       |   198 | It holds the complete command-line grammar.          |
  | `AgentRound.__init__`                         |    82 | It starts a round as one transaction.                |
  | `DreamcatcherDaemon.run`                      |    77 | It follows the daemon lifecycle in the architecture. |
  | `scheduler.assignments._inspect_pull_request` |    64 | It inspects an assignment's channel.                 |
  | `Scheduler._launch`                           |    57 | It creates a request's work, then starts its round.  |
  | `Scheduler.tick`                              |    52 | It follows the scheduler tick in the architecture.   |

- **S3.** 30 names have no direct importer, down from 33. Document models, the
  view model `RequestStatusValue`, callback protocols and the interfaces the
  architecture names account for them. Two helpers in `status/rounds.py` that
  only their own module called became private in this preparation.
- **C1.** The consistency review ran over the whole codebase in three parts and
  then once more to confirm. It found the cursor called a delivery position, the
  wrap-up round called the final turn, a tick called a cycle, the work called
  its round's owner, and web parts that both kinds share named for assignments,
  among others. #573 records each finding and how it was settled.
- **C2.** A reading of the ontology, the architecture and the contract against
  the code found claims that the five stages left behind, such as the
  preparation always readying the worktree and building a round's invocation
  after its record. This preparation corrects each, and the user guides with
  them.
- **C3, C4.** The user guides describe state format 6 and the `/work/` pages.
  The state format moves to 6 with an upgrade note in
  [Compatibility and upgrades](compatibility.md). The contract stays at version
  1, since its new input keys are additive and its new lines are instructions.
- **K1.** The architecture tests and the subprocess lint rule still check the
  four named boundaries. No other rule has failed review more than once.
- **K2.** All 1,179 default tests passed with full branch coverage in 25.13
  seconds. All eight browser tests passed in 9.32 seconds.
- **K3.** The triage read all 47 open issues apart from #554 and #560 against
  the ontology and the code. #456, #391, #494, #545 and #575 ask for work that
  the state format 6 phase did or that no longer applies. #575 also carries no
  type label.
- **K4.** All 17 pull requests answer the seven definition-of-done questions.
  Thirteen close an issue, and #552 names its spec.
- **E1.** The four special cases reported at v5.6.0 are gone, since the phase
  gave both kinds one tick, the web one control layout and one status class
  rule, and the request rows carry numbers as data. All 9 ledger entries remain
  in the code.
- **E2.** The count fell from 61 to 54. The errored round ending's exit status
  became optional when a round could error before its harness ran.
- **E3.** The phase added the channel and cursor and the signal, and removed the
  round purpose and the recovery round, keeping the ontology at 22 concepts.
- **E4.** The phase merged creation, retry, the harness session, the status
  reader, ending and the tick into one operation each, so the two creators no
  longer differ in shape (#456). 14 parallel pairs remain.

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
- **E4.** Read the operations of the two kinds of agent work in the namespace
  map, and list each that exists for one kind and not the other, or twice, where
  the ontology names no difference.
