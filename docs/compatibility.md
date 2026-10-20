# Compatibility and upgrades

The latest tagged release, v6.2.0, uses state format 6, as v6.0.0 and
v6.1.0 did. Saved work from those releases continues after the upgrade;
the first update refreshes the scheduler observations. v5.0.0 through
v5.6.2 used state format 5, and v4.0.0 used state format 4. Saved work
does not carry across from one format to the next.

## Upgrade from v5 to v6.0.0

Before installing v6.0.0:

1. Decide whether you can start issue conversations afresh. If you still
   need their saved context, postpone the upgrade.
2. Let every assignment finish its successful wrap-up and reach
   **complete**, or decide to finish its pull request yourself. v6.0.0
   does not carry on an assignment that v5 started, and while its pull
   request stays open and linked to the issue, it claims the issue, so
   no new assignment starts there.
3. Stop the v5 _dreamcatcher_ daemon and every standalone view, as
   [Restart views across state formats](#restart-views-across-state-formats)
   describes.

The new release starts with empty local state in `.dreamcatcher/v6/`. It
leaves `.dreamcatcher/v5/` untouched but does not read it. Existing
GitHub issues, comments and pull requests remain on GitHub.

A fresh conversation has read none of the issue's comments. If its issue
still has a conversation label, the new conversation is given every
comment you have posted on the issue, and _dreamcatcher_ may answer them
again.

There is no state migration. Once you have accepted the fresh start, run
the new daemon normally from the same main checkout.

## Upgrade from v4.0.0 to v5.0.0

Before installing v5.0.0:

1. Decide whether you can start issue conversations afresh. If you still
   need their saved context, postpone the upgrade.
2. Let every assignment finish its successful wrap-up and reach
   **complete**. An assignment with no round running may still need
   feedback or wrap-up.
3. Stop the _dreamcatcher_ daemon.

The new release starts with empty local state in `.dreamcatcher/v5/`. It
leaves `.dreamcatcher/v4/` untouched but does not read it. Existing
GitHub issues, comments and pull requests remain on GitHub.

A fresh conversation has read none of the issue's comments. If its issue
still has a conversation label, _dreamcatcher_ may treat existing
eligible comments as new input and answer them again.

There is no state migration. Once you have accepted the fresh start, run
the new daemon normally from the same main checkout.

## Release compatibility

Beginning with v5.0.0, tagged releases follow
[Semantic Versioning](https://semver.org/):

- A major release makes an incompatible change.
- A minor release adds compatible functionality.
- A patch release makes compatible fixes.

This promise covers documented commands, flags, configuration, saved
agent work and agent obligations. Python internals, exact diagnostic
wording and visual layout carry no stability promise.

An incompatible configuration or agent-contract change requires a major
release. A state-format change also requires a major release because
saved work does not continue automatically across formats. Every
breaking change gets a [changelog](changelog.md) entry explaining its
effect and what users must do before upgrading.

This policy does not assign compatibility promises to earlier releases.
Untagged commits on `main` are development code and carry no release
compatibility promise.

## State format

The state format is an integer independent of the release version. A
change that makes the structure or meaning of persisted records
incompatible increments it; several releases may share one state format.

_dreamcatcher_ reads and writes only the directory for its own format,
and ignores other format directories without changing them. The daemon
lock at `.dreamcatcher/daemon.lock` is shared across formats. v4.0.0 and
earlier use `.dreamcatcher/daemon.pid` instead, so stop an older daemon
before you start v5.0.0 or later.

A different format starts with empty local state. No migration is
promised.

### Restart views across state formats

A view reads only the records of its own state format. Running a view
and a daemon that use different state formats is not supported, and the
view may show stale status. _dreamcatcher_ does not promise to detect
the mismatch.

Before you install a release with a different state format:

1. Stop the old daemon. This also stops the web page that
   `dreamcatcher run` serves.
2. Stop every standalone view: `dreamcatcher web`, and any refreshing
   `status`, `assignment`, `conversation` or `feed` view.

After you install it, start the daemon and any views you still want from
the new installation. The restart depends on the state format, not the
release version. Releases that share a state format read the same
records.

## Agent contract

The current [agent contract](contract.md) is version **1**. It covers
assignment skills and conversation skills. Existing conforming skills
remain compatible while the contract version stays the same.

The contract number is an integer independent of the release and
state-format versions. A change that requires an existing conforming
skill or prompt to change increments it; clarifications and editorial
corrections do not. Version 1 documents the existing protocol rather
than changing it. _dreamcatcher_ does not negotiate the version at
runtime.
