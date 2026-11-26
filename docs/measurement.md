# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-11-26 at `8c6f551a`, for the v9.10.0 release
preparation. The review covers the pull requests merged since v9.9.0,
the last measured release: the documentation site's home page hero
(#906), the agent contract cut to what a skill must say (#910), the
v9.9.1 release preparation (#916), the default Codex recipes moved to
the GPT-6 models (#918), and the maintainer's chores (#919), with the
Dependabot updates. The consistency review and the pass over open issues
ran beside this measurement.

## Results

| Criterion                  | Measured                                                              | Status | Issue |
| -------------------------- | --------------------------------------------------------------------- | ------ | ----- |
| Cohesive modules           | 0 reviewed modules without one nameable responsibility                | met    |       |
| Focused functions          | 0 reviewed functions without one nameable job                         | met    |       |
| No unused exports          | 31 public definitions without a direct named importer, as at v9.8.0   | met    |       |
| One way                    | No derivation added; the start instruction still has two homes        | met    | #896  |
| No suppressions            | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                        | met    |       |
| One vocabulary             | 3 disagreements fixed, 1 already tracked; 1 test renamed              | met    |       |
| True documents             | 2 statements that #910 left false corrected                           | met    |       |
| Docs by purpose            | Tutorials, task guides, references and explanations remain separate   | met    |       |
| Versioned contract         | State format 8 unchanged since v9.0.0; contract remains 1             | met    |       |
| Machine-checked rules      | The 11 import-linter contracts and the hooks of v9.9.0 remain         | met    |       |
| Fast readable tests        | 41.40 seconds, 1,566 tests passed, 100% statement and branch coverage | met    |       |
| Current tracker            | 15 open issues read; 3 rewritten in the current words                 | met    |       |
| Reviewed changes           | 5 of 5 merged pull requests answer every definition-of-done question  | met    |       |
| Rules not cases            | 11 ledger entries, unchanged                                          | met    |       |
| Invariants by construction | 71 nullable class fields, as at v9.8.0                                | met    |       |
| Few concepts               | No concept added or removed                                           | met    |       |
| Symmetry                   | No operation added or removed for any kind of agent work              | met    |       |

## Deferred work and previous findings

The v9.6.0 measurement filed #870, the calm field's other names in code
and tests. It remains open.

Issue #896, one home for the instruction that starts each kind of agent
work, remains open.

Open issues in this interval:

- The open issues are #32, #492, #762, #844, #856, #857, #870, #882,
  #894, #896, #901, #902, #911, #914 and #917. #897 and #899 closed with
  #906 and #910.
- #492 called the harness session identifier "the session identifier"
  and proposed a journal entry named `session_seen`; it now says
  "harness session" in both.
- #914 proposed prompt wording that said "wind the assignment up"; it
  now says "wrap the assignment up", the concepts page's word.
- #917 called each sub-issue a "child" in prose, and quoted a
  notification as "Pull request became mergeable"; it now says
  "sub-issue", the out-of-date signal and the mergeable change.
- #882 and #917 still await the product owner's triage, which this pass
  does not replace.

## Notes

- **Cohesive modules, Focused functions.** The largest modules are those
  of v9.9.0, at the same sizes: `github.py` (931 lines),
  `agent_rounds.py` (785), `status/agent_work.py` (629) and
  `status/report.py` (543). The longest functions are unchanged, led by
  `_build_cli_parser` (197 lines), which reads as the list of commands.
  The only source change since v9.9.0 outside the default configuration
  builds the list alias in `documents.py` by call, for the type checker
  that the uv group update brought, and grows the module by one line.
- **No unused exports, One way.** No definition or export was added or
  removed, so the inventories of v9.8.0 stand.
- **No suppressions, Machine-checked rules.** The three coverage pragmas
  remain at `teardown.py:20`, `teardown.py:110` and `commands.py:270`,
  all platform arms. The import contracts and every hook pass.
- **One vocabulary, True documents.** The consistency review covered the
  changes since v9.9.0 against the enduring documents, the user
  documentation, the source and the rendered views. It found three
  disagreements that #910 left behind, and the release preparation fixes
  each one. The `CampaignChildAssignment` docstring and a test name in
  `tests/test_campaigns.py` said that the agent contract names the fault
  flag `is_fault`, which the contract no longer does; they now say that
  the lead's skill may read it by that name. `docs/compatibility.md`
  said that contract version 1 documents the existing protocol, where
  the contract now says only what a skill must and must not say; the
  sentence is gone. The contract required every campaign skill to tell
  the lead how to start a sub-issue's assignment, though
  `docs/start-a-campaign.md` offers a campaign prompt that starts none;
  the requirement now applies when the lead starts one, so that prompt,
  and every skill that met version 1 before #910, still meets it. The
  review also found the "per your assignment's rules" prompt wording
  that #914 already tracks. No word that a "Replaces:" line names
  appears in a replaced sense in the lines changed since v9.9.0, and no
  document or test still names the retired Codex models.
- **Versioned contract.** #910 cut the contract to what a skill must say
  and must not say. No skill that met it has to change, so it stays at
  version 1, as the v9.9.1 changelog says.
- **Fast readable tests.** The default suite passed with 1,566 tests,
  one platform-only skip, and 100% statement and branch coverage, in
  41.40 seconds.
- **Reviewed changes.** #906, #910, #918 and #919 each explain the
  change and answer every definition-of-done question, and #906 and #910
  close the issues they implement. #916 prepared the v9.9.1 patch
  release and answers them too. The Dependabot updates are exempt,
  including the commit on #915 that adapted `documents.py` and the tests
  to the updated type checker.
- **Rules not cases, Invariants by construction, Few concepts,
  Symmetry.** No conditional was added, so the ledger keeps its 11
  entries, and no field was added, so the nullable-field inventory keeps
  its 71. The concepts page is unchanged since v9.9.0.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- The diff of `src` from v9.9.0 establishes that only
  `default_config.toml` and `documents.py` changed, adding no
  definition, field, export or conditional, so the export and
  nullable-field inventories of v9.8.0 stand.
- A search for each word that a "Replaces:" line names covered the lines
  changed since v9.9.0, the repository's skills and every open issue.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the state of the tracker.
