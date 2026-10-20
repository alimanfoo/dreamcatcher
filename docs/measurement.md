# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md) replaces it
before each major or minor release. Earlier measurements are in Git history.

Measured on 2026-10-20 at `8de014d4`, with the v6.2.0 release preparation. The
review includes the 15 pull requests merged since v6.1.0 and the PR shepherding
and issue triage performed in the same maintainer session. The maintainer paused
issue triage before requesting this release, so this preparation records that
limitation rather than claiming a fresh full triage.

## Results

| Criterion                              | Measured                                                                  | Status   | Issue |
| -------------------------------------- | ------------------------------------------------------------------------- | -------- | ----- |
| S1 Modules are cohesive                | 0 reviewed modules without one nameable responsibility                    | met      |       |
| S2 Functions do one thing              | 0 reviewed functions without one nameable job                             | met      |       |
| S3 Exports are used                    | 31 names without a direct importer, all permitted                         | met      |       |
| S4 Each thing is done one way          | 0 remaining supported duplication findings                                | met      |       |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                            | met      |       |
| C1 One vocabulary                      | 1 confirmed symbol-contract disagreement remains                          | short    | #614  |
| C2 Enduring documents are true         | 0 new supported contradictions in the reviewed claims                     | met      |       |
| C3 Documentation by purpose            | 4 kinds of page, kept apart                                               | met      |       |
| C4 Formats and contracts are versioned | state format 6, contract 1, both with policy                              | met      |       |
| K1 Structural rules checked by machine | the 5 named rules checked                                                 | met      |       |
| K2 Suite is fast and speaks plainly    | 36.66 seconds, 100% branch coverage                                       | met      |       |
| K3 Tracker is current                  | 32 open issues; full release triage deferred by the maintainer            | deferred |       |
| K4 Every change reviewed to standard   | all 15 merged PRs explain their purpose and answer the definition of done | met      |       |
| E1 Rules, not cases                    | 9 ledger entries with external causes; no new unsupported case found      | met      |       |
| E2 Invariants by construction          | 57 optional fields, 1 known coupled set                                   | short    | #577  |
| E3 Concept economy                     | no new domain concept since v6.1.0                                        | met      |       |
| E4 Symmetry                            | shared work, round and status operations; 1 known uneven selection pair   | short    | #578  |

## Shortfalls

- **C1.** Reading a missing optional replaceable document in a read-only
  directory raises a sidecar-lock permission error instead of returning `None`.
  The release review reproduced #614 on macOS. The evidence is below.
- **K3.** The earlier session resolved and dispatched the issues covered by this
  release. It did not finish the backlog. No issue was rewritten, closed or
  dispatched during release preparation, following the maintainer's request to
  pause triage. The previous measurement's proposed closures are not carried
  forward as conclusions; several were rejected during the session.
- **E2.** An errored round ending's optional exit status and reason still need a
  validator to reject an unexplained error. #577 records the agreed separation
  of preparation, harness and finishing failures into distinct ending types.
- **E4.** The terminal lists older assignments at an issue but selects only the
  newest conversation. #578 remains open for selecting other saved work.

## Notes

- **S1, S2.** The largest modules are `github.py` (792 lines), `agent_rounds.py`
  (726), `tui/views.py` (532), and `status/agent_work.py` (507). They own the
  GitHub boundary, round execution and records, terminal views, and shared
  work-status derivation respectively. Document coordination remains in
  `documents.py`; tab selection remains in the web presentation.

  | Function                                      | Lines | Its job                                     |
  | --------------------------------------------- | ----: | ------------------------------------------- |
  | `cli._build_cli_parser`                       |   202 | It defines the command-line grammar.        |
  | `AgentRound.__init__`                         |    82 | It starts a round as one transaction.       |
  | `DreamcatcherDaemon.run`                      |    76 | It follows the daemon lifecycle.            |
  | `scheduler.assignments._inspect_pull_request` |    64 | It inspects an assignment's channel.        |
  | `Scheduler._launch`                           |    57 | It creates work and starts its round.       |
  | `Scheduler.tick`                              |    52 | It follows the scheduler's update sequence. |

- **S3.** The 31 names without direct imports are document models, projections,
  protocols, view models, entry points, or architecture and contract constants.
  The new `WriteOnceDreamcatcherDocument` and `describe_round_outcome` have
  production importers. A module-qualified call remains a caller even though the
  direct-import count does not count it.
