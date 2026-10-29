# Work with dreamcatcher

You are an agent working for the developer outside _dreamcatcher_. Use
_dreamcatcher_ to hand self-contained work to other agents, then leave
that work alone until it needs the developer.

The routes below come from this checkout's `dreamcatcher.toml`. A dreamcatcher daemon is running here.

## Set up and check

Setup belongs to the developer. Ask them to run `dreamcatcher init`
interactively and to run the long-lived `dreamcatcher run` daemon. Do
not script either command.

After setup, run `dreamcatcher status` with its output captured before
you act on an issue. Captured output prints one snapshot and returns. It
tells you whether work is already in progress, why a request has not
started, and whether work is in fault.

The issue is an assignment's whole brief. Before you apply a label, make
its title and body say what to change, why, and how to check the result.
Before an assignment starts, put further guidance in the issue by
editing it or commenting on it.

## Dispatch work

- `build-carefully` starts assignment work. codex starts with "$dream:smith GH{issue}", using `gpt-5.6-sol` at `high` effort.
- `build-quickly` starts assignment work. claude starts with "/dream:less GH{issue}", using `sonnet` at `medium` effort; codex starts with "$dream:less GH{issue}", using `gpt-5.6-terra` at `medium` effort.
- `ask-agent` starts conversation work. claude starts with "/dream:scout GH{issue}", using `opus` at `high` effort.
- `lead-program` starts campaign work. claude starts with "/dream:big GH{issue}", using `opus[1m]` at `high` effort.

Assign the issue to the developer, then apply exactly one route label
through the developer's GitHub account. Work starts at a later update
when an agent slot is free. An issue that an open issue blocks stays
held; use GitHub's blocked-by relationships to set the order.

## Follow an assignment

An assignment starts a separate agent in its own worktree and draft pull
request. The agent implements the issue and marks the pull request ready
for review. Ready for review is the signal that the assignment wants
attention, so you do not need to watch it more closely.

Once the pull request exists, put every instruction and answer there as
a review or comment. The agent receives the developer's posts since its
last turn at its next turn. Posts made while it works wait for the turn
after. It does not receive issue edits, issue comments, or another
person's review. Restate another person's feedback through the
developer's account when the agent should act on it.

The assignment repairs red checks twice before it waits for a post that
explains what it is missing. It also merges main when the branch
conflicts, or when it falls behind in a repository that requires
branches to be up to date. Do not push to its branch.

The pull request comes back for review. Review and merge it only when
the developer has allowed you to; otherwise leave it for the developer.
After a merge, the assignment takes a wrap-up turn and may file issues
for work that it left out.

## Run a campaign

Make the planned work real GitHub sub-issues of one parent, and use
blocked-by relationships to order them. Apply the campaign label to the
parent alone. The lead applies assignment labels to the sub-issues,
reviews their pull requests, and merges each one when it is ready,
green, and conflict-free. Do not label the sub-issues or merge their
pull requests yourself.

Talk to the lead on the parent issue, and expect its questions there.
Close the parent when the campaign is finished; closing it ends the
campaign.

Use a merge queue when the repository offers one. Otherwise leave
"Require branches to be up to date before merging" off, because each
merge would make every other campaign pull request rerun its assignment
and checks. A conflict still wakes an assignment to update its branch.

## Hold a conversation

A conversation answers questions in comments on its issue. Give guidance
and reply on that issue through the developer's account.

## Intervene

Use GitHub as the main interface. `dreamcatcher view` and
`dreamcatcher feed` show what is happening behind the scenes. After you
fix the cause of a fault, `dreamcatcher retry` lets the work run again.
`dreamcatcher stop` stops one running round so that you can redirect the
agent on GitHub. `dreamcatcher cancel` hands an assignment's pull
request to the developer to finish by hand.
