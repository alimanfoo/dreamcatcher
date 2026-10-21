# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-21 at `f080eae7`, for the v6.3.0 release
preparation. The review covers the changes since v6.2.0 and the issue
triage and PR review performed in the same maintainer session. The
maintainer ended issue triage before requesting this release, so a fresh
full backlog triage remains deferred.

## Results

| Criterion                              | Measured                                                                    | Status   | Issue |
| -------------------------------------- | --------------------------------------------------------------------------- | -------- | ----- |
| S1 Modules are cohesive                | 0 reviewed modules without one nameable responsibility                      | met      |       |
| S2 Functions do one thing              | 0 reviewed functions without one nameable job                               | met      |       |
| S3 Exports are used                    | 31 names without a direct importer, all permitted                           | met      |       |
| S4 Each thing is done one way          | 0 supported duplication findings remain                                     | met      |       |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                              | met      |       |
| C1 One vocabulary                      | 2 documentation disagreements corrected in this preparation                 | met      |       |
| C2 Enduring documents are true         | 0 supported contradictions remain in the reviewed claims                    | met      |       |
| C3 Documentation by purpose            | Tutorial, task guides, references and design explanations remain separate   | met      |       |
| C4 Formats and contracts are versioned | State format 6 and contract 1, both with policy                             | met      |       |
| K1 Structural rules checked by machine | The 5 named rules remain checked                                            | met      |       |
| K2 Suite is fast and speaks plainly    | 29.20 seconds, 100% statement and branch coverage                           | met      |       |
| K3 Tracker is current                  | Full backlog triage deferred by the maintainer                              | deferred |       |
| K4 Every change reviewed to standard   | All 14 merged PRs explain their purpose and answer the definition of done   | met      |       |
| E1 Rules, not cases                    | 9 ledger entries with external causes; no unsupported new case found        | met      |       |
| E2 Invariants by construction          | 53 nullable fields; the known coupled ending fields are resolved            | met      |       |
| E3 Concept economy                     | No new domain concept since v6.2.0                                          | met      |       |
| E4 Symmetry                            | Assignment and conversation selection now share one rule and implementation | met      |       |

## Deferred work and previous findings

The maintainer's session accepted, rejected or left open the issues it
reached, then explicitly ended triage. This release preparation did not
resume backlog triage or dispatch further work. K3 is therefore
deferred, not measured as having no shortfalls.

The previous measurement's three recorded shortfalls were settled during
that session. #614 was closed because read-only state directories are
outside the supported workflow; this review does not reopen that
accepted boundary. #577 now represents preparation or startup, harness,
and finishing failures with distinct ending types. #578 gives both kinds
of agent work the same exact-identifier selection and lists the other
work at the issue.

## Notes

- **S1, S2.** The largest modules are `github.py` (796 lines),
  `agent_rounds.py` (772), `cli.py` (514), and `status/agent_work.py`
  (507). Their responsibilities remain the GitHub boundary, round
  execution and records, command-line grammar and dispatch, and shared
  work-status derivation. The long functions below still follow one
  named job.

  | Function                                      | Lines | Its job                                     |
  | --------------------------------------------- | ----: | ------------------------------------------- |
  | `cli._build_cli_parser`                       |   209 | It defines the command-line grammar.        |
  | `AgentRound.__init__`                         |    82 | It records and starts one round.            |
  | `DreamcatcherDaemon.run`                      |    76 | It follows the daemon lifecycle.            |
  | `scheduler.assignments._inspect_pull_request` |    64 | It inspects an assignment's channel.        |
  | `Scheduler._launch`                           |    57 | It creates work and starts its round.       |
  | `Scheduler.tick`                              |    52 | It follows the scheduler's update sequence. |

- **S3, S4.** Names without direct imports are document models,
  projections, protocols, entry points, or architecture and contract
  constants. Module-qualified calls still count as callers. Exact work
  selection now goes through `select_agent_work`, the two terminal
  detail views share their implementation, and web refresh failures use
  one handler. Scheduler failures are listed once in each presentation.
- **C2.** The review checked saved dispatch labels, request cards, exact
  work selection, round endings, Windows startup cleanup, refresh
  failures and local-state failure handling against their stories. The
  stories leave cross-user authorization open in #594. They accept
  reporting damaged local records without partial status reports or
  machinery to isolate the damage. A page retaining its previous display
  does not claim to know the work's current status.
- **C3, C4.** Task guides and command references describe both issue
  references and exact work identifiers. The upgrade guide now tells
  users to restart standalone viewers across a state-format change. This
  release keeps format 6 and contract 1. Existing errored endings select
  their new in-memory type from their existing exit status and write
  back without a new persisted tag.
