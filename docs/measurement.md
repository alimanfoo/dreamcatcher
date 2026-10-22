# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-22 at `db94cc8f`, for the v7.0.0 release
preparation. The review covers the changes since v6.3.0: 17 merged pull
requests, which add campaigns as a third kind of agent work, move saved
state to state format 7, and queue campaigns behind the issues that
block their parents. The consistency review and the issue triage ran
beside this measurement.

## Results

| Criterion                              | Measured                                                                          | Status  | Issue |
| -------------------------------------- | --------------------------------------------------------------------------------- | ------- | ----- |
| S1 Modules are cohesive                | 0 reviewed modules without one nameable responsibility                            | met     |       |
| S2 Functions do one thing              | 0 reviewed functions without one nameable job                                     | met     |       |
| S3 Exports are used                    | 33 names without a direct importer; 1 is public with no caller outside its module | not met | #684  |
| S4 Each thing is done one way          | 1 fact derived in two scheduler modules                                           | not met | #685  |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                                    | met     |       |
| C1 One vocabulary                      | 9 disagreements corrected in this preparation; 1 remains                          | not met | #687  |
| C2 Enduring documents are true         | 1 architecture claim and 3 incomplete lists corrected in this preparation         | met     |       |
| C3 Documentation by purpose            | A campaign tutorial and a campaign task guide join the existing kinds of page     | met     |       |
| C4 Formats and contracts are versioned | State format 7 and contract 1, both with policy and a changelog entry             | met     |       |
| K1 Structural rules checked by machine | The 5 named rules remain checked, and cover the new campaign module               | met     |       |
| K2 Suite is fast and speaks plainly    | 40.77 seconds, 100% statement and branch coverage                                 | met     |       |
| K3 Tracker is current                  | 24 open issues triaged against the ontology; 7 rewritten, none to close           | met     |       |
| K4 Every change reviewed to standard   | All 15 PRs other than Dependabot's answer the definition of done                  | met     |       |
| E1 Rules, not cases                    | 9 ledger entries with external causes; no unsupported new case found              | met     |       |
| E2 Invariants by construction          | 65 nullable fields; no coupled-field defence found                                | met     |       |
| E3 Concept economy                     | Campaigns add one kind of agent work, with the case made in its spec              | met     |       |
| E4 Symmetry                            | Every kind shares selection, detail, feed, stop and retry; 1 asymmetry in status  | not met | #686  |

## Deferred work and previous findings

The previous measurement recorded no open shortfall and deferred the
backlog triage. This preparation ran it over all 24 open issues. Seven
named a concept by a word the ontology no longer uses, or described
files and functions that state format 7 replaced, and this preparation
rewrote them: #61, #63, #67, #109, #113, #492 and #635. "Delivery
position" became "cursor", and #109 and #113 now cover every kind of
agent work. No issue's work was done or no longer applied, so none was
closed.

The questions the previous measurement left open stand as they were.
Issue #594, whether a collaborator may start work on a teammate's
instance, stays open, and the teammate story still leaves it open. #635,
which would change the default models, is still open, and the default
configuration keeps its models. #631, then a draft, has merged as the
campaign specification in `specs/2026-10-20-campaigns/`, and its eight
stages have merged since, closing #593.

## Notes

- **S1, S2.** The largest modules are `github.py` (846 lines),
  `agent_rounds.py` (772), `status/agent_work.py` (559), `cli.py` (535)
  and `agent_work.py` (487). Their responsibilities remain the GitHub
  boundary, round execution and records, shared work-status derivation,
  command-line grammar and dispatch, and the shared work record. The new
  modules each own one thing: `campaigns.py` (277) the campaign round
  input and the comparison of the sub-issues, `scheduler/campaigns.py`
  (343) a campaign's inspection, `scheduler/issue_work.py` (133) what
  conversations and campaigns share, and `scheduler/blockers.py` (36)
  the read of an issue's blockers. The long functions below still follow
  one named job.

  | Function                                      | Lines | Its job                                          |
  | --------------------------------------------- | ----: | ------------------------------------------------ |
  | `cli._build_cli_parser`                       |   226 | It defines the command-line grammar.             |
  | `AgentRound.__init__`                         |    82 | It records and starts one round.                 |
  | `DreamcatcherDaemon.run`                      |    76 | It follows the daemon lifecycle.                 |
  | `Scheduler.tick`                              |    71 | It follows the scheduler's update sequence.      |
  | `scheduler.assignments._inspect_pull_request` |    66 | It inspects an assignment's channel.             |
  | `scheduler.campaigns._inspect_lead_input`     |    66 | It decides whether a lead round is due.          |
  | `Scheduler._launch`                           |    58 | It creates work and starts its round.            |
  | `commands.spawn_command`                      |    52 | It starts a child process and contains its tree. |

  `Scheduler.tick` grew by its second pass, which inspects the campaigns
  after the assignments and conversations, as the architecture's tick
  steps list.

- **S3.** The 33 names without a direct importer from another source
  module are document models, projections, protocols, entry points, and
  architecture and contract constants. Module-qualified calls count as
  callers. `scheduler.issue_work.find_pause` is the exception. It was
  private in `scheduler/conversations.py` at v6.3.0, became public when
  conversations and campaigns came to share it, and is now called only
  from `inspect_open_issue_work` in its own module. No test imports it.
- **S4.** Whether an issue that a REST endpoint lists is in the daemon's
  repository is derived twice, by the same case-insensitive comparison
  of `repository` with `context.repository`: in
  `scheduler.campaigns._observe_children`, which refuses a sub-issue in
  another repository, and in `scheduler.blockers._refer_to_issue`, which
  names a blocker's repository. #676 followed the sub-issue comparison,
  as its description says. The web page and the terminal name a blocker
  in another repository the same way, as `owner/name#123`.
