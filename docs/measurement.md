# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](https://github.com/alimanfoo/dreamcatcher/blob/main/specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-18 at `883941f`, with the v6.1.0 release preparation.

## Results

| Criterion                              | Measured                                       | Status | Issue      |
| -------------------------------------- | ---------------------------------------------- | ------ | ---------- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility  | met    |            |
| S2 Functions do one thing              | 0 functions without one nameable job           | met    |            |
| S3 Exports are used                    | 30 names without an importer, all permitted    | met    |            |
| S4 Each thing is done one way          | 1 fact derived more than once                  | short  | #452       |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas | met    |            |
| C1 One vocabulary                      | 2 disagreements left; every other one settled  | short  | #576, #590 |
| C2 Enduring documents are true         | 1 contradiction left                           | short  | #590       |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                    | met    |            |
| C4 Formats and contracts are versioned | state format 6, contract 1, both with policy   | met    |            |
| K1 Structural rules checked by machine | the 5 named rules checked                      | met    |            |
| K2 Suite is fast and speaks plainly    | 27 seconds on a laptop, 100% branch coverage   | met    |            |
| K3 Tracker is current                  | 41 issues reviewed; 6 to close; 17 to rewrite  | short  |            |
| K4 Every change reviewed to standard   | 6 pull requests answered; 1 names no issue     | short  | #579       |
| E1 Rules, not cases                    | 9 ledgered, all external; 0 unledgered         | met    |            |
| E2 Invariants by construction          | 54 optional fields, 1 coupled set              | short  | #577       |
| E3 Concept economy                     | 22 concepts; 0 added, 0 removed                | met    |            |
| E4 Symmetry                            | 14 parallel operations; 1 uneven pair          | short  | #578       |

## Shortfalls

- **S4.** The rule that a round without an ending was interrupted once its
  daemon has gone is still written in three places: the scheduler's unfinished
  round check, status's round outcome, and status's check that a round is
  working (#452).
- **C1.** A conversation whose last round errored reads as waiting, but when the
  comments that round was given have since been deleted, nothing is past its
  cursor and the scheduler starts no round (#576).
- **C1, C2.** Since #586 a tick reads work whose round is running, but status
  still takes a tick that read the work as one that looked after its round
  ended. A round that ends after such a tick shows that tick's reading as
  current until the next tick, and the ontology's and the architecture's reason
  for the waiting rule, that no tick has looked since, no longer holds (#590).
- **K3.** The triage proposes closing six open issues and rewriting seventeen
  that name a concept by a word the ontology no longer uses, or describe code
  that has since moved. Editing or closing an issue is the maintainer's call,
  and at v6.0.0 the maintainer chose to leave issues with retired words, so no
  issue tracks them.
- **K4.** #589 recorded a convention in the agent guide and names no issue or
  spec, and the standard still does not say whether a change may serve neither
  (#579).
- **E2.** An errored round ending's exit status and reason are both optional,
  and a validator requires one of them, where two ending types, one with each,
  would make the empty case unrepresentable (#577).
- **E4.** The terminal's detail commands list the older assignments at an issue
  but select only the newest conversation. An issue can hold several
  conversations, one for each conversation label, so an older or other-label
  conversation has no detail view or feed command there (#578).

## Notes

- **Since v6.0.0.** Six pull requests merged, none from Dependabot. #580
  shortens the cancel command's message, #582 gives the placeholder commit the
  checkout's author and skips CI on it, #584 drops the merge state and check
  result from an idle assignment's detail, #586 reads running work at each tick,
  #588 says main moved, behind main and conflicts with main in place of out of
  date, and #589 adds a bullet on what a bug is to the agent guide.
- **S1, S2.** The source changed in eight modules, by 62 lines added and 68
  removed, and no module or function grew enough to change its job. The largest
  modules are still `github.py` (792 lines), `agent_rounds.py` (705) and
  `tui/views.py` (532). The longest functions each do one job:

  | Function                                      | Lines | Its one job                                          |
  | --------------------------------------------- | ----: | ---------------------------------------------------- |
  | `cli._build_cli_parser`                       |   202 | It holds the complete command-line grammar.          |
  | `AgentRound.__init__`                         |    82 | It starts a round as one transaction.                |
  | `DreamcatcherDaemon.run`                      |    76 | It follows the daemon lifecycle in the architecture. |
  | `scheduler.assignments._inspect_pull_request` |    64 | It inspects an assignment's channel.                 |
  | `Scheduler._launch`                           |    57 | It creates a request's work, then starts its round.  |
  | `Scheduler.tick`                              |    52 | It follows the scheduler tick in the architecture.   |

- **S3.** 30 names have no direct importer, as at v6.0.0, since no change since
  added or removed a module-level name. Document models, the view model
  `RequestStatusValue`, callback protocols and the interfaces the architecture
  names account for them.
- **C1.** The consistency review ran in three parts: the source, the enduring
  documents against the code, and the user guides with the output a user sees.
  It found the daemon's docstring tying the agent marker to assignments,
  `describe_signal` saying its words tell the agent, the CLI's help calling its
  commands verbs, two user guides still describing the cancel message and idle
  details that #580 and #584 changed, the status list calling statuses states
  and an unknown status always a failure, and the tutorial naming the wrong
  install source and the wrong link to the assignment page. This preparation
  settles each of those. The status finding is #590.
- **C2.** The reading found three statements the code contradicts. The
  architecture's tick summary ended a closed issue's conversation even while its
  round ran, its setup section said the daemon refuses a checkout for every
  reason setup does, and K1 counted four machine checks where the architecture
  test makes five. This preparation corrects each. #590 is the one left.
- **C3, C4.** The user guides stay organised by purpose. The state format stays
  at 6 and the contract at version 1.
- **K1.** The subprocess lint rule and the architecture tests check the import
  boundaries, the dependency direction, and the names that presentation must not
  use to rediscover what status derives. The standard now names that fifth
  check. No other rule has failed review more than once.
- **K2.** All 1,181 default tests passed with full branch coverage in 27.11
  seconds. All 8 browser tests passed in 8.11 seconds, and all 9 integration
  tests in 2.57 seconds.
- **K3.** The triage read all 41 open issues against the ontology and the code.
  It proposes closing #78, which three sub-issues cover, #392, whose cause the
  round preparation removed, and #111, #399, #400 and #566, which under the
  agent guide's bullet on bugs describe hypotheses that lose no state. It
  proposes rewriting #36, #44, #63, #67, #68, #109, #113, #125, #130, #188,
  #404, #452, #492, #546, #548, #570 and #572. Every open issue carries one type
  label, and #78 and #492 also carry `accepted`.
- **K4.** All 6 pull requests answer the seven definition-of-done questions.
  #580, #582, #584, #586 and #588 each close an issue.
- **E1.** All 9 ledger entries remain in the code. The conditionals added since
  v6.0.0, a running round holding back another round and a closed issue's
  ending, and the merge state choosing its words, each apply a rule.
- **E2.** The count stays at 54, since no change since v6.0.0 added or removed
  an optional field.
- **E3.** #584, #586 and #588 corrected definitions in the ontology without
  adding or removing a concept.
- **E4.** #586 gave both kinds one answer to whether a round is running,
  `AgentWork.is_round_running`. 14 parallel pairs remain.

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
