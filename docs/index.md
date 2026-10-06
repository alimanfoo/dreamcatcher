# dreamcatcher

_dreamcatcher_ watches a GitHub repository for labelled issues, dispatches
agents for issue conversations and coding assignments, and carries each
assignment to a pull request for you to review and merge.

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
