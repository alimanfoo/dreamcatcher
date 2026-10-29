# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-29 at `84ab2e24`, for the v9.6.0 release
preparation. The review covers the six pull requests merged since
v9.5.0, all from the campaign on #863, which carried small changes to
the web view. The consistency review and issue triage ran beside this
measurement.

## Results

| Criterion                  | Measured                                                                                                    | Status | Issue |
| -------------------------- | ----------------------------------------------------------------------------------------------------------- | ------ | ----- |
| Cohesive modules           | 0 reviewed modules without one nameable responsibility                                                      | met    |       |
| Focused functions          | 0 reviewed functions without one nameable job                                                               | met    |       |
| No unused exports          | 31 public definitions without a direct named importer, as at v9.5.0                                         | met    |       |
| One way                    | GitHub's state on a card takes one rule in each theme; the header's height has one home, its rendered size  | met    |       |
| No suppressions            | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                                                              | met    |       |
| One vocabulary             | 3 disagreements found; 2 corrected in this preparation, 1 filed                                             | met    | #870  |
| True documents             | Each merged change corrected the documents it moved; two sentences corrected here                           | met    |       |
| Docs by purpose            | Tutorials, task guides, references and explanations remain separate                                         | met    |       |
| Versioned contract         | State format 8 unchanged since v9.0.0; contract remains 1                                                   | met    |       |
| Machine-checked rules      | The 11 import-linter contracts and the hooks of v9.5.0 remain                                               | met    |       |
| Fast readable tests        | 43.28 seconds, 1,563 tests passed, 100% statement and branch coverage                                       | met    |       |
| Current tracker            | 8 open issues read; the epic #863 waits only to be closed                                                   | met    |       |
| Reviewed changes           | All 6 merged pull requests answer every definition-of-done question                                         | met    |       |
| Rules not cases            | 11 ledger entries, unchanged                                                                                | met    |       |
| Invariants by construction | 71 nullable class fields, as at v9.5.0                                                                      | met    |       |
| Few concepts               | No domain concept added; the concepts page names the working motif and the calm field the stories described | met    |       |
| Symmetry                   | A card's GitHub state looks the same on every card in both themes                                           | met    |       |

## Deferred work and previous findings

The v9.5.0 measurement left no disagreement open.

The campaign on #863 carried five triaged tweaks: the working motifs
show from a 1184px window, in the gutter beside the page's text (#862);
their layer starts where the header's rendered height ends, measured in
`home.js` (#860); Matrix gives GitHub's state on a card no box (#847);
the ended list's toggle drops its "+" (#852); and each repository's web
view remembers its own theme (#848). The maintainer's review found that
the change for #847 had left a card's pull-request state underlined in
both themes, a regression no release ever carried, and the campaign
fixed it (#869).

The consistency review found that the calm field goes by "empty field"
and "motif field" in code and tests, which needs code and goldens to
change, so it is filed as #870 and holds no release back.

Triage in this interval:

- The open issues are #32, #492, #762, #844, #856, #857, #863 and #870.
  Each uses the concepts' words.
- #863's sub-issues have all closed, so its campaign ends when the
  product owner closes it.
- #856 carries a note that its link check conflicts with the rule that
  completed specs are never edited.

## Notes

- **Cohesive modules, Focused functions.** The largest modules are those
  of v9.5.0, at the same sizes: `github.py` (931 lines),
  `agent_rounds.py` (785), `status/agent_work.py` (629) and
  `status/report.py` (543). The longest functions are unchanged.
  `static/home.js` grows to 98 lines by the observer that measures the
  header.
- **No unused exports, One way.** An AST inventory finds 31 public class
  or function definitions without a direct named import, the same set as
  v9.5.0. In Matrix, `.pr-chip` and `.issue-state` share one rule, as
  they already did in Nature, and the header's height is no longer a
  number kept in step with its layout in each theme.
- **No suppressions, Machine-checked rules.** The three coverage pragmas
  remain at `teardown.py:20`, `teardown.py:110` and `commands.py:270`,
  all platform arms. The import contracts and every hook pass.
- **One vocabulary, True documents.** The review found three
  disagreements. Two are corrected here: the concepts page placed the
  working motif "in a side margin" where it now uses the gutter beside
  the page's text, and the stories said each repository keeps its own
  theme without the condition that its daemon has run. The third, the
  calm field's other names in code, is #870.
- **Fast readable tests.** The default suite passed with 1,563 tests,
  one platform-only skip, and 100% statement and branch coverage, in
  43.28 seconds. Its slowest test was
  `test_a_closed_parent_ends_the_campaign_once_its_round_finishes`, at
  21.09 seconds. The browser and read-only GitHub integration groups
  passed together: 80 tests, one platform-only skip, 15.19 seconds.
  Every pre-commit check passed.
- **Reviewed changes.** The maintainer reviewed the merged pull requests
  against their issues and rendered the home page with the fabricated
  web server at 1250px in Matrix and in Nature, light and dark, which
  found the underline regression filed as #869.
- **Rules not cases, Invariants by construction, Few concepts,
  Symmetry.** The ledger keeps its 11 entries and the nullable-field
  inventory its 71. The working motif and the calm field were already
  described in the stories; the concepts page now names them.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- AST inventories over `src` count public definitions without direct
  named importers and class fields whose own annotation admits `None`.
  Package exports and module-object callers are reviewed separately. The
  same inventories over v9.5.0 give the changes since then.
- The namespace and stubs guide targeted body reads and the diff from
  v9.5.0. The docs map guides the documentation review.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the tracker triage.
