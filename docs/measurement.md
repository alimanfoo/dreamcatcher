# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-24 at `4f985431`, for the v9.1.0 release
preparation. The review covers the 14 pull requests merged since v9.0.0,
with particular attention to the first-ending rule, the daemon stopping
when an update cannot complete, read-only collection fields, the home
card layout, ended assignment cards and pull request readiness. The
consistency review and issue triage ran beside this measurement.

## Results

| Criterion                              | Measured                                                                                                                                           | Status  | Issue      |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ---------- |
| S1 Modules are cohesive                | 0 reviewed modules without one nameable responsibility                                                                                             | met     |            |
| S2 Functions do one thing              | 0 reviewed functions without one nameable job                                                                                                      | met     |            |
| S3 Exports are used                    | 31 public definitions without a direct named importer, the same set as v9.0.0; each is a model, protocol, entry point or part of a named interface | met     |            |
| S4 Each thing is done one way          | Readiness and the pull request finding each gain one home; an ended assignment's card and its page and terminal view word its ending differently   | not met | #782       |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                                                                                                     | met     |            |
| C1 One vocabulary                      | 2 disagreements found, both corrected in this preparation                                                                                          | met     |            |
| C2 Enduring documents are true         | The stories and the architecture disagree on a harness that cannot be started; the conversation-answer promise has a known counterexample          | not met | #758, #781 |
| C3 Documentation by purpose            | Tutorials, task guides, references and explanations remain separate; no new page                                                                   | met     |            |
| C4 Formats and contracts are versioned | State format 8 unchanged since v9.0.0; contract remains 1; no breaking change                                                                      | met     |            |
| K1 Structural rules checked by machine | The 5 named rules remain checked                                                                                                                   | met     |            |
| K2 Suite is fast and speaks plainly    | 47.01 seconds, 1,538 tests passed, 100% statement and branch coverage                                                                              | met     |            |
| K3 Tracker is current                  | 10 open issues triaged; 5 bodies corrected; none ready to close                                                                                    | met     |            |
| K4 Every change reviewed to standard   | All 14 merged PRs answer all 7 definition-of-done questions                                                                                        | met     |            |
| E1 Rules, not cases                    | 11 ledger entries, unchanged; each new conditional applies a stated rule                                                                           | met     |            |
| E2 Invariants by construction          | 70 nullable class fields inspected, one added; a cancel's ended check moved into the conditional write                                             | met     |            |
| E3 Concept economy                     | No domain concept added; the ontology gains the first-ending rule and two trigger words                                                            | met     |            |
| E4 Symmetry                            | Every kind's ending follows the first-ending rule; cancellation keeps its documented difference                                                    | met     |            |

## Deferred work and previous findings

