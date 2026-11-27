# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-11-27 at `e30c7d1c`, for the v10.0.0 release
preparation. The review covers the pull requests merged since v9.10.0,
the last measured release: the branch-campaigns specification (#924) and
its nine stages, consumed requests (#934), pull request work (#935),
assignments that target a base branch (#936), the parent check (#937),
campaigns on a branch (#938), the coordinating lead (#939), cancelling a
campaign (#940), the finishing phase (#941), the tidy-up after stages 1
to 8 (#943) and the user guides (#945). No Dependabot update merged in
this interval. The consistency review and the pass over open issues ran
beside this measurement.

## Results

| Criterion                  | Measured                                                                 | Status  | Issue |
| -------------------------- | ------------------------------------------------------------------------ | ------- | ----- |
| Cohesive modules           | 0 reviewed modules without one nameable responsibility                   | met     |       |
| Focused functions          | 0 reviewed functions without one nameable job                            | met     |       |
| No unused exports          | 31 public definitions without a direct named importer; 2 left, 2 came    | met     |       |
| One way                    | No derivation added; the start instruction still has two homes           | met     | #896  |
| No suppressions            | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                           | met     |       |
| One vocabulary             | 8 disagreements found, 7 fixed and 1 filed; 9 replaced words fixed       | met     | #947  |
| True documents             | 3 architecture statements, 1 incomplete list and 1 story corrected       | met     |       |
| Docs by purpose            | Tutorials, task guides, references and explanations remain separate      | met     |       |
| Versioned contract         | State format 9 and contract version 2, each with a Breaking entry        | met     |       |
| Machine-checked rules      | The 11 import-linter contracts and the hooks of v9.10.0 remain           | met     |       |
| Fast readable tests        | 39.80 seconds, 1,583 tests passed, 100% statement and branch coverage    | met     |       |
| Current tracker            | 17 open issues read; 1 closed as done, 4 rewritten                       | met     |       |
| Reviewed changes           | 11 of 11 merged pull requests answer every definition-of-done question   | met     |       |
| Rules not cases            | 12 ledger entries, 1 added with an external cause                        | met     |       |
| Invariants by construction | 75 nullable class fields; 2 fallbacks for a missing application time     | not met | #948  |
| Few concepts               | 7 concepts added with the design's case; pausing a campaign removed      | met     |       |
| Symmetry                   | Campaigns gain cancellation and share pull request work with assignments | met     |       |

## Deferred work and previous findings

The v9.6.0 measurement filed #870, the calm field's other names in code
and tests. It remains open.

Issue #896, one home for the instruction that starts each kind of agent
work, remains open.

Open issues in this interval:

- The open issues were #32, #492, #762, #844, #856, #857, #870, #882,
  #894, #896, #901, #902, #911, #914, #917, #944 and #946. #925 to #933
  and #942 closed with the pull requests that implemented them. #944 and
  #946 are new maintenance issues.
- #894, the branch-campaign phase, closed as completed: its nine stages
  and the tidy-up have merged, and `specs/AGENTS.md` lists its
  specification folder as complete.
- #917 now names the campaign's pull request as the lead's channel. #914
  quotes the round prompts as they stand. #844 describes the chips as
  they are since #842. #492's example entry and module names match the
  code.
- This measurement and the consistency review filed #947 and #948.
- #882 and #917 still await the product owner's triage, which this pass
  does not replace.

## Notes

- **Cohesive modules, Focused functions.** The largest modules are
  `github.py` (1,019 lines, up from 931 with the parent read, the label
  application time and issue closure), `agent_rounds.py` (789),
  `status/agent_work.py` (577, down from 629) and `scheduler/tick.py`
  (567, up from 504 with the consumed-request check and the shared
  campaign pull request read). `relay.py` grew from 172 to 260 lines and
  `scheduler/conversations.py` from 127 to 208; each still owns one
  responsibility, the relay past a cursor and a conversation's
  inspection. `pull_request_work.py` (265) replaces
  `agent_assignments.py` and `agent_assignment_pull_requests.py`, and
  `scheduler/pull_requests.py` (140) replaces `scheduler/issue_work.py`.
  The longest function is still `_build_cli_parser` (196 lines), which
  reads as the list of commands. `Scheduler.tick` grew from 81 to 96
  lines and still reads as the tick's steps. The new
  `create_assignment_request_inspector` (61), `inspect_open_campaign`
  (51) and `_prepare_campaign_round` (44) each read as one inspection or
  preparation in order.
- **No unused exports, One way.** The same AST inventory as v9.8.0 finds
  31 public class or function definitions without a direct named
  importer. `github.LabellingEvent` gained an importer and
  `scheduler.issue_work.EligibleIssueWorkInspector` went with its
  module. `github.ParentIssue` is a GitHub response projection, and
  `relay.PullRequestPostCursor` is the type that the relay's
  `read_user_post_cursor` returns. Cancellation of pull request work has
  one operation, `cancel_pull_request_work`, which the command and the
  page share.
- **No suppressions, Machine-checked rules.** The three coverage pragmas
  remain at `teardown.py:20`, `teardown.py:110` and `commands.py:270`,
  all platform arms. The import contract "Agent work never reaches
  scheduling" names `pull_request_work` in place of the two modules it
  replaced. The import contracts and every hook pass.
- **One vocabulary, True documents.** The consistency review found eight
  disagreements. Seven were fixed for the release: the concepts page now
  says that users see a consumed request called used; the `PauseCause`
  docstring no longer says a campaign pauses; the `view` help and
  `about.md` describe campaigns and the base branch; the list of held
  reasons in `run-and-monitor.md` includes a sub-issue's unavailable
  campaign pull request; `index.md` no longer offers to request changes
  on your own pull request; and `read_pull_request_post_cursor` replaces
  `read_user_post_cursor`. #947 tracks the eighth, the round input's
  `finished_turn`. A search for each replaced word found nine uses of
  "failed" for an errored round or "running" for working, all fixed. A
  reading of the architecture against the code found four statements
  that the code did not bear out, all corrected: when an opening round
  is due, when wrap-up closes the issue, the order of the tick's
  cooldown and worktree removal, and the list of typed findings. One
  story no longer says that a lead can be held.
- **Versioned contract.** #934 raised the state format to 9 in
  `.dreamcatcher/v9/`, and #939 raised the agent contract to version 2.
  `docs/compatibility.md` states each, and the changelog's Breaking
  entries say what the user must do for each.
- **Fast readable tests.** The default suite passed with 1,583 tests,
  one platform-only skip, and 100% statement and branch coverage, in
  39.80 seconds. The 44 test names added since v9.10.0 each name a
  behaviour.
- **Reviewed changes.** All eleven pull requests explain the change,
  link the issue or the roadmap stage they implement, and answer every
  definition-of-done question. #924 holds the specification and links
  #894.
- **Rules not cases.** #936 added the ledger's twelfth entry,
  `pull_request_work.close_issue_for_merged_pull_request`, because
  GitHub acts on a closing keyword only for a pull request into the
  default branch. The other conditionals added apply rules the concepts
  page states, such as a conversation's label being a switch and a
  parent in another repository never matching a campaign.
- **Invariants by construction.** The nullable-field inventory rose from
  71 to 75. Six fields went with the round plan and the campaign's
  issue-comment cursor, and ten came: the application time and base
  branch on `AgentWorkRecord` and `DispatchRequest`, the prepared
  round's input and finisher, and the parent in GitHub's answer. The
  application time is absent exactly for a conversation, but the record
  carries kind and time as two fields, so two places defend against an
  assignment or campaign with no time: `scheduler/assignments.py:114`
  orders campaigns with `label_applied_at or datetime.min`, and
  `scheduler/tick.py:397` filters missing times out of the consumed
  applications.
- **Few concepts, Symmetry.** The concepts page gains the base branch,
  the campaign branch, a campaign's sub-issue, a consumed request, the
  coordinating and finishing phases, and pull request work, each of
  which the design in `specs/2026-11-26-branch-campaigns/` sets out.
  Pausing a campaign by its label is gone. A campaign now has the
  assignment's pull request channel, opening, wrap-up and cancellation
  through the shared pull request work, and the concepts page names the
  phases where the two differ.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
  The same tool over v9.10.0 gives the changes since then.
- AST inventories over `src` count public definitions without direct
  named importers and class fields whose own annotation admits `None`.
  The same inventories over v9.10.0 reproduce its 31 and 71 and give the
  changes since then.
- The namespace map and stubs guided targeted reads of the architecture
  and the stories and concepts pages against the code changed since
  v9.10.0.
- A search for each word that a "Replaces:" line names covered every
  open issue.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the state of the tracker.
