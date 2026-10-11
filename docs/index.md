---
title: dreamcatcher
template: home.html
hide:
  - navigation
  - toc
headline:
  - Run coding agents on your machine.
  - Steer them from GitHub.
lede:
  Label an issue, and an agent carries it to a pull request by itself, asking
  you on GitHub when it needs a decision or feedback.
points:
  - title: Your own setup.
    text:
      Agents run in your own Claude Code or Codex, on your machine, with nothing
      hosted and no new service to trust.
  - title: Steer from anywhere.
    text:
      The conversation happens on GitHub, so you can steer from your phone while
      the agents keep working at home.
  - title: Work in parallel.
    text: dreamcatcher runs as many agents at once as you allow.
---

## How it works

_dreamcatcher_ runs on your own machine, as a daemon in your repository's main
checkout. It watches the repository through `gh`, and starts each agent in
Claude Code or Codex. The label on an issue says which kind of work to start.

An **assignment** carries an issue to a pull request:

1. You label an issue and assign it to yourself.
2. _dreamcatcher_ opens a draft pull request for the issue, and starts an agent
   on it in a worktree of its own.
3. The agent works in rounds. When it needs a decision, it asks on the pull
   request, and _dreamcatcher_ passes your reply to its next round.
4. When the work is done, the agent marks the pull request ready for review.
   Review it as you would any pull request. _dreamcatcher_ passes each review
   and comment to another round, in which the agent addresses your feedback.
5. Keep iterating until you're happy, then merge the pull request. If the work
   should not land, close it.
6. The agent then takes one last round to wrap up.

A **conversation** answers your questions on an issue, and writes no code. Label
an issue for a conversation and post a question as a comment. The agent reads
the code and answers on the issue. Post another question, and the conversation
carries on.

Several agents can work at once, up to a number that you set. Follow them all on
a local web page, or in the terminal.

## Start here

If you already use _dreamcatcher_, read
[Compatibility and upgrades](compatibility.md) before replacing your
installation.

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed:

```sh
uv tool install git+https://github.com/alimanfoo/dreamcatcher
```

Then follow [From issue to pull request](tutorial.md) for the complete setup and
a first assignment.

## Guides

- [Configure labels and harnesses](configure.md).
- [Run and monitor _dreamcatcher_](run-and-monitor.md).
- [Discuss an issue](discuss-an-issue.md) without starting an implementation
  assignment.
- [Review an assignment](review-an-assignment.md) and give the agent feedback.
- [Stop and recover work](stop-and-recover.md).

## Reference

- Look up exact syntax and behaviour in the
  [command reference](command-reference.md).
- Find every accepted setting in the
  [configuration reference](configuration-reference.md).
- Plan upgrades with [Compatibility and upgrades](compatibility.md), and see
  user-visible changes in the [changelog](changelog.md).

## Customisable skills

How an agent works on an issue is up to the skill it runs. Each label points to
a prompt, and the prompt usually calls a skill.

The quickest way to start is with the skills from
[dream](https://alimanfoo.github.io/dream/), a separate plugin for Claude Code
and Codex. `dreamcatcher init` installs it and sets up a label for each skill:

| Skill         | On its own | Under _dreamcatcher_ |
| ------------- | ---------- | -------------------- |
| `dream:smith` | Yes        | An assignment        |
| `dream:less`  | Yes        | An assignment        |
| `dream:scout` | No         | A conversation       |

`dream:smith` plans a change, builds it a commit at a time, and reviews it
thoroughly. `dream:less` implements smaller tasks with lighter review.
`dream:scout` looks into an issue and answers your questions about it.

If you want your agents to work differently, write your own skill or prompt and
point a label to it. The [agent-facing contract](contract.md) explains what it
needs to do, and [Configure labels and harnesses](configure.md) shows how to set
up the label.
