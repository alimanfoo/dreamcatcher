# Changelog

Tagged releases follow Semantic Versioning beginning with v5.0.0. The state
format and agent contract have independent integer versions. See
[Compatibility and upgrades](compatibility.md) for the policy and current
upgrade instructions.

A change that users would notice gets an entry here: a change to a command, a
setting, a message, a view, the documentation, the state format or the agent
contract. Refactoring, tests and CI get none. The release notes on GitHub list
every merged pull request, so this page lists only what a user upgrading needs
to know.

From v5.1.0 on, each release groups its entries under these headings, adapted
from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), in this order,
leaving out any heading that would be empty:

- **Breaking** for what users must act on before upgrading;
- **Added** for new commands, settings, controls and pages;
- **Changed** for existing behaviour that now works differently; and
- **Fixed** for behaviour that was wrong.

Released changes stay under their release; development changes stay under
**Unreleased**, with the same headings, until they are tagged. From v5.0.0 on,
each entry links the pull request that made the change.

## Unreleased

## [v5.3.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.3.0) — 2026-10-07

### Added

- When a kind of agent work has no current work, the web home page now names the
  labels that start it in place of an empty panel.
  ([#460](https://github.com/alimanfoo/dreamcatcher/pull/460))

### Changed

- `dreamcatcher.toml` may now leave out `[[assignment]]` routes, as it could
  already leave out `[[conversation]]` routes. The web home page hides the panel
  for a kind of agent work that has neither routes nor work.
  ([#460](https://github.com/alimanfoo/dreamcatcher/pull/460))
- The top bar of every web page now links the version number to the
  documentation site, in place of a separate **Docs** link.
  ([#464](https://github.com/alimanfoo/dreamcatcher/pull/464))
- Dots now separate the repository, **issues** and **pulls** links in the top
  bar. ([#466](https://github.com/alimanfoo/dreamcatcher/pull/466))
- The documentation site lists **Review an assignment** straight after the
  tutorial. ([#462](https://github.com/alimanfoo/dreamcatcher/pull/462))

### Fixed

- A running daemon now stops, along with its rounds, when its lock file goes
  missing or is replaced, as happens when someone deletes the state directory. A
  second daemon could otherwise run against the same checkout beside it.
  ([#468](https://github.com/alimanfoo/dreamcatcher/pull/468))

## [v5.2.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.2.0) — 2026-10-07

### Added

- Every web page now links to the documentation site from its top bar.
  ([#438](https://github.com/alimanfoo/dreamcatcher/pull/438))
- The top bar of every web page now links to the repository's **issues** and
  **pulls** on GitHub, beside the repository's name.
  ([#441](https://github.com/alimanfoo/dreamcatcher/pull/441))
- `dreamcatcher init` prepares a repository's main checkout for `run`. It checks
  `gh`, Git and each harness, writes a default `dreamcatcher.toml` for the
  harnesses that are installed, installs the `dream` plugin, and creates the
  labels the configuration names. The tutorial now uses it.
  ([#439](https://github.com/alimanfoo/dreamcatcher/pull/439))

### Changed

- Nature is now the default web theme. Matrix remains available from the theme
  switch, and an existing theme choice is still remembered.
  ([#448](https://github.com/alimanfoo/dreamcatcher/pull/448))
- The complete example in the configuration reference now routes conversations
  to `dream:scout` and assignments to `dream:smith` and `dream:less`.
  ([#437](https://github.com/alimanfoo/dreamcatcher/pull/437))
- The terminal views and the web pages now use the same words for the same fact.
  The terminal shows a conversation round's code revision in seven characters,
  as the web pages already did.
  ([#488](https://github.com/alimanfoo/dreamcatcher/pull/488))

### Fixed

- Retrying conversation creation after a failed record write now reuses the
  worktree left by the earlier attempt. The first round still resets it to
  fetched main before the agent reads it.
  ([#453](https://github.com/alimanfoo/dreamcatcher/pull/453))
- The web home page heads its conversations panel **Conversations** again,
  beside **Assignments**, in place of **Issue conversations**.
  ([#449](https://github.com/alimanfoo/dreamcatcher/pull/449))

## [v5.1.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.1.0) — 2026-10-06

### Added

- The documentation is now a site at
  <https://alimanfoo.github.io/dreamcatcher/>, built from `docs/`. The agent
  contract and this changelog moved there from the repository root, to
  `docs/contract.md` and `docs/changelog.md`.
  ([#424](https://github.com/alimanfoo/dreamcatcher/pull/424))

### Changed

- The assignment and conversation pages now show **Stop** and **Cancel** as
  **stop round** and **cancel assignment**, at the foot of the page beside
  **resume by hand** and styled like it. **stop round** asks you to confirm, as
  **cancel assignment** already did. **Retry** stays at the top.
  ([#427](https://github.com/alimanfoo/dreamcatcher/pull/427))
- The product name is now _dreamcatcher_, in lower case, in the documentation,
  the help, the messages and the web pages. The web pages now write every issue
  number as `#123`, as GitHub does.
  ([#431](https://github.com/alimanfoo/dreamcatcher/pull/431))

## [v5.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.0.0) — 2026-10-06

- Terminal and web live views now keep following faulted assignments and
  conversations in fault or with a routing conflict, so recovery appears without
  reopening the view. They stop only when an assignment ends or a conversation
  leaves the status report.
  ([#415](https://github.com/alimanfoo/dreamcatcher/pull/415))
- Brought the words in the status views, CLI help and messages, and guides into
  line with each other. An assignment that needs your feedback shows how long
  since its last output rather than "idle". The terminal and web views share
  their labels and say "preferred harness" for the daemon's `--harness`. A
  scheduler tick is called an update wherever you read about one, so the daemon
  now reports "update failed". A route's per-harness settings are a dispatch
  recipe throughout, and the `run` help says one daemon runs per checkout.
  ([#416](https://github.com/alimanfoo/dreamcatcher/pull/416))
- The web pages and the terminal status view no longer report a running daemon
  as stopped, or its running rounds as interrupted, after the system clock is
  corrected. The daemon now holds an operating-system lock on
  `.dreamcatcher/daemon.lock` for as long as it runs, in place of
  `.dreamcatcher/daemon.pid`, so stop a v4.0.0 daemon before you start this
  release. ([#405](https://github.com/alimanfoo/dreamcatcher/pull/405))
- Added a `config` table to a Codex recipe in `dreamcatcher.toml`.
  _dreamcatcher_ passes each entry to every Codex round as `-c key=value`, so
  that a label can run Codex with settings such as a larger context window.
  ([#402](https://github.com/alimanfoo/dreamcatcher/pull/402))
- Added `dreamcatcher stop` to request a stop for the running round of a
  selected assignment or issue conversation.
  ([#374](https://github.com/alimanfoo/dreamcatcher/pull/374))
- Added `dreamcatcher cancel` and a **Cancel** control on the assignment page,
  so that you can finish an assignment's pull request by hand. A cancelled
  assignment runs no further rounds and shows as **cancelled**. The web home
  page and the terminal status view now group complete and cancelled assignments
  as **ended**. ([#376](https://github.com/alimanfoo/dreamcatcher/pull/376))
- A cancel or a retry request is no longer lost when the daemon records
  something about the same assignment or conversation at the same moment.
  ([#395](https://github.com/alimanfoo/dreamcatcher/pull/395))
- The web home page and the terminal status view show capacity, a global
  cooldown and the latest update's failures once each. Failures, such as a
  failed issue listing, appear on a **scheduler failures** row, and the web home
  page no longer hides them while capacity is full. The daemon's line for each
  update says what it launched, then any global cooldown, full capacity and
  failures. ([#389](https://github.com/alimanfoo/dreamcatcher/pull/389))
- Reshaped the documentation around reader tasks: a start-to-finish tutorial,
  focused task guides, complete command and configuration references, this
  changelog, compatibility guidance and a testing account.
  ([#370](https://github.com/alimanfoo/dreamcatcher/pull/370))
- The web assignment and conversation pages now show the "resume by hand"
  section only while no round is running, and update it without a reload when a
  round starts or ends. An open section stays open across refreshes.
  ([#385](https://github.com/alimanfoo/dreamcatcher/pull/385))
- Corrected CLI help to include routing conflicts among the conditions that end
  live conversation and conversation-feed views.
  ([#370](https://github.com/alimanfoo/dreamcatcher/pull/370))
- Ending a round on macOS no longer fails with a permission error when its
  harness has exited in the same moment, and starting a round on Windows no
  longer fails when its harness exits in the moment after it starts: a Windows
  child is now placed in its job before it runs.
  ([#371](https://github.com/alimanfoo/dreamcatcher/pull/371))
- A failed issue listing for an assignment label no longer prevents the rounds
  that existing assignments require. It prevents only the creation of new
  assignments. ([#387](https://github.com/alimanfoo/dreamcatcher/pull/387))
- State format 5 starts with empty local state in `.dreamcatcher/v5/`; state
  format 4 is left untouched and ignored. Finish assignments through successful
  wrap-up, stop the daemon, and accept fresh conversation context before
  upgrading. See
  [Upgrade from v4.0.0 to v5.0.0](compatibility.md#upgrade-from-v400-to-v500).
  ([#364](https://github.com/alimanfoo/dreamcatcher/pull/364))
- State format 5 puts the initial conversation title and body under
  `initial_issue`. [Agent contract version 1](contract.md) documents that
  current protocol; declaring the version does not itself change the input.
  Prompt and skill authors should check their assumptions against the contract.
  ([#364](https://github.com/alimanfoo/dreamcatcher/pull/364),
  [#370](https://github.com/alimanfoo/dreamcatcher/pull/370))
- The prompt that hands an assignment new pull request posts now opens with
  "User-posts prompt for pull request #N:" rather than "PR-inbox prompt", and
  each round's input file is `round-input.json` rather than `inbox.json`. A
  skill that recognises the old words should follow [the contract](contract.md)
  instead. ([#411](https://github.com/alimanfoo/dreamcatcher/pull/411))
- Added a **Retry** button to the web assignment and conversation pages while
  the work is in fault. It records the same retry request as
  `dreamcatcher retry` for the work the page shows.
  ([#386](https://github.com/alimanfoo/dreamcatcher/pull/386))
- A conversation in fault now shows **fault** even when its issue has a routing
  conflict, is no longer eligible, or has no scheduler observation yet, so its
  page offers **Retry**. Before, it could show idle, unknown or routing
  conflict. ([#394](https://github.com/alimanfoo/dreamcatcher/pull/394))
- The "resume by hand" command for a Codex session now sets the work's model,
  effort and harness config, as every other Codex round does.
  ([#408](https://github.com/alimanfoo/dreamcatcher/pull/408))

## [v4.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v4.0.0) — 2026-10-01

- State format 4 began with new local state. Configuration renamed assignment
  route tables from `[[dispatch]]` to `[[assignment]]` and changed the single
  `[conversation]` table to repeatable `[[conversation]]` routes. The `assignee`
  setting was removed; _dreamcatcher_ uses the account signed in through `gh`.

Evidence:
[state format 4 commit](https://github.com/alimanfoo/dreamcatcher/commit/fa275e7d9fb5e69e615872f88bafea419e8f0364),
[assignment-route rename](https://github.com/alimanfoo/dreamcatcher/commit/8c990658489dda9b541285594f63693a6eeaf402),
[conversation-route change](https://github.com/alimanfoo/dreamcatcher/commit/d6ac2d5bf471b13102e82dedb8e3dc6fb1857c64),
[assignee removal](https://github.com/alimanfoo/dreamcatcher/commit/cef7dfce8118ae3b4fd55f3ff09e4448547de08e).

## [v3.2.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v3.2.0) — 2026-09-26

- Added issue conversations, including follow-up and recovery rounds and support
  for both Claude and Codex. Older scheduler records within state format 3
  became invalid and had to be removed before restarting.

Evidence:
[scheduler-record change](https://github.com/alimanfoo/dreamcatcher/commit/e622711bf2421321264dcfc5734d1d3831d0f121).

## [v3.1.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v3.1.0) — 2026-09-23

- Added the local web dashboard for monitoring assignments and their feeds.

## [v3.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v3.0.0) — 2026-09-21

- Introduced numbered state directories with state format 3. Earlier unversioned
  local state was left untouched and ignored. Daemon interval and agent capacity
  moved from configuration into `run` options.

Evidence:
[state-directory change](https://github.com/alimanfoo/dreamcatcher/commit/d71c61dad960b1ac9f9034b67c7fd3766feaaebb),
[legacy-state removal](https://github.com/alimanfoo/dreamcatcher/commit/e1e3a47afba61ea3345542bd19da105891da278a),
[daemon-option change](https://github.com/alimanfoo/dreamcatcher/commit/8ba4a39f97fc52f30f92cbf3eab8edf7b720c5da).

## [v3.0.0.beta1](https://github.com/alimanfoo/dreamcatcher/releases/tag/v3.0.0.beta1) — 2026-09-20

- Replaced sessions with agent assignments and changed their unversioned saved
  records. No migration was provided for the pre-release state.

Evidence:
[assignment-boundary commit](https://github.com/alimanfoo/dreamcatcher/commit/f6b2fa60f4e2ee1f1546d1da14d753b5ddbdd4f9).

## [v2.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v2.0.0) — 2026-09-10

- Replaced the `scry` command with the `board`, `session` and `feed` views. The
  release did not change the saved-state layout.

Evidence:
[command change](https://github.com/alimanfoo/dreamcatcher/commit/b9395845e5719082fd109c6735a41d31c12b1cc5).

## [v1.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v1.0) — 2026-09-09

- First tagged release, using unversioned local state.
