# Reading guide for campaigns

## The big picture

This guide follows the code behind the
[campaign requirements](requirements.md) as stage 6 leaves it. Read the
sections in order, starting with `Scheduler.tick` in
[`scheduler/tick.py`](../../src/dreamcatcher/scheduler/tick.py).

Assignments, conversations and campaigns share that scheduling loop.
Each kind supplies its own inspection rules and round preparation. The
shared runner executes the round and records its outcome; status
reporting reads those records for the terminal and web views.

To see who holds the loop, read `DreamcatcherDaemon.run` and
`run_scheduler_tick` in [`daemon.py`](../../src/dreamcatcher/daemon.py).
The daemon loads configuration, holds the instance lock, runs updates,
and writes their results. It reconciles unfinished rounds at startup and
ends its running rounds on shutdown.

## From a label to eligible work

Read `DreamcatcherConfig` and `DispatchRoute` in
[`config.py`](../../src/dreamcatcher/config.py), then
`Scheduler._list_issues` and `_inspect_requests` in
[`scheduler/tick.py`](../../src/dreamcatcher/scheduler/tick.py). A label
selects a route containing harness recipes, and
`DreamcatcherConfig.identify_routes` finds the routes of one kind among
an issue's labels. Matching is case-insensitive. Discovery lists open
issues assigned to the signed-in account, deduplicates them and orders
them by creation time and number.

For a new assignment, `_ask_start_time_questions` in
[`scheduler/assignments.py`](../../src/dreamcatcher/scheduler/assignments.py)
checks for open linked pull requests and open blocking issues. Either
prevents a start. An existing assignment answers all assignment labels
on its issue and no longer uses those start-time checks. A conversation
or a campaign answers only its own label. The tick inspects in two
passes. The first looks up the assignment and conversation inspectors in
`_OPEN_WORK_INSPECTORS` and `_REQUEST_INSPECTORS`, and the second
inspects campaigns, so that a campaign can read what the first pass
found. Each pass inspects open work before new requests.

Continue to `Scheduler._launch_candidates` and `_choose_next_candidate`.
Inspection happens even at capacity. Launching then fills free slots,
the kinds taking turns in the order assignment, conversation, campaign,
and a kind with no candidate giving up its turn. Within each kind,
existing work precedes new requests. A failed launch takes no slot.

## Creating durable work

Follow `Scheduler._launch` into `create_agent_work` in
[`agent_work.py`](../../src/dreamcatcher/agent_work.py). Creation writes
`work.json` alone, fixing the issue, label, kind, harness and recipe
settings. Later configuration edits do not rewrite those settings.
`AgentWork` reads the session identifier, retry request and ending from
separate files beside that record.

The first assignment round calls `open_assignment_pull_request` in
[`agent_assignments.py`](../../src/dreamcatcher/agent_assignments.py).
It fetches main, prepares the worktree and branch, ensures a commit
beyond main, pushes, and records a draft pull request. Read
`find_or_create_assignment_pull_request` in
[`agent_assignment_pull_requests.py`](../../src/dreamcatcher/agent_assignment_pull_requests.py)
to see how a later attempt adopts the pull request already on that
branch. The work record exists before any of these external steps.

For the directory layout, read `StateDirectory` in
[`state.py`](../../src/dreamcatcher/state.py) and `AgentRoundPaths` in
[`agent_rounds.py`](../../src/dreamcatcher/agent_rounds.py). Work and
worktrees live separately under `.dreamcatcher/v7/`; each work directory
holds numbered round directories.

## Running and resuming a round

Start with `start_agent_round`, then read `AgentRound.__init__`,
`_prepare_and_spawn` and `_finish_round` in
[`agent_rounds.py`](../../src/dreamcatcher/agent_rounds.py). The round
records its start before preparation, saves its input and prompt, and
gives the prompt to the harness through standard input. The preparation
and finishing functions come from the work's kind.

