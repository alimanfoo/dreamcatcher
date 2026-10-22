# Reading guide for campaigns

## The big picture

This guide follows the code behind the
[campaign requirements](requirements.md) as stage 2 leaves it. Read the
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
or a campaign answers only its own label. The tick looks up each kind's
inspectors in `_OPEN_WORK_INSPECTORS` and `_REQUEST_INSPECTORS`.

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

Read `inspect_open_campaign`, `inspect_campaign_request`,
`_inspect_lead_input` and `_compose_campaign_round` in
[`scheduler/campaigns.py`](../../src/dreamcatcher/scheduler/campaigns.py).
A campaign label on an open, assigned parent starts a campaign without a
comment. Both inspectors read the parent's eligible comments past the
cursor through `list_new_comments` in
[`scheduler/issue_work.py`](../../src/dreamcatcher/scheduler/issue_work.py),
which conversations share. A round is due for a new comment, for a
campaign with no round yet, and after a round that errored or was
interrupted. A stopped round took its turn, so the lead then waits for a
new comment. The row's `CampaignFinding` in
[`scheduler/models.py`](../../src/dreamcatcher/scheduler/models.py)
records the count of new comments, which status reads.

Then read `prepare_campaign_round` and `read_parent_comment_cursor` in
[`campaigns.py`](../../src/dreamcatcher/campaigns.py). Preparation
refreshes the detached worktree, as a conversation round does, and
freezes a `CampaignRoundInput` holding the parent issue, the comments
and the revision. The cursor is the newest comment among the delivered
inputs, which `AgentWork.list_relayed_round_paths` selects, as an
assignment's is the newest post among its relayed inputs. Recovery
therefore recomputes the comments from GitHub against the delivered
inputs. `compose_campaign_input_prompt` in
[`prompts.py`](../../src/dreamcatcher/prompts.py) names that input and
the limits on the lead. The round plan has no finishing step, so the
lead's final output stays in the feed.

Stage 2 stops there. The input holds no child snapshot, notifications or
routes, and nothing compares inputs, so child changes wake no lead
round. Later stages add those through the same inspector and input.

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
unfinished round. Every round receives the instruction to mark every
GitHub post. Conversation instructions allow investigation and requested
issue changes, but forbid implementation, Git mutations, pull-request
changes and direct publication of the conversation reply.

Continue to `_CLAUDE_PERMISSION_ARGUMENTS` in
[`claude.py`](../../src/dreamcatcher/claude.py) and the first/resumed
round builders in `_CodexHarnessAdapter` in
[`codex.py`](../../src/dreamcatcher/codex.py). They choose permissions
by work kind. Claude receives tool allow/deny settings, and a campaign's
let the lead comment, review, merge, edit issues, fetch and check out
commits, while denying editing and other Git mutations. Codex receives
sandbox and approval settings; a campaign round takes an assignment's
reviewed settings, so under Codex the prompt alone keeps the lead from
implementing. These are the arguments this code supplies, rather than
guarantees about every external harness version.

## Status, cards and refreshes

Start with `read_status_report` in
[`status/report.py`](../../src/dreamcatcher/status/report.py), then
`AgentWorkStatusReader.derive` in
[`status/agent_work.py`](../../src/dreamcatcher/status/agent_work.py).
The report reads local work, rounds and the latest scheduler record. The
scheduler never consumes the report. `_did_tick_read_ending` uses the
row's round number to tell whether the update saw the latest ending. A
round can finish while its displayed status awaits another update.

Follow `compose_home_view` and `_compose_section` in
[`web/views.py`](../../src/dreamcatcher/web/views.py) into
[`templates/home.html`](../../src/dreamcatcher/templates/home.html).
Each kind, campaigns included, has a tab, with active work cards,
unstarted request rows and collapsed ended work. A conversation's or a
campaign's page uses
[`issue-work.html`](../../src/dreamcatcher/templates/issue-work.html),
composed by `compose_issue_work_view`. The
[`agent-work-card.html`](../../src/dreamcatcher/templates/partials/agent-work-card.html)
template needs saved work; an unstarted issue instead uses
[`request-row.html`](../../src/dreamcatcher/templates/partials/request-row.html)
and has no work page yet. A view of every campaign child must account
for that distinction.

The home view refreshes every two seconds.
[`static/home.js`](../../src/dreamcatcher/static/home.js) restores the
selected tab after refresh, and
[`static/base.js`](../../src/dreamcatcher/static/base.js) prevents
refreshes from changing whether a details element is open. Read
`test_home_tabs_switch_by_pointer_and_keyboard_and_survive_refresh` and
`test_a_refresh_leaves_an_opened_section_open` in
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

- `inspect_open_issue_work` in
  [`scheduler/issue_work.py`](../../src/dreamcatcher/scheduler/issue_work.py)
  returns a paused finding before any further inspection. A paused
  conversation needs nothing more, but stage 3's paused campaign still
  needs its child picture, so that shared path must change for it.
- `CampaignFinding.new_comments` and the campaign trigger in
  `describe_round_trigger` in
  [`status/rounds.py`](../../src/dreamcatcher/status/rounds.py) describe
  parent comments, a start and a recovery. Child changes need their own
  finding fields and trigger words.
- `_is_eligible` in [`relay.py`](../../src/dreamcatcher/relay.py)
  ignores marked agent posts, including a lead's marked review. The
  current prompts require that marker everywhere. Both sides matter when
  tracing how a lead's feedback could reach a child.
- `PullRequest.check_result` in
  [`github.py`](../../src/dreamcatcher/github.py) prioritises failure
  over running checks. A failing aggregate does not establish that all
  checks have finished. The boundary reads blockers, but has no
  operation for listing a parent's sub-issues.
- `inspect_open_assignment` in
  [`scheduler/assignments.py`](../../src/dreamcatcher/scheduler/assignments.py)
  reads nothing from GitHub while the assignment is in fault. A comment
  cannot itself clear fault. Ended assignments also leave the
  scheduler's open-work inspection, including those cancelled for manual
  takeover.
- `list_user_posts_past_cursor` and `list_issue_comments_past_cursor` in
  [`relay.py`](../../src/dreamcatcher/relay.py) use different cursor
  precision. Pull-request posts compare timestamps alone; issue comments
  compare timestamp and identifier.
- The
  [`agent-work-card.html`](../../src/dreamcatcher/templates/partials/agent-work-card.html)
  template uses the work identifier as its HTML identifier. Rendering
  the same card in both its normal tab and an expanded campaign would
  duplicate that identifier. `latestOutputsByWork` in
  [`static/home.js`](../../src/dreamcatcher/static/home.js) also keys
  activity updates by that identifier.
