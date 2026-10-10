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
  Label an issue, and an agent takes it on with your own Claude Code or Codex,
  alongside as many others as you like. Each carries its issue to a pull request
  and asks you on GitHub when it needs a decision, so you can steer from
  anywhere, even your phone.
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
4. When the work is done, the agent marks the pull request ready for review. You
   review it as you would any pull request: comment to ask for changes, or merge
   or close it.
5. The agent then takes one last round to wrap up.

A **conversation** answers your questions on an issue, and writes no code. Label
an issue for a conversation and post a question as a comment. The agent reads
the code and answers on the issue. Post another question, and the conversation
carries on.

Several agents can work at once, up to a number that you set. Follow them all on
a local web page, or in the terminal.

## Ready-made skills from dream

_dreamcatcher_ decides when an agent starts and what it works on. A skill
decides how the agent does the work: each label's route names the prompt that an
agent starts with, and that prompt normally invokes a skill.

[dream](https://alimanfoo.github.io/dream/) is a separate plugin of skills for
Claude Code and Codex, and the skills below plug straight in.
`dreamcatcher init` installs dream, and creates a label named after each skill
that starts it:

| Skill         | On its own | Under _dreamcatcher_ |
| ------------- | ---------- | -------------------- |
| `dream:smith` | Yes        | An assignment        |
| `dream:less`  | Yes        | An assignment        |
| `dream:scout` | No         | A conversation       |

`dream:smith` plans a change, builds it one commit at a time and reviews it.
`dream:less` builds a small, self-contained change with no plan. `dream:scout`
investigates an issue before any code, and answers your questions on it. A skill
of your own works too, when it follows the [agent-facing contract](contract.md).

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

## Write a skill or prompt

The [agent-facing contract](contract.md) defines what custom assignment skills
and issue-conversation prompts must do.
