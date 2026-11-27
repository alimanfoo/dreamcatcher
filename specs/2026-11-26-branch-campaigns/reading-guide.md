# Reading guide: campaigns on a branch of their own

This guide is for whoever designs the change in
[requirements.md](requirements.md): every campaign runs on a branch of
its own, with one pull request into main that is the lead's channel, and
behaves like an assignment wherever that makes sense. It says what to
read and in what order. It follows the code as the roadmap's stages
land.

## The big picture

Everything _dreamcatcher_ decides happens in one scheduler tick,
`Scheduler.tick` in `src/dreamcatcher/scheduler/tick.py`. A tick reads
every piece of agent work from disk, lists the open issues assigned to
the user, and inspects in two passes: assignments and conversations
first, campaigns second. Campaigns go second because a campaign sees its
sub-issues through what the first pass found of their assignments
(`_observe_assignments`, which builds an `AssignmentObservations`), so
no sub-issue's pull request is read twice. Each pass inspects open work
first and then the requests that no open work answers. Each inspection
returns a row, which is what the tick found and what the views show, and
perhaps a candidate, which is a round the tick may start. The tick then
fills free agent slots from the candidates.

The tick knows two shapes of channel. An assignment's channel is its
pull request: a first round opens it, and later rounds are woken by the
user's posts, by pull request signals and by the pull request being
merged or closed. Conversations and campaigns share the other shape,
issue work: the issue's state, labels and assignee decide whether the
work has ended or is held, and the user's comments on the issue wake it.

The change moves campaigns from the issue-work shape to the pull-request
shape, while keeping what only a campaign has: the observation of the
parent's sub-issues and the notifications the lead gets when one
changes. Most of the pull-request machinery is written for assignments
but is generic in substance. The places where it isn't are the sharp
edges at the end.

Read in this order: the tick, the two channel shapes, the campaign as it
is, the relay, Git and pull request opening, the GitHub boundary,
permissions and prompts, requests and holds, ending and cancel, then
status. Read `docs/concepts.md` and `docs/architecture.md` first for the
words.

## The tick

Start at `Scheduler.tick` in `scheduler/tick.py`. Its docstring gives
the order. `_inspect` runs a pass with a map of open-work inspectors and
request inspectors by kind: `_OPEN_WORK_INSPECTORS` and
`_REQUEST_INSPECTORS` for the first pass, and a second map built inline
for campaigns, with `observations` bound in. `_inspect_open_work` drops
the candidate of work whose round is running, but keeps its row.
`_inspect_requests_of_kind` turns each dispatch label on a listed issue
into a request row. `_launch_candidates` and `_choose_next_candidate`
fill slots in rotation by kind. `_launch` creates the work of a request
(`create_agent_work`), composes the round's plan, and starts the round.

The shapes that pass between these are in `scheduler/inspection.py`:
`SchedulingContext`, `Inspection`, `Candidate` and `RoundPlan`. A
`RoundPlan` is a preparation that runs inside the round before the
harness and returns its input, an input prompt, and an optional
finishing step. A request inspector is handed only the context, the
issue, the route and the row, not the list of work.

## Two shapes of channel

The assignment shape is `inspect_open_assignment` in
`scheduler/assignments.py`. With no `pull-request.json` in the work's
directory (`read_work_pull_request_number`), the round due is the
opening round, `_compose_opening_round`, whose preparation is
`open_work_pull_request` and which has no input. Once the pull request
exists, `_inspect_pull_request` reads it, reads the user's posts past
the cursor and the pull request signals, and notes a merged or closed
pull request that no round has wrapped up. `_compose_relay_round`
freezes an `AssignmentRoundInput` and, for a wrap-up, sets
`complete_pull_request_work` as the finishing step. Once an assignment
exists, its issue's labels play no part.

The issue-work shape is `inspect_open_issue_work` in
`scheduler/issue_work.py`. It reads the issue. A closed issue ends the
work with "issue closed" once no round is running. `_find_hold` then
holds it when its own label is gone or the issue is unassigned (a
pause), or when another label of its kind is on the issue. Next it
checks who applied the label, and only then calls the kind's
`inspect_eligible`.

## The campaign as it is

Read `scheduler/campaigns.py` and then `campaigns.py`.

