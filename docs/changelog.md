# Changelog

Tagged releases follow Semantic Versioning beginning with v5.0.0. The
state format and agent contract have independent integer versions. See
[Compatibility and upgrades](compatibility.md) for the policy and
current upgrade instructions.

A change that users would notice gets an entry here: a change to a
command, a setting, a message, a view, the documentation, the state
format or the agent contract. Refactoring, tests and CI get none. The
release notes on GitHub list every merged pull request, so this page
lists only what a user upgrading needs to know.

From v5.1.0 on, each release groups its entries under these headings,
adapted from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
in this order, leaving out any heading that would be empty:

- **Breaking** for what users must act on before upgrading;
- **Added** for new commands, settings, controls and pages;
- **Changed** for existing behaviour that now works differently; and
- **Fixed** for behaviour that was wrong.

Released changes stay under their release; development changes stay
under **Unreleased**, with the same headings, until they are tagged.
From v5.0.0 on, each entry links the pull request or commit that made
the change.

## Unreleased

## [v9.6.1](https://github.com/alimanfoo/dreamcatcher/releases/tag/v9.6.1) — 2026-10-29

### Fixed

- The default `agent-campaign` route now runs the dream plugin's
  `dream:big` campaign skill, which dream 44.0.0 renamed from
  `dream:lead`. Existing installations must update the dream plugin to
  44.0.0 or later, then change their `dreamcatcher.toml` campaign
  prompts to `/dream:big GH{issue}` for Claude and
  `$dream:big GH{issue}` for Codex by hand, because `dreamcatcher init`
  leaves an existing file unchanged.
  ([#875](https://github.com/alimanfoo/dreamcatcher/pull/875))
- Squash-merging an assignment pull request no longer carries a CI-skip
  instruction onto main. The assignment's draft pull request now runs CI
  once. ([#876](https://github.com/alimanfoo/dreamcatcher/pull/876))

## [v9.6.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v9.6.0) — 2026-10-29

### Changed

- Working motifs now follow the web header's rendered height, so they
  stay beneath a taller or wrapped header.
  ([#868](https://github.com/alimanfoo/dreamcatcher/pull/868))
- The home page shows its working-agent motifs on narrower windows, from
  1184px wide, in the gutter beside the page's text.
  ([#867](https://github.com/alimanfoo/dreamcatcher/pull/867))
- Each repository's web view remembers its own theme, once its daemon
  has run, so switching the theme on one instance's page no longer
  switches it on another's.
  ([#866](https://github.com/alimanfoo/dreamcatcher/pull/866))
- In the Matrix theme, GitHub's state at the right of a card's first row
  is plain text on every card, as in Nature, without a box around a pull
  request's state.
  ([#864](https://github.com/alimanfoo/dreamcatcher/pull/864))
- The toggle that opens a tab's ended work reads "3 ended", without a
  "+" before it, as a campaign's line of sub-issues already does.
  ([#865](https://github.com/alimanfoo/dreamcatcher/pull/865))

## [v9.5.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v9.5.0) — 2026-10-28

### Added

- The home page shows each working agent as a small moving motif in the
  window's side margins: a falling column of glyphs in Matrix, and in
  Nature a falling dandelion seed on a light page and a firefly on a
  dark one. A tab with nothing active holds a calm field of the same
  motif beneath its hint. Nothing moves when the system asks for reduced
  motion. ([#855](https://github.com/alimanfoo/dreamcatcher/pull/855))

### Changed

- Every web page keeps its content to a column 1120px wide, where it was
  1320px, so that a laptop's window leaves side margins for the motifs.
  ([#855](https://github.com/alimanfoo/dreamcatcher/pull/855))
- The web header is narrower: the issues and pulls links sit under the
  repository name, and the daemon's process identifier replaces "daemon
  running". ([#859](https://github.com/alimanfoo/dreamcatcher/pull/859))
- The page that names the things _dreamcatcher_ deals with and says what
  the words mean is now called Concepts, at `docs/concepts.md`, and its
  opening paragraph says it is a glossary with rules. It was called the
  ontology. The old address,
  `https://alimanfoo.github.io/dreamcatcher/ontology/`, no longer
  resolves. ([#829](https://github.com/alimanfoo/dreamcatcher/pull/829))
- Each section of [Concepts](concepts.md) ends with the words that its
  concepts replace, such as "stage" for a sub-issue. The help of
  `dreamcatcher status` now says "requests with no open work", where it
  said "labels waiting for work".
  ([#838](https://github.com/alimanfoo/dreamcatcher/pull/838))
- A card whose status is unknown gives the read that failed, without the
  words "cannot tell:" before it, because its status already says
  unknown. ([#843](https://github.com/alimanfoo/dreamcatcher/pull/843))
- A request that the scheduler holds back has one status, held, where it
  was blocked, held or routing conflict. Its card says what GitHub says
  of its issue, such as "open, blocked by #810", and beneath its status
  what the user has to do, when they have to act.
  ([#843](https://github.com/alimanfoo/dreamcatcher/pull/843))
- Every card on the home page, for work or for a request, gives the
  issue first, then the label and status, then the detail, then the
  agent's latest output. An assignment with no pull request yet shows
  nothing where it said "no pull request yet".
  ([#843](https://github.com/alimanfoo/dreamcatcher/pull/843))
- In the Nature theme, a status and the `agent` label of the latest
  output no longer have a dot before them.
  ([#843](https://github.com/alimanfoo/dreamcatcher/pull/843))
- A campaign's sub-issue that has no assignment and no request says
  whether it is open or closed, and a closed one's title shows as
  quietly as ended work's. Before, a closed sub-issue looked like work
  still to do.
  ([#843](https://github.com/alimanfoo/dreamcatcher/pull/843))
- A conversation or a campaign card gives its issue's state, open or
  closed, at the right of its first line. A conversation or a campaign
  that has ended shows "ended", where it showed "closed", and its card
  says that the issue is closed.
  ([#849](https://github.com/alimanfoo/dreamcatcher/pull/849))
- A conversation or a campaign that the scheduler holds back shows as
  held, where it showed as idle with "paused, …". Its card says why
  beside the issue, such as "open, label removed" or "open, labelled by
  octocat", and says beneath what brings it back, such as "put the label
  back to resume". Held work comes after idle work and before unknown
  work. ([#849](https://github.com/alimanfoo/dreamcatcher/pull/849))
- A campaign's line of sub-issues counts, after how many are closed, the
  assignments and requests under the campaign by the status that each
  shows, as in "32 of 35 sub-issues closed · 6 working, 3 waiting, 1
  held, 5 completed". The "+" before the line is gone.
  ([#849](https://github.com/alimanfoo/dreamcatcher/pull/849))
- [Concepts](concepts.md) names the card: what _dreamcatcher_ shows for
  one piece of work, one request or one sub-issue, as a work card, a
  request card or a sub-issue card. The documentation calls each of them
  a card where it called some of them rows, and "request row" now means
  only what the scheduler found for a request.
  ([#853](https://github.com/alimanfoo/dreamcatcher/pull/853))
- A work's page opens with its work card, as the home page shows it: the
  issue and the state of its pull request or issue first, then the
  label, harness, model and effort, with the status, then the detail. A
  conversation or a campaign page now says whether its issue is open or
  closed, and who applied the label that holds it. The issue's number
  links to GitHub, as on the home page, where the whole heading did, and
  the strip of labelled facts is gone.
  ([#853](https://github.com/alimanfoo/dreamcatcher/pull/853))
- Each row of work in `dreamcatcher status` gives GitHub's state after
  the status, as a request's row does: an assignment's pull request and
  where it stands, or a conversation's or a campaign's issue state, then
  a semicolon and the detail, as in
  `PR #52 ready; 1 new post to answer`.
  ([#853](https://github.com/alimanfoo/dreamcatcher/pull/853))
- `dreamcatcher view` gives a conversation's or a campaign's issue state
  on an `issue` line, such as `open, labelled by octocat`, or `closed`
  once the work has ended. Its status line gives the status and the
  detail, where a held conversation's also said what GitHub holds.
  ([#853](https://github.com/alimanfoo/dreamcatcher/pull/853))
- The documentation says "held" where the scheduler holds work back, and
  keeps "paused" for the user's own act of removing a label or an
  assignee. ([#853](https://github.com/alimanfoo/dreamcatcher/pull/853))

### Fixed

- On the web page, a feed stops following when you scroll it away from
  its end by any means, including the keyboard, and follows again when
  you scroll back to its end. Before, only a pointer press, the mouse
  wheel or a click on a round link stopped it, so Page Up left the feed
  jumping back to its end on the next refresh.
  ([#846](https://github.com/alimanfoo/dreamcatcher/pull/846))
- On the web page, every new line of a feed shows as soon as it arrives,
  and a feed that is following stays at its end. Before, the page typed
  each line in one after another, so a busy agent left blank lines in
  the feed and the feed fell behind the agent. A card's latest output on
  the home page now changes in place, without being typed.
  ([#828](https://github.com/alimanfoo/dreamcatcher/pull/828))
- The home page and `dreamcatcher status` no longer show a dispatch
  label's request card beside the work that just started for it. For a
  few seconds after an update started work, until the update finished,
  the issue showed twice.
  ([#830](https://github.com/alimanfoo/dreamcatcher/pull/830))

## [v9.4.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v9.4.0) — 2026-10-27

### Changed

- The `dreamcatcher.toml` that `dreamcatcher init` writes names each
  dispatch label after the kind of work that it asks for, not after the
  skill that its route runs: `agent-conversation` in place of
  `dream:scout`, `agent-assignment` in place of `dream:smith`,
  `agent-assignment-easy` in place of `dream:less` and `agent-campaign`
  in place of `dream:lead`. Each route's prompt still invokes the same
  skill. `init` leaves an existing `dreamcatcher.toml` alone, so a
  repository that already has one keeps its labels. To switch such a
  repository to the new names, rename each label on GitHub, where an
  issue keeps its label through the rename. Then rename the route's
  `label` in `dreamcatcher.toml` to match, commit and push the file, and
  restart the daemon. Rename a conversation or campaign label only when
  none of its conversations or campaigns is open, because an open one
  pauses when its label is renamed. An open assignment is unaffected, as
  [the user renames a dispatch label](stories.md#the-user-renames-a-dispatch-label)
  tells. ([#820](https://github.com/alimanfoo/dreamcatcher/pull/820))

### Fixed

- A dispatch label that the user applied still counts as theirs after
  the label is renamed on GitHub. Before, every issue that carried the
  label when it was renamed showed its request as held, with the label
  applied by an unknown account. A label that GitHub shows before it
  records who applied it now shows that the update cannot tell who
  applied it, where before it showed as applied by an unknown account.
  ([#819](https://github.com/alimanfoo/dreamcatcher/pull/819))

## [v9.3.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v9.3.0) — 2026-10-26

### Changed

- Work starts, and a paused conversation or campaign resumes, only on a
  dispatch label that the signed-in user applied themselves. A label
  that a colleague, a bot or a deleted account applied starts nothing,
  and the request shows as held, naming who applied the label and saying
  that the user can remove and re-add it. After the upgrade, an open
  conversation or campaign whose label someone else applied pauses until
  the user does so.
  ([#809](https://github.com/alimanfoo/dreamcatcher/pull/809))

## [v9.2.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v9.2.0) — 2026-10-25

### Changed

- The documentation home page says in one short paragraph each what an
  assignment, a conversation and a campaign are for. The campaign
  tutorial, now
  [From parent issue to merged pull requests](campaign-tutorial.md),
  opens by explaining why you would use a campaign, and the
  documentation calls the issues that a campaign carries sub-issues, not
  stages. Advice on merge queues for parallel pull requests moves to
  [Start a campaign](start-a-campaign.md).
  ([#799](https://github.com/alimanfoo/dreamcatcher/pull/799))
- A kind of work that the daemon routes no label for tells the user to
  add the route and restart the daemon to enable it, in place of first
  saying that the daemon routes none, on the home page and in
  `dreamcatcher view`.
  ([#802](https://github.com/alimanfoo/dreamcatcher/pull/802))
- Ended work of every kind shows the state it ended in, such as
  "completed" or "closed", once in place of "ended", on its card, its
  page and in `dreamcatcher view`.
  ([#796](https://github.com/alimanfoo/dreamcatcher/pull/796))

### Fixed

- A Claude conversation whose agent waits on background subagents posts
  the agent's last answer, instead of a message saying that it is still
  waiting or an error that the harness returned no final output.
  ([#793](https://github.com/alimanfoo/dreamcatcher/pull/793))
- A Codex conversation runs in a checkout whose path holds a percent
  sign or a line ending, instead of stopping the daemon.
  ([#795](https://github.com/alimanfoo/dreamcatcher/pull/795))

## [v9.1.1](https://github.com/alimanfoo/dreamcatcher/releases/tag/v9.1.1) — 2026-10-25

### Added

- A security policy says how to report a vulnerability in private.
  ([#787](https://github.com/alimanfoo/dreamcatcher/pull/787))

## [v9.1.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v9.1.0) — 2026-10-24

### Changed

- A lead round's trigger says that a sub-issue **handed back** and that
  its **pull request changed**, where it said **handback** and **pull
  request**.
  ([#777](https://github.com/alimanfoo/dreamcatcher/pull/777))
- The daemon stops when an update cannot complete, for example because a
  record under `.dreamcatcher/` is damaged or a write fails. It prints
  the file and what is wrong with it, ends its rounds and its web page
  as Ctrl-C does, and leaves the record of the last complete update in
  place. Fix the cause and start the daemon again, and the interrupted
  work carries on. The daemon used to report the failure and try again
  at every update, and a conversation or campaign whose own records
  could not be read showed the failure on its row.
  ([#773](https://github.com/alimanfoo/dreamcatcher/pull/773))
- An open page whose refresh gets no answer from the server, as when the
  daemon has stopped, keeps what it shows and warns "Refresh failed.
  Check the terminal running dreamcatcher." It used to show no warning.
  ([#773](https://github.com/alimanfoo/dreamcatcher/pull/773))
- Each card and request row on the web home page keeps GitHub's
  information at its top and _dreamcatcher_'s at its bottom.
  ([#770](https://github.com/alimanfoo/dreamcatcher/pull/770))
- An ended assignment's card on the web home page says "completed" or
  "cancelled" once, where it said "ended", and every ended card's title
  is quieter.
  ([#779](https://github.com/alimanfoo/dreamcatcher/pull/779))
- A pull request that is ready for review now shows in brighter text
  than a draft, on an assignment's card and on its page. In the matrix
  theme, every other pull request now shows in the subdued text.
  ([#780](https://github.com/alimanfoo/dreamcatcher/pull/780))
- An assignment whose pull request is merged or closed, and whose
  wrap-up round has yet to start, is waiting "awaiting wrap-up", where
  it said that the pull request is merged or closed.
  ([#766](https://github.com/alimanfoo/dreamcatcher/pull/766))
- A campaign's sub-issue with no assignment and no request shows only
  its number and title on the web page, without the "no assignment" line
  and the open or closed badge.
  ([#764](https://github.com/alimanfoo/dreamcatcher/pull/764))
- The first example in the configuration guide includes a campaign
  route, so it shows each kind of route the guide describes.
  ([#775](https://github.com/alimanfoo/dreamcatcher/pull/775))

### Fixed

- On the web page, a lead round that names its sub-issues lists its
  trigger and timing beside its number, on separate lines, as every
  other round does.
  ([#777](https://github.com/alimanfoo/dreamcatcher/pull/777))
- A wrap-up round that finishes as the user cancels its assignment
  leaves the assignment cancelled, so its worktree, branch and
  uncommitted work stay the user's. A cancel that comes after the
  wrap-up round changes nothing, and `dreamcatcher cancel` says that the
  assignment has already ended.
  ([#774](https://github.com/alimanfoo/dreamcatcher/pull/774))

## [v9.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v9.0.0) — 2026-10-23

### Breaking

- Saved state moves to state format 8, in `.dreamcatcher/v8/`. Saved
  work from v7.0.0 and v8.0.0 does not carry across: before upgrading,
  let each assignment reach its wrap-up or finish its pull request by
  hand, and accept that conversations and campaigns start afresh, as
  [the upgrade instructions](compatibility.md#upgrade-from-v800-to-v900)
  describe. ([#740](https://github.com/alimanfoo/dreamcatcher/pull/740))

### Changed

- The feed no longer shows a subagent's steps, so subagents that run at
  once no longer interleave their lines with each other's and the
  agent's. A Claude round still shows each subagent when the agent sends
  it and its report when it finishes, and the report is no longer
  indented. A Codex round shows a `[wait]` line as soon as the agent
  waits on its subagents.
  ([#729](https://github.com/alimanfoo/dreamcatcher/pull/729))
- The status views count down to the next update from when the last
  update finished, and show **updating** while an update runs, with a
  pulse on the web page unless the browser asks for reduced motion. The
  countdown used to start when an update started, so it reached 0s early
  and stayed there through the next update.
  ([#740](https://github.com/alimanfoo/dreamcatcher/pull/740))
- Each update lists the open issues assigned to the signed-in account
  once, whatever the number of routes, rather than once for each
  dispatch label. A failed listing now starts no new work of any kind,
  and shows as one scheduler failure.
  ([#726](https://github.com/alimanfoo/dreamcatcher/pull/726))
- A lead round's trigger names each sub-issue that woke it, with what
  changed, such as `#687: checks finished, mergeable`, in place of a
  count of the sub-issues that changed. The web page links each
  sub-issue.
  ([#741](https://github.com/alimanfoo/dreamcatcher/pull/741))
- No view shows the revision of main that a conversation or campaign
  round was given.
  ([#741](https://github.com/alimanfoo/dreamcatcher/pull/741))
- Once an assignment completes, or a conversation or campaign ends with
  its issue, the next update removes its worktree, and an assignment's
  local branch, to free the disk. Its record stays, so the home page,
  `dreamcatcher status` and `dreamcatcher view` still show it, without
  the worktree or a hand-resume command. A cancelled assignment keeps
  both. A removal that fails is printed with the update and not tried
  again. ([#732](https://github.com/alimanfoo/dreamcatcher/pull/732))
- The web home page always shows the Assignments, Conversations and
  Campaigns tabs, and `dreamcatcher status` a section for each kind.
  Before, a kind's tab and section were hidden while the daemon routed
  no label of that kind and had none of its work. Now the tab says that
  the daemon routes none of that kind, and links to the documentation
  that shows how to add the route to `dreamcatcher.toml`.
  ([#751](https://github.com/alimanfoo/dreamcatcher/pull/751))
- Round lists on the web and in the terminal omit successful outcomes,
  so running and exceptional outcomes stand out.
  ([#753](https://github.com/alimanfoo/dreamcatcher/pull/753))
- The upgrade guide explains how to reclaim the disk an earlier state
  format holds, after keeping any cancelled assignment's work you want.
  ([#742](https://github.com/alimanfoo/dreamcatcher/pull/742))
- The campaign guides explain when to use GitHub's merge queue, or leave
  its up-to-date requirement off, to avoid repeated agent rounds after
  each stage merges.
  ([#754](https://github.com/alimanfoo/dreamcatcher/pull/754))

### Fixed

- A campaign's sub-issue card shows a new assignment in the update that
  starts it, instead of waiting one more update.
  ([#739](https://github.com/alimanfoo/dreamcatcher/pull/739))
- The documentation home page's headline fits a phone held sideways.
  ([#743](https://github.com/alimanfoo/dreamcatcher/pull/743))
- An invalid web feed position is now called a position in its error
  message, matching the terminal feed.
  ([#748](https://github.com/alimanfoo/dreamcatcher/pull/748))
- Switching theme on the web keeps the page's place in the address, so
  the home page stays on the tab it showed.
  ([#744](https://github.com/alimanfoo/dreamcatcher/pull/744))
- The feed shows the report of a Claude subagent that hands its report
  back, where it showed only a line saying the report was delivered
  elsewhere.
  ([#729](https://github.com/alimanfoo/dreamcatcher/pull/729))

## [v8.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v8.0.0) — 2026-10-23

### Breaking

- `dreamcatcher view` replaces `dreamcatcher assignment`,
  `dreamcatcher conversation` and `dreamcatcher campaign`, and `stop`
  and `feed` no longer take `--assignment`, `--conversation` or
  `--campaign`. `retry`, `stop`, `cancel`, `view` and `feed` each take
  `GH<n>` for the one piece of agent work at the issue, of any kind, or
  an agent work identifier for that exact work. `retry` clears the fault
  of that one piece, or reports that it is not in fault, so it now
  reaches a conversation in fault that is not the newest at its issue.
  When the issue has more than one piece, the command changes nothing
  and prints a command for each piece, with its identifier, so the view
  no longer lists the other work at the issue.
  ([#691](https://github.com/alimanfoo/dreamcatcher/pull/691))

### Changed

- The default `dream:less` recipes now use Sonnet at high effort for
  Claude and `gpt-5.6-terra` at high effort for Codex. Existing
  configuration files and work already created keep their recipes.
  ([#707](https://github.com/alimanfoo/dreamcatcher/pull/707))
- A work page on the web names its kind and opens in the same browser
  tab, and its `< home` link returns to the tab of that kind. The home
  page's tabs are in the address, so the back button moves between them.
  ([#698](https://github.com/alimanfoo/dreamcatcher/pull/698))

### Fixed

- On macOS and Linux, closing the terminal that runs `dreamcatcher run`,
  ending the daemon with `kill`, or shutting the machine down now ends
  its rounds as interrupted, as Ctrl-C does. Before, their harnesses
  carried on without the daemon.
  ([#690](https://github.com/alimanfoo/dreamcatcher/pull/690))
- After the machine restarts, starting the daemon no longer ends a
  program that has taken the process identifier of a round from before
  the restart.
  ([#690](https://github.com/alimanfoo/dreamcatcher/pull/690))
- The reason given when a campaign cannot observe a sub-issue names it
  by its number alone, and the reason given when a conversation cannot
  post its answer names no issue, so the web pages no longer show an
  issue in the terminal's `GH12` form.
  ([#692](https://github.com/alimanfoo/dreamcatcher/pull/692))
- A conversation round input that cannot be read now fails the status
  report with the file and what is wrong with it, as an assignment's or
  a campaign's does. Before, the round's trigger read "comments" and its
  revision was left out.
  ([#704](https://github.com/alimanfoo/dreamcatcher/pull/704))
- On a work page on the web, a round's boundary stays at the top of the
  feed only while that round is in view, so the end of a long, wrapped
  boundary no longer shows beneath the next round's.
  ([#700](https://github.com/alimanfoo/dreamcatcher/pull/700))

## [v7.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v7.0.0) — 2026-10-22

### Breaking

- Saved state moves to state format 7, in `.dreamcatcher/v7/`. Saved
  work from v6 does not carry across: before upgrading, let each
  assignment reach its wrap-up or finish its pull request by hand, and
  accept that conversations start afresh, as
  [the upgrade instructions](compatibility.md#upgrade-from-v6-to-v700)
  describe. ([#662](https://github.com/alimanfoo/dreamcatcher/pull/662))

### Added

- Campaigns, a third kind of agent work. A `[[campaign]]` route in
  `dreamcatcher.toml` names a label and the lead's recipes. Labelling a
  parent issue assigned to you starts a campaign: the lead takes a round
  in a worktree checked out at main, posts on GitHub itself, and keeps
  its final output in the feed. Each comment you post on the parent then
  wakes the lead in the same harness session, on main refreshed, and
  comments posted while the campaign is paused reach it when it resumes.
  Closing the parent ends the campaign. The lead's input also holds the
  parent's sub-issues and where each one's assignment stands, and a
  sub-issue that needs the lead's attention wakes it too. The lead
  leaves the agent marker off its feedback on a sub-issue's pull
  request, so the assignment's agent is given that feedback as it is
  given yours. [Start a campaign](start-a-campaign.md) explains how, and
  the [campaign skill contract](contract.md#campaign-skill-contract)
  says what the lead is given.
  ([#662](https://github.com/alimanfoo/dreamcatcher/pull/662),
  [#667](https://github.com/alimanfoo/dreamcatcher/pull/667),
  [#671](https://github.com/alimanfoo/dreamcatcher/pull/671),
  [#672](https://github.com/alimanfoo/dreamcatcher/pull/672),
  [#674](https://github.com/alimanfoo/dreamcatcher/pull/674))
- The web home page has a Campaigns tab, where each active campaign
  counts its closed sub-issues and expands to show each one's assignment
  card, request or issue, and the terminal has a `dreamcatcher campaign`
  view. `stop` and `feed` take `--campaign`, and `retry` also clears the
  fault of the newest campaign at the issue.
  ([#662](https://github.com/alimanfoo/dreamcatcher/pull/662),
  [#671](https://github.com/alimanfoo/dreamcatcher/pull/671),
  [#673](https://github.com/alimanfoo/dreamcatcher/pull/673))
- The `dreamcatcher.toml` that `dreamcatcher init` writes routes the
  `dream:lead` label to campaigns, and `init` creates that label. The
  route's recipes run the dream plugin's `dream:lead` skill, which
  carries a parent issue's sub-issues through their assignments to
  merge. [Start a campaign](start-a-campaign.md) explains what it does.
  ([#677](https://github.com/alimanfoo/dreamcatcher/pull/677))
- Campaigns can be queued: a campaign shows as blocked while an open
  issue blocks its parent on GitHub, and starts once every blocker is
  closed. [Start a campaign](start-a-campaign.md#queue-campaigns)
  explains how.
  ([#682](https://github.com/alimanfoo/dreamcatcher/pull/682))
- A second tutorial,
  [From parent issue to merged stages](campaign-tutorial.md), takes a
  parent issue with two dependent sub-issues through `dream:lead` to
  merge. ([#680](https://github.com/alimanfoo/dreamcatcher/pull/680))

### Fixed

- Starting _dreamcatcher_ for the first time in a repository no longer
  fails on Python 3.13 before any agent work exists.
  ([#664](https://github.com/alimanfoo/dreamcatcher/pull/664))
- [Stop and recover work](stop-and-recover.md) now says that work
  resumed after an errored or interrupted round also takes up what
  arrived meanwhile.
  ([#680](https://github.com/alimanfoo/dreamcatcher/pull/680))
- The animated status view on the documentation home page now shows the
  statuses, round details and dispatch labels that the web home page
  shows, rather than a "needs user feedback" status that the web page no
  longer has.
  ([#647](https://github.com/alimanfoo/dreamcatcher/pull/647))
- A request blocked by an issue in another repository now names that
  issue with its repository, as `owner/name#123`, on the web home page
  and in `dreamcatcher status`, and the web page links to it there. It
  had been shown and linked as an issue in this repository. The web home
  page also no longer puts a space before each comma between the issues
  a request names.
  ([#676](https://github.com/alimanfoo/dreamcatcher/pull/676))

## [v6.3.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v6.3.0) — 2026-10-21

### Added

- `assignment`, `conversation`, `feed` and `stop` accept an agent work
  identifier, such as `GH123-20260912-192458-assignment`, to select that
  exact assignment or conversation instead of the newest at the issue.
  ([#628](https://github.com/alimanfoo/dreamcatcher/pull/628))

### Changed

- Scheduler failures now show one to a line, apart from the other
  instance facts, on the web home page and in `dreamcatcher status`. A
  failed GitHub read names its gh command without the options, such as
  `gh issue list`, rather than the whole command line.
  ([#623](https://github.com/alimanfoo/dreamcatcher/pull/623))
- When a refresh fails, an assignment or conversation page now keeps its
  feed and shows a warning with the reason, as the home page already
  did. The warning clears once a refresh succeeds. The home page's
  warning now uses the same words.
  ([#637](https://github.com/alimanfoo/dreamcatcher/pull/637))
- The `assignment` and `conversation` views list the other work of their
  kind at the issue, with each one's identifier, dispatch label and
  status, and stay on the work they opened on when newer work arrives.
  ([#628](https://github.com/alimanfoo/dreamcatcher/pull/628))
- The upgrade instructions now say to stop every standalone view, such
  as `dreamcatcher web` or a refreshing `status`, before you install a
  release with a different state format, and to start the views again
  from the new installation. A view left running from the old format may
  show stale status. Upgrades that keep the state format need no such
  step. See
  [Restart views across state formats](compatibility.md#restart-views-across-state-formats).
  ([#639](https://github.com/alimanfoo/dreamcatcher/pull/639))
- Looking up the work at one issue now reads only matching work
  directories, without opening unrelated records.
  ([#640](https://github.com/alimanfoo/dreamcatcher/pull/640))
- The user stories clarify how request cards relate to saved work and
  which local-state failures need user repair. They also record that
  authorization to start work on another user's instance remains an open
  question, rather than an endorsed workflow.
  ([#627](https://github.com/alimanfoo/dreamcatcher/pull/627),
  [#632](https://github.com/alimanfoo/dreamcatcher/pull/632),
  [#634](https://github.com/alimanfoo/dreamcatcher/pull/634))
- The README now directs ideas, suggestions and questions to GitHub
  Discussions, alongside the documentation link.
  ([#642](https://github.com/alimanfoo/dreamcatcher/pull/642))

### Fixed

- On Windows, a harness that cannot be started safely now errors its
  round and never runs.
  ([#625](https://github.com/alimanfoo/dreamcatcher/pull/625))
- On a narrow web home page, a long status now moves below the issue's
  title and wraps within the row, instead of squeezing the title into a
  column of single characters.
  ([#624](https://github.com/alimanfoo/dreamcatcher/pull/624))

## [v6.2.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v6.2.0) — 2026-10-20

### Added

- The [user stories](stories.md) describe expected behaviour for normal
  use, user errors and external faults, including which limitations are
  accepted. A bug includes a failure of the handling a story promises.
  ([#592](https://github.com/alimanfoo/dreamcatcher/pull/592),
  [#598](https://github.com/alimanfoo/dreamcatcher/pull/598))

### Changed

- An idle assignment whose pull request is still a draft now reads
  "needs feedback" rather than "draft", because the agent is waiting on
  you. ([#612](https://github.com/alimanfoo/dreamcatcher/pull/612))
- The web home page shows assignments and conversations in tabs rather
  than side by side, giving the selected kind of agent work the full
  dashboard width.
  ([#596](https://github.com/alimanfoo/dreamcatcher/pull/596))
- A round that resumes an assignment after a round that did not finish,
  with nothing new to relay, now shows the trigger "recover" instead of
  "carry on".
  ([#609](https://github.com/alimanfoo/dreamcatcher/pull/609))
- Activity notes now show the current round's worktree as `<worktree>`
  wherever its absolute path appears, so more of a command remains
  visible. ([#602](https://github.com/alimanfoo/dreamcatcher/pull/602))

### Fixed

- Repeated state-document reads from the web and terminal views no
  longer prevent the daemon from replacing those documents on Windows.
  ([#601](https://github.com/alimanfoo/dreamcatcher/pull/601))
- A conversation whose errored or interrupted round's comments the user
  deleted now shows as idle once the next update finds nothing to
  answer, instead of waiting for a round that will not start.
  ([#615](https://github.com/alimanfoo/dreamcatcher/pull/615))
- Assignments and conversations now show as idle while a finished round
  awaits the next update, instead of appearing to need another round
  because the last update's channel reading is stale.
  ([#600](https://github.com/alimanfoo/dreamcatcher/pull/600))
- Deleting an open assignment's worktree now errors its next round and
  lets the daemon continue. A second failure puts the assignment in
  fault, as the user story promises.
  ([#599](https://github.com/alimanfoo/dreamcatcher/pull/599))
- An assignment round that follows an errored or interrupted one is now
  told to continue the unfinished assignment while its pull request is
  open, even when no new posts or signals have arrived. Before, an agent
  could read the empty input as nothing to do and end its turn.
  ([#607](https://github.com/alimanfoo/dreamcatcher/pull/607))

## [v6.1.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v6.1.0) — 2026-10-18

### Changed

- The empty commit that starts an assignment now uses the checkout's Git
  author and skips CI. Checks begin with the agent's first real commit
  instead. ([#582](https://github.com/alimanfoo/dreamcatcher/pull/582))
- `dreamcatcher cancel` says only that the assignment is cancelled. It
  no longer reads the pull request to name it in the message.
  ([#580](https://github.com/alimanfoo/dreamcatcher/pull/580))
- An idle assignment's detail no longer repeats the merge state and
  check result that its pull request chip shows. It says ready for
  review, draft, merged or closed, or that checks are still failing
  after two attempts.
  ([#584](https://github.com/alimanfoo/dreamcatcher/pull/584))
- The views say main moved, where they said out of date, for a round
  that main moving on woke. The pull request chip says behind main or
  conflicts with main in place of out of date.
  ([#588](https://github.com/alimanfoo/dreamcatcher/pull/588))

- `dreamcatcher --help` lists its commands under "commands", where it
  said "verbs", and a bare `dreamcatcher` asks for a command.
  ([#591](https://github.com/alimanfoo/dreamcatcher/pull/591))

### Fixed

- An assignment's pull request chip keeps showing whether the pull
  request is draft or ready, its merge state and its check result while
  a round runs.
  ([#586](https://github.com/alimanfoo/dreamcatcher/pull/586))

## [v6.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v6.0.0) — 2026-10-17

### Breaking

- _dreamcatcher_ moves to state format 6. It keeps its local state in
  `.dreamcatcher/v6/` and starts with none, so the assignments and
  conversations that v5 saved are not carried on. Stop a v5 daemon
  before you start v6.
  [Compatibility and upgrades](compatibility.md#upgrade-from-v5-to-v600)
  says what to settle first.
  ([#561](https://github.com/alimanfoo/dreamcatcher/pull/561))

### Added

- Once an assignment's pull request is ready for review, _dreamcatcher_
  wakes the agent without a post from you when the base branch leaves
  the pull request behind it or in conflict with it, and when a check
  fails. Each is relayed once for each commit at the head of the pull
  request, and a draft gets neither. After two rounds in a row woken by
  failing checks, a failing check does not wake the agent again until a
  round has something else to relay, such as a post from you.
  ([#571](https://github.com/alimanfoo/dreamcatcher/pull/571))
- The views show an assignment's merge state and check result beside
  draft or ready, and an idle assignment says when its checks are
  running or still failing after two attempts.
  ([#571](https://github.com/alimanfoo/dreamcatcher/pull/571))
- A Claude assignment round may run `gh pr checks` and `gh run view`
  without being asked, so that it can read why a check failed.
  ([#571](https://github.com/alimanfoo/dreamcatcher/pull/571))
- An assignment round's input file gains two keys: `pull_request_head`,
  the pull request's head commit when the round started, and `signals`,
  which lists `out_of_date` or `check_failure` when either woke the
  round. The agent contract stays at version 1, and an assignment skill
  may ignore both, since the prompt carries the instructions.
  ([#571](https://github.com/alimanfoo/dreamcatcher/pull/571))
- A conversation ends when its issue is closed, and the web home page
  lists it with your other ended work.
  ([#568](https://github.com/alimanfoo/dreamcatcher/pull/568))

### Changed

- Assignments and conversations share one set of states: working,
  waiting, idle, fault, unknown and ended. The states needs user
  feedback, complete and cancelled are gone. An assignment that needs
  your feedback reads as idle, and one that completed or that you
  cancelled reads as ended with that detail.
  ([#565](https://github.com/alimanfoo/dreamcatcher/pull/565))
- `dreamcatcher status` and the web home page list each labelled issue
  that has no work yet beside the work of its kind, and say why no work
  has started: available, blocked by an issue, claimed by a pull
  request, waiting for a comment, carrying conflicting labels, or
  unknown because a read failed. The sections of available, blocked and
  routing-conflict issues are gone.
  ([#565](https://github.com/alimanfoo/dreamcatcher/pull/565))
- A round that fails before its agent starts, such as an assignment's
  first round when it cannot push the branch, is an errored round. It
  counts towards a fault like any other, and the failed setups section
  is gone from the views.
  ([#562](https://github.com/alimanfoo/dreamcatcher/pull/562))
- After a round errors or is interrupted, the next round is given the
  same input again, with a line saying that the previous round did not
  finish. The feed and the rounds table say what woke each round.
  ([#562](https://github.com/alimanfoo/dreamcatcher/pull/562))
- A conversation belongs to the conversation label that started it.
  Removing that label, unassigning the issue or adding a second
  conversation label pauses it, and undoing the change resumes it in the
  same harness session. Another conversation label starts a conversation
  of its own once it is the issue's only conversation label.
  ([#568](https://github.com/alimanfoo/dreamcatcher/pull/568))
- Every assignment and conversation has an identifier that ends in its
  kind, such as `GH12-20261017-093000-assignment`, and an assignment's
  branch is named after it, such as
  `dreamcatcher-GH12-20261017-093000-assignment`. The `conversation`
  command, and `feed` and `stop` with `--conversation`, select the
  newest conversation at the issue, and `retry` clears the faults of the
  newest assignment and the newest conversation.
  ([#561](https://github.com/alimanfoo/dreamcatcher/pull/561))
- The web page of an assignment or a conversation is at
  `/work/<identifier>`. The `/assignments/<identifier>` and
  `/conversations/<issue>` addresses are gone.
  ([#561](https://github.com/alimanfoo/dreamcatcher/pull/561))
- An issue with an open assignment no longer has its blockers and linked
  pull requests read at every update, so the daemon makes fewer GitHub
  reads. ([#568](https://github.com/alimanfoo/dreamcatcher/pull/568))
- The web interface's matrix theme drops its boxes, as the nature theme
  did. Panels become headings over a rule, assignments, issues and
  conversations are rows divided by rules, and the feed and rounds line
  up with their headings. The filled chip alone marks an assignment that
  needs your feedback, and the current round's number shows in inverse
  video. ([#543](https://github.com/alimanfoo/dreamcatcher/pull/543))

### Fixed

- `dreamcatcher status` and the web interface read the dispatch labels
  that the running daemon loaded, where they read `dreamcatcher.toml`
  before. They no longer disagree with the daemon after you edit the
  file, and they still work when it is missing or broken.
  ([#561](https://github.com/alimanfoo/dreamcatcher/pull/561))
- Removing conversation label A from an issue and adding label B no
  longer resumes A's conversation with A's settings. B starts a
  conversation of its own, and A's stays paused.
  ([#568](https://github.com/alimanfoo/dreamcatcher/pull/568))
- An assignment interrupted while it set up its branch, worktree or pull
  request no longer leaves them behind with no record that names them.
  The assignment is recorded first, and its next round finishes the
  setup. ([#562](https://github.com/alimanfoo/dreamcatcher/pull/562))
- An assignment relays a post by the signed-in account however GitHub
  writes the login's capitals, and no longer relays a post whose body is
  only whitespace, as conversations already did.
  ([#573](https://github.com/alimanfoo/dreamcatcher/pull/573))

## [v5.6.2](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.6.2) — 2026-10-15

### Changed

- The web interface's nature theme takes a crisper look. Assignments,
  issues and conversations are rows divided by rules in place of blurred
  cards, the feed and rounds lose their boxes, and only the states that
  need you keep a filled pill. The documentation site follows, and its
  home page now shows a miniature of the web interface.
  ([#539](https://github.com/alimanfoo/dreamcatcher/pull/539))

## [v5.6.1](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.6.1) — 2026-10-12

### Fixed

- The web interface's nature theme separates the cards of ended
  assignments and makes them more compact, so their blurred surfaces no
  longer run together.
  ([#525](https://github.com/alimanfoo/dreamcatcher/pull/525))
- A conversation or assignment page before its first round now leaves
  the rounds panel blank, and an empty conversation feed invites you to
  post a comment, where both showed a dashed placeholder before.
  ([#528](https://github.com/alimanfoo/dreamcatcher/pull/528))

## [v5.6.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.6.0) — 2026-10-12

### Changed

- `dreamcatcher run` now opens and serves the web interface beside the
  daemon. Use `--noweb` to run only the daemon; the standalone
  `dreamcatcher web` command remains available for manual control.
  ([#518](https://github.com/alimanfoo/dreamcatcher/pull/518))
- `dreamcatcher run` now includes the installed software version in its
  startup message.
  ([#522](https://github.com/alimanfoo/dreamcatcher/pull/522))

### Fixed

- The web interface's nature theme gives each round's heading the page
  background, so the heading no longer sits in a band of a slightly
  different colour.
  ([#520](https://github.com/alimanfoo/dreamcatcher/pull/520))

## [v5.5.1](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.5.1) — 2026-10-12

### Fixed

- The web interface's nature theme no longer draws a hard outline around
  the home page cards in its dark scheme, so their edges stay soft as in
  the light one.
  ([#515](https://github.com/alimanfoo/dreamcatcher/pull/515))
- The agent contract, the ontology and the guides to configuring and
  customising skills now name conversation skills beside assignment
  skills, where they spoke of conversation prompts before. The agent
  contract stays at version 1, and existing skills and prompts need no
  change. ([#513](https://github.com/alimanfoo/dreamcatcher/pull/513))

## [v5.5.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.5.0) — 2026-10-11

### Added

- A how-to guide, "Customise skills", says how to start with dream's
  skills and how to write and route your own. It replaces the home page
  section on skills.
  ([#505](https://github.com/alimanfoo/dreamcatcher/pull/505))
- _dreamcatcher_ is published on PyPI. Install it with
  `uv tool install dreamcatcher`.
  ([#512](https://github.com/alimanfoo/dreamcatcher/pull/512))

### Changed

- The web interface's nature theme now follows the viewer's system light
  or dark setting. Its dark scheme uses a dusk palette and shows the
  moon crossing the sky at night; the Matrix theme is unchanged.
  ([#507](https://github.com/alimanfoo/dreamcatcher/pull/507))
- The documentation now introduces the dream plugin, says which of its
  skills run under _dreamcatcher_, and links to the dream documentation
  site. ([#499](https://github.com/alimanfoo/dreamcatcher/pull/499))
- The documentation home page opens with a hero: a short account of what
  _dreamcatcher_ does over an animated status view.
  ([#500](https://github.com/alimanfoo/dreamcatcher/pull/500))
- The documentation site sets its text in Geist and its headings in
  Instrument Serif, and offers a dusk scheme beside the day one. It
  follows your system setting, and the header has a switch between the
  two. ([#500](https://github.com/alimanfoo/dreamcatcher/pull/500))
- The documentation home page leads with what sets _dreamcatcher_ apart:
  agents that run in your own setup, that you steer from GitHub wherever
  you are, and as many at once as you allow. It explains how
  _dreamcatcher_ works before it introduces the dream plugin's skills,
  so it no longer reads as if _dreamcatcher_ provides them.
  ([#501](https://github.com/alimanfoo/dreamcatcher/pull/501))
- The documentation home page no longer shows a label above its
  headline, and its account of an assignment includes the rounds that
  address your review. Its last section says that you can start with
  dream's skills or write your own.
  ([#502](https://github.com/alimanfoo/dreamcatcher/pull/502))
- The documentation home page hero has tighter wording.
  ([#503](https://github.com/alimanfoo/dreamcatcher/pull/503))
- The documentation home page lists the how-to guides in the same order
  as the navigation.
  ([#504](https://github.com/alimanfoo/dreamcatcher/pull/504))

### Fixed

- Assignment setup no longer runs the repository's commit and pre-push
  hooks on the empty placeholder commit, so a hook that cannot run in a
  fresh worktree no longer stops agent work from starting. The agent's
  own commits and pushes still run them.
  ([#497](https://github.com/alimanfoo/dreamcatcher/pull/497))
- The documentation home page says to assign the issue to yourself
  before you ask a question in a conversation, and it links to the
  agent-facing contract again.
  ([#512](https://github.com/alimanfoo/dreamcatcher/pull/512))

## [v5.4.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.4.0) — 2026-10-08

### Changed

- Terminal and web status views now share their daemon, instance,
  agent-work, and round ordering and wording.
  ([#488](https://github.com/alimanfoo/dreamcatcher/pull/488))
- The default `dream:less` recipes now use medium effort for both
  harnesses. Existing configuration files are unchanged.
  ([2aa4d8b](https://github.com/alimanfoo/dreamcatcher/commit/2aa4d8b847ab7536d46a9163137c41c33f43b931))

### Fixed

- The web home page's empty panels now tell users to assign the issue to
  the signed-in GitHub account and apply a route label. The conversation
  panel also says to comment from that account.
  ([#486](https://github.com/alimanfoo/dreamcatcher/pull/486))
- `dreamcatcher init` now gives suitable next steps when the
  configuration has only conversation routes or no routes. It no longer
  fails with a traceback.
  ([#487](https://github.com/alimanfoo/dreamcatcher/pull/487))
- The web home page now reports a failed background refresh while
  keeping the last successful status visible. The warning clears after a
  successful refresh.
  ([#489](https://github.com/alimanfoo/dreamcatcher/pull/489))

## [v5.3.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.3.0) — 2026-10-07

### Added

- When a kind of agent work has no current work, the web home page now
  names the labels that start it in place of an empty panel.
  ([#460](https://github.com/alimanfoo/dreamcatcher/pull/460))

### Changed

- `dreamcatcher.toml` may now leave out `[[assignment]]` routes, as it
  could already leave out `[[conversation]]` routes. The web home page
  hides the panel for a kind of agent work that has neither routes nor
  work. ([#460](https://github.com/alimanfoo/dreamcatcher/pull/460))
- The top bar of every web page now links the version number to the
  documentation site, in place of a separate **Docs** link.
  ([#464](https://github.com/alimanfoo/dreamcatcher/pull/464))
- Dots now separate the repository, **issues** and **pulls** links in
  the top bar.
  ([#466](https://github.com/alimanfoo/dreamcatcher/pull/466))
- The documentation site lists **Review an assignment** straight after
  the tutorial.
  ([#462](https://github.com/alimanfoo/dreamcatcher/pull/462))

### Fixed

- A running daemon now stops, along with its rounds, when its lock file
  goes missing or is replaced, as happens when someone deletes the state
  directory. A second daemon could otherwise run against the same
  checkout beside it.
  ([#468](https://github.com/alimanfoo/dreamcatcher/pull/468))

## [v5.2.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.2.0) — 2026-10-07

### Added

- Every web page now links to the documentation site from its top bar.
  ([#438](https://github.com/alimanfoo/dreamcatcher/pull/438))
- The top bar of every web page now links to the repository's **issues**
  and **pulls** on GitHub, beside the repository's name.
  ([#441](https://github.com/alimanfoo/dreamcatcher/pull/441))
- `dreamcatcher init` prepares a repository's main checkout for `run`.
  It checks `gh`, Git and each harness, writes a default
  `dreamcatcher.toml` for the harnesses that are installed, installs the
  `dream` plugin, and creates the labels the configuration names. The
  tutorial now uses it.
  ([#439](https://github.com/alimanfoo/dreamcatcher/pull/439))

### Changed

- Nature is now the default web theme. Matrix remains available from the
  theme switch, and an existing theme choice is still remembered.
  ([#448](https://github.com/alimanfoo/dreamcatcher/pull/448))
- The complete example in the configuration reference now routes
  conversations to `dream:scout` and assignments to `dream:smith` and
  `dream:less`.
  ([#437](https://github.com/alimanfoo/dreamcatcher/pull/437))

### Fixed

- Retrying conversation creation after a failed record write now reuses
  the worktree left by the earlier attempt. The first round still resets
  it to fetched main before the agent reads it.
  ([#453](https://github.com/alimanfoo/dreamcatcher/pull/453))
- The web home page heads its conversations panel **Conversations**
  again, beside **Assignments**, in place of **Issue conversations**.
  ([#449](https://github.com/alimanfoo/dreamcatcher/pull/449))

## [v5.1.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.1.0) — 2026-10-06

### Added

- The documentation is now a site at
  <https://alimanfoo.github.io/dreamcatcher/>, built from `docs/`. The
  agent contract and this changelog moved there from the repository
  root, to `docs/contract.md` and `docs/changelog.md`.
  ([#424](https://github.com/alimanfoo/dreamcatcher/pull/424))

### Changed

- The assignment and conversation pages now show **Stop** and **Cancel**
  as **stop round** and **cancel assignment**, at the foot of the page
  beside **resume by hand** and styled like it. **stop round** asks you
  to confirm, as **cancel assignment** already did. **Retry** stays at
  the top. ([#427](https://github.com/alimanfoo/dreamcatcher/pull/427))
- The product name is now _dreamcatcher_, in lower case, in the
  documentation, the help, the messages and the web pages. The web pages
  now write every issue number as `#123`, as GitHub does.
  ([#431](https://github.com/alimanfoo/dreamcatcher/pull/431))

## [v5.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v5.0.0) — 2026-10-06

- Terminal and web live views now keep following faulted assignments and
  conversations in fault or with a routing conflict, so recovery appears
  without reopening the view. They stop only when an assignment ends or
  a conversation leaves the status report.
  ([#415](https://github.com/alimanfoo/dreamcatcher/pull/415))
- Brought the words in the status views, CLI help and messages, and
  guides into line with each other. An assignment that needs your
  feedback shows how long since its last output rather than "idle". The
  terminal and web views share their labels and say "preferred harness"
  for the daemon's `--harness`. A scheduler tick is called an update
  wherever you read about one, so the daemon now reports "update
  failed". A route's per-harness settings are a dispatch recipe
  throughout, and the `run` help says one daemon runs per checkout.
  ([#416](https://github.com/alimanfoo/dreamcatcher/pull/416))
- The web pages and the terminal status view no longer report a running
  daemon as stopped, or its running rounds as interrupted, after the
  system clock is corrected. The daemon now holds an operating-system
  lock on `.dreamcatcher/daemon.lock` for as long as it runs, in place
  of `.dreamcatcher/daemon.pid`, so stop a v4.0.0 daemon before you
  start this release.
  ([#405](https://github.com/alimanfoo/dreamcatcher/pull/405))
- Added a `config` table to a Codex recipe in `dreamcatcher.toml`.
  _dreamcatcher_ passes each entry to every Codex round as
  `-c key=value`, so that a label can run Codex with settings such as a
  larger context window.
  ([#402](https://github.com/alimanfoo/dreamcatcher/pull/402))
- Added `dreamcatcher stop` to request a stop for the running round of a
  selected assignment or issue conversation.
  ([#374](https://github.com/alimanfoo/dreamcatcher/pull/374))
- Added `dreamcatcher cancel` and a **Cancel** control on the assignment
  page, so that you can finish an assignment's pull request by hand. A
  cancelled assignment runs no further rounds and shows as
  **cancelled**. The web home page and the terminal status view now
  group complete and cancelled assignments as **ended**.
  ([#376](https://github.com/alimanfoo/dreamcatcher/pull/376))
- A cancel or a retry request is no longer lost when the daemon records
  something about the same assignment or conversation at the same
  moment. ([#395](https://github.com/alimanfoo/dreamcatcher/pull/395))
- The web home page and the terminal status view show capacity, a global
  cooldown and the latest update's failures once each. Failures, such as
  a failed issue listing, appear on a **scheduler failures** row, and
  the web home page no longer hides them while capacity is full. The
  daemon's line for each update says what it launched, then any global
  cooldown, full capacity and failures.
  ([#389](https://github.com/alimanfoo/dreamcatcher/pull/389))
- Reshaped the documentation around reader tasks: a start-to-finish
  tutorial, focused task guides, complete command and configuration
  references, this changelog, compatibility guidance and a testing
  account. ([#370](https://github.com/alimanfoo/dreamcatcher/pull/370))
- The web assignment and conversation pages now show the "resume by
  hand" section only while no round is running, and update it without a
  reload when a round starts or ends. An open section stays open across
  refreshes.
  ([#385](https://github.com/alimanfoo/dreamcatcher/pull/385))
- Corrected CLI help to include routing conflicts among the conditions
  that end live conversation and conversation-feed views.
  ([#370](https://github.com/alimanfoo/dreamcatcher/pull/370))
- Ending a round on macOS no longer fails with a permission error when
  its harness has exited in the same moment, and starting a round on
  Windows no longer fails when its harness exits in the moment after it
  starts: a Windows child is now placed in its job before it runs.
  ([#371](https://github.com/alimanfoo/dreamcatcher/pull/371))
- A failed issue listing for an assignment label no longer prevents the
  rounds that existing assignments require. It prevents only the
  creation of new assignments.
  ([#387](https://github.com/alimanfoo/dreamcatcher/pull/387))
- State format 5 starts with empty local state in `.dreamcatcher/v5/`;
  state format 4 is left untouched and ignored. Finish assignments
  through successful wrap-up, stop the daemon, and accept fresh
  conversation context before upgrading. See
  [Upgrade from v4.0.0 to v5.0.0](compatibility.md#upgrade-from-v400-to-v500).
  ([#364](https://github.com/alimanfoo/dreamcatcher/pull/364))
- State format 5 puts the initial conversation title and body under
  `initial_issue`. [Agent contract version 1](contract.md) documents
  that current protocol; declaring the version does not itself change
  the input. Prompt and skill authors should check their assumptions
  against the contract.
  ([#364](https://github.com/alimanfoo/dreamcatcher/pull/364),
  [#370](https://github.com/alimanfoo/dreamcatcher/pull/370))
- The prompt that hands an assignment new pull request posts now opens
  with "User-posts prompt for pull request #N:" rather than "PR-inbox
  prompt", and each round's input file is `round-input.json` rather than
  `inbox.json`. A skill that recognises the old words should follow
  [the contract](contract.md) instead.
  ([#411](https://github.com/alimanfoo/dreamcatcher/pull/411))
- Added a **Retry** button to the web assignment and conversation pages
  while the work is in fault. It records the same retry request as
  `dreamcatcher retry` for the work the page shows.
  ([#386](https://github.com/alimanfoo/dreamcatcher/pull/386))
- A conversation in fault now shows **fault** even when its issue has a
  routing conflict, is no longer eligible, or has no scheduler
  observation yet, so its page offers **Retry**. Before, it could show
  idle, unknown or routing conflict.
  ([#394](https://github.com/alimanfoo/dreamcatcher/pull/394))
- The "resume by hand" command for a Codex session now sets the work's
  model, effort and harness config, as every other Codex round does.
  ([#408](https://github.com/alimanfoo/dreamcatcher/pull/408))

## [v4.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v4.0.0) — 2026-10-01

- State format 4 began with new local state. Configuration renamed
  assignment route tables from `[[dispatch]]` to `[[assignment]]` and
  changed the single `[conversation]` table to repeatable
  `[[conversation]]` routes. The `assignee` setting was removed;
  _dreamcatcher_ uses the account signed in through `gh`.

Evidence:
[state format 4 commit](https://github.com/alimanfoo/dreamcatcher/commit/fa275e7d9fb5e69e615872f88bafea419e8f0364),
[assignment-route rename](https://github.com/alimanfoo/dreamcatcher/commit/8c990658489dda9b541285594f63693a6eeaf402),
[conversation-route change](https://github.com/alimanfoo/dreamcatcher/commit/d6ac2d5bf471b13102e82dedb8e3dc6fb1857c64),
[assignee removal](https://github.com/alimanfoo/dreamcatcher/commit/cef7dfce8118ae3b4fd55f3ff09e4448547de08e).

## [v3.2.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v3.2.0) — 2026-09-26

- Added issue conversations, including follow-up and recovery rounds and
  support for both Claude and Codex. Older scheduler records within
  state format 3 became invalid and had to be removed before restarting.

Evidence:
[scheduler-record change](https://github.com/alimanfoo/dreamcatcher/commit/e622711bf2421321264dcfc5734d1d3831d0f121).

## [v3.1.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v3.1.0) — 2026-09-23

- Added the local web dashboard for monitoring assignments and their
  feeds.

## [v3.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v3.0.0) — 2026-09-21

- Introduced numbered state directories with state format 3. Earlier
  unversioned local state was left untouched and ignored. Daemon
  interval and agent capacity moved from configuration into `run`
  options.

Evidence:
[state-directory change](https://github.com/alimanfoo/dreamcatcher/commit/d71c61dad960b1ac9f9034b67c7fd3766feaaebb),
[legacy-state removal](https://github.com/alimanfoo/dreamcatcher/commit/e1e3a47afba61ea3345542bd19da105891da278a),
[daemon-option change](https://github.com/alimanfoo/dreamcatcher/commit/8ba4a39f97fc52f30f92cbf3eab8edf7b720c5da).

## [v3.0.0.beta1](https://github.com/alimanfoo/dreamcatcher/releases/tag/v3.0.0.beta1) — 2026-09-20

- Replaced sessions with agent assignments and changed their unversioned
  saved records. No migration was provided for the pre-release state.

Evidence:
[assignment-boundary commit](https://github.com/alimanfoo/dreamcatcher/commit/f6b2fa60f4e2ee1f1546d1da14d753b5ddbdd4f9).

## [v2.0.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v2.0.0) — 2026-09-10

- Replaced the `scry` command with the `board`, `session` and `feed`
  views. The release did not change the saved-state layout.

Evidence:
[command change](https://github.com/alimanfoo/dreamcatcher/commit/b9395845e5719082fd109c6735a41d31c12b1cc5).

## [v1.0](https://github.com/alimanfoo/dreamcatcher/releases/tag/v1.0) — 2026-09-09

- First tagged release, using unversioned local state.
