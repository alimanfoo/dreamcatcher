# Plan: reshape the documentation

This plan carries out
[GH333](https://github.com/alimanfoo/dreamcatcher/issues/333),
[Stage 4 of the engineering-standard roadmap](roadmap.md#stage-4-reshape-the-documentation).
The roadmap remains authoritative. This document orders the work and gives each
part a completion check.

## Agreed page map

Keep the pages flat under `docs/`. The README is the entrance, not another
guide.

| Path                              | Reader-facing title            |
| --------------------------------- | ------------------------------ |
| `docs/tutorial.md`                | From issue to pull request     |
| `docs/configure.md`               | Configure labels and harnesses |
| `docs/run-and-monitor.md`         | Run and monitor Dreamcatcher   |
| `docs/discuss-an-issue.md`        | Discuss an issue               |
| `docs/review-an-assignment.md`    | Review an assignment           |
| `docs/stop-and-recover.md`        | Stop and recover work          |
| `docs/command-reference.md`       | Command reference              |
| `docs/configuration-reference.md` | Configuration reference        |
| `docs/compatibility.md`           | Compatibility and upgrades     |
| `docs/testing.md`                 | Testing                        |

Keep `docs/ontology.md`, `docs/architecture.md`, `docs/standard.md` and
`CONTRACT.md` at their existing paths. Add `CHANGELOG.md` at the repository
root. Leave the other existing explanation and contributor documents in place.

The current README's installation and first dispatch belong in the tutorial;
routes and harness selection in the configuration guide and reference;
foreground operation and views in the run-and-monitor guide and command
reference; conversation participation in the discussion guide; feedback and
wrap-up in the review guide; and interruption, faults and retry in the
stop-and-recover guide. State-format upgrades belong in compatibility. Detailed
scheduling, lifecycle and persistence design stays in the ontology and
architecture, for human and agent developers. User-facing pages and navigation
do not link to either document. Explain the observable behaviour users need
directly, without requiring knowledge of that design.

## Writing requirement

User-facing documentation must be accessible and readable. Ask what the reader
needs to know at each point, rather than how much the project can tell them.
Lead each guide with its task and prerequisites, give a short path to the
outcome, and introduce consequences where they affect the next decision. Link to
deeper explanation and exhaustive reference instead of inserting them into the
walkthrough. Explain unfamiliar terms on first use. The tutorial follows one
working route, not a catalogue of alternatives. Keep the references complete but
easy to scan; completeness need not make every page exhaustive. Links from
user-facing pages lead to other user-facing guidance, not the ontology or
architecture. Developer definitions remain authoritative for implementation;
they do not replace an accessible explanation of relevant behaviour for users.

## Implementation strategy

Use fresh `gpt-5.6-sol` workers with high reasoning, one writer at a time on
branch `GH333`. Each worker reads the repository instructions, relevant skills,
this plan and the authoritative sources for its assigned pages. Workers do not
commit or publish changes. The coordinating session reviews the actual changes
and supporting evidence, resolves findings, and records progress here before
starting the next writer.

1. Coordinator: settle the page map and content ownership (Part 1).
2. Worker: command and configuration references, and contract audit (Part 2).
3. Worker: tutorial and task guides (Part 3).
4. Worker: compatibility, changelog and testing evidence (Part 4).
5. Worker: README and documentation-index integration (Part 5).
6. Coordinator and a fresh read-only reviewer: review the assembled newcomer
   journey, consistency and completeness; run checks and tests (Part 6).

Keep the work together as one coherent GH333 change. The coordinator owns final
integration and commits. Read-only research and review may run alongside a
writer, but two agents must not edit the same files concurrently.

## Progress

- Part 1: page map agreed with the user; README destinations recorded above.
- Part 2: references and contract audit implemented and reviewed against the
  parser, configuration models, prompts and recorded inputs. Corrected the
  assignment/conversation routing-conflict distinction during review. Reference
  examples validate; 105 targeted tests pass. No user-facing links to the
  ontology or architecture remain. Links to planned guides await Part 3.
- Baseline: 1,048 default tests pass with 100% branch coverage (176.41 seconds).
- Part 3: tutorial and five task guides implemented and reviewed in reading
  order. Review corrected Git setup ordering, made Claude sign-in and plugin
  scope explicit, and removed unnecessary investigation-worktree and permission
  internals. Both configuration examples validate; 70 CLI/configuration tests
  and all checks on the six pages pass. No live agent was dispatched.
- Part 4: compatibility, changelog and testing pages implemented and reviewed.
  Historical entries are brief; upgrade guidance focuses on v4.0.0 to v5.0.0.
  Release evidence and test/CI claims checked against their sources. Two test
  commands in `AGENTS.md` now enable the encoding gate. All checks on these
  pages and the targeted encoding-gate test pass.
- Fresh-reader review found no blockers and two useful clarifications, now
  incorporated: verify the installed skill before dispatch, and distinguish a
  conversation's saved recipe from its eligibility under current routes.
- Part 5: README reduced from 307 to 50 lines, with task-based navigation and no
  links to the ontology or architecture. `CHANGELOG.md` is indexed through the
  configured documentation roots. Review made the README-to-tutorial handoff
  explicit for readers who already ran the install command.
- Part 6: assembled newcomer journey and semantic consistency reviewed, with no
  remaining supported findings in scope. Review corrected the distinction
  between new conversation inputs and recovery, routing-conflict endings in the
  reference, CLI help and view docstring, and the testing page's description of
  golden comparisons. The CLI help checks cover all seven verbs and the
  routing-conflict wording in both relevant commands; 47 focused tests pass. No
  runtime logic changed.
- Final default suite: 1,051 tests pass, 9 deselected, 100% branch coverage
  (176.11 seconds). Whole-repository checks and the isolated installed-command
  smoke check pass. Separate browser and live GitHub integration tests were not
  run locally. Implementation and local verification are complete; the change is
  ready for review on `GH333`.

## Definition-of-done review

1. This change serves GH333 and Stage 4 of the engineering-standard roadmap.
2. The default tests, coverage gate, all applicable repository checks and
   package smoke check pass. No check was manually skipped or suppressed.
   Separate test suites and the live walkthrough are explicitly outside the
   local evidence.
3. No runtime module, function, export or dependency was added. The existing CLI
   parser and view keep their responsibilities; only help and a docstring
   changed. The added help test is small and behaviour-named.
4. No domain concept or vocabulary was introduced.
5. The standard now records the agreed tutorial endpoint, reader boundary and
   state-format isolation. The ontology and architecture remain unchanged; the
   current-phase roadmap names the help wording exceptions.
6. The README's replaced material was removed after its destinations were ready.
7. No runtime conditional or special case was added.

## Starting point

The design discussion has produced drafts on branch `GH333`:

- [The standard](../../docs/standard.md) now describes state-format isolation
  under C4 and a pull request ready for review as the tutorial's endpoint under
  C3.
- [The compatibility policy](../../docs/compatibility.md) states the agreed
  release, state-format and agent-contract versioning rules.
- [The contract](../../CONTRACT.md) declares version 1 after correcting the two
  known discrepancies: delivery positions come from recorded round inputs, and
  the initial conversation input holds its title and body in `initial_issue`.
- The roadmap records all six decisions from the discussion.

At that starting point, the README had not yet been divided into pages, and the
changelog and testing page remained to be written. The progress record above
describes the completed work.

## Part 1: Settle the document map and content ownership

Assign every useful part of the current README a destination before rewriting
it. Use the agreed division: tutorial, task guides, command and configuration
references, and explanation.

Keep the ontology, architecture and contract at their existing paths. Identify
repeated rules and retain one authoritative account, with shorter explanations
elsewhere. Within user documentation, link to the appropriate guide or reference
for further detail, never to the ontology or architecture. Follow the ownership
agreed in the roadmap: domain meanings and rules in the ontology, implementation
boundaries in the architecture, accepted commands and settings in the
references, and supplied inputs and agent obligations in the contract.

Completion check: every useful part of the README has a home, and every planned
page answers a distinct reader need.

## Part 2: Write the command and configuration references

Write pages named "Command reference" and "Configuration reference". Check them
against the parser, configuration models and relevant tests. Cover every
command, argument, flag and setting, including defaults, required values,
constraints and interactions.

Finish checking the agent contract against the current prompts and input
documents. The two known corrections are already drafted; this pass establishes
that contract version 1 accurately describes the whole interface.

Completion check: a reader can answer an exact command or configuration question
without consulting implementation code or the scheduler explanation.

## Part 3: Write the tutorial and task guides

Write "From issue to pull request" using one concrete harness and assignment
skill. Establish a consistent installation workflow, explain authentication and
plugin prerequisites, and carry the reader through configuration, issue
assignment and labelling, dispatch, observation and readiness for review.
Distinguish the draft pull request Dreamcatcher opens at dispatch from the
completed implementation the agent marks ready.

Write the guides for configuring, running, monitoring, discussing, reviewing,
stopping and recovering work. Let the tasks determine page boundaries; closely
related short tasks can share a page. Explain the consequences readers need and
link to the full rules and reference entries.

Validate configuration examples with the actual configuration reader, check
command examples against the CLI, and walk through the tutorial in order for
missing steps. Any live walkthrough should use a disposable repository.

Completion check: the tutorial works as a continuous journey, while each guide
makes sense independently.

## Part 4: Complete compatibility, changelog and testing documentation

Finish the drafted compatibility page and link it from the contract and
changelog. Preserve the agreed policy: independent versions, isolated state
directories, contract version 1, and semantic releases beginning with 5.0.0.

Reconstruct historical state-format breaks from commits and releases, with brief
entries and links to evidence. Do not write detailed migration instructions for
obsolete releases: the user is currently the sole user and runs v4.0.0. Focus
actionable upgrade guidance on v4.0.0 to the next release, keeping the current
state-format-5 break under "Unreleased". The changelog's header states the
versioning scheme, links to the compatibility policy and says that changes users
would notice receive entries.

Write the testing page from the actual tests and CI configuration. Explain what
branch coverage, encoding checks, recorded harness streams, real subprocess
boundaries exercised through stand-in executables, and rendered-view goldens
establish. Distinguish the default suite on Linux, macOS and Windows, separate
browser tests on Linux, and live GitHub integration tests outside CI.

Completion check: each historical or testing claim has supporting evidence, and
upgrade instructions say exactly what users need to do.

## Part 5: Make the README the entrance to the documents

Reduce the README to the description, working installation command and a concise
map organised around reader needs. Remove material whose new home is complete.

Add `CHANGELOG.md` to uncoded's documentation roots and regenerate the index.
Check links and headings, including links into the old README.

Completion check: readers can identify where to start and where to look
something up directly from the README.

## Part 6: Review the whole and close Stage 4

Read the documentation in the order a newcomer would encounter it, then review
terminology and claims against the code and enduring documents. Check especially
for duplicated rules, unexplained prerequisites and pages mixing instruction
with exhaustive reference.

Run the existing checks and the required test suite before committing. Record
the C3 and C4 results in the engineering-standard roadmap and answer the
standard's definition of done in the pull request.

Completion check: C3 and C4 are demonstrably met, the documentation map reflects
the agreed structure, and the pull request explains the corrections made to the
standard and roadmap.

## Why this order

The references precede the tutorial because they establish the exact facts its
examples use. The README comes near the end because its destinations should be
complete when it becomes the map. The final review reads the assembled
documentation across page boundaries, where repetition and missing links become
visible.
