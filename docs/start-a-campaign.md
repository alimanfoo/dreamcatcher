# Start a campaign

A campaign hands a planned body of work to an agent, the lead. The
campaign's parent issue holds the goal, and the parent's sub-issues are
the stages. The lead works through GitHub, as its prompt directs.

_dreamcatcher_ gives the lead a round when the campaign starts, another
for each comment you post on the parent, and another when a sub-issue
changes in a way that the lead needs to hear of. It ends the campaign
when you close the parent.

You need a configured campaign route and a running daemon. For a first
campaign, follow the worked example in
[From parent issue to merged stages](campaign-tutorial.md).

## Configure a campaign route

The `dreamcatcher.toml` that `dreamcatcher init` writes routes the
`dream:lead` label to campaigns. Its recipes run the
[`dream:lead`](https://github.com/alimanfoo/dream/blob/main/plugins/dream/skills/lead/SKILL.md)
skill from the dream plugin. The skill starts each stage on an
assignment route, reviews the stage's pull request and checks its proof,
gives the stage's agent feedback, and merges the pull request once the
stage is done. It asks you on the parent before it changes the plan.

`init` never changes an existing `dreamcatcher.toml`, so a file written
before the route existed has none. Copy the `[[campaign]]` route from
the [default configuration](configuration-reference.md#complete-example)
into it.

The dream plugin has had `dream:lead` since version 43.3.0, and `init`
leaves an installed plugin as it is. If you installed the plugin before
then, update it with the plugin commands of each harness that runs the
route.

To give the lead other instructions, add a campaign route of your own
beside `dream:lead`, under a label of its own. Its prompt tells the lead
what to do with the parent and with your comments on it. For example,
this prompt makes a lead that summarises the plan and then talks with
you:

```toml
[[campaign]]
label = "summarise-plan"

[campaign.claude]
prompt = "Read GH{issue} and its sub-issues. Reply to the comments in your input in one comment on GH{issue}. If your input holds no comment, post a comment on GH{issue} that summarises the plan."
model = "opus[1m]"
effort = "high"
```

Run [`dreamcatcher init`](command-reference.md#init) to create the label
on GitHub, then restart the daemon so that it reads the new route. The
[campaign skill contract](contract.md#campaign-skill-contract) says what
_dreamcatcher_ gives the lead and what the lead must leave to you.

## Start the campaign

On GitHub:

1. Keep the parent issue open.
2. Assign it to the account authenticated through `gh`.
3. Add exactly one configured campaign label, such as `dream:lead`.

If open issues block the parent on GitHub, the campaign waits until
every one of them is closed.

A campaign needs no comment to start. At its next update with a free
agent slot, _dreamcatcher_ checks out current `origin/main` in a
worktree of the campaign's own, and starts the lead with the configured
prompt. Its input holds any comments you have already posted on the
parent, the parent's sub-issues with where each one's assignment stands,
and the daemon's assignment routes. The lead posts on GitHub itself.
_dreamcatcher_ keeps the lead's final output in the feed and posts none
of it.

Monitor the campaign on the web home page's Campaigns tab, where its
card shows how many of the parent's sub-issues are closed. Expand the
count to see each sub-issue with its assignment's card and the row of
each request for an assignment on it that has no open work, or the
sub-issue alone when it has neither. Each assignment's card stays on the
Assignments tab too. Once the campaign ends, its card moves to the ended
list and shows only the campaign itself. You can also monitor the
campaign in the terminal:

```sh
dreamcatcher campaign GH123
dreamcatcher feed GH123 --campaign
```

## Queue campaigns

To run one campaign after another, mark the later parent as blocked by
the earlier parent on GitHub, then assign and label both parents. The
later campaign waits, and its request shows as blocked by the earlier
parent.

Close the earlier parent when you are satisfied with its campaign, and
the later campaign starts at the next update with a free agent slot.
Closing every sub-issue does not close the parent, and the lead is told
never to close it, so the next campaign waits for you.

## Talk to the lead

Comment on the parent to talk to the lead. At the next update with a
free agent slot, _dreamcatcher_ refreshes the lead's worktree to current
`origin/main` and gives the lead every comment you have posted since its
last round, in the same harness session. The lead answers on GitHub
itself. Its own posts carry the agent marker, so they never wake it.

When the lead gives a sub-issue's assignment feedback on its pull
request, it leaves the marker off. The assignment's agent is then given
the feedback as it is given yours, and the lead hears of the agent's
answer once the assignment hands back.

## Changes among the sub-issues

At each update, _dreamcatcher_ compares the parent's sub-issues with
those it last gave the lead. A sub-issue added to or removed from the
parent wakes the lead at once. A sub-issue that is closed or reopened,
an assignment that finishes its turn, ends or falls into fault, a pull
request that changes its head, state or draft flag, checks that finish,
and a pull request that becomes mergeable wake the lead once the
sub-issue's assignment has no round running or due. The lead's input
names each sub-issue that changed and what changed, beside the whole
current picture. Changes that arrive together, or while the lead cannot
take a round, reach it in one round.

## Pause or end a campaign

Remove the campaign's label from the parent, or unassign the parent from
yourself, to pause the campaign. A round that is already running
finishes. Comments you post while the campaign is paused wake nothing.
Restore the label and the assignee to resume the same campaign, and the
lead is given every comment you posted while it was paused, and what
changed among the sub-issues meanwhile. A second campaign label on the
parent is a routing conflict, and pauses the campaign in the same way
until one of the labels comes off.

Close the parent to end the campaign. It ends once any running round
finishes. Only you close the parent: the lead is told never to close it.
If you reopen the parent with its label still on, a new campaign starts.

## Stop or recover a round

To stop a lead's round, or to recover after one errors or the daemon
stops, follow [Stop and recover work](stop-and-recover.md).
