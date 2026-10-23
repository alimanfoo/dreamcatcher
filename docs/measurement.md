# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-23 at `eec16efc`, for the v8.0.0 release
preparation. The review covers the changes since v7.0.0: 12 merged pull
requests, which let every terminal command select work of any kind with
one argument, end a daemon's rounds on SIGTERM and SIGHUP, put the home
page's tabs in the address, and fix the four shortfalls that the
previous measurement recorded. The consistency review and the issue
triage ran beside this measurement.

## Results

| Criterion                              | Measured                                                                                                             | Status  | Issue      |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------- | ---------- |
| S1 Modules are cohesive                | 0 reviewed modules without one nameable responsibility                                                               | met     |            |
| S2 Functions do one thing              | 0 reviewed functions without one nameable job                                                                        | met     |            |
| S3 Exports are used                    | 36 names without a direct importer; 2 public with no caller outside their module, 2 package exports with no importer | not met | #713       |
| S4 Each thing is done one way          | 1 round input read by different rules; 2 GitHub name comparisons made in more than one place                         | not met | #712, #714 |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                                                                       | met     |            |
| C1 One vocabulary                      | 3 disagreements corrected in this preparation; 2 remain                                                              | not met | #715, #716 |
| C2 Enduring documents are true         | 1 incomplete architecture claim corrected in this preparation                                                        | met     |            |
| C3 Documentation by purpose            | `view` replaces three commands in the reference and the guides; no new page                                          | met     |            |
| C4 Formats and contracts are versioned | State format 7 and contract 1 unchanged; the command change has a Breaking entry and an upgrade section              | met     |            |
| K1 Structural rules checked by machine | The 5 named rules remain checked                                                                                     | met     |            |
| K2 Suite is fast and speaks plainly    | 46.45 seconds, 100% statement and branch coverage                                                                    | met     |            |
| K3 Tracker is current                  | 20 open issues triaged against the ontology; 6 rewritten, none to close                                              | met     |            |
| K4 Every change reviewed to standard   | All 12 PRs answer the definition of done                                                                             | met     |            |
| E1 Rules, not cases                    | 10 ledger entries with external causes, 1 new; no unsupported new case found                                         | met     |            |
| E2 Invariants by construction          | 66 nullable fields, none added; 2 raises defend round input states its model could refuse                            | not met | #712       |
| E3 Concept economy                     | No concept added; the ontology changes only the definition of retry                                                  | met     |            |
| E4 Symmetry                            | Every command but cancel takes any kind; 1 asymmetry in how a round input is read                                    | not met | #712       |

## Deferred work and previous findings

The previous measurement recorded four shortfalls, and a fix for each
has merged. Pull request #702 fixes #684, making `find_pause` private
again; #703 fixes #685, deciding in `github.py` alone whether an issue
is in the daemon's repository; #704 fixes #686, reading every kind's
round input in `status.rounds` the same way; and #692 fixes #687 for the
two reasons it named. Two of those fixes left new findings behind,
recorded under S3, S4, E2 and E4.

The triage read all 20 open issues against the ontology, and this
preparation rewrote six of them. Four named a concept by a word the
ontology does not use: "subissue" and "child issue" became "sub-issue"
in #693, #694 and #699, and "lead agent" became "lead" in #709. Two, #97
and #109, named the commands that `dreamcatcher view` replaced. No
issue's work was done or no longer applied, so none was closed.

Of the questions left open last time, #594 stays open. The new defaults
in #707 settle #635, giving `dream:less` Sonnet and `gpt-5.6-terra` at
high effort, and the startup sweep in #690 settles #61 by skipping a
round that started before the last boot.

## Notes

- **S1, S2.** The largest modules are `github.py` (854 lines),
  `agent_rounds.py` (772), `status/agent_work.py` (564),
  `scheduler/tick.py` (474), `agent_work.py` (460) and `web/app.py`
  (455). Their responsibilities are unchanged: the GitHub boundary,
  round execution and records, shared work-status derivation, the tick,
  the shared work record and the web routes. `cli.py` shrank from 535 to
  446 lines when one work argument replaced the kind selectors and the
  three detail commands. `daemon.py` grew from 274 to 321 lines, all of
  it the shutdown signals and the startup sweep, which belong to the
  daemon lifecycle that the architecture lists. The long functions below
  still each do one named job.

  | Function                                      | Lines | Its job                                          |
  | --------------------------------------------- | ----: | ------------------------------------------------ |
  | `cli._build_cli_parser`                       |   187 | It defines the command-line grammar.             |
  | `AgentRound.__init__`                         |    82 | It records and starts one round.                 |
  | `DreamcatcherDaemon.run`                      |    80 | It follows the daemon lifecycle.                 |
  | `Scheduler.tick`                              |    71 | It follows the scheduler's update sequence.      |
  | `scheduler.assignments._inspect_pull_request` |    66 | It inspects an assignment's channel.             |
  | `scheduler.campaigns._inspect_lead_input`     |    66 | It decides whether a lead round is due.          |
  | `Scheduler._launch`                           |    58 | It creates work and starts its round.            |
  | `commands.spawn_command`                      |    52 | It starts a child process and contains its tree. |

  `DreamcatcherDaemon.run` grew by 4 lines, for the context that turns
  termination signals into an interrupt.

