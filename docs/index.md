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
  Dispatch agents to implement, investigate and coordinate your issues.
points:
  - title: Your own setup.
    text:
      Agents run in Claude Code or Codex on your machine, with nothing
      hosted and no new service to trust.
  - title: Steer from anywhere.
    text:
      The conversation happens on GitHub, so you can steer from your
      phone while the agents keep working at home.
  - title: Built for long-horizon work.
    text:
      Agents fan out where they can and converge where issues depend on
      each other, so a roadmap keeps moving without losing the plot.
---

## How it works

_dreamcatcher_ runs on your own machine, as a daemon in your
repository's main checkout. It watches the repository through `gh`, and
starts each agent in Claude Code or Codex. The label on an issue says
which kind of work to start.

An **assignment** implements one issue in its own worktree and pull
request. Review it as you would any pull request: leave review comments
or line comments, or request a change. The agent addresses your feedback
in its next round. Keep iterating, then merge when you are satisfied, or
close it if the work should not land.

A **conversation** investigates one issue without changing code. Ask a
question in an issue comment, and the agent answers on the issue. Each
later question carries on the same conversation.

A **campaign** gives an agent called the lead several issues to
shepherd. Gather them as sub-issues of one parent; some can run together
and some can wait on others. The lead sets up assignments, reviews and
merges their pull requests, and asks you on the parent when a decision
is needed.

Several agents can work at once, up to a number that you set. Follow
them all on a local web page, or in the terminal.

## Start here

If you already use _dreamcatcher_, read
[Compatibility and upgrades](compatibility.md) before replacing your
installation.

With [uv](https://docs.astral.sh/uv/getting-started/installation/)
installed:

```sh
uv tool install dreamcatcher
```

Then follow [From issue to pull request](tutorial.md) for the complete
setup and a first assignment. To try a campaign, follow
[From parent issue to merged pull requests](campaign-tutorial.md), which
uses the same setup.

## Guides

- [Review an assignment](review-an-assignment.md) and give the agent
  feedback.
- [Discuss an issue](discuss-an-issue.md) without starting an
  implementation assignment.
- [Start a campaign](start-a-campaign.md) to hand a parent issue's
  sub-issues to a lead.
- [Stop and recover work](stop-and-recover.md).
- [Run and monitor _dreamcatcher_](run-and-monitor.md).
- [Configure labels and harnesses](configure.md).
- [Customise skills](customise-skills.md), starting with the ready-made
  ones from [dream](https://alimanfoo.github.io/dream/).

## Reference

- Look up exact syntax and behaviour in the
  [command reference](command-reference.md).
- Find every accepted setting in the
  [configuration reference](configuration-reference.md).
- Write an assignment skill, a conversation skill or a campaign skill to
  the [agent-facing contract](contract.md).
- Plan upgrades with [Compatibility and upgrades](compatibility.md), and
  see user-visible changes in the [changelog](changelog.md).
