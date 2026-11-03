# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-11-03 at `62607693`, for the v9.9.0 release
preparation. The review covers the two pull requests merged since
v9.8.0: the maintainer skill, with the triage judgments and product
rules moved out of `AGENTS.md` (#900), and working from the repository's
default branch whatever its name (#904). The consistency review and the
pass over open issues ran beside this measurement.

## Results

| Criterion                  | Measured                                                              | Status | Issue |
| -------------------------- | --------------------------------------------------------------------- | ------ | ----- |
| Cohesive modules           | 0 reviewed modules without one nameable responsibility                | met    |       |
| Focused functions          | 0 reviewed functions without one nameable job                         | met    |       |
| No unused exports          | 31 public definitions without a direct named importer, as at v9.8.0   | met    |       |
| One way                    | The default branch is found in one place, `fetch_default_branch`      | met    | #896  |
| No suppressions            | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                        | met    |       |
| One vocabulary             | 1 disagreement fixed; 4 test names and 1 open issue rewritten         | met    |       |
| True documents             | #904 corrected the concepts, stories, architecture and contract       | met    |       |
| Docs by purpose            | Tutorials, task guides, references and explanations remain separate   | met    |       |
| Versioned contract         | State format 8 unchanged since v9.0.0; contract remains 1             | met    |       |
| Machine-checked rules      | The 11 import-linter contracts and the hooks of v9.8.0 remain         | met    |       |
| Fast readable tests        | 46.51 seconds, 1,566 tests passed, 100% statement and branch coverage | met    |       |
| Current tracker            | 14 open issues read; 1 rewritten in the current words                 | met    |       |
| Reviewed changes           | 2 of 2 merged pull requests answer every definition-of-done question  | met    |       |
| Rules not cases            | 11 ledger entries, unchanged                                          | met    |       |
| Invariants by construction | 71 nullable class fields, as at v9.8.0                                | met    |       |
| Few concepts               | No concept added or removed                                           | met    |       |
| Symmetry                   | Every kind's worktree follows the default branch through one helper   | met    |       |

## Deferred work and previous findings

The v9.6.0 measurement filed #870, the calm field's other names in code
and tests. It remains open.

Issue #896, one home for the instruction that starts each kind of agent
work, remains open.

Open issues in this interval:

- The open issues are #32, #492, #762, #844, #856, #857, #870, #882,
  #894, #896, #897, #899, #901 and #902.
- #894 described the code before #904 in terms of `main`, such as
  "behind main" and `has_commits_since_main`; it is rewritten to say the
  default branch.
- #882 still awaits the product owner's triage, which this pass does not
  replace.

## Notes

- **Cohesive modules, Focused functions.** The largest modules are those
  of v9.8.0, at the same sizes: `github.py` (931 lines),
  `agent_rounds.py` (785), `status/agent_work.py` (629) and
  `status/report.py` (543). #904 grows `git.py` to 230 lines, with
  `fetch_default_branch` doing one job: fetch, follow the remote's HEAD
  and return its name.
- **No unused exports, One way.** #904 renamed the Git helpers from
  `*_main` to `*_default_branch`, and each keeps its importers. Every
  worktree, comparison and pull request base reads the default branch
  through `fetch_default_branch` and `origin/HEAD`, and nothing stores
  its name.
- **No suppressions, Machine-checked rules.** The three coverage pragmas
  remain at `teardown.py:20`, `teardown.py:110` and `commands.py:270`,
  all platform arms. The import contracts and every hook pass.
- **One vocabulary, True documents.** The consistency review found one
  disagreement: the tutorial showed a bare `git push` as a command that
  `init` prints, where `init` prints `git push origin` with the default
  branch. The release preparation corrects the tutorial. "main moved" is
  newly replaced by "out of date", and no replaced word appears in the
  source, the documents, the output or the repository's skills. Four
  test names still said "main" for the default branch or the main
  checkout; they are renamed. "installation" and "carry on" appear only
  in other senses: installing software, and plain English.
- **Fast readable tests.** The default suite passed with 1,566 tests,
  one platform-only skip, and 100% statement and branch coverage, in
  46.51 seconds.
- **Reviewed changes.** #900 and #904 each explain the change and answer
  every definition-of-done question.
- **Rules not cases, Invariants by construction, Few concepts,
  Symmetry.** No conditional was added, so the ledger keeps its 11
  entries, and no field was added, so the nullable-field inventory keeps
  its 71. #904 adds no concept: the default branch and the out-of-date
  signal were already named.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- The diff of `src` from v9.8.0 establishes that #904 renamed
  definitions and added one parameter and one return value, and added no
  field or export, so the export and nullable-field inventories of
  v9.8.0 stand.
- A search for each word that a "Replaces:" line names covered the lines
  changed since v9.8.0, the source, the documents, the repository's
  skills and every open issue.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the state of the tracker.
