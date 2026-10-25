# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-25 at `e659f0af`, for the v9.2.0 release
preparation. The review covers the 12 pull requests merged since v9.1.0,
with particular attention to a Claude round's final output, the Codex
final-output path, the words ended work shows, the feed position parser,
the campaign documentation and the supply-chain checks. The consistency
review and issue triage ran beside this measurement.

## Results

| Criterion                              | Measured                                                                                                                                           | Status | Issue |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----- |
| S1 Modules are cohesive                | 0 reviewed modules without one nameable responsibility                                                                                             | met    |       |
| S2 Functions do one thing              | 0 reviewed functions without one nameable job                                                                                                      | met    |       |
| S3 Exports are used                    | 31 public definitions without a direct named importer, the same set as v9.1.0; each is a model, protocol, entry point or part of a named interface | met    |       |
| S4 Each thing is done one way          | The words ended work shows have one home in `status`; the card, the page and the terminal view read them                                           | met    |       |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                                                                                                     | met    |       |
| C1 One vocabulary                      | 5 disagreements found, 4 corrected in this preparation and 1 accepted as a landing-page simplification                                             | met    |       |
| C2 Enduring documents are true         | The two disagreements v9.1.0 left open are resolved; one overstated timing claim corrected in this preparation                                     | met    |       |
| C3 Documentation by purpose            | Tutorials, task guides, references and explanations remain separate; no new page                                                                   | met    |       |
| C4 Formats and contracts are versioned | State format 8 unchanged since v9.0.0; contract remains 1; no breaking change                                                                      | met    |       |
| K1 Structural rules checked by machine | The 5 named rules remain checked; zizmor now checks the workflows                                                                                  | met    |       |
| K2 Suite is fast and speaks plainly    | 52.16 seconds, 1,553 tests passed, 100% statement and branch coverage                                                                              | met    |       |
| K3 Tracker is current                  | 6 open issues triaged; 1 body corrected; none ready to close                                                                                       | met    |       |
| K4 Every change reviewed to standard   | All 11 merged PRs answer all 7 definition-of-done questions; 1 Dependabot PR                                                                       | met    |       |
| E1 Rules, not cases                    | 11 ledger entries, unchanged; each new conditional applies a stated rule                                                                           | met    |       |
| E2 Invariants by construction          | 72 nullable class fields inspected, two added; one defended failure removed                                                                        | met    |       |
| E3 Concept economy                     | No domain concept added; "stage" leaves the documents as a second name for a sub-issue                                                             | met    |       |
| E4 Symmetry                            | Ended work of every kind shows its state the same way; Claude and Codex both take the last answer once the stream ends                             | met    |       |

## Deferred work and previous findings

