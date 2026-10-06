# Releasing

The maintainer decides when to release. This page lists what to do before
publishing one. The package takes its version from the Git tag, so creating the
tag is the only version change.

## Choose the version

[The compatibility policy](compatibility.md#release-compatibility) decides the
number. An incompatible change makes a major release, and so does any change to
the state format. Compatible new functionality makes a minor release, and
compatible fixes alone make a patch release.

## Check the standard

Do this before a major or minor release. A patch release skips it.

1. Run the consistency review, the `uncoded-consistency-review` skill, over the
   source, the enduring documents, the user documentation and the output a user
   sees. Fix what is quick to fix, and file an issue for each other finding.
2. Triage the open issues against [the ontology](ontology.md). Rewrite each one
   that names a concept by a word the ontology does not use for it. Close each
   one whose work is done or no longer applies, and say why.
3. Measure every criterion in [the standard](standard.md), reading the three
   enduring documents against the code. `tools/measure_source.py` reports the
   module and function line counts. Replace [the measurement](measurement.md)
   with the results, and file an issue for each shortfall.

A shortfall does not hold the release back. A failing test or check does.

## Prepare the release

1. Move the entries under **Unreleased** in [the changelog](changelog.md) into a
   section for the new version, headed like the released sections below it.
2. Update the opening of [Compatibility and upgrades](compatibility.md), which
   names the latest release and the state format it uses.
3. Merge these changes, and the measurement, in one pull request, and wait for
   CI to pass on `main`.

## Publish

Create the release on GitHub from `main`. Tag it with the version, such as
`v5.0.0`, and use the version's changelog section as the release notes.
