# Dreamcatcher engineering standard

This document says what Dreamcatcher holds itself to. It is the third enduring
document, beside [the ontology](ontology.md), which fixes the words, and
[the architecture](architecture.md), which fixes the boundaries. The ontology
says what things are called. The architecture says where each decision lives.
This document says how good the result has to be, and how we tell.

Every pull request is reviewed against it. Every phase remeasures against it.
Where the code falls short, the shortfall is an issue with a number, not a
matter of taste.

## The aim

Dreamcatcher aims to be as simple, clear, consistent and elegant as the finest
open source projects. Those four words carry a precise meaning here.

- **Simple** means there is no more of it than the job needs. Each part is small
  enough to hold in mind, and each thing is done one way.
- **Clear** means a reader who knows the domain can find the code for a concept
  from its name, read it in one sitting, and be told nothing twice.
- **Consistent** means the same idea looks the same everywhere it appears, and
  every rule we state is one a reader can check.
- **Elegant** means special cases dissolve into general rules, so that nothing
  in the code is arbitrary and nothing could be taken away.

The rest of this document turns each word into criteria that can be measured.

## Exemplars

The standard is not invented from nothing. Five projects set it, one dimension
each. For each we name the property we take from it, so that a criterion below
can be traced to a project that has already met it.

- **pre-commit.** A Python command that shells out, kept in small modules, at
  mechanically enforced full coverage, with nothing added that no need called
  for. It sets the bar for module size, public surface and the test suite.
- **Trio.** Few concepts that compose, a design document that stays
  authoritative, and naming treated as design. It sets the bar for elegance, for
  vocabulary and for the enduring documents.
- **attrs and structlog.** Keyword-only APIs, a philosophy page that says why,
  and a changelog with a stated deprecation policy. They set the bar for API
  design and release practice.
- **Click and Flask.** A small stable core with clean extension points, and
  documentation organised by what the reader is trying to do. They set the bar
  for layering and for the shape of the documentation.
- **SQLite.** A documented file format, a stated compatibility commitment, and a
  published account of how the project is tested. It sets the bar for the state
  format, the contract and the account of testing.

pre-commit and Trio are primary. Between them they cover structure, clarity and
elegance, which is where the greatest distance lies.

## Criteria

Each criterion has a **measure**, which says what number or fact we read; a
**bar**, which says what value passes; and a **check**, which says what enforces
it. The check is a machine where a machine can tell cheaply and without false
alarms, and a reviewer everywhere else. Review is a check in its own right, not
a gap waiting for a tool. A mechanical check is code, so it meets this standard
like any other code, and it earns its place only when a criterion has failed in
review more than once and the check would be small and exact. Adding checks is
not progress towards the standard. Meeting the criteria is.

### Simplicity

**S1. Modules are small.**

- Measure: lines in each file under `src/dreamcatcher`.
- Bar: no file exceeds 600 lines. A responsibility that needs more becomes a
  package whose files each hold one concept from the ontology.
- Check: the phase measurement, and review of any file a change grows.

**S2. Functions fit on a screen.**

- Measure: lines in each function.
- Bar: no function exceeds 50 lines, except those the architecture names and
  explains, such as the scheduler tick when it reads as the listed steps.
- Check: the phase measurement, and review of any function a change grows.

**S3. Exports are used.**

- Measure: top-level names without a leading underscore that no other module
  under `src` imports.
- Bar: every such name is a document model, a view model a template consumes, or
  part of an interface the architecture names. Nothing is public because a test
  wanted it.
- Check: review.

**S4. Each thing is done one way.**

- Measure: places where two functions derive the same fact.
- Bar: one. A fact derived in `status` is not derived again in `tui` or `web`,
  and a word chosen in one presentation is the word in the other.
- Check: review, guided by the consistency review skill.

**S5. Nothing is suppressed.**

- Measure: `noqa`, `type: ignore` and `pragma: no cover` markers under `src`.
- Bar: zero of the first two. A coverage pragma marks a platform-specific arm
  and nothing else.
- Check: the lint hooks and the coverage gate, already in place.

### Clarity

**C1. One vocabulary.**

- Measure: disagreements the consistency review reports between two claims about
  one concept, in code, output, documents and the issue tracker.
- Bar: zero.
- Check: the consistency review, run at each phase boundary and on any pull
  request that names a concept.

**C2. The enduring documents are true.**

- Measure: statements in the ontology, architecture and this document that the
  code contradicts.
