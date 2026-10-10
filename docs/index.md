# dreamcatcher

_dreamcatcher_ watches a GitHub repository for labelled issues, dispatches
agents for issue conversations and coding assignments, and carries each
assignment to a pull request for you to review and merge.

## Skills for the agents

Every agent that _dreamcatcher_ starts follows a skill, which says how to do the
work. [dream](https://alimanfoo.github.io/dream/) is a plugin of skills for
Claude Code and Codex, and `dreamcatcher init` installs it and routes a label of
each skill's name to that skill:

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
