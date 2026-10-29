# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-29 at `326689f1`, for the v9.7.0 release
preparation. The review covers the four pull requests merged since
v9.6.1: the upgrade to uncoded 6.0.0 (#879), the move to `dream:sift`
for triage (#881), the `dreamcatcher about` command (#884), and its
rework into an explanation of dreamcatcher's mechanics with the
correction of "turn" across the documents (#885). The consistency review
and the pass over open issues ran beside this measurement.

## Results

| Criterion                  | Measured                                                              | Status | Issue |
| -------------------------- | --------------------------------------------------------------------- | ------ | ----- |
| Cohesive modules           | 0 reviewed modules without one nameable responsibility                | met    |       |
| Focused functions          | 0 reviewed functions without one nameable job                         | met    |       |
| No unused exports          | 31 public definitions without a direct named importer, as at v9.6.1   | met    |       |
| One way                    | `about` prints one fixed text; a round has one definition again       | met    |       |
| No suppressions            | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                        | met    |       |
| One vocabulary             | "Turn" kept to its harness meaning; 2 wording tensions corrected here | met    |       |
| True documents             | Each merged change corrected the documents it moved; 3 corrected here | met    |       |
| Docs by purpose            | Tutorials, task guides, references and explanations remain separate   | met    |       |
| Versioned contract         | State format 8 unchanged since v9.0.0; contract remains 1             | met    |       |
| Machine-checked rules      | The 11 import-linter contracts and the hooks of v9.6.1 remain         | met    |       |
| Fast readable tests        | 49.87 seconds, 1,566 tests passed, 100% statement and branch coverage | met    |       |
| Current tracker            | 9 open issues read; 2 rewritten in the concepts' words                | met    |       |
| Reviewed changes           | 3 of 4 merged pull requests answer every definition-of-done question  | short  |       |
| Rules not cases            | 11 ledger entries, unchanged                                          | met    |       |
| Invariants by construction | 71 nullable class fields, as at v9.6.1                                | met    |       |
| Few concepts               | No concept added; "user's agent", added by #884, is removed here      | met    |       |
| Symmetry                   | `about` explains each kind of agent work in the same parts            | met    |       |

## Deferred work and previous findings

The v9.6.0 measurement filed #870, the calm field's other names in code
and tests. It remains open.

The first `about` change, #884, added a "user's agent" concept without
the spec that the standard asks of a new concept. The rework in #885
left the term in only one story, so this preparation removes the concept
and the story says "the agent".

The rework in #885 also corrected "turn" across the concepts, stories,
contract, architecture, guides and docstrings, and added an "Ambiguous
terms" section to the concepts page. The campaign round input's field
`finished_turn` keeps its name, because renaming it changes the agent
contract.

Open issues in this interval:

- The open issues are #32, #492, #762, #844, #856, #857, #870, #882 and
  #886. #886, a CI change, merges beside this preparation.
- #844 named a request card a "request row", and #492 named the concepts
  page "the ontology"; both are rewritten.
- #882 awaits the product owner's triage, which this pass does not
  replace.

## Notes

- **Cohesive modules, Focused functions.** The largest modules are those
  of v9.6.1, at the same sizes: `github.py` (931 lines),
  `agent_rounds.py` (785), `status/agent_work.py` (629) and
  `status/report.py` (543). `about.py` is 15 lines and reads one text.
- **No unused exports, One way.** An AST inventory finds 31 public class
  or function definitions without a direct named import, the same set as
  v9.6.1. `about` no longer repeats the routes that `dreamcatcher.toml`
  holds, and `config.read_default_dreamcatcher_config` went with them.
- **No suppressions, Machine-checked rules.** The three coverage pragmas
  remain at `teardown.py:20`, `teardown.py:110` and `commands.py:270`,
  all platform arms. The import contracts and every hook pass.
- **One vocabulary, True documents.** The consistency review found no
  disagreement between `about`, the code and the documents. It found two
  tensions with the concepts page's rule for "turn": the page now allows
  the word for a harness's own events, such as Codex's `turn.failed`,
  and a docstring names the field `finished_turn` rather than calling a
  round a turn. The release checklist and the standard now call their
  pass over open issues bringing them up to date, not triage, which the
  `dream:sift` protocol now means.
- **Fast readable tests.** The default suite passed with 1,566 tests,
  one platform-only skip, and 100% statement and branch coverage, in
  49.87 seconds. Its slowest test was
  `test_a_closed_parent_ends_the_campaign_once_its_round_finishes`, at
  21.12 seconds. The browser and read-only GitHub integration groups
  passed together: 80 tests, one platform-only skip, 16.39 seconds.
  Every pre-commit check passed.
- **Reviewed changes.** #879, the uncoded upgrade, answered the four
  criteria headings of the standard rather than the definition-of-done
  questions; the maintainer merged it without catching that. The other
  three answer every question.
- **Rules not cases, Invariants by construction, Few concepts,
  Symmetry.** The ledger keeps its 11 entries and the nullable-field
  inventory its 71.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- AST inventories over `src` count public definitions without direct
  named importers and class fields whose own annotation admits `None`.
  Package exports and module-object callers are reviewed separately. The
  same inventories over v9.6.1 give the changes since then.
- The namespace and stubs guide targeted body reads and the diff from
  v9.6.1. The docs map guides the documentation review.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the state of the tracker.