- Bar: zero. A pull request that moves the code past one of them corrects it in
  the same change and says so.
- Check: review, plus the dependency test under K1 for the architecture's
  structural claims.

**C3. Documentation is organised by purpose.**

- Measure: whether a reader can install, configure, run and consult a command
  reference without reading how the scheduler thinks.
- Bar: four kinds of page, kept apart: a tutorial that gets someone to a first
  pull request, how-to pages for each task, a reference for every command and
  setting, and explanation for the design. The README points to them and holds
  nothing else.
- Check: review of the documentation map that `uncoded` maintains.

**C4. Formats and contracts are versioned.**

- Measure: whether the state format and the agent-facing contract each carry a
  version and a compatibility statement.
- Bar: each does. A change to either is a numbered break, recorded in the
  changelog with what the user does about it.
- Check: review.

### Consistency

**K1. Every structural rule is checked by a machine.**

- Measure: rules in the architecture that could be checked mechanically and are
  not.
- Bar: zero. The import boundaries for `subprocess`, rich and Flask, and the
  dependency direction between modules, are the first four.
- Check: banned-import rules in ruff, and one test that asserts the dependency
  direction over the import graph.

**K2. The suite is fast and speaks the user's language.**

- Measure: wall-clock time of the default run, and test names.
- Bar: under 60 seconds on a laptop, at full branch coverage. Every test is
  named for a behaviour a user could recognise, not a function it calls.
- Check: CI reports the time; review reads the names.

**K3. The tracker is current.**

- Measure: open issues that use a word the ontology has retired.
- Bar: zero.
- Check: triage at each phase boundary.

**K4. Every change is reviewed against this standard.**

- Measure: pull requests that name the spec they serve and answer the definition
  of done below.
- Bar: all of them.
- Check: the pull request template.

### Elegance

These criteria rest more on review than the others, and an objection under them
must name the question that fails and show the evidence. Elegance is not a word
for "I would have done it differently".

**E1. Rules, not cases.**

- Measure: conditionals whose condition names a particular situation rather than
  applies a general rule, and the ledger in `docs/special-cases.md` that lists
  each one with its cause.
- Bar: every such conditional is on the ledger, and every entry has an external
  cause, such as a GitHub quirk or a Windows behaviour. Nothing on the ledger
  exists because of a choice this project made.
- Check: review, asking of each new branch whether it would go if a rule were
  stated more generally.

**E2. Invariants held by construction.**

- Measure: branches, raises and asserts that defend against a state the types
  could have made unrepresentable, such as two optional fields that must be both
  present or both absent.
- Bar: zero. Where two facts must agree, one type carries both, as the round
  ending classes carry outcome, time and exit status together.
- Check: review, and a count that each phase records.

**E3. Concept economy.**

- Measure: the change to the ontology in each pull request, against the case its
  spec makes.
- Bar: a feature adds a concept only when the spec shows that the existing
  concepts cannot compose to it. Removing a concept needs no case.
- Check: spec review.

**E4. Symmetry.**

- Measure: for concepts the ontology treats as parallel, such as the two kinds
  of agent work, the operations that exist for one kind and not the other, or
  exist twice.
- Bar: parallel concepts have parallel operations with parallel names, and share
  code where the ontology says they are the same. An asymmetry stands only where
  the ontology names the difference.
- Check: review, reading the namespace map.

## Definition of done

A pull request is done when its author can say yes to each of these.

1. It names the spec it serves, or the issue that it closes.
2. The tests and every check pass, and no check was skipped or suppressed.
3. Nothing it adds exceeds the bars in S1 and S2, and nothing it exports is
   without a caller.
4. Every word it introduces is in the ontology, or the ontology grew in the same
   change.
5. Any enduring document it makes false, it corrects.
6. It removes what it replaces.
7. Every conditional it adds applies a rule, or is on the ledger with its
   external cause.

## Exceptions

A criterion may be waived for one place, never in general. The waiver is written
where the check will read it: a sentence in the architecture for S2, a per-file
rule in `pyproject.toml` for K1, a pragma with its reason for S5, an entry on
the ledger for E1. A waiver with no reason a reader can find is a violation.

## Measurement

Each phase begins by measuring every criterion and recording the numbers in that
phase's spec folder, beside the plan for closing the gaps. The first such
measurement is the
[baseline of 2026-09-30](../specs/2026-09-30-engineering-standard/roadmap.md).
