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

Work:

- Divide the README into pages under `docs/`: a tutorial to a first pull
  request, how-to pages for configuration and for each command, a reference for
  every setting and flag, and the existing explanation documents. The README
  keeps the one-paragraph description, the install line and a map.
- Add `CHANGELOG.md`. Its header names the versioning scheme and where the
  compatibility statement lives. A change users would notice gets an entry.
  Record the four state-format breaks to date, so the file starts true.
- Give the state format and the agent contract each a version and a
  compatibility statement, in words a user can act on.
- Add a page that says how Dreamcatcher is tested: the coverage gate, the
  encoding gate, the recorded harness streams, the stand-in executables, the
  golden views, and the three operating systems.

Check: C3 and C4 met.

## Stage 5: Bring the suite under a minute

Outcome: the default run takes under 60 seconds on a laptop.

Work:

- Profile the slowest tests. The eight slowest are end-to-end conversation and
  scheduler tests that spawn stand-in processes and wait on them.
- Where a test waits on a real clock or a real process for a fact a pinned clock
  or an in-process fake could give, change it. Where the end-to-end run is what
  the test proves, keep it and mark it so a developer can leave the marked tests
  to CI.

Check: K2 met.

## Stage 6: Keep it there

Outcome: the standard applies to every change without anyone remembering to
apply it.

Work:

- Add a pull request template that asks the definition of done, one question per
  line.
- Triage the 39 open issues against the ontology. Rewrite the six that use
  retired words or close them with the reason. Repeat at each phase boundary.
- Add the consistency review to the checklist for closing a phase.
- Add the E3 question to the spec review: does this phase add a concept, and
  does its spec show the existing ones cannot compose to it?

Check: K3, K4 and E3 met.

## Completion

This phase is complete when every row of the baseline table reads "Met", the
measurement has been repeated and recorded below the baseline, and the next
phase's spec can begin from a standard that holds.