The finishing function runs after a successful harness exit, unless the
round was forcibly ended. A reportable failure in preparation or
finishing makes the round errored. The adapter builds the invocation
before the round is recorded, so a failure there belongs to the
scheduler instead.

For continuity, read `AgentWork.find_harness_session_identifier` in
[`agent_work.py`](../../src/dreamcatcher/agent_work.py). It uses the
recorded identifier or looks for one in raw output. The next round
resumes that session when possible; otherwise it starts a new one with
the saved instructions.

## Feedback and delivery

Read `list_user_posts` in
[`github.py`](../../src/dreamcatcher/github.py), then
`list_user_posts_past_cursor` and `_is_eligible` in
[`relay.py`](../../src/dreamcatcher/relay.py). Comments, reviews and
inline comments are combined. Eligible posts come from the signed-in
account, say something, and contain no `<!-- dreamcatcher -->` marker.
An approval or request for changes can count without a body.

The cursor is the position already delivered. Follow
`read_user_post_cursor` in
[`agent_assignments.py`](../../src/dreamcatcher/agent_assignments.py)
back to `AgentWork.list_relayed_round_paths` in
[`agent_work.py`](../../src/dreamcatcher/agent_work.py). It selects
saved inputs from successful, stopped and running rounds. Errored and
interrupted rounds do not count, so their input can be selected again.
The next input is rebuilt from GitHub, including new posts and omitting
deleted ones.

Read `_compose_relay_round` in
[`scheduler/assignments.py`](../../src/dreamcatcher/scheduler/assignments.py)
to see the selected posts saved with the pull request's state, head
commit and signals. A running round prevents another launch, while later
updates can still observe new posts.

## Signals and stage completion

Read `find_pull_request_signals` in
[`relay.py`](../../src/dreamcatcher/relay.py). An open, non-draft pull
request can raise an out-of-date or check-failure signal. Each is
relayed only at a head commit different from the last head that carried
that signal.

Then read `is_check_failure_withheld` in
[`agent_assignments.py`](../../src/dreamcatcher/agent_assignments.py).
Two consecutive relayed inputs containing a check failure withhold
further check-failure signals. An input without one breaks the sequence.
Other signals can still wake the assignment. This is separate from
fault, which concerns errored rounds.

For completion, read `_inspect_pull_request` and `_compose_relay_round`
in
[`scheduler/assignments.py`](../../src/dreamcatcher/scheduler/assignments.py).
A merged or closed pull request calls for wrap-up if its terminal state
has not already been relayed. A successful wrap-up calls
`complete_assignment` in
[`agent_assignments.py`](../../src/dreamcatcher/agent_assignments.py).
Downstream eligibility checks the blocking issue's state, not this
assignment ending. The next stage can therefore become eligible while
the previous assignment is still wrapping up.

## Conversations, pausing and publication

Read `inspect_open_issue_work` and `find_pause` in
[`scheduler/issue_work.py`](../../src/dreamcatcher/scheduler/issue_work.py),
which conversations and campaigns share. The issue is read first.
Closing it ends the work once no round is running. Removing the work's
label, removing the user as assignee, or adding another configured label
of its kind pauses new rounds; a running round continues. Only work that
is neither paused nor in fault reaches its kind's further inspection.

`inspect_open_conversation` in
[`scheduler/conversations.py`](../../src/dreamcatcher/scheduler/conversations.py)
passes that further inspection: reading the comments past the cursor.
Paused conversations read no comments. Restoring eligibility resumes the
saved conversation with comments past its cursor.

Follow `prepare_conversation_round` in
[`issue_conversations.py`](../../src/dreamcatcher/issue_conversations.py)
into `refresh_detached_worktree` in
[`git.py`](../../src/dreamcatcher/git.py). Every round refreshes to
fetched main, discarding earlier local changes. Its input records the
revision and comments, adding the issue title and body when starting a
new harness session. A new conversation needs an eligible comment; the
label alone does not start it.

