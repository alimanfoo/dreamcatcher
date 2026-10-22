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

### Changed

- A work page on the web names its kind and opens in the same browser
  tab, and its `< home` link returns to the tab of that kind. The home
  page's tabs are in the address, so the back button moves between them.
  ([#698](https://github.com/alimanfoo/dreamcatcher/pull/698))

### Fixed

- The reason given when a campaign cannot observe a sub-issue names it
  by its number alone, and the reason given when a conversation cannot
  post its answer names no issue, so the web pages no longer show an
  issue in the terminal's `GH12` form.
  ([#692](https://github.com/alimanfoo/dreamcatcher/pull/692))

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