Both disagreements left open by the v9.0.0 measurement have moved. A
wrap-up can no longer overwrite a cancellation (#757): #774 records the
first ending for good under the document lock, so a cancelled assignment
keeps its worktree. The recorded Claude stream whose interim and empty
result events the adapter treats as final answers (#758) remains open,
and the conversation story's promise of one answer still has that
counterexample.

The deferred work the v9.0.0 measurement listed is done, apart from the
unused recorded-feed goldens (#759). Frozen dataclass collection fields
are read-only (#731, through #765), duplicated test helpers have one
home (#735, through #767), the slow macOS test server is built as the
product builds it (#755, through #772), and a failed update stops the
daemon (#756, through #773). The presentation questions are settled too:
ended cards (#733, through #779), the wrap-up wait (#734, through #766),
the card layout (#736, through #770) and pull request readiness (#737,
through #780). A bare campaign sub-issue shows its title alone (#728,
through #764).

The changes since v9.0.0 leave three follow-ups, each filed. An ended
assignment's page still shows "ended" with its reason beneath, where its
card now shows the reason once (#782). A harness invocation that cannot
be built now stops the daemon, because it fails before the round is
recorded (#781). Scheduling tests fabricate rounds after the scheduler's
clock since the round writer has one home (#778).

The triage read all 10 open issues against the ontology and the code. It
corrected five bodies: #781 says scheduler tick and errored rounds where
it said update and a round-error lifecycle, #782 no longer calls the
page's two status words signals, #762 says agent posts, #594 says usage
allowance where it said tokens, and #492's example record drops a
purpose field that nothing records. #782 also gained a comment that the
terminal's view shows the same pair as the page. No issue's work is
done, so none was closed. #761 carries `documentation` rather than one
of the three type labels.

Issues #32, #492, #594, #761 and #762 also remain open.

## Notes

- **S1, S2.** The largest modules are `github.py` (863 lines),
  `agent_rounds.py` (772), `status/agent_work.py` (591),
  `scheduler/tick.py` (506), `agent_work.py` (484), `web/app.py` (467)
  and `status/report.py` (464). They retain their boundary's one
  responsibility. `status/agent_work.py` grows by the readiness flag and
  the open pull request finding that the summary and the flag share.
  `documents.py` (443) grows by the write-once write that endings use,
  which shares its staging with every other write. The tick shrinks as
  launch failures leave it.

  | Function                                      | Lines | Its job                                     |
  | --------------------------------------------- | ----: | ------------------------------------------- |
  | `cli._build_cli_parser`                       |   187 | Define the command-line grammar.            |
  | `AgentRound.__init__`                         |    82 | Record and start one round.                 |
  | `DreamcatcherDaemon.run`                      |    82 | Follow the daemon lifecycle.                |
  | `Scheduler.tick`                              |    81 | Follow the scheduler's update sequence.     |
  | `scheduler.assignments._inspect_pull_request` |    66 | Inspect an assignment's channel.            |
  | `scheduler.campaigns._inspect_lead_input`     |    66 | Decide whether a lead round is due.         |
  | `Scheduler._launch`                           |    61 | Create work and start its round.            |
  | `commands.spawn_command`                      |    52 | Start a child and contain its process tree. |

- **S3, S4.** An AST inventory finds 31 public class or function
  definitions without a direct named import from another source module,
  the same set as at v9.0.0. Review also accounts for imports through
  module objects, package exports, document and view models, callback
  protocols and the console entry point. It establishes no unused public
  function. `InvalidSchedulerRecordError` and
  `WebCampaignChild.is_closed` are gone with what used them.
  `ObservedPullRequest.is_ready_for_review` is now the one home of "open
  and not a draft", which the status words and the chip both read, and
  `_pull_request_finding` replaces the status's inline lookup. The card
  rule that #779 added in `web.views._compose_work_card` words an ended
  assignment's ending as "completed" or "cancelled", where the
  assignment's web page and the terminal's view of it still show "ended"
  with the reason beneath. #782 asks whether the page should follow the
  card; the terminal's view stands with the page.
- **S5, K1.** The three coverage pragmas remain at `teardown.py:20`,
  `teardown.py:110` and `commands.py:270`, all platform arms. The
  architecture tests and lint rules pass, with no suppression added.
- **C2.** The review compares the changed ending, daemon, scheduler,
  status and web paths with all four enduring documents. #773 and #774
  corrected the stories, ontology and architecture in the same changes,
  and the review finds no stale sentence among them. The architecture
  still says that a harness invocation that cannot be built fails the
  tick, which is true and which #781 would change; the stories' "The
  harness refuses or breaks" says instead that a harness that cannot be
  started errors its round, so the two documents disagree until #781
  lands. The conversation story's one-answer promise remains
  contradicted by #758, which this preparation does not change.
- **C3, C4.** The documentation map retains pages by reader purpose. The
  configuration guide's first example gains a campaign route, and the
  stop-and-recover guide says when the daemon stops by itself; neither
  links to a developer document. State format 8 is unchanged. The new
  `ended.json.lock` sidecar sits beside a document that both v9.0.0 and
  v9.1.0 read, so saved work carries across, and the compatibility
  opening says so. The agent contract remains version 1.
- **K2.** The default suite passed with 1,538 tests, one platform-only
  skip, and 100% statement and branch coverage, in 47.01 seconds while
  the consistency review and triage also ran. Its slowest test was
  `test_a_closed_parent_ends_the_campaign_once_its_round_finishes`, at
  21.01 seconds. The separate browser and read-only GitHub integration
  groups passed together: 44 tests, one platform-only skip, 21.31
  seconds. Every pre-commit check passed. The 30 tests added since
  v9.0.0 are named for behaviour; the six `a_write_if_absent` tests name
  a document write, in the style of their module's other write tests.
  Local timing does not establish timing on the other platforms; CI
  covers their behaviour.
- **K4.** The reviewed PRs are #719, #764, #765, #766, #767, #770, #772,
  #773, #774, #775, #776, #777, #779 and #780. Each explains the change,
  links its issue and answers all seven questions; #775 answers two of
  them as not applicable. No Dependabot PR merged in this interval, and
  no commit reached main outside a pull request.
- **E1.** The ledger keeps its 11 entries, none added or removed. The
  new conditionals apply stated rules: the first-ending rule in
  `write_json_if_absent`, `cancel_assignment` and the `cancel` command;
  readiness in the pull request chip; the stories' rule that an ended
  assignment's card gives its reason once; and the page's fallback
  warning when a refresh reaches no server.
- **E2, E3, E4.** The nullable-field inventory is a prompt for review,
  not a target count. It adds `WebAgentWorkCard.detail`, absent exactly
  when the card's status words carry an ended assignment's reason; one
  composer sets both and no branch defends their agreement. The removed
  `is_open` check in `cancel_assignment` gives way to the conditional
  write, which cannot race. No new defensive raise was established. No
  domain concept is added: "awaiting wrap-up" is a detail of waiting,
  and "handed back" and "pull request changed" are the words for
  existing changes. Every kind's ending goes through `end_agent_work`
  and its first-ending rule; only assignments can be cancelled, as the
  ontology says. The ended card's reason wording applies to assignments,
  whose ending has two reasons, while conversations and campaigns end
  only when their issue closes.

## Semantic Consistency Review

### Scope

The namespace, source stubs, changed symbol contracts, enduring and user
documents, templates and open issues were reviewed, weighted to changes
since v9.0.0. Mechanical sweeps found every identifier and path the
enduring documents name, every boolean named as a question, and no
collection field that breaks the read-only rule. Formatting and design
preferences are excluded. Existing issues are reused for supported
findings.

### Summary

Two new disagreements were found and corrected in this preparation. The
one disagreement between enduring documents, on a harness that cannot be
started, is tracked by #781.

### Vocabulary findings

#### 1. The user guides said a cancelled assignment shows as ended on the home page

**Claim A** — `docs/command-reference.md` and `docs/stop-and-recover.md`

> The cancelled assignment shows as **ended** with the detail cancelled
> on the web home page and in `dreamcatcher view`

**Claim B** — `src/dreamcatcher/web/views.py` · `_compose_work_card` ·
body

> `status_words=status.detail if is_ended_assignment else str(status.value),`

**How they differ:** Since #779 an ended assignment's card says
"cancelled" or "completed" once. The campaign tutorial said the same of
a completed stage's card. The three guides now name the card's word and
keep "ended" for `dreamcatcher view`.

### Symbol-contract findings

#### 2. The words for a due wrap-up were described as something new

**Claim A** — `src/dreamcatcher/status/agent_work.py` ·
`_describe_what_is_new` · docstring

> Describe what the latest tick found new in the work's channel, if
> anything.

**Claim B** — the same function · body

> `if finding.is_wrap_up_due: return "awaiting wrap-up"`

**How they differ:** Since #766 the function names a due wrap-up round,
which is not something new in the channel. The docstring now says the
words explain why the finding makes a round due.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- AST inventories over `src` count public definitions without direct
  named importers and class fields whose own annotation admits `None`.
  Package exports and module-object callers are reviewed separately. The
  same inventories over v9.0.0 give the changes since then.
- The namespace and stubs guide targeted body reads and the diff from
  v9.0.0. The docs map guides the documentation review.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the tracker triage.
