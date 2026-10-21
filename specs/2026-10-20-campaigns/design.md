# Design for campaigns

## What we're building

A campaign commissions a lead to carry a parent issue's sub-issues
through their ordinary assignments. The lead uses `dream:lead` to
review, coordinate and merge through GitHub. The daemon decides when the
lead has something to consider. The user alone closes the parent issue.

This design follows the [requirements](requirements.md) and the code in
the [reading guide](reading-guide.md). It adds a third kind of agent
work while retaining the shared work records, round runner, capacity and
recovery rules.

## How it works

### One campaign through the system

The user assigns the parent issue to themselves and applies a campaign
label. At an update, the daemon discovers the request and reads its
children. The campaign needs no comment to start. When a slot is
available, it records the work, prepares a detached worktree from main,
saves the initial input, and starts the lead.

The lead reads the plan on GitHub. It labels and assigns open children
where needed, preserving labels the user already chose. It chooses among
the daemon's configured assignment routes and asks on the parent when
the choice or the plan is unclear. The dependency chain controls which
assignment starts. Starting an assignment does not wake the lead.

A child finishes its turn. At the next update, the ordinary assignment
inspection establishes whether another round is due. When none is
running or due, the campaign compares the child's current facts with the
snapshot in the previous delivered lead input. A relevant difference
makes a lead round due. If capacity is unavailable, a later update
repeats the comparison.

The lead's next input gives the whole current picture and highlights why
it was woken. The lead reads the pull request, runs the stage's proof,
and posts feedback or merges when satisfied. Feedback uses the existing
assignment relay. A merge closes the child issue, allowing the next
stage to start. The previous assignment can still be taking its wrap-up
round.

The user may intervene, pause the lead, add children or end the
campaign. These actions leave child assignments governed by their
ordinary rules.

### Work, routes and lifetime

Add `campaign` to `AgentWorkKind` and a campaign route list to the
configuration. Label identities remain unique across all kinds. The
default `dream:lead` route supplies recipes for both harnesses, using
the same capable defaults as the existing general assignment route.

Reuse `AgentWorkRecord`, its identifier convention, the saved harness
session, round directories, retry request and ending. No campaign branch
or pull request is created. Its channel is the parent issue.

Use the conversation's label-based identity and lifetime rules. A
campaign belongs to its starting label; removing that label or the
user's assignment pauses new rounds. Another configured campaign label
on the issue is a routing conflict. A running round finishes. Restoring
eligibility resumes the same campaign and session. Changing to another
label follows the existing conversation convention of retaining the old
work paused and starting new work under the new label.

Parent closure ends the campaign once no round is running, before
considering fault or further input. No wrap-up round is required merely
to record that ending. A reopened parent can receive a new campaign.
Only the user closes the parent; waiting for a decision does not remove
the campaign label.

### Observing the children

Add a paginated GitHub read for
`repos/{repository}/issues/{parent}/sub_issues`. It returns the direct
children with their issue numbers, titles, states, labels and assignees.
Normalise the REST fields through the GitHub projection boundary. The
GitHub relationship is authoritative; no separate campaign ownership
file is introduced.

Keep the work already read at the start of an update available for
lookup, including ended assignments. Match each child to its newest
local assignment by issue number. Retain ordinary assignment inspections
and new-request findings for that same update. An ended assignment
remains visible as ended, rather than appearing to have vanished.

The snapshot contains presentation context and the small set of facts
used for notification. Comparison matches children by issue number, so
incidental list order is not a change.

| Fact                                                                                        | Purpose                                                                                                      |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| The child issue's number, title and state identify it and describe its progress.            | Membership and issue-state changes can require coordination.                                                 |
| The latest assignment identifier and pull-request reference locate its work.                | Replacement assignments remain distinguishable when round numbering restarts.                                |
| The last round that took its turn identifies its latest handback.                           | Successful and stopped rounds count; errored and interrupted rounds do not.                                  |
| Whether the child is settled records whether it has a round running or due.                 | A transition to settled remains visible even if the lead received an intervening snapshot while it was busy. |
| The pull request's state, draft flag and observed head describe the reviewed work.          | Changes can require review or a different response to the stage.                                             |
| The check result and whether any checks are still running describe the checks at that head. | A failing aggregate alone cannot show when the final check finishes.                                         |
| The assignment's ending and fault describe termination or a need for intervention.          | These are local facts and remain available when no pull-request inspection runs.                             |

A startable assignment request counts as work due even before the work
record exists. An ended assignment has no new round due, though a
running round still counts while cancellation is stopping it. A child
with neither work nor a startable request has no assignment round to
wait for.

Use the existing assignment inspection's observations. Extend its
`PullRequestFinding` to retain the observed head and whether any checks
are running, calculated from the individual checks already read. Do not
query a pull request again just for campaign inspection. When fault or
ending means no fresh inspection exists, retain the reference and
available local facts without pretending to have current checks. The
lead can read GitHub itself.

### Comparing snapshots and producing notifications

Use the newest lead input that counts as delivered under
`AgentWork.list_relayed_round_paths`. It supplies one previous snapshot
for the whole campaign. Do not scan older inputs separately for each
child.

