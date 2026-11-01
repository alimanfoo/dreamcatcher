# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-11-01 at `54499f6b`, for the v9.8.0 release
preparation. The review covers the three pull requests merged since
v9.7.0: the home page's point on long-horizon work and the narrower rule
for documentation entries in the changelog (#889), a formatting fix to
the home page (#890), and the order of the kinds of agent work as
assignment, campaign, conversation (#895). The consistency review and
the pass over open issues ran beside this measurement.

## Results

| Criterion                  | Measured                                                               | Status | Issue |
| -------------------------- | ---------------------------------------------------------------------- | ------ | ----- |
| Cohesive modules           | 0 reviewed modules without one nameable responsibility                 | met    |       |
| Focused functions          | 0 reviewed functions without one nameable job                          | met    |       |
| No unused exports          | 31 public definitions without a direct named importer, as at v9.7.0    | met    |       |
| One way                    | The order of the kinds comes from `AgentWorkKind`; one copy deferred   | met    | #896  |
| No suppressions            | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                         | met    |       |
| One vocabulary             | 0 disagreements; 1 open issue rewritten in the concepts' words         | met    |       |
| True documents             | #895 corrected the rotation order in the concepts and the architecture | met    |       |
| Docs by purpose            | Tutorials, task guides, references and explanations remain separate    | met    |       |
| Versioned contract         | State format 8 unchanged since v9.0.0; contract remains 1              | met    |       |
| Machine-checked rules      | The 11 import-linter contracts and the hooks of v9.7.0 remain          | met    |       |
| Fast readable tests        | 59.19 seconds, 1,566 tests passed, 100% statement and branch coverage  | met    |       |
| Current tracker            | 12 open issues read; 1 rewritten in the concepts' words                | met    |       |
| Reviewed changes           | 2 of 3 merged pull requests answer every definition-of-done question   | short  |       |
| Rules not cases            | 11 ledger entries, unchanged                                           | met    |       |
| Invariants by construction | 71 nullable class fields, as at v9.7.0                                 | met    |       |
| Few concepts               | No concept added or removed                                            | met    |       |
| Symmetry                   | Each kind keeps its parallel operations; only their order changed      | met    |       |

## Deferred work and previous findings

The v9.6.0 measurement filed #870, the calm field's other names in code
and tests. It remains open.

The coherence review of #895 found that `init`'s next step and the
`status` guidance for an empty section each say how to start each kind
of agent work, in wording that has drifted apart. #895 deferred it, and
issue #896 now holds it.

Open issues in this interval:

- The open issues are #32, #492, #762, #844, #856, #857, #870, #882,
  #893, #894, #896 and #897.
- #893 called a sub-issue a "stage"; it is rewritten.
- #882 still awaits the product owner's triage, which this pass does not
  replace.

## Notes

- **Cohesive modules, Focused functions.** The largest modules are those
  of v9.7.0, at the same sizes: `github.py` (931 lines),
  `agent_rounds.py` (785), `status/agent_work.py` (629) and
  `status/report.py` (543). The source changes since v9.7.0 reorder
  existing members and text, and add or remove none.
- **No unused exports, One way.** The public definitions and their
  importers are those of v9.7.0. #895 made the route order follow
  `AgentWorkKind`. `_report_next_steps` still chooses `init`'s next step
  through a chain of branches in that order, and #896 records it beside
  the duplicated wording.
- **No suppressions, Machine-checked rules.** The three coverage pragmas
  remain at `teardown.py:20`, `teardown.py:110` and `commands.py:270`,
  all platform arms. The import contracts and every hook pass.
- **One vocabulary, True documents.** The consistency review found no
  disagreement in the code, the output or the documents. No replaced
  word appears in what changed since v9.7.0. The home page's new point
  speaks of "long-horizon work" and "a roadmap" as plain description,
  not as concepts. A sweep of every list of all three kinds found none
  left in the old order outside the released changelog, the upgrade
  notes and the dated specifications.
- **Fast readable tests.** The default suite passed with 1,566 tests,
  one platform-only skip, and 100% statement and branch coverage, in
  59.19 seconds; a first run beside other work took 61.01 seconds. Its
  slowest test,
  `test_a_closed_parent_ends_the_campaign_once_its_round_finishes` at
  21.46 seconds, sets much of that time. The browser group passed 69
  tests and the read-only GitHub integration group 11, each with one
  platform-only skip.
- **Reviewed changes.** #890, a formatting fix to the home page made in
  GitHub's editor, has no description. #889 and #895 answer every
  question.
- **Rules not cases, Invariants by construction, Few concepts,
  Symmetry.** The ledger keeps its 11 entries and the nullable-field
  inventory its 71.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- The diff of `src` from v9.7.0 establishes that no definition, import
  or field changed, so the export and nullable-field inventories of
  v9.7.0 stand.
- A search for each word that a "Replaces:" line names covered the lines
  changed since v9.7.0, the source, the documents, the repository's
  skills and every open issue.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the state of the tracker.