- **S3.** 36 names have no direct importer from another source module.
  The rest are document models, projections, protocols, view models,
  entry points, and architecture and contract constants. Since #691,
  `scheduler/__init__.py` exports `derive_agent_work_fault` and
  `read_scheduler_record` with no importer under `src`: `status` and
  `scheduler.tick` import both from `scheduler.faults`, and only
  `tests/test_cli.py` uses the package export. Since #704,
  `issue_conversations.read_conversation_input` and
  `campaigns.read_campaign_input` have no caller outside their modules.
  The same inventory finds 35 names at v7.0.0, against the 33 the
  previous measurement reported, so the count depends on its method.
- **S4.** `read_conversation_input` refuses a round input that relays no
  comments, names another issue, or holds comments out of order. Since
  #704, `status.rounds` reads the same file with none of those checks,
  so for the newest relayed input the scheduler can hold a read failure
  in the conversation's row while status counts the input's comments.
  Two comparisons older than v7.0.0 are also made in more than one
  place: whether a GitHub login names the signed-in account, in
  `github._UserPostProjection.is_written_by` and
  `scheduler.issue_work._find_pause`; and whether two label names are
  one label, in `config`, `_find_pause` and the scheduler tick. #703
  settled the same pattern for repositories.
- **S5.** The three coverage pragmas remain at `teardown.py:20`,
  `teardown.py:110` and `commands.py:270`, all platform arms. The new
  platform choice in `daemon._TERMINATION_SIGNALS` is a conditional
  expression, which needs no pragma, and is on the ledger.
- **C1.** The consistency review, weighted to the changes since v7.0.0,
  corrected three disagreements: a conversation round input naming
  another issue gave the reason "input names GH9", which can reach the
  web pages, and now says "issue 9", as #692 did for its siblings; the
  triage skill's "external fault" is now the stories' "expected fault";
  and the architecture's retry paragraph now names the `retry` command
  beside the web interface. Two remain. The web feed calls how far a
  page has shown a round's feed its cursor, which the ontology keeps for
  how far the agent has read in its channel, while the terminal feed
  calls the same idea a position. The scheduler names the fault flag
  `is_fault`, where status names the same question `is_in_fault`.
- **C2.** The review read the daemon, web, status, retry and
  work-selection claims of the ontology, the architecture and the
  stories against the changed code. #690, #691 and #698 each corrected
  the documents they moved past. One claim was incomplete, and this
  preparation completes it: the architecture said only that the web
  interface requests a retry, and since #691 the `retry` command does it
  the same way.
- **C3, C4.** The command reference documents `view`, and the how-to
  pages and the campaign tutorial use `view` and `feed GH123`. No page
  was added. State format 7 and contract 1 are unchanged. The command
  change has a Breaking entry in the changelog and an upgrade section in
  [Compatibility and upgrades](compatibility.md).
- **K1, K2.** All 1,482 default tests passed in 46.45 seconds, with 100%
  statement and branch coverage, against 1,454 in 40.77 seconds at
  v7.0.0. The macOS run skips the Windows-only containment module;
  Windows CI exercises it. The separate browser and live GitHub
  integration tests passed, 35 of them, in 19.78 seconds.
  `tests/test_architecture.py` is unchanged, and the new `signal` and
  `psutil` imports fall under no boundary rule. The new test functions
  are named for behaviours, such as
  `test_an_issue_with_more_than_one_piece_of_work_asks_which` and
  `test_the_address_names_the_home_tab_so_back_and_forward_move_between_tabs`.
- **K4.** The 12 PRs are #690, #691, #692, #698, #700, #701, #702, #703,
  #704, #705, #707 and #708. Each says what it changes and why and
  answers all seven questions by number. Eleven link the issue they
  close, and #708, a change to the triage skill, names the triage it
  follows. No Dependabot PR merged in the interval.
- **E1.** The new branches apply rules: a round from before the last
  boot cannot still be alive; a signal the daemon was started to ignore
  stays ignored; cancel is for assignments, as the ontology says; an
  issue with more than one piece of work names none; and a feed round
  that opens in a refresh holds its own boundary. The one new platform
  case, that Windows has no hangup signal, is on the ledger.
- **E2.** The optional-field count is 66, as at v7.0.0 by the same
  count; the previous page gave 65. `read_conversation_input` raises for
  an input that relays no comments and for comments out of order, states
  that validators on `ConversationRoundInput` could refuse.
- **E3.** The ontology's only change rewrites the definition of retry to
  match #691. No concept was added.
- **E4.** `retry`, `stop`, `view` and `feed` each take work of every
  kind through one argument, and only `cancel` refuses work that is not
  an assignment, as the ontology says. The terminal no longer lists
  other work beside one piece's view, which the web page never did. One
  asymmetry remains: only a conversation's input reader checks that the
  input names the work's issue and holds ordered comments, although
  `CampaignRoundInput` has the same fields and the ontology names no
  difference that calls for it.

## Method

- `tools/measure_source.py` supplies module and function line counts.
  Review checks responsibility rather than imposing a length limit.
- An AST inventory finds public top-level definitions without direct
  imports from another source module, and checks each package's
  `__all__` against imports from outside the package. Review classifies
  each remaining name. The same inventory finds 35 names at v7.0.0.
- A separate AST count finds class fields whose own annotation admits
  `None`, and gives 66 at both v7.0.0 and `eec16efc`.
- The documents were read against the stubs and the bodies of the
  changed daemon, CLI, status, TUI and web code, and against the diff
  since v7.0.0.
- Default tests establish branch coverage and timing. Browser tests
  exercise rendered interactions; integration tests read the live GitHub
  service. Both ran at `eec16efc`. CI also validates Linux and Windows
  behaviour.
- PR descriptions establish K4 for the interval since v7.0.0.