`inspect_campaign_request` handles a campaign label with no campaign. It
asks `list_open_blocking_issues` (in `scheduler/blockers.py`) and stops
if anything blocks the parent. It asks no claim question, so a linked
pull request has no bearing. `inspect_open_campaign` sends an open
campaign through `inspect_open_issue_work`. Both call
`_observe_children`, which lists the parent's sub-issues and, through
`_observe_child` and `_observe_child_assignment`, pairs each with its
newest assignment and with the first pass's inspection of it, giving a
`CampaignChild` that is settled or not. The observation fails whole if
any sub-issue can't be observed, including one in another repository.

`_inspect_lead_input` decides whether a lead round is due. It reads the
newest delivered input (`read_delivered_campaign_input`), the parent's
comments past that input's cursor (`list_new_comments`), and
`compare_campaign_children` in `campaigns.py`, which turns differences
between the delivered and current sub-issues into
`CampaignChildNotification`s. A round is due for comments,
notifications, a campaign with no rounds yet, or a last round that did
not finish. `_compose_campaign_round` sets `prepare_campaign_round` as
the preparation, which resets the worktree to main with
`refresh_detached_worktree` and freezes a `CampaignRoundInput`: parent,
children, notifications, comments, cursor, revision and assignment
routes. There is no finishing step, because the lead posts for itself.

The sub-issue observation and the comparison survive the change. The
parent's comments as input, the worktree detached at main, and the issue
rules of `issue_work.py` are what it replaces.

## The relay

Read `relay.py`, then the readers it uses in `pull_request_work.py`.

`list_user_posts_past_cursor` takes any pull request number, gathers
comments, reviews and inline comments through `list_user_posts` in
`github.py`, and keeps the user's that don't carry the agent marker
(`_is_eligible`). Nothing in it knows it serves an assignment.

`find_pull_request_signals` raises out-of-date and check-failure for an
open pull request that is ready for review, once per head commit, and
leaves out a check failure that the relay rule withholds. It reads its
memory from `pull_request_work.py`: `read_signal_relay_head` and
`is_check_failure_withheld` read past rounds as `AssignmentRoundInput`,
and so do the post cursor `read_user_post_cursor` and the wrap-up check
`is_wrap_up_relayed`. All of them go through `_read_relayed_inputs`,
which reads the inputs of rounds that consumed their input or are
running, newest first, via `AgentWork.list_relayed_round_paths` in
`agent_work.py`.

## Git and opening a pull request

Read `git.py`, then `open_work_pull_request` in `pull_request_work.py`.

The candidate can carry a base branch into the work record through
`Scheduler._launch`. `open_work_pull_request` first looks for a pull
request on the assignment's branch, named by `compose_work_branch`. If
it finds none, `_publish_work_branch` uses `fetch_base_branch` to fetch
the recorded base or the default. It adds the worktree from the base
ref, makes a placeholder commit if `has_commits_since_base` finds
nothing past the base, and pushes with `push_branch`.
`create_pull_request` opens the draft into the same base and writes
"Closes #N" as the body. `refresh_detached_worktree` continues to reset
detached worktrees to `origin/HEAD`. The pull request's number goes into
`pull-request.json`. A retry adopts the existing pull request even if
the base is gone. When there is no pull request, it reuses any worktree
or placeholder commit that the previous attempt left.

## The GitHub boundary

Read `github.py` for what exists. It reads issues, sub-issues
(`list_sub_issues`, from parent to children only), blockers, labelling
events, pull requests (`read_pull_request`: state, draft flag, merge
state, head, checks), the pull requests on a branch, the user's posts on
a pull request, and issue comments. It creates labels and draft pull
requests, posts issue comments, and closes an issue as completed.

It has no read from an issue to its parent. Claims come from
`read_issue_pull_request_context`, which reads GitHub's
`closedByPullRequestsReferences` and keeps the open ones; that list also
holds pull requests that someone linked by hand. GitHub's documentation
says it acts on a closing keyword only in a pull request into the
default branch. On that account, which the code cannot show, a
campaign's pull request into main would claim its parent, and a
sub-issue's pull request into the campaign branch would claim nothing.

`PullRequestMergeState.is_out_of_date` counts `BEHIND` and `DIRTY`, and
`is_mergeable` counts `CLEAN`, `HAS_HOOKS` and `UNSTABLE`.

## Permissions and prompts

