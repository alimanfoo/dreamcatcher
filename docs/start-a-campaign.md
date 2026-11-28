# Start a campaign

Give a parent issue and its sub-issues to an agent, the lead. The
default `agent-campaign` route uses `dream:big` to dispatch the
sub-issues, review their pull requests and merge them into a single
campaign branch. You review and merge the campaign's pull request into
the default branch.

For a worked example, see
[Run your first campaign](campaign-tutorial.md).

## Configure a campaign route

The `dreamcatcher.toml` that `dreamcatcher init` writes routes
`agent-campaign` to the `dream:big` skill from the
[dream](https://alimanfoo.github.io/dream/) plugin. The lead also needs
at least one assignment route to dispatch the sub-issues.

If your configuration has no campaign route, copy the `[[campaign]]`
route from the
[default configuration](configuration-reference.md#complete-example).
`init` leaves an existing configuration and plugin installation in
place. Check the
[upgrade instructions](compatibility.md#upgrade-from-v9-to-v1000) for
the minimum dream plugin version and the campaign skill contract.

For your own campaign instructions, configure a separate
[route](configure.md) with a prompt that follows the
[campaign skill contract](contract.md#campaign-skill-contract).

GitHub doesn't let an account approve its own pull request. If your
rules require review on every branch, exempt campaign branches so the
lead can merge sub-issue pull requests. These branches are named
`dreamcatcher-GH<n>-…-campaign`.

If your CI runs only on pull requests into the default branch, the lead
merges sub-issue pull requests without CI checks. Run CI on pull
requests into any branch to check those changes before the lead merges
them.

After adding either route, run
[`dreamcatcher init`](command-reference.md#init) to create the label on
GitHub, then
[start or restart the daemon](run-and-monitor.md#start-the-daemon) so it
reads the new route.

## Start the campaign

On GitHub, gather the work as direct sub-issues in the same repository.
Record any dependencies as blocked-by links. Assign the open parent
issue to the account authenticated through `gh` and apply one configured
campaign label yourself, such as `agent-campaign`.

When the [request can start](configure.md#label-an-issue-for-agent-work)
and an agent slot is free, _dreamcatcher_ creates the campaign branch
from the default branch, opens a draft pull request and starts the lead
in its worktree. The lead receives the sub-issues, their assignment
status and the daemon's assignment routes.

On the web home page's **Campaigns** tab, the campaign card links to its
pull request and shows the closed sub-issue count. Expand the count to
see each sub-issue and its assignment or requests. The assignments also
appear on the **Assignments** tab. When the campaign ends, its card
moves to the ended list, and GitHub keeps the sub-issue history. To
follow the campaign in the terminal, use its parent issue number:

```sh
dreamcatcher view GH123
dreamcatcher feed GH123
```

## Talk to the lead

Post comments or reviews on the campaign's pull request. At the next
update with a free agent slot, the lead receives your new posts in the
same harness session and answers on the pull request. If a colleague
asks for changes, post the feedback you want the lead to act on under
your own account. The lead's final words for each round stay in the
feed.

The lead gives feedback to a sub-issue's agent on that assignment's pull
request. The agent receives it as feedback from your account and answers
there. The lead hears when the assignment hands back.

## Changes among the sub-issues

You can add a sub-issue while the campaign is open, including after its
pull request is ready for review. The lead dispatches the assignment and
reviews and merges its pull request into the campaign branch. A campaign
pull request that was ready stays ready while the extra work runs.

The lead hears about a change to a sub-issue once its assignment has no
round running or due.

## Review and merge the campaign

While the campaign pull request is a draft, the lead coordinates
sub-issue assignments. When it judges every sub-issue done, it can
review and fix the whole change, then marks the pull request ready for
review. Once it's ready, the lead handles feedback, conflicts with the
default branch and failing checks, as described in
[Out-of-date branches and failing checks](review-an-assignment.md#out-of-date-branches-and-failing-checks).
Marking the pull request as a draft again returns the lead to
coordinating on its next round.

Merge the pull request when you're satisfied. GitHub closes the parent.
If you decide to abandon the change, close the pull request instead.
Either action calls for the lead's wrap-up round. Keep the daemon
running until the campaign shows **completed**. The next update removes
its worktree and local branch.

### Start a fresh campaign

If you close the campaign's pull request without merging, sub-issues
whose pull requests merged into the campaign branch stay closed. Their
work never reached the default branch.

Once the campaign has ended, reopen the sub-issues you want redone on
GitHub. Then remove and re-add the campaign label on the open parent. If
the new lead treats a reopened sub-issue as done, ask it on the new
campaign's pull request to dispatch a fresh assignment for that
sub-issue.

## Stop or take over

Use the controls in [Stop and recover work](stop-and-recover.md) to stop
a round or cancel the campaign and finish its pull request yourself. The
lead continues to work through the campaign pull request if you change
the parent's labels or assignee, or close the parent by hand.

## Queue campaigns

Mark the later parent as blocked by the earlier parent on GitHub, then
assign and label both parents. The later request shows as held while the
earlier parent is open. When you merge the earlier campaign's pull
request, GitHub closes its parent. The later campaign can start at the
next update once all its blockers are closed and an agent slot is free.