Return to `post_conversation_answer` in
[`issue_conversations.py`](../../src/dreamcatcher/issue_conversations.py).
The round publishes its final answer with attribution and the agent
marker. `NO_REPLY` publishes nothing. A missing answer or failed post
errors the round, leaving its comments eligible again.

## The campaign so far

Read `Scheduler.tick` and `_observe_assignments` in
[`scheduler/tick.py`](../../src/dreamcatcher/scheduler/tick.py). After
the first pass, the tick keeps every piece of work it read at the start
of the update, ended assignments included, and the first pass's
assignment inspections. `_observe_assignments` turns them into
`AssignmentObservations`: the newest assignment at each issue, this
update's inspection of the open assignment or of the assignment request
at each issue, and the first failed listing under an assignment label,
if any.

Then read `inspect_open_campaign`, `inspect_campaign_request`,
`_observe_children`, `_observe_child`, `_observe_child_assignment`,
`_inspect_lead_input` and `_compose_campaign_round` in
[`scheduler/campaigns.py`](../../src/dreamcatcher/scheduler/campaigns.py).
Both inspectors observe the sub-issues first, through `list_sub_issues`
in [`github.py`](../../src/dreamcatcher/github.py), and only then hand
the open campaign to `inspect_open_issue_work` in
[`scheduler/issue_work.py`](../../src/dreamcatcher/scheduler/issue_work.py).
That shared path is unchanged: a paused campaign still returns its pause
before any further inspection, and `_record_children` adds the observed
sub-issues to whatever row comes back, so the overview stays current
while the lead is paused or in fault.

A sub-issue is settled when its newest assignment has no round running
and the first pass made no round due for it, where a startable
assignment request counts as a round due. `_observe_child_assignment`
records the assignment's identifier, its pull request number, the newest
round that took its turn, its ending and whether it is in fault. It
copies the observed pull request from the first pass's
`PullRequestFinding`, and no sub-issue's pull request is read again. An
assignment that has ended or is in fault keeps its pull request number
with no observation.

The observation fails, and holds no partial picture, when the sub-issue
read fails, when the first pass could not read a sub-issue's assignment
or assignment request, or when a listing under an assignment label
failed and a sub-issue has no open assignment. `_inspect_lead_input`
then records the failure as the row's finding, reads no comments and
starts no round. Otherwise it reads the newest delivered input once, and
the parent's eligible comments past that input's cursor through
`list_new_comments`, which conversations share. It then compares the
observed sub-issues with the input's through `compare_campaign_children`
in [`campaigns.py`](../../src/dreamcatcher/campaigns.py). A round is due
for a new comment, for a notification, for a campaign with no round yet,
and after a round that errored or was interrupted. A stopped round took
its turn, so the lead then waits for new input. The row's
`CampaignFinding` in
[`scheduler/models.py`](../../src/dreamcatcher/scheduler/models.py)
records the counts of new comments and of changed sub-issues, and
`RequestRow.children` the observed sub-issues.

Read the models in
[`campaigns.py`](../../src/dreamcatcher/campaigns.py): `CampaignChild`
and `CampaignChildAssignment` form the snapshot, which the row and the
round input share. The observed pull request is `ObservedPullRequest` in
[`agent_assignments.py`](../../src/dreamcatcher/agent_assignments.py),
which `PullRequestFinding` extends, so the campaign module imports no
scheduler type. Then read `prepare_campaign_round` and
`read_delivered_campaign_input`. Preparation refreshes the detached
worktree, as a conversation round does, and freezes a
`CampaignRoundInput` holding the parent issue, the sub-issues, the
notifications, the comments, the cursor, the revision and the running
daemon's assignment routes. The cursor reaches the newest comment, or
carries forward the cursor of the newest delivered input, which
`AgentWork.list_relayed_round_paths` selects. Recovery therefore
recomputes the comments, the sub-issues and the notifications from
GitHub against the last delivered input. `compose_campaign_input_prompt`
in [`prompts.py`](../../src/dreamcatcher/prompts.py) names that input
and the limits on the lead. The round plan has no finishing step, so the
lead's final output stays in the feed.