In `claude.py`, a lead's permissions are
`_CLAUDE_CAMPAIGN_ALLOWED_TOOLS` and
`_CLAUDE_CAMPAIGN_DISALLOWED_TOOLS`, chosen by kind in
`_CLAUDE_PERMISSION_ARGUMENTS`. The lead may create, edit and comment on
issues, comment on, review, merge and check pull requests, use `gh api`,
and fetch, check out and switch, and is denied editing, committing and
pushing. Every Claude round runs under `--permission-mode auto`
(`_build_base_arguments`). `gh pr ready` is on the assignment list
(`_CLAUDE_ASSIGNMENT_ALLOWED_TOOLS`) but not the campaign list. In
`codex.py`, `build_new_session_round` and `build_resumed_round` give a
campaign exactly an assignment's settings, `--approve-for-me` or
`_REVIEWED_RESUME_PERMISSION_SETTINGS`; only a conversation gets
`_CONVERSATION_PERMISSION_SETTINGS`. `_CAMPAIGN_INPUT_PROMPT` tells the
lead not to commit, push or open a pull request.

In `prompts.py`, `_CAMPAIGN_INPUT_PROMPT` describes the parent's
comments, the worktree refreshed to the default branch, and that
removing the parent's label or assignee pauses the campaign.
`_CAMPAIGN_POST_INSTRUCTIONS` tells the lead to leave the marker off
feedback on a sub-issue's pull request. `_ASSIGNMENT_INPUT_PROMPT` is
where an assignment learns that its pull request was merged or closed.
The signal lines `_OUT_OF_DATE_LINE` and `_CHECK_FAILURE_LINE`, chosen
through `_SIGNAL_LINES` by `compose_assignment_input_prompt`, tell the
agent to merge the base branch in and push, or fix the cause and push.
`compose_round_prompt` picks the post instructions by kind.

## Requests, answering and holds

`_inspect_requests_of_kind` in `tick.py` skips a label that open work
answers, through `AgentWork.answers_request` in `agent_work.py`. An open
assignment answers every assignment label on its issue; a conversation
or campaign answers only its own label. A request with two labels of one
kind gets a `ConflictingLabelsFinding`, and one whose label someone else
applied gets a `LabelAppliedByOtherFinding` from
`find_label_applied_by_other` in `scheduler/labelling.py`. Only then
does the kind's request inspector run. For an assignment that is
`inspect_assignment_request`, whose `_ask_start_time_questions` asks
about claiming pull requests and blockers.

The findings are in `scheduler/models.py`. `HoldFinding` is the union of
`PausedFinding`, `LabelAppliedByOtherFinding` and
`ConflictingLabelsFinding`. `StartTimeFinding` and
`BlockingIssuesFinding` hold claims and blockers. `RequestFinding` is
the union of every finding a row can hold. In status, `describe_request`
in `status/requests.py` turns a hold into "held" with a fact and advice
from `describe_hold` in `status/findings.py`, and turns claims and
blockers into "linked to" and "blocked by" in `_list_holding_facts`.

## Ending, cleanup and cancel

`end_agent_work` in `agent_work.py` writes `ended.json` only if there is
no ending yet, so the first ending wins. `AgentWorkEndReason` is
completed, cancelled or issue closed. An assignment ends completed in
its wrap-up round's finishing step, `complete_pull_request_work`. Before
that, `prepare_assignment_round_input` closes the issue of an assignment
merged into another base branch, then builds the input. A campaign ends
"issue closed" in `inspect_open_issue_work` when a tick finds the parent
closed and no round running, with no wrap-up round.

`Scheduler._remove_ended_worktrees` in `tick.py` removes the worktree of
work that a tick sees end, through `_remove_worktree_and_branch`: an
assignment's worktree and local branch with
`remove_work_worktree_and_branch`, and any other work's worktree with
`remove_agent_work_worktree`. Cancelled work is skipped.

`cancel_pull_request_work` in `pull_request_work.py` records "cancelled"
and asks a running round to stop, and nothing in it is specific to
assignments. `_cancel_assignment` in `cli.py` and `_can_cancel` in
`web/app.py` each refuse work that isn't an assignment.

## Status and the home page

`AgentWorkStatus` in `status/agent_work.py` reads the pull request
number through `read_work_pull_request_number`, which reads
`pull-request.json` from the work's directory whatever the kind.
`pull_request_summary` uses the tick's `PullRequestFinding` when the row
has one, and otherwise the merged or closed state of the newest relayed
input, read as `AssignmentRoundInput` by
`read_relayed_pull_request_state`. `issue_state` is none for an
assignment. `children` and `closed_children_summary` come from the row
for an active campaign.

