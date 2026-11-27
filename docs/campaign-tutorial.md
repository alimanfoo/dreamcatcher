# Run your first campaign

A campaign gives an agent called the lead a parent issue and its
sub-issues. In this tutorial the lead will carry two dependent
sub-issues into a campaign branch. You'll review their combined change
on the campaign's pull request and merge it into the default branch.

Use a repository with a `README.md` where you're happy for the lead to
merge sub-issue pull requests under your GitHub account. The campaign
branch must allow merges without an approving review. See
[Configure a campaign route](start-a-campaign.md#configure-a-campaign-route)
for the branch and plugin requirements.

## 1. Set up dreamcatcher

Follow steps 1 to 4 of [Run your first assignment](tutorial.md), through
pushing `dreamcatcher.toml` in
[step 4](tutorial.md#4-run-dreamcatcher-init). Then return here to
prepare the issues and start the daemon.

If you already run _dreamcatcher_ on the repository, check that its
configuration has a campaign route that runs `dream:big` and an
assignment route for the sub-issues.

## 2. Write the plan

The parent holds the goal. Each sub-issue defines one change and says
how the lead can tell it is done. From the main checkout, create the
parent and assign it to yourself:

```sh
gh issue create --assignee "@me" --title "Add a project glossary" --body "Give the project a glossary that readers can reach from the README. Divide the work between its sub-issues."
```

Suppose `gh` prints a URL ending in `/issues/123`. Use your issue
numbers in place of 123 for the parent and 124 and 125 for the
sub-issues.

Create the first sub-issue:

```sh
gh issue create --parent 123 --title "Add GLOSSARY.md" --body "Add GLOSSARY.md at the root of the repository, with one entry that defines the project's name in one sentence. Done when GLOSSARY.md contains that entry."
```

Create the second sub-issue, blocked by the first:

```sh
gh issue create --parent 123 --blocked-by 124 --title "Link the glossary from the README" --body "Add a line to README.md that links to GLOSSARY.md. Done when the link in README.md opens GLOSSARY.md."
```

Open the parent on GitHub. It lists both sub-issues, and issue 125 shows
that issue 124 blocks it.

## 3. Start dreamcatcher

From the main checkout, start the daemon in its own terminal:

```sh
dreamcatcher run --harness claude --interval 30 --max-agents 2
```

Keep this terminal open. _dreamcatcher_ looks for work, waits 30 seconds
after each look and runs at most two agent rounds at once. Your browser
opens the web home page.

## 4. Start the campaign

Apply the `agent-campaign` label to the parent:

```sh
gh issue edit 123 --add-label agent-campaign
```

At the next update, _dreamcatcher_ creates the campaign branch from the
default branch, opens a draft pull request and starts the lead. Open the
**Campaigns** tab on the home page and find the draft pull request on
the campaign card. Select the sub-issue count to see both issues.

The lead reads the plan, assigns the sub-issues to you and applies an
assignment label to each. After the lead ends its round, the draft
campaign can show **idle**, awaiting feedback or sub-issue changes.
Issue 124 starts an assignment whose pull request targets the campaign
branch. Issue 125's request shows as **held**, blocked by #124.

Follow the lead on the campaign page or in a second terminal:

```sh
dreamcatcher feed GH123
```

## 5. Watch the first sub-issue

When the first assignment hands back, the lead reviews its pull request
against issue 124. If a change is needed, the lead comments on that pull
request, the assignment's agent responds in its next round, and the lead
reviews again. You can follow or join the exchange there.

Once the sub-issue is done and its checks pass, the lead merges the pull
request into the campaign branch. _dreamcatcher_ closes issue 124 during
the assignment's wrap-up. The campaign card then shows
`1 of 2 sub-issues closed`.

## 6. Watch the handoff

Issue 125 can now start from the campaign branch, which already holds
`GLOSSARY.md`. Its agent adds the link, and the lead reviews and merges
the second pull request into the campaign branch. After the second
assignment wraps up, the campaign card shows `2 of 2 sub-issues closed`.

If the lead needs a decision along the way, it asks on the campaign's
pull request. Reply there from the account that `gh` is signed in as.

## 7. Review and merge the campaign

When the lead judges both sub-issues done, it reviews the combined
change and can push fixes before marking the campaign's pull request
**ready for review**. Open that pull request and check that it adds the
glossary and the README link. If you want a change, post feedback on
that pull request. The lead responds there and can push updates.

Merge the campaign's pull request when you're satisfied. GitHub closes
the parent, and the lead takes a final wrap-up round. Keep the daemon
running until the campaign shows **completed**.

[Start a campaign](start-a-campaign.md) covers queueing campaigns,
adding sub-issues during review and taking over from the lead.