Both disagreements left open by the v9.1.0 measurement are resolved. A
Claude round's final output is now the last result event with text, read
once the stream ends (#758, through #793), so the conversation story's
promise of one answer holds for a round that waits on background
subagents. Codex is given its final-output path relative to the
worktree, so building a harness invocation can no longer fail and the
stories and the architecture agree again (#781, through #795).

The follow-ups the v9.1.0 measurement filed are done or declined. Ended
work of every kind shows how it ended once, in place of "ended", on its
card, its page and in `dreamcatcher view`, from one rule in `status`
(#782, through #796). The unused recorded-feed goldens are gone (#759,
through #794). #778, on the scheduling tests' fabricated round times,
was declined in triage: no test depends on it, and the mistake it guards
against would fail loudly.

Since v9.1.0 the repository also checks its workflows with zizmor, pins
its build backend, and holds the release engineering decisions of #785
(#787, #800). Feed positions are parsed without a regular expression,
which closes CodeQL's recurring false positive (#786, through #797). The
agent guide installs the commit hooks from the main checkout only (#789,
through #801), and the hint for an unrouted kind of work is plainer
(#784, through #802). The campaign documentation explains what a
campaign is for and calls its issues sub-issues (#761, through #799).

The triage read all 6 open issues against the ontology and the code. It
corrected one body: #762 now speaks of the pull request of a sub-issue's
assignment where it spoke of a stage's pull request. No issue's work is
done, so none was closed. #803, filed during this interval, asks that an
ended campaign keep its sub-issues under its card.

Issues #32, #492, #594, #762 and #803 remain open.

## Notes

- **S1, S2.** The largest modules are `github.py` (863 lines),
  `agent_rounds.py` (785), `status/agent_work.py` (614),
  `scheduler/tick.py` (506), `agent_work.py` (484), `web/app.py` (467)
  and `status/report.py` (464). They retain their boundary's one
  responsibility. `agent_rounds.py` grows by the round's final-output
  path from its worktree, and loses the flag that settled the final
  output at the first result event. `status/agent_work.py` grows by the
  table of words that ended work shows. The longest functions are those
  of v9.1.0, with the same jobs.

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
  the same set as at v9.1.0. Review also accounts for imports through
  module objects, package exports, document and view models, callback
  protocols and the console entry point. It establishes no unused public
  function. The card rule that v9.1.0 found in
  `web.views._compose_work_card` is gone: `AgentWorkStatus.words` is the
  one home of the words ended work shows, and the card, the page's live
  state and both terminal renderers read it.
- **S5, K1.** The three coverage pragmas remain at `teardown.py:20`,
  `teardown.py:110` and `commands.py:270`, all platform arms. The
  architecture tests and lint rules pass, with no suppression added.
  zizmor now runs as a frozen commit hook over the workflows, beside
  actionlint.
- **C1.** The consistency review below found five disagreements. Four
  are corrected here; the home page's account of what a campaign's lead
  does is accepted as written.
- **C2.** The review compares the changed final-output, harness, status,
  web and documentation paths with all four enduring documents. #793,
  #795, #796 and #799 corrected the stories, ontology and architecture
  in the same changes. The architecture said that the round reads
  Claude's answer once the stream ends, which holds unless a process the
  harness left behind keeps the stream open; it now says so.
- **C3, C4.** The documentation map retains pages by reader purpose. The
  campaign tutorial is renamed, and its section on parallel pull
  requests moves to the campaign task guide, where a campaign with
  several sub-issues open at once needs it. State format 8 and the agent
  contract's version 1 are unchanged; the contract's campaign section
  changes only its wording, from stages to sub-issues.
- **K2.** The default suite passed with 1,553 tests, one platform-only
  skip, and 100% statement and branch coverage, in 52.16 seconds. Its
  slowest test was
  `test_a_closed_parent_ends_the_campaign_once_its_round_finishes`, at
  21.43 seconds. The separate browser and read-only GitHub integration
  groups passed together: 45 tests, one platform-only skip, 26.49
  seconds. Every pre-commit check passed. The 14 tests added since
  v9.1.0 are named for behaviour. Local timing does not establish timing
  on the other platforms; CI covers their behaviour.
- **K4.** The reviewed PRs are #787, #790, #793, #794, #795, #796, #797,
  #799, #800, #801 and #802. Each explains the change, links its issue
  and answers all seven questions. Dependabot's #791 bumped virtualenv
  in the uv security group. Branch protection now applies to
  administrators too, so no commit reaches main outside a pull request,
  and none did in this interval.
- **E1.** The ledger keeps its 11 entries, none added or removed. The
  new conditionals apply stated rules: a Claude result event with blank
  text gives no final output, because the answer is the last result
  event with text; ended work's words come from one table of end
  reasons; and a feed position accepts ASCII digits alone.
- **E2, E3, E4.** The nullable-field inventory is a prompt for review,
  not a target count. It adds `AgentWorkStatus.detail` and
  `WebAgentLiveState.detail`, absent exactly when the work has ended,
  because its status words then say how it ended.
  `AgentWorkStatus.words` reads the work's ending through a cast that
  relies on an ended status having a recorded ending, as the ended
  list's sort in `status/report.py` already did; no branch or raise
  defends it. Building a harness invocation no longer raises, because
  the path it carries cannot hold a character that `cmd.exe` acts on. No
  domain concept is added, and "stage" leaves the documents, where it
  was a second name for a sub-issue. Ended work of every kind now shows
  its state the same way, and Claude and Codex both give the last answer
  of a round.

## Semantic Consistency Review

### Scope

The namespace, the whole diff from v9.1.0, the source, templates,
enduring and user documents, the agent guide, the packaging and the
workflows were reviewed. Each change was checked against the other
claims about its concept: the absence of "stage", the words ended work
shows, the unrouted-kind hint, the final output of both harnesses, the
feed position, the harness recordings, the CI packaging check, the
security policy and the hook installation. Formatting and design
preferences are excluded.

### Summary

Five disagreements were found. Four were corrected in this preparation,
and one is accepted.

### Vocabulary findings

#### 1. Which paths need no quoting check

**Claim A** — `AGENTS.md` · "Module and process boundaries"

> A name that _dreamcatcher_ chose itself, such as a work identifier or
> a path inside the state directory, needs no check.

**Claim B** — `src/dreamcatcher/agent_rounds.py` ·
`AgentRoundPaths.final_output_from_worktree` · docstring

> Every name in it is one that dreamcatcher chose, never the checkout's
> own path, so a harness's command line can carry it on every platform.

**How they differ:** The state directory lies inside the checkout, so an
absolute path in it carries the checkout's own path, which can hold a
percent sign. The guide now exempts a path made only of _dreamcatcher_'s
names, such as a round's files from its worktree.

#### 2. What a campaign's lead does

**Claim A** — `docs/index.md` · "How it works"

> The lead sets up assignments, reviews and merges their pull requests,
> and asks you on the parent when a decision is needed.

**Claim B** — `docs/start-a-campaign.md` · opening

> The configured prompt tells the lead what to do with them. The default
> `dream:lead` route shepherds each sub-issue through an assignment and
> merged pull request

**How they differ:** The home page describes the default route's lead as
every campaign's. This is accepted: the home page introduces the product
to a newcomer, and the task guide gives the qualification.

#### 3. The changelog's rule and its Unreleased section

**Claim A** — `docs/changelog.md` · preamble

> A change that users would notice gets an entry here: a change to a
> command, a setting, a message, a view, the documentation, the state
> format or the agent contract.

**Claim B** — `docs/changelog.md` · Unreleased, which held no entry for
the pull request that rewrote the home page and the campaign tutorial.

**How they differ:** That change is one a user notices, so the v9.2.0
section now has an entry for it, citing its pull request.

### Symbol-contract findings

#### 4. When the round reads Claude's final output

**Claim A** — `docs/architecture.md` · "Issue conversations"

> Claude supplies the answer in the last result event that has text,
> which the round reads once Claude's output stream ends.

**Claim B** — `src/dreamcatcher/agent_rounds.py` ·
`AgentRound._read_final_output` · body

> `self._stdout_reader.join(_FINAL_OUTPUT_CAPTURE_TIMEOUT_SECONDS)`

**How they differ:** The round waits for the stream to end for at most
five seconds, for a process the harness left behind that keeps the pipe
open. The architecture now says so.

#### 5. An article before "assignment's agent"

`docs/architecture.md` · "Campaigns" read "the lead reaches a
assignment's agent", a slip left by the change from "stage". It now
reads "an assignment's agent".

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- AST inventories over `src` count public definitions without direct
  named importers and class fields whose own annotation admits `None`.
  Package exports and module-object callers are reviewed separately. The
  same inventories over v9.1.0 give the changes since then.
- The namespace and stubs guide targeted body reads and the diff from
  v9.1.0. The docs map guides the documentation review.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the tracker triage.