- **K1, K2.** All 1,283 default tests passed in 29.20 seconds, with 100%
  statement and branch coverage. The separate 18 browser and 9 live
  GitHub integration tests passed in 55.26 seconds. The default suite
  includes the architecture checks. Test names describe behaviours,
  including selecting older work, retaining a feed after a failed
  refresh, and ending a child whose containment failed. Repository
  checks and the strict documentation build passed. The macOS runs skip
  the Windows-only containment module; Windows CI exercises it.
- **K4.** The 14 PRs are #621, #623, #624, #625, #627, #628, #629, #632,
  #634, #636, #637, #639, #640 and #642. The README PR, #642, had only a
  short description; the release review added its numbered definition of
  done using its passing CI as evidence. PR #631 remains draft and is
  excluded. No change to the default models from #635 is included.
- **E1, E2.** The new branches apply general rules for work selection,
  process cleanup, round outcomes and failed refreshes. Windows process
  containment remains covered by the existing operating-system ledger
  entry. The optional-field count was recomputed; it counts class fields
  whose own type admits `None`, not fixed-`None` fields or a callback's
  nullable result. No remaining coupled-field defence was established in
  the reviewed models. The known ending-status/reason coupling is now
  held by the three errored-ending types.
- **E3, E4.** An exact identifier selects an existing piece of agent
  work; it introduces no new domain concept or stored index. Assignments
  and conversations share selection, detail, feed and stop operations.
  Retry and cancel retain their documented issue-based selection.

## Semantic consistency review

### Scope

The review used the namespace and relevant stubs, the four enduring
documents, user references and guides, and changed terminal and browser
output. Symbol bodies were read to confirm candidates and the largest
functions' responsibilities. Historical specifications retain their
historical vocabulary. Full issue-tracker triage remains deferred as
stated above.

### Summary

Two documentation disagreements are corrected in this preparation.
Neither changes runtime behaviour. No other supported vocabulary or
symbol-contract disagreement remains in the reviewed scope.

### Vocabulary findings

#### 1. Read-failure isolation was stated too broadly

**Claim A** — `docs/ontology.md`, Scheduling work:

> A failed read prevents only the launches that depend on it.

**Claim B** — `docs/stories.md`, A local record cannot be read:

> One damaged file holds up every piece of work, not just its own, and
> nothing sets it aside so that the rest can go on or the rest of the
> status can show.

Both describe the effect of a failed scheduling read. The first states a
rule for every failed read; the second explicitly accepts a failed local
read holding up the whole update. The architecture also put the broad
request-read claim next to the local-record exception. This preparation
limits the isolated-read rule to GitHub reads and points the ontology to
the accepted local-state failure story. The architecture retains its
explicit conversation-cursor exception. `Scheduler.tick` reads local
work before launching, and `DreamcatcherDaemon.run_scheduler_tick`
reports a failed tick without replacing the last complete record.

#### 2. The recovery guide implied that retry searches for faulted work

**Claim A** — `docs/stop-and-recover.md`, Recover from errors and
faults:

> clears the fault of the newest faulted assignment and faulted
> conversation at that issue.

**Claim B** — `docs/command-reference.md`, retry:

> The command checks the newest assignment and the newest issue
> conversation independently and clears the fault of each one that is in
> fault.

Both describe `dreamcatcher retry GH<n>`. The first could select older
faulted work when newer work is healthy, while the second selects the
newest work first. `cli._retry_agent_work` implements the second rule by
calling `find_newest_agent_work` before testing each result for fault.
This preparation makes the recovery guide say that same rule.

### Symbol-contract findings

No supported symbol-contract disagreement was established. The old
read-only-directory finding is an accepted unsupported workflow, as
recorded above.

## Method

- `tools/measure_source.py` supplies module and function line counts.
  Review checks responsibility rather than imposing a length limit.
- An AST inventory finds public top-level definitions without direct
  imports from another source module. Review classifies each remaining
  name and checks module-qualified callers.
- A separate AST count finds nullable class-field annotations. Review
  checks whether any fields require a coupled-state defence.
- The consistency review requires two supported claims about the same
  concept before reporting a disagreement.
- Default tests establish branch coverage and timing. Browser tests
  exercise rendered interactions; integration tests read the live GitHub
  service. They ran on the integrated tree at `86af413d`; its source,
  tests and dependency files match the release base exactly.
  Documentation checks ran on the release preparation. CI also validates
  Linux and Windows behaviour.
- PR descriptions and diffs establish K4 for the interval since v6.2.0.
  This review does not claim that deferred backlog triage was completed.