- **S4.** #605 replaces the repeated interpretation of a round without an ending
  with `interpret_agent_round_outcome`. #615 uses one observation rule for both
  the completed-round and unfinished-conversation status cases.
- **C2.** #600 and #615 settle the previous measurement's disagreement between
  scheduler observations and waiting status. #599 makes the deleted-worktree
  behaviour match its story. The review checked those rules, the revised
  recovery prompt, document coordination and the recorded status examples.
- **C3, C4.** The user stories join the developer documentation; task guides,
  tutorial and references retain their separate purposes. Old state-format-6
  work still reads. `RequestRow.ended_round` defaults to absent for old
  scheduler records, and the next update records a fresh observation. The agent
  contract remains version 1.
- **K1.** The default suite includes the architecture checks for subprocess,
  Rich and Flask imports, dependency direction, and presentation code
  re-deriving status.
- **K2.** All 1,229 default tests passed in 36.66 seconds with 100% statement
  and branch coverage. The 10 browser tests and 9 live GitHub integration tests
  passed together in 9.92 seconds. Sandbox restrictions initially prevented
  Chromium startup and GitHub access; rerunning with those permissions passed.
- **K4.** The 15 PRs are #592, #596, #598, #599, #600, #601, #602, #604, #605,
  #607, #609, #610, #612, #613 and #615. All explain their purpose and answer
  the seven questions. The standard now permits a self-contained change without
  a separate issue or spec, so the old #579 shortfall is resolved.
- **E1.** The added conditionals apply document mutability, path boundaries,
  round outcomes, observation freshness and tab-selection rules. No additional
  ledger entry was needed.
- **E2.** The optional-field count was recomputed from all model and dataclass
  annotations; it is not inferred from the previous count. The new scheduler
  field records an observation, not another lifecycle state.
- **E3, E4.** Assignments and conversations continue to share work, round,
  outcome and status concepts. Their recovery differs because an assignment can
  have unfinished implementation work without new posts, while a conversation
  needs an eligible comment to answer.

## Semantic consistency review

### Scope

The review used the namespace and stubs, the four enduring documents, the user
references and guides, and the changed terminal and web output. It revisited
changed contracts and the previous measurement's findings. Historical specs
retain their historical vocabulary. Open issues were inventoried; their full
triage remains deferred as described above.

### Summary

The earlier status and round-outcome disagreements are resolved. This
preparation corrects one stale definition in the agent guide. One existing
symbol-contract disagreement remains, tracked by #614.

### Vocabulary findings

The agent guide's introduction said, "A happy path that does not hold is a bug",
while its issue convention said, "A bug is behaviour that contradicts a story in
`docs/stories.md`, including the handling that a user error or expected fault
story promises." Both define how an agent classifies the same finding, but the
first excludes promised fault handling. This preparation replaces the first
passage with the agreed definition.

No other new vocabulary disagreement was established in the reviewed scope.

### Symbol-contract findings

`documents.read_json_if_exists` promises:

> Return the JSON document, or None when its path does not exist.

The same call delegates to `_read_text`, whose replaceable-document branch first
takes a lock:

```python
with _hold_document_lock(path=path):
    return _decode(contents=path.read_bytes(), path=path)
```

A reproduction created an empty directory, set its mode to `0555`, confirmed
that `absent.json` did not exist, and called the reader with a replaceable
model. It raised `ReportableError` for permission denied on `absent.json.lock`.
The missing-document contract and the observed result concern the same public
call and disagree. #614 already tracks this shortfall; no duplicate issue was
filed.

## Method

- `tools/measure_source.py` supplies module and function line counts. Review
  checks responsibility rather than enforcing a length limit.
- An AST count collects public top-level definitions and removes names imported
  directly by another source module. Review classifies the remaining names.
- An AST count finds class-level annotations admitting `None` on dataclasses and
  document models, and review checks coupled fields.
- The consistency-review skill requires two supported claims about the same
  concept before reporting a disagreement.
- The default suite establishes branch coverage and timing. Browser tests
  exercise rendered interactions; integration tests call the real GitHub CLI.
- The merged PR descriptions establish K4 over the interval since v6.1.0. The
  current issue inventory establishes the scope left for later triage.