Each update compares that snapshot with the current observation and
selects the notifiable differences. No notification object waits between
updates. Only a round that actually starts records a new input.

| Difference                                                  | When it is notifiable                                                                                                             |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| A child was added or removed.                               | Notify independently of whether other children are working.                                                                       |
| A child issue was closed or reopened.                       | Notify when that child has no assignment round running or due.                                                                    |
| An assignment has handed back.                              | Notify when the child is settled and its assignment, finished turn or settled state differs from the previous snapshot.           |
| A pull request's readiness, head or terminal state changed. | Notify when the child is settled and the observation is known.                                                                    |
| Checks finished, or a finished check result changed.        | Notify when the child is settled and its known checks have no run still pending. Compare the head, result and running-check flag. |
| An assignment ended or entered fault.                       | Notify once it has no running round; ordinary inspection supplies no further round while it is ended or in fault.                 |

The assignment identifier appearing for the first time does not itself
generate a notification while work is running or due. Feed output,
elapsed time, main moving and ordinary check progress do not wake the
lead. A change back to the previously delivered facts needs no separate
event history.

For example, the lead can receive a snapshot while a child is still
working on round 4. When it later settles, the settled flag changes and
makes that handback visible, even though the round number was already
observed. If round 3 finished but round 4 was immediately due, round 3
needed no separate notification.

Several differences produce one batch. The lead sees current facts and
their relevant differences, not a replay of every intermediate state.
Changes after the launching update's observations remain available to
later comparisons.

### Parent comments and round input

Reuse the existing eligible-comment rule on the parent. Only the
signed-in user's speaking, unmarked comments count. The lead remains
free to read GitHub at any time; the saved comments identify the user's
new input rather than restricting what it may inspect.

Each campaign input contains the parent reference, the current child
snapshot, the highlighted changes, the new eligible parent comments, the
parent comment position reached, the checked-out main revision, and the
daemon's active assignment routes with their recipes. The comment
position is carried forward when a child-only round contains no new
parent comments, so the previous delivered input is sufficient for the
next comparison. It is part of the round input, not a separate cursor
file.

Supplying active routes matters because the daemon's startup
configuration may differ from the file now on main. Existing campaign
settings stay frozen in its work record; the available choices for child
assignments come from the current daemon.

A new campaign, an unfinished lead round, new parent comments, or a
notifiable child change can make a round due. Pause, fault, read
failure, capacity and cooldown apply before launch. An unfinished lead
round can recover even if its earlier actions have left no new child
notification.

### Recovery and failed reads

Recovery resumes the existing harness session when available. The lead
keeps its knowledge of actions completed in the earlier attempt and
continues from there. Errored and interrupted inputs do not advance
delivery; successful, stopped and running inputs do. A stopped lead
waits for new input instead of automatically repeating the stopped
round.

The new input is recomputed from current observations against the
previous delivered input. A recovery prompt says the previous round did
not finish. The lead checks current GitHub state where an earlier
action's outcome is uncertain or where a new decision depends on it.
This does not require a separate action journal.

If a GitHub read needed for the snapshot fails, report the failure and
start no lead round from that incomplete picture. Do not treat missing
data as a removed child or a state transition. The next update retries,
leaving the comparison point unchanged. This deliberately allows one
unreadable child to delay the lead, including a reply to a parent
comment. Other assignments continue under their own inspections. Not
having a fresh pull-request read because an assignment is in fault or
ended is not itself a read failure.

Campaigns share fault and cooldown rules. A user retry clears the fault
by recording a timestamp. The lead investigates a child's fault, posts
useful directions on the child's pull request when possible, and reports
the problem and proposed resolution on the parent. The user handles the
retry.

### Scheduling and code ownership

Keep one scheduler and two inspection passes. Inspect ordinary
assignments and conversations, including new requests, first. Inspect
campaigns second, passing the ordinary observations and the latest
assignments by issue. The campaign pass does not consume status reports
or invoke the child agents.

Launch after inspection, using a cycle of assignment, conversation and
campaign. Skip kinds with no candidate. Preserve
existing-work-before-new-work ordering within each kind, and advance the
cycle on a failed launch as today. Inspection order therefore does not
give assignments strict launch priority over campaigns.

Campaign round-input models, the previous-input reader, snapshot
comparison and workspace preparation belong in a campaign module
alongside `agent_assignments.py` and `issue_conversations.py`. Campaign
eligibility and round composition belong in `scheduler/campaigns.py`.
Keep GitHub reads in `github.py` and persisted scheduler observations in
`scheduler/models.py`. Status consumes those observations through its
existing read-only boundary. Generalise the existing issue pause checks
for conversations and campaigns without adding a workflow framework or a
new round runner.

Update the places that assume two kinds explicitly: configuration,
setup, request inspection, scheduling alternation, prompt selection,
harness permissions, round descriptions, commands and both
presentations. Extend stop, retry, feed and detail selection to
campaigns. Cancellation remains an assignment control; campaigns end
through parent closure.

### Workspace, messages and merge judgment