`compare_campaign_children` is a pure function of the newest delivered
sub-issues and the current ones. It returns a
`CampaignChildNotification` naming each sub-issue's
`CampaignChildChange` values: a sub-issue added or removed at once, and
every other change once the sub-issue is settled.
`_list_assignment_changes` compares an assignment with the one of the
same identifier, so a replacement shares nothing with the assignment
that it replaced, and `_list_pull_request_changes` compares the observed
pull requests. Nothing keeps a notification between updates.

## Fault, retry, stop and cancel

Read `derive_agent_work_fault`, `read_scheduler_record` and
`start_cooldown_if_required` in
[`scheduler/faults.py`](../../src/dreamcatcher/scheduler/faults.py). The
latest two endings must both be errors at or after the later of the
retry timestamp and the last cooldown's end. Two counted faults start a
15-minute shared cooldown. Expiry advances that boundary. The faults of
paused conversations and campaigns do not count towards a new cooldown.

`request_agent_work_retry` in
[`agent_work.py`](../../src/dreamcatcher/agent_work.py) records a
timestamp; it does not launch a process or erase history. Read
`_retry_agent_work` in [`cli.py`](../../src/dreamcatcher/cli.py) for the
command that retries the newest faulted work of every kind at an issue.
`_request_work_retry` in
[`web/app.py`](../../src/dreamcatcher/web/app.py) targets one work item
and checks that the submitted round is still the faulted one.

`request_agent_round_stop` and `AgentRound._watch_for_stop_request` in
[`agent_rounds.py`](../../src/dreamcatcher/agent_rounds.py) stop a round
while leaving its work open. `cancel_assignment` in
[`agent_assignments.py`](../../src/dreamcatcher/agent_assignments.py)
records an ending before requesting a stop, leaving the branch and pull
request for the user. `Scheduler._launch` rechecks the ending after
starting a round to cover a concurrent cancellation.

## Instructions and harness permissions

Read `compose_round_prompt` and the conversation and campaign input
prompts in [`prompts.py`](../../src/dreamcatcher/prompts.py), alongside
the [agent-facing contract](../../docs/contract.md). The prompt directs
an agent to its saved input and explains an earlier stopped or
unfinished round. Every round ends with the instruction to mark its
GitHub posts, which `compose_round_prompt` chooses by the work's kind.
An assignment or a conversation marks every post. A campaign's lead
marks every post except its feedback on a sub-issue's pull request,
which `_CAMPAIGN_POST_INSTRUCTIONS` asks it to leave unmarked so that
the assignment relay gives it to the stage's agent as a user post.
Conversation instructions allow investigation and requested issue
changes, but forbid implementation, Git mutations, pull-request changes
and direct publication of the conversation reply.

Continue to `_CLAUDE_PERMISSION_ARGUMENTS` in
[`claude.py`](../../src/dreamcatcher/claude.py) and the first/resumed
round builders in `_CodexHarnessAdapter` in
[`codex.py`](../../src/dreamcatcher/codex.py). They choose permissions
by work kind. Claude receives tool allow/deny settings, and a campaign's
let the lead comment, review, merge, edit issues, fetch and check out
commits, while denying editing and other Git mutations. Claude approves
a shell call by those rules only when every command in it matches one,
and otherwise its auto mode classifier judges the call, refusing a merge
that no person approved. The campaign input prompt therefore asks the
lead to run each `gh pr merge` as a command of its own. Codex receives
sandbox and approval settings; a campaign round takes an assignment's
reviewed settings, so under Codex the prompt alone keeps the lead from
implementing. These are the arguments this code supplies, rather than
guarantees about every external harness version.

## The lead skill