`AgentWorkStatusReader.derive` runs working, ended, fault, unknown,
held, awaiting update and waiting, then idle. `_derive_waiting` says "no
pull request yet" for an assignment alone. `_derive_idle` picks its
words by finding type: `describe_idle_pull_request` for a
`PullRequestFinding`, and the round's ending for a `CampaignFinding`.
`_describe_what_is_new` does the same for waiting.

The web card is built in `_compose_work_card` in `web/views.py`, and
`templates/partials/work-card.html` draws the pull request chip and the
issue state side by side, each only when present. In the terminal,
`_describe_github_state` in `tui/status.py` prefers the pull request,
and `_render_agent_work` in `tui/views.py` chooses an assignment or
issue-work summary by kind. A sub-issue's card under a campaign comes
from `list_campaign_child_statuses` in `status/report.py`, which takes
the assignment and the assignment request statuses at the sub-issue's
issue. Round triggers are read back from inputs in `status/rounds.py`:
`_describe_assignment_round_trigger` and
`_describe_campaign_round_trigger`.

## The work record and the state format

`AgentWorkRecord` in `agent_work.py` is written once at creation. It
holds the base branch when the request chooses a branch other than the
default. The assignment's own branch is derived from its identifier.
Facts that change later each have a file beside the record.
`STATE_FORMAT_VERSION` in `state.py` is 9.

## Tests to read

`tests/test_campaign_scheduling.py`, `tests/test_campaigns.py`,
`tests/test_campaign_status.py`, `tests/test_assignment_scheduling.py`,
`tests/test_assignment_requests.py`, `tests/test_pull_request_work.py`,
`tests/test_relay.py` and `tests/test_git.py` cover the code above.

## The sharp edges

- **The relay's memory is in the assignment's input shape.** The post
  cursor, the head at which each signal was relayed, the relay rule and
  the wrap-up check all read past rounds as `AssignmentRoundInput`, and
  `read_delivered_campaign_input` reads them as `CampaignRoundInput`.
  Both models refuse fields they don't declare (`DreamcatcherDocument`
  in `documents.py` forbids extras). So a campaign that reuses these
  readers needs more than extra fields in its input: the model each
  reader parses with has to change too.
- **The two-attempt rule would not hold for a lead.**
  `is_check_failure_withheld` withholds when the last two relayed inputs
  both carried a check failure. A lead's rounds between fixes, such as
  those woken by notifications, reset the count.
- **"Closes #N" is inert off the default branch.** By GitHub's
  documentation, a sub-issue's pull request into the campaign branch
  neither closes nor claims its issue. Wrap-up preparation explicitly
  closes its issue after the merge.
- **No read from a sub-issue to its parent.** The sub-issue rule needs
  one, or an inversion of the parent-to-children lists.
- **Pass order.** Assignment requests are inspected before campaigns,
  and a request inspector is not handed the list of work, so the
  sub-issue rule's question about the parent's open campaign pull
  request has no answer at that point today.
- **A closed parent ends a campaign at once.** Under
  `inspect_open_issue_work`, the parent closing when the campaign's pull
  request merges would end the campaign before any wrap-up round.
- **The signal lines tell the agent to push.** They are shared, and
  would tell a lead to do what it must not.
- **Permissions.** `gh pr ready` is not on Claude's campaign list, so no
  allow rule approves a lead marking its pull request ready, and Claude
  Code's auto mode decides it. `gh pr merge:*` matches the campaign's
  own pull request into main. On Codex a campaign has an assignment's
  settings; whether Codex's reviewer would stop a lead's commit is
  Codex's behaviour, which the code does not show. The prompt forbids
  committing, pushing and opening a pull request, but not editing files.
- **Cancel is gated twice.** `cli.py` and `web/app.py` each refuse
  non-assignments.
- **Cleanup knows only assignments have branches.**
  `_remove_worktree_and_branch` deletes a local branch for an assignment
  alone.
- **Status words are chosen by finding type.** A campaign with both a
  pull request and sub-issues fits neither `PullRequestFinding` nor
  `CampaignFinding` cleanly.
- **Unverified GitHub behaviour.** Whether a pull request awaiting a
  required review reports `BLOCKED` in place of `BEHIND` or `DIRTY` is
  not settled by the code. If it does, `is_out_of_date` would not fire
  for the campaign's pull request until it is approved.
