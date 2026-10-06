# dreamcatcher

dreamcatcher watches a GitHub repository for labelled issues, dispatches agents
for issue conversations and coding assignments, and carries each assignment to a
pull request for you to review and merge.

Read the documentation at <https://alimanfoo.github.io/dreamcatcher/>. It starts
with a tutorial that takes one issue to a pull request, and it holds the guides,
the command and configuration references, and the agent-facing contract.

## Install

If you already use Dreamcatcher, read
[Compatibility and upgrades](https://alimanfoo.github.io/dreamcatcher/compatibility/)
before replacing your installation.

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed:

```sh
uv tool install git+https://github.com/alimanfoo/dreamcatcher
```

## Contributing

Start with the [agent guide](AGENTS.md) for the development setup, project
conventions and required checks. The documentation's
[development pages](https://alimanfoo.github.io/dreamcatcher/standard/) say how
good the work has to be, how it is tested and how it is released. Their sources
are in [docs](docs).
