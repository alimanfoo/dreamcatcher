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

| Criterion                              | Measured                     | Bar                      | Status     |
| -------------------------------------- | ---------------------------- | ------------------------ | ---------- |
| S1 Modules are small                   | 7 files over 600 lines       | none                     | short      |
| S2 Functions fit on a screen           | 22 functions over 50 lines   | none unless named        | short      |
| S3 Exports are used                    | 57 names without an importer | each of a permitted kind | unmeasured |
| S4 Each thing is done one way          | 2 duplicates found           | none                     | short      |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`   | 0, 0                     | met        |
| C1 One vocabulary                      | 5 open disagreements         | none                     | short      |
| C2 Enduring documents are true         | 1 contradiction              | none                     | short      |
| C3 Documentation by purpose            | 1 page of 293 lines          | 4 kinds of page          | short      |
| C4 Formats and contracts are versioned | neither versioned            | both                     | short      |
| K1 Structural rules checked by machine | 1 of 4 import rules          | all                      | short      |
| K2 Suite is fast and speaks plainly    | 178 seconds                  | under 60                 | short      |
| K3 Tracker is current                  | 6 issues in retired words    | none                     | short      |
| K4 Every change reviewed to standard   | no template                  | template                 | short      |

The evidence behind each row:

- **S1.** `scheduler` 1858, `web` 1243, `tui` 1015, `status` 1004,
  `agent_assignments` 711, `agent_rounds` 663, `github` 614.
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
  `state` imports `AgentRoundReader` from `agent_rounds`. Issue 183 records it.
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

Two measures need care when they are read again.

- The S3 count is by name, so it includes the web view models the templates
  consume and the document models that tests read back. The criterion permits
  both. The count is a ceiling until the check can tell those kinds apart.
- The K2 time is one laptop's. CI records its own, and the bar applies to the
  laptop figure because that is the one a developer waits for.

## Rules for the work

- The behaviour budget is zero. No stage changes a persisted document, a
  command, a prompt, a scheduling decision or any output a user sees, except
  where a stage says so and names the change.
- Each stage leaves every check passing and every enduring document true.
- A stage that splits a module keeps the architecture's ownership: the scheduler
  still owns every scheduling decision when it is a package.
- Dated specs stay as they are. This one is corrected as the work reveals what
  it got wrong, and the correction says why.
- The stages merge in order. Stage 1 guards stage 2, which guards stage 3.

## Stage 1: Make the architecture enforceable

Outcome: every structural rule the architecture states is a rule a commit cannot
break, and the one known violation is gone.

Work:

- Add ruff banned-import rules so that `subprocess` is imported only in
  `commands`, rich only in `tui`, and Flask only in `web`. Remove the per-file
  waiver that stands in for the first, if the banned-import rule makes it
  redundant.
- Add one test that reads the import graph under `src` and asserts the
  dependency direction the architecture states: the daemon depends on the
  scheduler and never the reverse; assignment and round modules do not import
  the scheduler; status does not import presentation; state and documents import
  no domain module.
- Move `AgentRoundReader` out of `state`, closing issue 183, so that test
  passes.
- Add the tests for S1 and S2 with today's offenders listed as permitted, so the
  list can only shrink.

Check: K1 met. S1 and S2 measurable on every commit.

## Stage 2: Reduce concentration

Outcome: no module exceeds the S1 bar, and each file holds one concept.

Work, one pull request per module, largest first:

- `scheduler` becomes a package. Its seams are already visible in its names:
  issue observation and availability; fault and global cooldown; assignment
  candidates and required rounds; conversation candidates and recovery; the tick
  that alternates and launches. The package keeps one public face so the daemon,
  status and CLI import what they import today.
- `web` divides along Flask's own lines: the app and routes, the view models,
  the feed tail, and the server. Templates and static files stay where they are.
- `status` and `tui` are asked the same question. Each likely divides by the
  ontology's two kinds of agent work, assignments and conversations, with the
  report and the shared rendering apart.
- `agent_assignments`, `agent_rounds` and `github` are just over the bar. Each
  is reviewed for a seam before it is split, and a file that has one concept and
  650 lines earns a named exception rather than a split.

As each module is split, its permitted entries in the S1 and S2 tests come out.

Check: S1 met. S2 met except for the named functions.

## Stage 3: Trim the surface and settle the words

Outcome: the public surface is the interface the architecture names, and the
consistency review reports nothing.

Work:

- Run the consistency review over source, documents and output. Close issues
  315, 317, 318, 322 and 324 as part of resolving what it reports.
- For each of the 57 exported names, decide which of the three permitted kinds
  it is or make it private. Give the S3 check a way to tell the kinds apart,
  such as a module convention for view models, so the count becomes a bar.
- Remove the two S4 duplicates found in the baseline, and any others the review
  turns up. The word for a status lives in `status`; a presentation shows it.

Check: S3, S4 and C1 met.

## Stage 4: Reshape the documentation

Outcome: a reader finds what they need by what they are trying to do, and the
project states what it promises to keep stable.

Work:

- Divide the README into pages under `docs/`: a tutorial to a first pull
  request, how-to pages for configuration and for each command, a reference for
  every setting and flag, and the existing explanation documents. The README
  keeps the one-paragraph description, the install line and a map.
- Add `CHANGELOG.md`. Record the four state-format breaks to date, so the file
  starts true.
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

Check: K3 and K4 met.

## Completion

This phase is complete when every row of the baseline table reads "Met", the
measurement has been repeated and recorded below the baseline, and the next
phase's spec can begin from a standard that holds.
