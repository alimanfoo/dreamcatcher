# From parent issue to merged pull requests

Some work spans several issues, each needing its own pull request. They
may be steps towards one feature, some waiting on others, or unrelated
fixes that could all go at once. With assignments alone, you'd shepherd
each one yourself: start it, review its pull request, merge it, and
start whatever was waiting on it.

A campaign hands that shepherding to an agent, called the lead. You
gather the issues as sub-issues of one parent issue, and label the
parent. The lead sets up an assignment for each sub-issue, and
_dreamcatcher_ starts each one once nothing blocks it. The lead reviews
each pull request against what its sub-issue says done looks like,
merges it, and asks you on the parent when a decision is needed.

The lead merges pull requests without waiting for your review. Use a
repository that has a `README.md`, and where you are happy for the lead
to merge under your GitHub account. If `main` requires an approving
review before a merge, the lead cannot merge, because GitHub does not
let an account approve its own pull request.

This tutorial creates a parent issue with two sub-issues. The second is
blocked by the first, so the lead carries their pull requests to `main`
in order. At the end, you close the parent.

## 1. Set up dreamcatcher

Follow steps 1 to 4 of [From issue to pull request](tutorial.md), and
stop once you have pushed `dreamcatcher.toml` at the end of
[step 4](tutorial.md#4-run-dreamcatcher-init). Don't prepare an issue or
start _dreamcatcher_ yet. Those steps install the tools, sign you in and
write a `dreamcatcher.toml` that routes the `agent-campaign` label to
campaigns.

If you already run _dreamcatcher_ on the repository, check that your
tools meet [step 1](tutorial.md#1-install-the-tools) of that tutorial.
Its `dreamcatcher.toml` needs a campaign route that runs `dream:lead`
and at least one assignment route for the lead to give the sub-issues.
[Configure a campaign route](start-a-campaign.md#configure-a-campaign-route)
says how to add the route and update the `dream` plugin.

## 2. Write the plan

A campaign's plan is a parent issue that holds the goal, with the work
divided among its sub-issues. Each sub-issue says how to tell that its
work is done, and the lead checks that before it merges.

From the main checkout, create the parent issue and assign it to
yourself:

```sh
gh issue create --assignee "@me" --title "Add a project glossary" --body "Give the project a glossary that readers can reach from the README. Divide the work between its sub-issues."
```

`gh` prints the address of the new issue. Suppose it ends in
`/issues/123`. The commands below call the parent 123 and the sub-issues
124 and 125; replace each number with the one that `gh` prints for you.

Create the first sub-issue of the parent:

```sh
gh issue create --parent 123 --title "Add GLOSSARY.md" --body "Add GLOSSARY.md at the root of the repository, with one entry that defines the project's name in one sentence. Done when GLOSSARY.md is on main with that entry."
```

Create the second sub-issue, blocked by the first:

```sh
gh issue create --parent 123 --blocked-by 124 --title "Link the glossary from the README" --body "Add a line to README.md that links to GLOSSARY.md. Done when README.md on main links to GLOSSARY.md."
```

Open the parent on GitHub. It lists both sub-issues, and issue 125 shows
that issue 124 blocks it. _dreamcatcher_ starts no assignment for a
blocked issue, so the second sub-issue waits until the first one closes.

## 3. Start dreamcatcher

From the main checkout, start the daemon in its own terminal:

```sh
dreamcatcher run --harness claude --interval 30 --max-agents 2
```

Keep this terminal open. _dreamcatcher_ looks for work, waits 30 seconds
after each look, and runs at most two agent rounds at once, so the lead
and an assignment's agent can work at the same time. Your browser opens
the web home page.

## 4. Start the campaign

Add the `agent-campaign` label to the parent:

```sh
gh issue edit 123 --add-label agent-campaign
```

At its next update, _dreamcatcher_ starts the lead. On the web home
page, open the **Campaigns** tab. The campaign's card shows the parent,
the lead's status and `0 of 2 sub-issues closed`. Select the count to
show the sub-issues.

In its first round, the lead reads the plan and sets up an assignment
for each sub-issue. It assigns each sub-issue to you and adds an
assignment label, such as `agent-assignment`. Then it ends its turn, and
the campaign shows as **idle**. Under the card:

- issue 124 gets an assignment, which opens a draft pull request and
  starts work; and
- issue 125 shows as **held**, open and **blocked by #124**.

The count then reads `0 of 2 sub-issues closed · 1 working, 1 held`:
after GitHub's count of the closed sub-issues, it counts the cards and
rows under the campaign by the status that each shows.

The lead does not post on the parent to say what it set up. Follow it in
its feed instead, on the campaign's page or in a second terminal:

```sh
dreamcatcher feed GH123
```

## 5. Watch the first sub-issue

The first assignment's agent implements what the sub-issue asks for, and
marks the pull request ready for review when it is done. You don't need
to review it yourself, but you can comment on it as you would on any
pull request.

Once the assignment's agent has finished its turn, _dreamcatcher_ wakes
the lead, and the lead reviews the pull request. It checks the
sub-issue's "Done when" at the pull request's head. If something is
missing, it comments on the pull request, the assignment's agent answers
in its next round, and the lead reviews again.

When the sub-issue is done and its checks pass, the lead merges the pull
request. The merge closes issue 124, and the card's count begins
`1 of 2 sub-issues closed`. The first sub-issue's assignment takes one
last wrap-up round, then shows as **completed**.

## 6. Watch the handoff

Issue 124 is closed, so issue 125 is no longer blocked. At the next
update, _dreamcatcher_ starts the second sub-issue's assignment from
`main`, which now holds `GLOSSARY.md`. If the second sub-issue needs to
know something from the first, the lead comments on issue 125 before it
merges the first pull request, and the second assignment's agent reads
that comment when it starts.

The second assignment then goes the same way as the first: its agent
works, the lead reviews and merges, and the card shows
`2 of 2 sub-issues closed · 2 completed`.

## 7. Answer the lead when it asks

The lead asks you on the parent when a decision is needed, for example:

- no assignment route clearly fits a sub-issue;
- an assignment's agent asks something that the plan does not settle;
- a sub-issue falls into fault, or its pull request is closed without a
  merge; or
- the plan itself would need to change.

The lead posts under your account, so GitHub does not notify you of its
comments. Its posts end with "written by an agent". If the sub-issues
stop moving while the campaign shows as **idle**, read the parent:

```sh
gh issue view 123 --comments
```

Answer with a comment on the parent. At the next update, the lead is
given your comment and carries on from where it stopped.

## 8. Close the parent

When every sub-issue is closed, the lead posts once on the parent to say
so. Open `README.md` on GitHub, and follow its link to `GLOSSARY.md`.

If you are satisfied, close the parent:

```sh
gh issue close 123
```

The campaign ends once any running round finishes, and its card moves to
the ended list. If you want more work instead, add another sub-issue to
the parent, and the lead sets up its assignment.

When you have no more work for _dreamcatcher_, press Ctrl-C in the
terminal where it runs to stop it.

Continue with [Start a campaign](start-a-campaign.md) to give the lead a
plan of your own, talk to it on the parent, or pause the campaign.
