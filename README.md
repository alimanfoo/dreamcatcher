# dreamcatcher

dreamcatcher watches a GitHub repository for labelled issues, dispatches agents
for issue conversations and coding assignments, and carries each assignment to a
pull request for you to review and merge.

## Start here

If you already use Dreamcatcher, read
[Compatibility and upgrades](docs/compatibility.md) before replacing your
installation.

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed:

```sh
uv tool install git+https://github.com/alimanfoo/dreamcatcher
```

Then follow [From issue to pull request](docs/tutorial.md) for the complete
setup and a first assignment.

## Guides

- [Configure labels and harnesses](docs/configure.md).
- [Run and monitor Dreamcatcher](docs/run-and-monitor.md).
- [Discuss an issue](docs/discuss-an-issue.md) without starting an
  implementation assignment.
- [Review an assignment](docs/review-an-assignment.md) and give the agent
  feedback.
- [Stop and recover work](docs/stop-and-recover.md).

## Reference

- Look up exact syntax and behaviour in the
  [command reference](docs/command-reference.md).
- Find every accepted setting in the
  [configuration reference](docs/configuration-reference.md).
- Plan upgrades with [Compatibility and upgrades](docs/compatibility.md), and
  see user-visible changes in the [changelog](CHANGELOG.md).
- Read [Testing](docs/testing.md) for what the test suite and CI establish.

## Write a skill or prompt

The [agent-facing contract](CONTRACT.md) defines what custom assignment skills
and issue-conversation prompts must do.

## Contributing

Start with the [agent guide](AGENTS.md) for the development setup, project
conventions and required checks.
