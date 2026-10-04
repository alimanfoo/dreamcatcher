# Changelog

Tagged releases follow Semantic Versioning beginning with v5.0.0. The state
format and agent contract have independent integer versions. See
[Compatibility and upgrades](docs/compatibility.md) for the policy and current
upgrade instructions.

A change that users would notice gets an entry here. Released changes stay under
their release; development changes stay under **Unreleased** until they are
tagged.

## Unreleased (v5.0.0)

- Added `dreamcatcher stop` to request a stop for the running round of a
  selected assignment or issue conversation.
- Added `dreamcatcher cancel` and a **Cancel** control on the assignment page,
  so that you can finish an assignment's pull request by hand. A cancelled
  assignment runs no further rounds and shows as **cancelled**. The web home
  page and the terminal status view now group complete and cancelled assignments
  as **ended**.
- The web home page and the terminal status view show what held the latest
  scheduler tick once each: capacity and a global cooldown on their own rows,
  and failures, such as a failed issue listing, on a **scheduler failures** row.
  The web home page no longer hides a failure from a tick held at capacity.
- Reshaped the documentation around reader tasks: a start-to-finish tutorial,
  focused task guides, complete command and configuration references, this
  changelog, compatibility guidance and a testing account.
- Corrected CLI help to include routing conflicts among the conditions that end
  live conversation and conversation-feed views.
- Ending a round on macOS no longer fails with a permission error when its
  harness has exited in the same moment, and starting a round on Windows no
  longer fails when its harness exits in the moment after it starts: a Windows
  child is now placed in its job before it runs.
- A failed issue listing for an assignment label no longer holds the rounds that
  existing assignments require. It holds only the creation of new assignments.
- State format 5 starts with empty local state in `.dreamcatcher/v5/`; state
  format 4 is left untouched and ignored. Finish assignments through successful
  wrap-up, stop the daemon, and accept fresh conversation context before
  upgrading. See
  [Upgrade from v4.0.0 to v5.0.0](docs/compatibility.md#upgrade-from-v400-to-v500).
- State format 5 puts the initial conversation title and body under
  `initial_issue`. [Agent contract version 1](CONTRACT.md) documents that
  current protocol; declaring the version does not itself change the input.
  Prompt and skill authors should check their assumptions against the contract.

Evidence:
[state format 5 commit](https://github.com/alimanfoo/dreamcatcher/commit/cb091b86916369bfd83c2cc7afebda69eeb37838).

## [v4.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v4.0.0) — 2026-10-01

- State format 4 began with new local state. Configuration renamed assignment
  route tables from `[[dispatch]]` to `[[assignment]]` and changed the single
  `[conversation]` table to repeatable `[[conversation]]` routes. The `assignee`
  setting was removed; Dreamcatcher uses the account signed in through `gh`.

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