Read the `dream:lead` skill in
[`plugins/dream/skills/lead/SKILL.md`](https://github.com/alimanfoo/dream/blob/main/plugins/dream/skills/lead/SKILL.md)
in the dream repository. Then read the `[[campaign]]` route in
[`default_config.toml`](../../src/dreamcatcher/default_config.toml),
labelled `dream:lead`, whose recipes invoke it as
`/dream:lead GH{issue}` and `$dream:lead GH{issue}`, with the models and
efforts of the `dream:smith` route. `init` writes that route and creates
its label, and the repository's own
[`dreamcatcher.toml`](../../dreamcatcher.toml) carries the same route.
The skill owns the lead's judgment: it takes up each sub-issue by where
its work stands, starts the stages on a route that it chooses, reviews
and proves each settled pull request, prepares the later stages before a
merge releases them, and asks the user on the parent before any change
to the plan. The daemon supplies the input and the marker rule around
it, so the skill repeats neither.

## Status, cards and refreshes

Start with `read_status_report` in
[`status/report.py`](../../src/dreamcatcher/status/report.py), then
`AgentWorkStatusReader.derive` in
[`status/agent_work.py`](../../src/dreamcatcher/status/agent_work.py).
The report reads local work, rounds and the latest scheduler record. The
scheduler never consumes the report. `_did_tick_read_ending` uses the
row's round number to tell whether the update saw the latest ending. A
round can finish while its displayed status awaits another update.
`AgentWorkStatus.children` and `children_summary` give an active
campaign the sub-issues that its latest row holds, and the words that
count the closed ones out of the total, or "sub-issues unknown" when the
row holds none. An ended campaign has neither. Then read
`DreamcatcherStatusReport.list_campaign_child_statuses`. It pairs each
sub-issue with a `CampaignChildStatus`: the status of the assignment
that the update matched to it, looked up by that assignment's
identifier, and the request statuses at its issue for an assignment that
has no open work. The report does not match sub-issues to work again; it
reads the match from the row.

Follow `compose_home_view` and `_compose_section` in
[`web/views.py`](../../src/dreamcatcher/web/views.py) into
[`templates/home.html`](../../src/dreamcatcher/templates/home.html).
Each kind, campaigns included, has a tab, with active work cards,
unstarted request rows and collapsed ended work. A conversation's or a
campaign's page uses `issue-work.html`, composed by
`compose_issue_work_view`. `_compose_work_card` gives an active
campaign's card a `WebCampaignChildOverview` through
`_compose_child_overview`: the count, and a `WebCampaignChild` for each
sub-issue holding its assignment's card, composed by the same
`_compose_work_card`, and its request statuses. Every other card has no
overview, an ended campaign's included, so an ended campaign shows only
its own card in the ended list.

`home.html` renders a card with an overview through
[`campaign.html`](../../src/dreamcatcher/templates/partials/campaign.html).
It puts the lead's
[`agent-work-card.html`](../../src/dreamcatcher/templates/partials/agent-work-card.html)
and a `details` block of the sub-issues side by side in one wrapper, so
the lead's card never contains a sub-issue's latest output. Inside the
block, each sub-issue shows its assignment's card and the
`request-row.html` of each of its requests, or a row of its own when it
has neither. The block sets `id_prefix` to the campaign's identifier,
and both partials put that prefix before their HTML identifier, so a
card inside a campaign never shares an identifier with the same card on
its own tab. A request row's identifier also holds its label
percent-encoded, so two distinct labels on one issue never share one.

The home view refreshes every two seconds.
[`static/home.js`](../../src/dreamcatcher/static/home.js) restores the
selected tab after refresh, and keys each card's latest-output animation
by its HTML identifier, so the two appearances of one assignment animate
apart. [`static/base.js`](../../src/dreamcatcher/static/base.js)
prevents refreshes from changing whether a details element is open. The
sub-issues' block always renders, holding only its count while the
sub-issues are unknown or there are none, so the same element stays open
when they are known again. Read
`test_home_tabs_switch_by_pointer_and_keyboard_and_survive_refresh`,
`test_a_refresh_leaves_an_opened_section_open` and the campaign tests in
[`tests/test_browser.py`](../../tests/test_browser.py) for the exercised
behaviour.

## The activity feed

Read `AgentRound._read_stdout` and `_append_feed_events` in
[`agent_rounds.py`](../../src/dreamcatcher/agent_rounds.py), then
`FeedRenderer` in [`feed.py`](../../src/dreamcatcher/feed.py). Raw
harness stdout is saved separately from the readable feed. The feed
timestamps prose and tool notes; tool-note details are flattened and
clipped at 200 characters. It is an activity view, not a lossless tool
transcript.

For the web reader, follow `read_agent_feed` and `read_agent_tail` in
[`web/feed.py`](../../src/dreamcatcher/web/feed.py). They read across
numbered rounds. Their cursor is a round number and file position,
separate from the GitHub cursor that controls input delivery. This is
the existing activity record behind the decision to keep the parent
issue for collaboration rather than routine action logging.

## The sharp edges

- The campaign inspectors read the sub-issues before
  `inspect_open_issue_work` reads the parent, so a paused campaign keeps
  its overview without changing that shared path. The cost is one
  sub-issue read on the update that finds the parent closed or cannot
  read it. A campaign request with conflicting labels reads nothing, so
  its row holds no sub-issues.
- `CampaignFinding` counts both the new parent comments and the changed
  sub-issues, and the campaign trigger in `describe_round_trigger` in
  [`status/rounds.py`](../../src/dreamcatcher/status/rounds.py) names a
  start, a recovery and both counts. A round with no input yet says only
  that comments or changes woke it.
- `_is_eligible` in [`relay.py`](../../src/dreamcatcher/relay.py)
  ignores marked agent posts, including a lead's marked review. A
  campaign's prompt asks the lead to leave the marker off its feedback
  on a sub-issue's pull request alone, so that feedback reaches the
  stage's agent and every other post of the lead's stays out of the
  relay. Both sides matter when tracing how a lead's feedback reaches a
  child.
- `PullRequest.check_result` in
  [`github.py`](../../src/dreamcatcher/github.py) prioritises failure
  over running checks, so a failing aggregate does not establish that
  all checks have finished. `PullRequest.has_running_checks` carries
  that separately, and the check-completion rule compares both.
- `inspect_open_assignment` in
  [`scheduler/assignments.py`](../../src/dreamcatcher/scheduler/assignments.py)
  reads nothing from GitHub while the assignment is in fault. A comment
  cannot itself clear fault. Ended assignments leave the scheduler's
  open-work inspection, including those cancelled for manual takeover,
  so a sub-issue's ended assignment has no observed pull request.
- GitHub can list a sub-issue from another repository. `SubIssue` keeps
  its repository, and `_observe_children` treats one from another
  repository as unobservable before `_observe_child` matches the rest to
  local work by number, so a campaign with such a sub-issue waits with
  its overview unknown. Observing work in another repository is not
  supported.
- An unreadable `pull-request.json` under any sub-issue's newest
  assignment, ended ones included, fails the whole update, as the story
  of a local record that cannot be read promises.
- `list_user_posts_past_cursor` and `list_issue_comments_past_cursor` in
  [`relay.py`](../../src/dreamcatcher/relay.py) use different cursor
  precision. Pull-request posts compare timestamps alone; issue comments
  compare timestamp and identifier.
- A sub-issue's card on the Campaigns tab is composed from the same
  status as its card on the Assignments tab, but the overview follows
  the latest update's match, while the Assignments tab reads local work
  directly. An update observes the sub-issues before it launches
  anything, so an assignment that it starts appears on the Assignments
  tab at once, and under its sub-issue only after the next update.