Reuse the detached-worktree refresh before each lead round. During
review, the lead may fetch and check out a child pull-request commit in
detached mode and run its proof. It does not take over the child's
branch or commit implementation changes. It asks the child to make
corrections on the stage pull request. The refreshed workspace and
resumed session serve the same distinct roles as they do for
conversations.

The lead publishes its own messages. No finishing function automatically
posts its final answer on the parent; final output remains in the feed.
There is no separate continuing campaign record or routine parent action
log.

Campaign prompts omit the agent marker on feedback posted to child pull
requests, allowing the existing assignment relay to deliver it as user
feedback. Posts elsewhere, including the parent, keep the marker.
Existing assignment and conversation prompts retain their current marker
rule. The lead respects the user's interventions and asks on the parent
before changing requirements, settled design or roadmap stages and
dependencies.

The `dream:lead` skill owns review judgment and GitHub coordination. It
checks the stage's proof against its completion conditions, considers
relevant changes on main, and gets specification corrections made before
merging. It reviews the current pull-request head and takes new user
feedback into account. It respects the repository's merge restrictions.
On a repository requiring branches to be current, the existing
assignment machinery handles the out-of-date signal. The lead ends its
turn when waiting for work or checks; it does not poll main or restart
reviews for every unrelated commit.

Give campaigns explicit harness permissions for the required GitHub
review, merge, issue-editing and comment operations, and for fetching
and checking out commits to verify them. Configure these in the
adapters, where this repository already owns unattended permissions,
rather than trying to set reserved permission keys through recipe
config. Keep the existing assignment and conversation permission
behaviours intact.

### Status and the web overview

Each open campaign's scheduler observation records its current child
list, issue states and work references, alongside what explains its
eligibility or pause. Continue gathering the overview while the lead is
paused. The latest update, not the last lead input, feeds the live
campaign display.

Status derives the lead's ordinary work status and combines child
membership with existing assignment and request statuses. Count closed
GitHub issues, not completed or cancelled assignments. Every child
appears, including one with no saved assignment or no dispatch request
yet. Failure to read the campaign picture is reported as unknown, not as
an empty campaign.

The web interface adds a Campaigns tab. Each active campaign shows its
lead summary, the closed/total count and an expandable child overview.
Use existing assignment summaries and request information; do not
rederive lifecycle rules in web code. Child assignments remain in the
Assignments tab too.

Give each displayed appearance its own HTML identifier. Keep the lead
card and the expandable child block as siblings within a campaign
wrapper, so the existing card-output reader does not mistake a child's
output for the lead's. Preserve expansion through the existing
details-refresh behaviour.

An ended campaign appears in the ordinary expandable ended section with
its summary and parent link. It has no nested child cards and needs no
archived child snapshot. Individual assignments remain visible under
their own rules.

## What changes, and what goes away

- Add campaign routes, work kind, input and observation models,
  inspection, status and views, and the corresponding command selectors.
- Add the sub-issue GitHub read and retain the head and running-check
  information already available in assignment inspections.
- Replace two-kind scheduling choices with explicit three-kind handling
  and fair alternation. Share the existing issue-lifetime mechanics
  where they agree.
- Add `dream:lead` in the dream plugin and a campaign section to the
  agent contract. The daemon owns dispatch and delivery; the skill owns
  judgment.
- Remove assignment-start notifications from the requirements. They
  create no routine action for the lead and would spend rounds on
  information alone.
- Remove child cards from ended campaigns. This removes the need to
  preserve a final campaign snapshot purely for an infrequently used
  historical view.
- Update the ontology, stories, architecture, configuration and command
  references, contract, compatibility page and changelog with
  implementation.

Use state format 7 and a major release. Older versions would reject
campaign records in the shared v6 directory. A separate format isolates
the new records and leaves old state untouched; no migration is
introduced. Users finish or take over old assignments and accept fresh
conversations before upgrading, following the existing policy. The
shared daemon lock remains outside the format directory.

Keep agent contract version 1. Adding a campaign contract does not
require existing conforming assignment or conversation skills to change.
Coordinate the dream plugin release so the default route can invoke
`dream:lead`.

The implementation needs behaviour tests for notification filtering and
coalescing, busy-to-settled comparisons, changes during lead rounds,
recovery, pausing and ending, failed reads, fault/cooldown and
three-kind capacity. Exercise both harnesses' prompts and permissions.
Regenerate affected view goldens and check nested cards, unique
identifiers, unstarted children and expansion across refresh in the
browser. Retain full branch coverage and the repository's existing
checks.

## Why it's this and not something else

Periodic lead wake-ups would save comparison code but repeatedly spend
agent rounds discovering that nothing needs action. A separate
notification queue would preserve intermediate transitions that the lead
does not need, and would add delivery state and recovery work.

One full snapshot per delivered lead input is sufficient. Including
whether each child has settled avoids a separate history lookup for
every child. The latest snapshot supplies the comparison point; GitHub
and the resumed session supply the collaboration context.

Strict assignment launch priority could starve leads behind unrelated
work. The existing alternation model extends without that cost. A
campaign branch would change the established stage-to-main workflow and
defer integration; ordinary child assignments and GitHub dependencies
already provide it.

## What's still open

No design decisions remain open.
