# Start a campaign

A campaign hands a planned body of work to an agent, the lead. The
campaign's parent issue holds the goal, and the parent's sub-issues are
the stages. The lead works through GitHub, as its prompt directs.

_dreamcatcher_ gives the lead a round when the campaign starts, another
for each comment you post on the parent, and another when a sub-issue
changes in a way that the lead needs to hear of. It ends the campaign
when you close the parent.

You need a configured campaign route and a running daemon.

## Configure a campaign route

The `dreamcatcher.toml` that `dreamcatcher init` writes has no campaign
route, so add one. Its prompt tells the lead what to do with the parent
and with your comments on it. For example, this prompt makes a lead that
summarises the plan and then talks with you:

```toml
[[campaign]]
label = "dream:lead"

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

A campaign needs no comment to start. At its next update with a free
agent slot, _dreamcatcher_ checks out current `origin/main` in a
worktree of the campaign's own, and starts the lead with the configured
prompt. Its input holds any comments you have already posted on the
parent, the parent's sub-issues with where each one's assignment stands,
and the daemon's assignment routes. The lead posts on GitHub itself.
_dreamcatcher_ keeps the lead's final output in the feed and posts none
of it.

Monitor the campaign on the web home page's Campaigns tab, where its
card shows how many of the parent's sub-issues are closed and links to
each, or in the terminal:

```sh
dreamcatcher campaign GH123
dreamcatcher feed GH123 --campaign
```

## Talk to the lead

Comment on the parent to talk to the lead. At the next update with a
free agent slot, _dreamcatcher_ refreshes the lead's worktree to current
`origin/main` and gives the lead every comment you have posted since its
last round, in the same harness session. The lead answers on GitHub
itself. Its own posts carry the agent marker, so they never wake it.

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

To watch what the lead is given before you rely on a real lead skill,
give the route a prompt that only reports its input, such as
`Print the notifications in your input. Do not change anything on GitHub.`

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

## When a round does not finish

If a lead round errors, or the daemon stops during it, the next update
gives the lead its comments again, with any you have posted since and
the changes among the sub-issues since its last finished round, in the
same harness session, and tells it that its previous round did not
finish. Two errored rounds in a row put the campaign in fault. Fix the
cause, then run `dreamcatcher retry GH123` or use the retry control on
the campaign's web page.

To stop a running round, run `dreamcatcher stop GH123 --campaign` or use
the stop control on the campaign's web page. A stopped lead has taken
its turn, so no round follows it on its own. Comment on the parent with
fresh direction, and the next round tells the lead that you stopped its
previous round.
