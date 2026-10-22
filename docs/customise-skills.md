# Customise skills

How an agent works on an issue is up to the skill it runs. Each label
points to a prompt, and the prompt usually calls a skill. So by choosing
the skills, you choose how your agents work.

## Start with dream's skills

The quickest way to start is with the skills from
[dream](https://alimanfoo.github.io/dream/), a separate plugin for
Claude Code and Codex. [`dreamcatcher init`](command-reference.md#init)
installs it and sets up a label for each skill:

| Skill         | On its own | Under _dreamcatcher_ |
| ------------- | ---------- | -------------------- |
| `dream:smith` | Yes        | An assignment        |
| `dream:less`  | Yes        | An assignment        |
| `dream:scout` | No         | A conversation       |
| `dream:lead`  | No         | A campaign           |

`dream:smith` plans a change, builds it a commit at a time, and reviews
it thoroughly. `dream:less` implements smaller tasks with lighter
review. `dream:scout` looks into an issue and answers your questions
about it. `dream:lead` leads a campaign, carrying a parent issue's
sub-issues through their assignments to merge.

## Write your own

If you want your agents to work differently, write your own skill or
prompt and point a label to it.

1. Write the skill or prompt. An assignment skill must follow the
   [assignment skill contract](contract.md#assignment-skill-contract),
   so that it picks up the branch and draft pull request that
   _dreamcatcher_ has already opened. A conversation skill must follow
   the
   [conversation skill contract](contract.md#conversation-skill-contract),
   so that it investigates the issue and returns an answer for
   _dreamcatcher_ to publish. A campaign skill must follow the
   [campaign skill contract](contract.md#campaign-skill-contract), so
   that the lead coordinates the sub-issues through GitHub and leaves
   the parent issue to you. A conversation or campaign prompt can
   instead give plain instructions, because _dreamcatcher_ adds the
   operational requirements.
2. If you wrote a skill, make it available where the agent runs. Each
   agent works in a fresh worktree of `origin/main`, so either install
   the skill at user scope, or commit it to the repository and push it.
3. Add a route to `dreamcatcher.toml` that points a label to a prompt.
   The prompt calls your skill or gives the conversation or campaign
   instructions directly. Run `dreamcatcher init` to create the label on
   GitHub, commit and push `dreamcatcher.toml`, and restart the daemon
   so that it reads the new route.

A route for an assignment skill looks like this:

```toml
[[assignment]]
label = "my-skill"

[assignment.claude]
prompt = "/my-skill GH{issue}"
model = "opus[1m]"
effort = "high"
```

Then label an issue with your new label, and an agent works on it with
your skill. [Configure labels and harnesses](configure.md) explains
routes in more detail, including how to give a route a Codex recipe too.
