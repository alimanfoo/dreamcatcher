# Engineering standard: baseline and path

This spec records the first measurement of Dreamcatcher against
[the engineering standard](../../docs/standard.md), and the ordered work that
closes each gap. The standard is enduring and lives in `docs/`. This document is
dated: it says where the project stood on 2026-09-30 and how it moves from
there. When the work is done, this document stays as a record and the next phase
measures again.

## Why now

The architecture migration is complete. The modules it set out to retire are
gone, each responsibility has one owner, and the module graph has no cycles. The
suite passes at full branch coverage on three operating systems, and the source
carries no suppressed warnings. That is a sound footing. What remains is shape,
enforcement and documentation: four modules hold half the source, the
architecture's rules are kept by reviewers rather than tools, and the user
documentation is one long page. Those are the gaps this path closes.

## Baseline, 2026-09-30

Measured on `main` at `b4ac40a`.

| Criterion                              | Measured                              | Bar                      | Status     |
| -------------------------------------- | ------------------------------------- | ------------------------ | ---------- |
| S1 Modules are cohesive                | 4 modules of several responsibilities | none                     | short      |
| S2 Functions fit on a screen           | 22 functions over 50 lines            | none unless named        | short      |
| S3 Exports are used                    | 57 names without an importer          | each of a permitted kind | unmeasured |
| S4 Each thing is done one way          | 2 duplicates found                    | none                     | short      |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`            | 0, 0                     | met        |
| C1 One vocabulary                      | 5 open disagreements                  | none                     | short      |
| C2 Enduring documents are true         | 1 contradiction                       | none                     | short      |
| C3 Documentation by purpose            | 1 page of 293 lines                   | 4 kinds of page          | short      |
| C4 Formats and contracts are versioned | neither versioned                     | both                     | short      |
| K1 Structural rules checked by machine | 1 of 4 import rules                   | all                      | short      |
| K2 Suite is fast and speaks plainly    | 178 seconds                           | under 60                 | short      |
| K3 Tracker is current                  | 6 issues in retired words             | none                     | short      |
| K4 Every change reviewed to standard   | no template                           | template                 | short      |
| E1 Rules, not cases                    | no ledger                             | ledger, external causes  | unmeasured |
| E2 Invariants by construction          | 0 found; 81 optionals unaudited       | 0                        | unmeasured |
| E3 Concept economy                     | 21 concepts, no rule                  | rule applied per change  | short      |
| E4 Symmetry                            | 12 against 9 in the scheduler         | parallel or named        | short      |

The evidence behind each row:

- **S1.** `scheduler` 1858, `web` 1243, `tui` 1015 and `status` 1004. Those
  modules hold half the source and each contains several nameable
  responsibilities. `agent_assignments` 711, `agent_rounds` 663 and `github` 614
  are the next places to inspect, not automatic split points.
- **S2.** The longest are `build_cli_parser` at 161 lines and the scheduler
  `tick` at 127. Ten of the 22 are in `scheduler`.
- **S3.** Public top-level names that no other module under `src` imports. The
  count includes view models the templates consume and document models the tests
  read back, which the criterion permits.
- **S4.** `web` relabels one status value as "needs feedback" where `status` and
  `tui` say "needs user feedback". `web` derives draft-or-ready from the pull
  request observation itself rather than reading a derived fact.
- **S5.** The three coverage pragmas each mark a platform-specific arm.
- **C1.** The consistency review has not run since the migration. Issues 315,
  317, 318, 322 and 324 record disagreements already known.
- **C2.** The architecture says `state` knows storage mechanics only, and
  `state` imports `AgentRoundReader` from `agent_rounds`.
- **C3.** The README holds install, configuration, behaviour rules and the
  command reference in one page.
- **C4.** The state format is at v4 with no compatibility statement. The
  contract carries no version. There is no changelog.
- **K1.** The `subprocess` rule is a ruff per-file waiver. The rich and Flask
  rules and the dependency direction rest on review, and the dependency
  direction has the one violation C2 records.
- **K2.** 808 test functions, 1028 with parameters, in 178 seconds on one
  laptop. The eight slowest each take over 1.3 seconds and spawn stand-in
  processes. Names already read as behaviours.
- **K3.** 39 issues open. Six use retired words: 67, 105, 109, 118, 125, 130.
- **K4.** There is no pull request template.
- **E1.** There is no ledger, so the count of special cases is unknown. A search
  finds two branches with an external cause already: each harness adapter
  refuses a session identifier that its JSON did not give as text.
- **E2.** A search for branches that defend an impossible state finds none. The
  records under `agent_rounds`, `agent_assignments`, `issue_conversations` and
  `scheduler`, and the other dataclasses and models under `src`, hold 81
  optional fields whose pairing has not been audited, so the count is unmeasured
  rather than met. The original count of 53 omitted 28 fields; the Stage 3 audit
  recounted the cited revision from its syntax tree.
- **E3.** The ontology defines 21 concepts. No rule yet asks a change to justify
  a new one.
- **E4.** The scheduler names 12 symbols for issue conversations and 9 for agent
  assignments, and the shapes differ: conversations have a candidate, a
  candidate result, a recovery candidate, a new-round candidate and a prepared
  round, where assignments have a candidate, an inspection result and a required
  round. Assignment inspection is public and conversation inspection private.
  The read operations differ too: `find_harness_session_identifier` beside
  `find_issue_conversation_harness_session_identifier`, and
  `find_open_agent_assignments_by_issue` with no conversation counterpart.

Two measures need care when they are read again.

- The S3 count is by name, so it includes the web view models the templates
  consume and the document models that tests read back. The criterion permits
  both. The count is a ceiling until the check can tell those kinds apart.
- The K2 time is one laptop's. CI records its own, and the bar applies to the
  laptop figure because that is the one a developer waits for.

The Stage 3 E2 audit began with 85 optional fields in the current tree, four
more than the corrected baseline after the intervening work. It found eight
coupled field sets: six in-memory sets were replaced by one type in item 4, and
two persisted sets are listed in the design for item 5's v5 break. The E2
measurement is therefore eight found, six fixed and two deferred.

Stage 3 item 8 repeated the C1 and S4 measurements over the source, enduring
documents, README and output strings. After its findings were resolved, the
consistency review reported zero disagreements, so C1 is zero. The two duplicate
derivations in the baseline were removed and the review found no others, so S4
is zero duplicates.

Stage 3 item 9 repeated the S3 measurement on the current source. The
measurement parses every Python module under `src`, collects each module-level
class, function, assignment and type-alias name without a leading underscore,
then removes a name when another source module imports it directly. Names are
counted by defining module and name. This is the same method a later measurement
must use.

The first pass made eight implementation details private: `AgentRoundHarness`,
`compose_agent_round_ending`, `ClaudeHarnessAdapter`, `build_cli_parser`,
`CodexHarnessAdapter`, `read_worktree_revision`,
`refuse_invalid_harness_session_identifier` and `create_app`. Repeating the
complete measurement at that head found 91 names, because the first pass had
counted classes and functions but not every constant and type alias. Fifty-eight
more implementation details became private. The two names that another source
module used through their module, `compose_first_round_prompt` and
`SHOULD_START_NEW_PROCESS_SESSION`, now have direct importers. `NO_REPLY` and
`STATE_FORMAT_VERSION` remain public because the architecture names their
interfaces.

The 31 names that remain are all of the permitted kinds:

| Name                               | Kind                   | Document or named interface             |
| ---------------------------------- | ---------------------- | --------------------------------------- |
| `AssignmentRecord`                 | document model         | persisted assignment record             |
| `PullRequestObservation`           | document model         | persisted pull request observation      |
| `DispatchRecipe`                   | document model         | `dreamcatcher.toml` dispatch recipe     |
| `BlockingIssue`                    | document model         | GitHub blocking-issue response          |
| `GitHubIssueLabel`                 | document model         | GitHub issue-label response             |
| `GitHubRepository`                 | document model         | GitHub repository response              |
| `GitHubResponseProjection`         | document model         | extensible GitHub response projection   |
| `GitHubUserAccount`                | document model         | GitHub account response                 |
| `InlineReviewComment`              | document model         | GitHub inline-review-comment response   |
| `PostedIssueComment`               | document model         | GitHub posted-comment response          |
| `PullRequestReview`                | document model         | GitHub pull-request-review response     |
| `ConversationRecord`               | document model         | persisted conversation record           |
| `InitialConversationIssue`         | document model         | persisted initial conversation issue    |
| `IssueCommentCursor`               | document model         | persisted issue-comment cursor          |
| `DaemonLockRecord`                 | document model         | persisted daemon lock record            |
| `read_user_post_delivery_cursor`   | architecture interface | user-post delivery position             |
| `AgentRoundFinisher`               | architecture interface | agent-round completion callback         |
| `HarnessSessionIdentifierRecorder` | architecture interface | harness-session recording callback      |
| `main`                             | architecture interface | command-line entry point                |
| `ChildProcess`                     | architecture interface | external-command process result         |
| `PullRequestReviewVerdict`         | architecture interface | GitHub review verdict                   |
| `HarnessSessionResumption`         | architecture interface | scheduler-to-harness resumption request |
| `AssignmentInspection`             | architecture interface | assignment inspection result            |
| `AssignmentRoundCandidate`         | architecture interface | continuing-assignment candidate         |
| `FirstAssignmentRoundCandidate`    | architecture interface | first-assignment-round candidate        |
| `ConversationRecoveryCandidate`    | architecture interface | conversation-recovery candidate         |
| `IssueObservationResult`           | architecture interface | scheduler issue observation             |
| `derive_issue_availability`        | architecture interface | scheduler issue availability            |
| `DreamcatcherDaemonStatus`         | architecture interface | daemon status report                    |
| `NO_REPLY`                         | architecture interface | agent-facing no-reply result            |
| `STATE_FORMAT_VERSION`             | architecture interface | persisted-state compatibility version   |

No remaining name is a template view model. The S3 measurement is therefore 31
permitted names and no unclassified public name.

Stage 3 item 10 repeated every criterion the stage owns after all ten items.

| Criterion                     | Measured                                            | Bar                      | Status |
| ----------------------------- | --------------------------------------------------- | ------------------------ | ------ |
| S3 Exports are used           | 31 permitted names, 0 unclassified                  | each of a permitted kind | met    |
| S4 Each thing is done one way | 0 duplicate derivations                             | none                     | met    |
| C1 One vocabulary             | 0 consistency-review disagreements                  | none                     | met    |
| E1 Rules, not cases           | 9 special cases, all externally caused and ledgered | ledger, external causes  | met    |
| E2 Invariants by construction | 70 optional fields, 0 coupled field sets            | 0                        | met    |
| E4 Symmetry                   | 15 parallel operations, 8 named asymmetries         | parallel or named        | met    |

The E1 walk inspected every source module and classified the branches that name
a particular situation. [The ledger](../../docs/special-cases.md) records the
nine such cases. The conversation creation refusal remains because an
interrupted process or a failed Git cleanup can leave the unrecorded worktree;
normal creation and failed record writes either finish or remove it. No case has
an internal cause.

The E4 remeasurement read the design's parallel names and asymmetries against
the current namespace. Every one of the 15 operation rows has both sides. The
unequal symbol shapes are the ones the design names: `AssignmentInspection` adds
issue observations to the shared result; three assignment candidate types stand
against two conversation candidate types because their ranking lists cut the
lifecycle differently; `ConversationObservation` adds the title and routing
conflict that exist before a conversation record; and
`find_open_assignments_by_issue` has no counterpart because an issue may have
many assignments over time but at most one conversation. The design's eight
standing asymmetries all remain explained by the ontology, and the audit found
no other one.

Stage 3 set out to make the public surface the architecture's interface, settle
one vocabulary and give the two kinds of agent work one named shape. It did all
three. Nothing in the stage's outcome or ordered work remains undone.

## Rules for the work

- The behaviour budget is zero. No stage changes a persisted document, a
  command, a prompt, a scheduling decision or any output a user sees, except
  where a stage says so and names the change.
- Each stage leaves every check passing and every enduring document true.
- A stage that splits a module keeps the architecture's ownership: the scheduler
  still owns every scheduling decision when it is a package.
- Dated specs stay as they are. This one is corrected as the work reveals what
  it got wrong, and the pull request that corrects it says why.
- The stages merge in order. Stage 1 guards stage 2, which guards stage 3.

## Stage 1: Make the architecture enforceable

Outcome: every structural rule the architecture states is a rule a commit cannot
break, and the one known violation is gone.

Work:

- Add ruff banned-import rules so that rich is imported only in `tui`, and Flask
  only in `web`. Keep the per-file waiver that lets `commands` alone import
  `subprocess`, because bandit's subprocess-import rule is already that ban.
- Add one test that reads the import graph under `src` and asserts the
  dependency direction the architecture states: the daemon depends on the
  scheduler and never the reverse; assignment, conversation and round modules do
  not import the scheduler; status and feed do not import presentation; the
  GitHub and harness adapters import neither presentation nor the scheduler;
  state and documents import no domain module.
- Move `AgentRoundReader` out of `state`, so that test passes.

Check: K1 met.

## Stage 2: Reduce concentration

Outcome: each module owns one coherent responsibility, with packages where a
clean separation of concerns supports one.

Work:

- Add `tools/measure_source.py` for S1 and S2, so later phases read the same
  numbers the same way. It is a measurement, not a hook.

Then one pull request per module, largest first:

- `scheduler` becomes a package. Its seams are already visible in its names:
  issue observation and availability; fault and global cooldown; assignment
  candidates and required rounds; conversation candidates and recovery; the tick
  that alternates and launches. The package keeps one public face so the daemon
  and CLI import what they import today. Status imports the scheduler's records
  and derivations from the two submodules that own them, and the architecture
  test holds it to those.
- The split moves code and changes no shape. The asymmetry E4 records stays as
  it was, now readable in `scheduler/assignments.py` and
  `scheduler/conversations.py` side by side. Healing it is a design decision,
  not a split, and is Stage 3 work.
- `web` becomes a package divided as Flask divides itself: view models that
  import no Flask and are tested without it, the app and routes as a thin shell
  over them, the feed tail, and the server. Templates and static files stay
  where they are.
- `status` becomes a package dividing assignment, conversation, shared-round,
  report-reading and report concerns, named in parallel with the scheduler's
  submodules. `tui` becomes a package that separates the instance-status view
  from shared Rich rendering while keeping assignment, conversation and feed
  views at its public package boundary.
- Review `agent_assignments`, `agent_rounds` and `github` for useful seams. Keep
  a module intact when splitting it would separate no responsibility or add
  coupling merely to reduce its line count.
- The ruff bans on rich and Flask that Stage 1 added go, and the architecture
  test takes over both. Ruff could waive the whole rule for a file but not one
  library for one file, so `tui` could have imported Flask unseen, and
  `pyproject.toml` recorded that as K1's one exception. The test checks each
  library against the one package that may import it, so the exception closes.
  The commit hook no longer catches a stray rich import; the suite does.

Check: S1 met by review, with module line counts retained as a way to order that
review. S2 met except for the named functions.

## Stage 3: Trim the surface and settle the words

Outcome: the public surface is the interface the architecture names, and the
consistency review reports nothing.

The stage begins with a design, written with the user before any code: one shape
for the two kinds of agent work, deciding which of the differences the scheduler
and status splits made visible follow from the ontology and which are accidents.
The design is [agent-work-shape.md](agent-work-shape.md), and its last part is
the plan the work below carries out.

Work, in order. Each item is a sub-issue of the stage's issue, blocked by the
one before it, and each is one pull request.

1. Rename to the ontology's short forms. Every name that says agent assignment
   or issue conversation says assignment or conversation, so the names the
   design introduces and the names that exist today share one form.
2. Make the two kinds two scheduler classes with one base, and give the running
   set one owner and a record with no ending one meaning.
3. Give each kind one inspection returning one bundle, with one issue listing,
   candidates that carry facts, and fault derived once.
4. Audit the 53 optional fields for pairs that must agree, and give each pair in
   memory one type. List the pairs in persisted records for the next item.
   Record the E2 count.
5. Break the state format to v5: one observation type for both kinds, the
   delivery position read from recorded inputs, and every persisted pair the
   audit listed.
6. Give each kind one launch returning the round it started, the session rule
   one home, and the tick the eight steps the architecture lists, so the launch
   chain and the issue observer's parameter bundle are gone.
7. Give each kind one status reader with one base, the round text one home, and
   settle the status wording the design lists.
8. Run the consistency review over source, documents and output, and resolve
   what it reports. Remove the two S4 duplicates found in the baseline, and any
   others the review turns up. The word for a status lives in `status`; a
   presentation shows it. Issues 315, 317, 318, 322 and 324 were closed before
   the stage began.
9. For each of the 57 exported names, decide which of the three permitted kinds
   it is or make it private. Record the count that remains and what each is.
10. Start the ledger at `docs/special-cases.md`. Walk every conditional that
    names a situation, enter it with its cause, and delete or generalise any
    whose cause is internal. Then measure every Stage 3 criterion again and
    record it below the baseline.

Two rules hold across the stage:

- The break to v5 is the one change to persisted documents the phase permits.
  Version 5 starts with empty local state, as version 4 did.
- Status wording may change where two kinds of agent work or two presentations
  say one thing in two ways, so that one wording wins and says more. The design
  lists each string that changes. The behaviour budget stays zero otherwise: no
  command, prompt or scheduling decision changes.

Check: S3, S4, C1, E1 and E2 met, and E4 measured again after stage 2.

## Stage 4: Reshape the documentation

Outcome: a reader finds what they need by what they are trying to do, and the
project states what it promises to keep stable.

The [documentation plan](documentation-plan.md) orders the work below and gives
each part a completion check.

Work:

- Divide the README into pages under `docs/`, organised by reader purpose: a
  tutorial, task guides, complete command and configuration references, and the
  existing explanation documents. The README keeps the one-paragraph
  description, the install line and a map. Keep the pages in Markdown and use
  the existing link checks.
- Keep user-facing pages accessible: give readers what they need at each step,
  explain unfamiliar terms, and link to deeper detail when it becomes useful.
  The tutorial follows one working path; guides do not become references.
  User-facing pages and navigation do not link to the ontology or architecture:
  those are developer documents. Explain the observable behaviour users need
  directly, and link within the user documentation for further detail.
- Call the tutorial "From issue to pull request": set up Dreamcatcher, dispatch
  an agent to implement a GitHub issue, and follow its work until the pull
  request is ready for review. Distinguish the draft pull request Dreamcatcher
  opens at dispatch from the completed implementation the agent marks ready.
- Make the tutorial self-contained. Give one complete installation workflow and
  use its command form consistently. Choose one concrete harness and assignment
  skill; explain how to install and authenticate the required tools and install
  any plugin the skill needs. State the repository prerequisites. Include
  configuring the route, assigning and labelling the issue, starting the daemon,
  following the agent's work, and recognising that the pull request is ready for
  review. Check the instructions in order for any unstated prerequisite.
- Organise how-to guides around configuring labels and harnesses, running and
  monitoring work, discussing an issue, reviewing an assignment, stopping work,
  and recovering from a fault. Every command is covered, but the guides follow
  tasks rather than command boundaries. Put exhaustive syntax, settings, flags,
  defaults and constraints in pages named "Command reference" and "Configuration
  reference". Link readers to the compatibility policy for upgrades and the
  contract for writing assignment skills and conversation prompts.
- Give each rule one authoritative home. The ontology owns domain meanings and
  rules; the architecture owns implementation boundaries; the command and
  configuration references own accepted commands, options and settings; and the
  agent contract owns the inputs Dreamcatcher supplies and the agent's
  obligations. Task guides explain the consequences readers need and link to
  user-facing references where needed, not developer design documents. Correct
  the contract against the current code before declaring its version, including
  delivery positions derived from recorded round inputs and the initial
  conversation input's `initial_issue` object.
- Add `CHANGELOG.md`. Its header names the versioning scheme and where the
  compatibility statement lives. A change users would notice gets an entry.
  Explain user-visible effects and required upgrade actions. Reconstruct the
  state-format breaks from commits and releases, linking to the evidence rather
  than assuming the historical count remains current. Keep historical entries
  brief, without detailed migration guidance for obsolete releases: the sole
  current user runs v4.0.0. Focus actionable upgrade guidance on that version to
  the next release. Keep released changes separate from unreleased work: the
  state-format-5 break belongs under "Unreleased" until it is released.
- Give the state format and the agent contract each a version and a
  compatibility statement, in words a user can act on. Preserve the existing
  state isolation: Dreamcatcher reads and writes its own state-format directory
  and ignores other format directories. The daemon lock remains shared across
  formats.
- State the [compatibility policy](../../docs/compatibility.md): tagged releases
  follow semantic versioning, while the state format and agent contract have
  independent integer versions. The promise covers documented commands, flags,
  configuration, saved agent work and agent obligations. Incompatible changes
  require a major release and a changelog entry with upgrade instructions.
  Establish contract version 1 after correcting its description of the current
  protocol. The next release is 5.0.0 because it includes state format 5; the
  policy applies from that release onward. Untagged `main` is development code.
- Add a page that explains what each testing technique establishes: the branch
  coverage gate, encoding failures, recorded harness streams, real subprocess
  boundaries exercised through stand-in executables, and rendered-view goldens.
  Describe the actual scope of the checks: the default suite runs on Linux,
  macOS and Windows; browser tests run separately on Linux; and live GitHub
  integration tests are separate from CI. Verify these claims against the test
  configuration, fixtures and CI workflow.
- Correct the two CLI help descriptions that omit an existing view-ending
  condition. The conversation description changes "enters fault or leaves the
  status report" to "enters fault, has a routing conflict or leaves the status
  report". The feed description adds "A conversation's routing conflict also
  ends its feed view." These wording corrections are the stage's only exception
  to the zero behaviour budget; the conditions themselves do not change.

Check: C3 and C4 met.

### Stage 4 measurement, 2026-10-03

- **C3 met.** The 50-line README leads to one tutorial, five task guides and
  complete command and configuration references. Compatibility and testing have
  their own pages. Developer design explanations remain separate, with no links
  to the ontology or architecture from user-facing pages. The documentation
  index includes the changelog. A fresh-reader review of the assembled journey
  has no outstanding findings; the examples validate against the current
  configuration model. No live agent walkthrough was run.
- **C4 met.** State format 5 and agent contract 1 each have an explicit
  compatibility policy. The corrected contract describes the current protocol.
  The changelog separates released history from the unreleased state-format
  break, and upgrade guidance focuses on v4.0.0 to v5.0.0. Each build continues
  to read and write only its own format directory; no runtime version
  negotiation, migration or state-handling change was introduced.

The bounded consistency review compared the new documentation and contract with
their implementation and testing evidence. Its findings were corrected and
rechecked, including the CLI help and view docstring that omitted routing
conflict as a conversation-view ending. No supported findings remain in that
scope. This does not remeasure the issue tracker or the other stages' criteria.

The final default suite passes 1,051 tests with 9 deselected and 100% branch
coverage in 176.11 seconds. All applicable repository checks and the isolated
installed-command smoke check pass. The separate browser and live GitHub suites
were not run locally. Stage 5 still owns the suite-duration shortfall.

## Stage 5: Bring the suite under a minute

Outcome: the default run takes under 60 seconds on a laptop.

Work:

- Profile the suite by where its time goes, not by its slowest tests alone. At
  the baseline no test takes two seconds. The time is spread over some 350 tests
  that each spawn a few stand-in processes, and on macOS a spawn costs more than
  the work it does.
- Take out the cost that is not the test's. A stand-in's launcher is written
  once a session, not once a test.
- Where a test waits on a real clock or a real process for a fact a pinned clock
  or an in-process fake could give, change it. Where the end-to-end run is what
  the test proves, keep it.
- Run the default suite on every processor, because what remains is waiting on
  child processes.

Check: K2 met.

### Stage 5 measurement, 2026-10-03

Measured on the same laptop as the baseline, with 1,051 tests at full branch
coverage.

- **Where the time went.** The 179-second baseline run started 2,454 child
  processes: 1,246 stand-in `gh`, 1,061 `git` and 124 stand-in harnesses. Their
  lifetimes account for 165 of its 167 seconds of test time, and no test takes
  two seconds. Each test wrote fresh launchers for its stand-ins, and macOS
  assesses a newly written executable file the first time it runs, which costs
  about a third of a second. The suite paid that 354 times, about 100 seconds.
- **What changed.** One launcher is written a session and each stand-in is a
  name for it, which brought the serial run to 79 seconds. The stop-request
  watcher takes its wait between polls as a parameter, so the stop test drives
  both arms of the poll without a clock, which closes #329. The test of a round
  interrupted as its harness succeeds releases that harness through a file
  rather than after a one-second delay. The lock test's parameter ids no longer
  carry a process id, so every worker collects the same tests. The default run
  uses pytest-xdist on every processor.
- **K2 met.** The default run takes 22.5 seconds on this laptop's fourteen cores
  and 24.5 seconds on four workers, at 100% branch coverage. Serially it takes
  79 seconds, so the parallel run is what meets the bar. Test names were not
  remeasured; the baseline found them already reading as behaviours.
- **Two defects the faster suite exposed.** On macOS, ending the process group
  of a harness that has exited in the same moment, before its status is
  collected, raised a permission error. `teardown.end_process_tree` now reads
  that as a group with nothing left in it, and the ledger records why. On
  Windows, a child that exited between its creation and its placement in a Job
  Object could not be placed, which failed its launch; the parallel run on the
  four-core runner hit that in three runs of four. A Windows child now starts
  suspended and is placed before it runs.
- **Not done.** No test is marked for leaving to CI, because the default run
  meets the bar with every test in it. Windows was not remeasured: process
  startup is the cost there, as #291 found, and a launcher is copied for each
  stand-in there because a symbolic link is a privilege.

## Stage 6: Keep it there

Outcome: the standard applies to every change without anyone remembering to
apply it.

Work:

- Ask every pull request description to answer the definition of done by number,
  under its own heading. A pull request template would reach almost none of
  them, because Dreamcatcher opens each draft pull request with a description of
  its own and the assignment skills replace it when the work is done. The agent
  guide asks for the answers instead, and review reads them before merging.
- Let question 4 of the definition of done ask the E3 question. Every spec
  arrives in a pull request, so a concept added to the ontology comes with a
  spec that shows the existing concepts cannot compose to it.
- Write a release checklist, and let it run the consistency review, the triage
  of open issues and the measurement of every criterion before each major or
  minor release. Nothing defines when a phase begins or ends, and phases
  overlap, so a phase boundary is not a moment a checklist can wait for. A
  release is.
- Run those checks once now, so the next release begins from a measurement. The
  ontology records no retired words, so the K3 measure counts issues that name a
  concept by a word the ontology does not use for it, and issues that ask for
  work already done.

Check: K3, K4 and E3 met.

### Stage 6 measurement, 2026-10-04

- **K3 met.** The triage rewrote 24 open issues in the ontology's words and
  closed five: three whose work was done and two that no longer applied. The
  baseline's list of six undercounted, because it looked for retired words the
  ontology never recorded.
- **K4 met.** #377 answered the definition of done by number, under its own
  heading, and so does the pull request that records this measurement.
- **E3 met.** The ontology holds 21 concepts, as at the baseline, and none was
  added without a case.

The first run of the release checklist's checks found shortfalls beyond this
stage's own criteria. The pull request that records this measurement fixed the
mechanical ones: six functions over the S2 bar, an identical lookup for each
kind of agent work, and 20 statements in the ontology and architecture that the
code contradicted. The rest are issues, and
[the measurement page](../../docs/measurement.md) lists each one against its
criterion.

## Completion

This phase is complete when every row of the baseline table reads "Met", the
measurement has been repeated and recorded on
[the measurement page](../../docs/measurement.md), and the next phase's spec can
begin from a standard that holds.
