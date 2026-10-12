# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release, and a phase plans its work from it. Earlier
measurements are in the Git history. The first was the
[baseline of 2026-09-30](https://github.com/alimanfoo/dreamcatcher/blob/main/specs/2026-09-30-engineering-standard/roadmap.md).

Measured on 2026-10-12 at `a5a7e59`, with the v5.6.0 release preparation.

## Results

| Criterion                              | Measured                                       | Status | Issue      |
| -------------------------------------- | ---------------------------------------------- | ------ | ---------- |
| S1 Modules are cohesive                | 0 modules without one nameable responsibility  | met    |            |
| S2 Functions do one thing              | 0 functions without one nameable job           | met    |            |
| S3 Exports are used                    | 33 names without an importer, all permitted    | met    |            |
| S4 Each thing is done one way          | 2 facts derived more than once                 | short  | #452, #455 |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas | met    |            |
| C1 One vocabulary                      | 2 disagreements; 1 fixed                       | short  | #511       |
| C2 Enduring documents are true         | 0 new contradictions                           | met    |            |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                    | met    |            |
| C4 Formats and contracts are versioned | state format 5, contract 1, both with policy   | met    |            |
| K1 Structural rules checked by machine | the 4 named rules checked                      | met    |            |
| K2 Suite is fast and speaks plainly    | 25 seconds on a laptop, 100% branch coverage   | met    |            |
| K3 Tracker is current                  | 44 issues reviewed; 2 corrected, none closed   | met    |            |
| K4 Every change reviewed to standard   | 6 pull requests answered; 1 names no issue     | short  | #510       |
| E1 Rules, not cases                    | 9 ledgered, all external; 4 unledgered         | short  | #419, #457 |
| E2 Invariants by construction          | 61 optional fields, 0 coupled sets             | met    |            |
| E3 Concept economy                     | 22 concepts; 1 added                           | met    |            |
| E4 Symmetry                            | 14 parallel operations; 1 uneven creation pair | short  | #456       |

## Shortfalls

- **S4.** The terminal and web views still derive issue-row status and evidence
  separately. That work waits on #455, which first settles how both kinds of
  agent work observe an issue. The rule that a round without an ending was
  interrupted once its daemon has gone remains in recovery, status and outcome
  reporting (#452).
- **C1.** The home page's terminal illustration writes an issue as `#41`, where
  `dreamcatcher status` writes `GH41`, and shows columns that the status view
  does not print (#511).
- **K4.** #516 prepared v5.5.1 under the release procedure and names no issue or
  spec. The standard still does not say whether a change may serve neither
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

- **Since v5.5.0.** Six pull requests merged. #513 names the conversation skill
  in the ontology and splits the agent contract into an assignment skill
  contract and a conversation skill contract, still at version 1. #515 and #520
  soften the nature theme's dark card edges and give the round heading the page
  background. #516 prepared v5.5.1. #518 makes `dreamcatcher run` serve the web
  interface for the daemon's lifetime unless `--noweb` is given. #522 adds the
  installed version to the daemon's startup message. Python source changed in
  `cli.py`, `daemon.py`, `web/app.py` and `web/server.py`.
- **S1, S2.** The largest modules are `github.py` (703 lines), `agent_rounds.py`
  (658) and `web/app.py` (635). `web/app.py` grew by 37 lines, and
  `web/server.py` grew from 75 to 144, when they took on background serving.
  `web/app.py` still serves and renders the web interface, and `web/server.py`
  still binds and runs its server. The longest functions each do one job:

  | Function                   | Lines | Its one job                                              |
  | -------------------------- | ----: | -------------------------------------------------------- |
  | `cli._build_cli_parser`    |   197 | It holds the complete command-line grammar.              |
  | `read_status_report`       |    97 | It composes the instance's status report.                |
  | `AgentRound.__init__`      |    87 | It starts a round as one transaction.                    |
  | `AssignmentCreator.create` |    86 | It follows assignment creation as the ontology lists it. |
  | `DreamcatcherDaemon.run`   |    84 | It follows the daemon lifecycle in the architecture.     |
  | `Scheduler.tick`           |    55 | It follows the scheduler tick in the architecture.       |

  `_build_cli_parser` grew by the `--noweb` option. `DreamcatcherDaemon.run`
  grew by holding the web server for its lifetime and by putting the version in
  its startup message.

- **S3.** The same 33 names have no direct importer. Document models, callback
  protocols and domain interfaces account for them. The new
  `serve_web_in_background` export has its caller in `cli`.
- **C1.** #509 is resolved, since the ontology now defines the conversation
  skill. The consistency review found that the architecture and a comment in
  `agent_rounds.py` still called the writer of stop requests "the web process",
  which #518 had renamed the web interface elsewhere. This preparation fixes
  both.
- **C2.** #518 added the web server to the daemon's duties in the architecture,
  and the code agrees, since the server starts after the orphan sweep and stops
  when the daemon's loop exits. The stop guide left the web page out of what
  Ctrl-C stops, and this preparation adds it. The known window in which a second
  daemon can run after the lock path is deleted remains accepted as an edge
  case.
- **C3, C4.** The run, monitoring and recovery guides, the command reference and
  the tutorial now describe the web interface opening with `run`. The contract's
  new sections stay at version 1, because #513 changed no obligation, and the
  state format stays at 5.
- **K1.** The architecture tests and subprocess lint rule still check the four
  named boundaries. No other rule has failed review more than once.
- **K2.** All 1,210 default tests passed with full branch coverage in 24.53
  seconds. All eight browser tests passed in 8.34 seconds. The new tests name
  behaviours a user sees, such as `--noweb` running only the daemon and a
  browser that cannot open being reported.
- **K3.** The triage read all 44 open issues against the ontology, and rewrote
  #70 and #393 to its words. No open issue's work is complete or obsolete, and
  every one carries a type label.
- **K4.** All six pull requests answer the seven definition-of-done questions.
  #513, #515, #518, #520 and #522 each close an issue.
- **E1.** #518 adds conditionals for the `--noweb` opt-out, the serving thread's
  state and how its failure is passed on. Each applies a general rule. The four
  special cases reported earlier remain.
- **E2.** The count of 61 is unchanged, since no model changed.
- **E3.** #513 added the conversation skill, which the contract and the skills
  guide already used, bringing the ontology to 22 concepts.
- **E4.** The 14 parallel operations of the two kinds of agent work are
  unchanged. The two creators still differ in shape (#456, blocked by #425).
  #518 adds `serve_web_in_background` and `run_web_server_in_background` beside
  `serve_web` and `run_web_server`, and each pair shares one shape.

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