- **C1.** The ontology names "child" as the code's word for a sub-issue,
  as #678 settled. The consistency review, weighted to the changes since
  #678, corrected nine disagreements: the package and site descriptions,
  which named only assignments; the ontology's missing `owner/name#123`
  form for an issue in another repository; "subissue" in the
  conversation prompt and contract; "no work yet" for a request row in
  the `status` help and two guides; "settled route" in the command
  reference; "child worktree" and "a round is one turn" in the tutorial;
  the contract's "a round is over when the process exits"; and the
  stories' page-refresh story, which left out the campaign page. One
  remains, #687: a sub-issue the campaign cannot observe is named `GH12`
  on the web pages, where the ontology writes `#12`.
- **C2.** The review read the campaign, queuing and blocker claims of
  the ontology, the architecture and the stories against
  `scheduler/campaigns.py`, `campaigns.py`, `scheduler/issue_work.py`,
  `scheduler/blockers.py`, `status` and the web views. One claim was
  contradicted, and this preparation corrects it with the lists beside
  it. The architecture's scheduling section says that a local record
  that cannot be read fails the tick "whichever work it belongs to", and
  that "A conversation's comment cursor is the exception".
  `inspect_open_issue_work` holds as the row's read failure any round
  input that a conversation's or a campaign's further inspection cannot
  read, and `test_a_delivered_input_that_cannot_be_read_starts_no_round`
  asserts it for a campaign's newest delivered input. Two lists beside
  it leave out what the code holds: the campaign section's Claude
  permissions omit `gh run view`, and the agent-round and persisted-fact
  sections list a campaign round input without its assignment routes,
  and the latter without its sub-issues and notifications. The stories
  hold for every campaign path read, including sub-issues in another
  repository, a paused lead, failed observations and queued campaigns.
- **C3, C4.** `campaign-tutorial.md` and `start-a-campaign.md` sit under
  Tutorials and How-to guides, the command and configuration references
  cover `campaign`, `--campaign` and `[[campaign]]`, and no user page
  links to a design document. State format 7 has an upgrade section in
  [Compatibility and upgrades](compatibility.md) and a Breaking entry in
  the changelog. The campaign skill contract joins contract 1, because
  it asks nothing new of an existing conforming skill.
- **K1, K2.** All 1,454 default tests passed in 40.77 seconds, with 100%
  statement and branch coverage, against 1,283 in 29.20 seconds at
  v6.3.0. The macOS run skips the Windows-only containment module;
  Windows CI exercises it. The separate browser and live GitHub
  integration tests passed, 32 of them, in 23.72 seconds. The
  architecture test now keeps `campaigns` from reaching the scheduler.
  The 111 new test functions are named for behaviours, such as
  `test_a_stopped_lead_waits_for_fresh_direction_and_is_told_it_was_stopped`
  and `test_changes_during_a_lead_round_wake_the_lead_after_it`. CI now
  runs the suite on Python 3.12 to 3.15 on every operating system.
- **K4.** The 15 PRs are #631, #647, #651, #662, #664, #667, #671, #672,
  #673, #674, #676, #677, #678, #680 and #682. Each says what it changes
  and why, links its issue or spec, or says that it needs none, as #651
  does, and answers all seven questions by number. #649 and #653 are
  Dependabot's and are excluded.
- **E1, E2.** The new branches apply rules: a kind's prompt, permissions
  and inspectors, the notification table, mergeability, an open blocker,
  and an issue in another repository. The optional-field count counts
  class fields whose own type admits `None`, as before; 12 of the 65 are
  new. `CampaignChildAssignment` holds a pull request number and the
  observed pull request side by side, and an observed pull request
  implies a number, but no branch defends that pairing, so it counts
  nothing here.
- **E3.** The ontology adds campaign, lead, parent issue, child,
  campaign skill, campaign route and the campaign notifications, and
  names conversations and campaigns together as issue work. The
  requirements and design in `specs/2026-10-20-campaigns/` make the
  case: neither existing kind coordinates assignments across a parent's
  sub-issues, and the design reuses the work record, the round runner,
  the conversation's label rules and the assignment relay rather than
  adding more.
- **E4.** Every kind has its detail command, `stop`, `feed`, `retry` and
  its page at `/work/<identifier>`, and a conversation and a campaign
  share one page layout. Only cancel is limited to assignments, as the
  ontology says. `status.rounds` reads a round's input differently by
  kind. `_read_conversation_input` turns a damaged conversation input
  into a trigger of "comments" and no revision. A damaged campaign input
  loses only its revision in `_read_given_revision` and then fails the
  listing in `_describe_campaign_round_trigger`, as a damaged assignment
  input does.

## Method

- `tools/measure_source.py` supplies module and function line counts.
  Review checks responsibility rather than imposing a length limit.
- An AST inventory finds public top-level definitions without direct
  imports from another source module, and checks each package's
  `__all__`. Review classifies each remaining name and checks
  module-qualified callers. The same inventory run on v6.3.0 finds 30
  names, against the 31 the previous measurement reported.
- A separate AST count finds nullable class-field annotations, and gives
  53 at v6.3.0, as before. Review checks whether any fields require a
  coupled-state defence.
- The documents were read against the namespace map, the stubs and the
  bodies of the changed scheduler, campaign, status and web code.
  Historical specifications keep their historical vocabulary.
- Default tests establish branch coverage and timing. Browser tests
  exercise rendered interactions; integration tests read the live GitHub
  service. Both ran at `db94cc8f`. CI also validates Linux and Windows
  behaviour.
- PR descriptions establish K4 for the interval since v6.3.0.
