# Reading guide for campaigns on a branch of their own

The [requirements](requirements.md) and [design](design.md) explain the
goal and the whole change. This guide follows the code as the
[roadmap](roadmap.md) lands. The scheduler, work records and round
inputs described here reflect stage 5.

## The tick

Start with `Scheduler.tick` in `src/dreamcatcher/scheduler/tick.py`. It
reads the saved work and takes one listing of open issues assigned to
the user. The first pass inspects assignments and conversations. The
second inspects campaigns and reuses the first pass's
`AssignmentObservations` for their sub-issues. Each pass inspects open
work before requests. The tick then cleans up ended work and fills free
slots from the candidates.

`scheduler/inspection.py` defines the results each inspector returns.
`Inspection` carries a request row and an optional `Candidate`. A
candidate composes a `RoundPlan` when the scheduler selects it. A plan
supplies a preparation, an input prompt and an optional finisher.

## Two shapes of channel

Read `scheduler/pull_requests.py`. `read_pull_request_activity` reads
the current pull request and the user posts past the cursor, and asks
the relay for signals and wrap-up memory. `PullRequestActivity` says
when the shared triggers make a round due and prepares the shared input
and wrap-up finisher. `scheduler/assignments.py` supplies the assignment
opening plan and prompt.

`scheduler/campaigns.py` uses that activity for a campaign that has
opened its pull request. `_observe_children` pairs the parent's
sub-issues with the first pass's results. When a required read fails
there is no partial picture. `compare_campaign_children` in
`campaigns.py` compares that picture with the newest delivered input. A
notification can wake the lead independently of pull request activity.
Open campaigns keep their sub-issue observations while in fault.

`scheduler/issue_work.py` handles conversations. It reads the issue and
applies the label and assignee rules before the conversation inspector
reads comments. The issue's closure ends the conversation once no round
is running.

## Git and round input

Read `open_work_pull_request` in `pull_request_work.py`. It adopts a
pull request left by an earlier attempt, or cuts a worktree from the
recorded base, adds a placeholder commit if needed, pushes and opens a
draft with a closing keyword. An empty base selects the default branch.
The pull request number is written to `pull-request.json`.

An assignment opening round supplies its prompt. A campaign opening
round also supplies the new pull request number and the worktree head.
When an earlier attempt already opened the pull request, the campaign's
opening preparation relays GitHub's current state, head and posts, and a
terminal state completes through the shared wrap-up finisher. The
campaign worktree stays on its branch across rounds.
`CampaignRoundInput` extends `PullRequestRoundInput` with the observed
sub-issues, their notifications and the daemon's assignment routes.

Read `relay.py` for post eligibility and relay memory. The readers
validate the recorded input for the work's kind, then use the shared
fields for the post cursor, signal history and whether wrap-up was
relayed. `AgentWork.list_relayed_round_paths` selects the inputs from
rounds that consumed their input or are running.

## Requests and holds

`AgentWork.answers_request` lets open pull request work answer every
label of its kind at its issue. The tick checks the remaining requests
for label conflicts, label ownership and consumption. A clear assignment
or campaign request then goes through `ask_start_time_questions` in
`scheduler/pull_requests.py`, which reads claims and blockers.

The assignment inspector uses the direct parent and the newest saved
campaign to choose the base. All sub-issues of a parent share that
decision in the assignment pass. The campaign pass uses the same pull
request observation when it inspects the campaign's channel.

`github.py` projects GitHub's responses. Claims come from
`closedByPullRequestsReferences` and are limited to open pull requests.
The direct parent's absence requires an explicit null response.
`close_issue_as_completed` posts a marked comment before closing an
issue and can reuse that comment after a failed close.

## Ending and status

A merged or closed pull request calls for a wrap-up round. The shared
preparation closes the issue first on a merge into a recorded alternate
base. The shared finisher records completion after a successful harness
exit. `Scheduler._remove_ended_worktrees` removes the worktree and local
branch of ended pull request work and leaves cancelled work for the
user. The command and web cancel controls still accept assignments at
stage 5.

`PullRequestFinding` in `scheduler/models.py` carries the shared channel
observation and the count of campaign notifications.
`status/agent_work.py` derives the pull request summary and any reason
to wait, and `status/rounds.py` derives the round triggers from the
input, including links to sub-issues. The home page uses the shared pull
request chip beside each work title. Conversation cards show their issue
state.

## Later stages

Stage 6 updates the lead's input prompt, Claude permissions and campaign
skill contract. Stage 7 makes the prompt and the lead's behaviour follow
the pull request's draft flag. Stage 8 exposes campaign cancellation,
and stage 9 updates the guides. The check-failure relay currently counts
consecutive relayed inputs, so a round between fixes that relays no
check-failure resets the count.

## Tests to read

Start with the stand-in walkthrough and channel tests in
`tests/test_campaign_scheduling.py`. For the inputs and their display,
read `tests/test_campaigns.py`, `tests/test_relay.py` and
`tests/test_campaign_status.py`. For the shared Git and GitHub
operations, see `tests/test_assignment_requests.py`,
`tests/test_pull_request_work.py` and `tests/test_git.py`.
