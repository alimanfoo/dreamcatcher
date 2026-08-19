# dreamcatcher

dreamcatcher watches a repository for labelled issues, dispatches an autonomous
coding session for each, and carries each issue to a pull request for you to
review and merge.

Nothing reaches a pull request yet. `run` starts, reads the config, and idles.
`scry` is still a stub that says so when you run it.

## Install

You need [uv](https://docs.astral.sh/uv/). It fetches its own Python, so you
need nothing else.

```sh
uvx --from git+https://github.com/alimanfoo/dreamcatcher dreamcatcher --version
```

## Commands

`run` is the daemon. It keeps going in the foreground, dispatching a session per
labelled issue.

It needs a `dreamcatcher.toml` at the repo root. It says in plain words what is
wrong with the one it finds. Here is one to start from:

```toml
interval = 300
max_agents = 1
harness = "claude"

[[dispatch]]
label = "dream:smith"
[dispatch.claude]
prompt = "/dream:smith GH{issue}"
model = "opus[1m]"
effort = "xhigh"
[dispatch.codex]
prompt = "$dream:smith GH{issue}"
model = "gpt-5.6-sol"
effort = "xhigh"
```

`interval` is the seconds between ticks, and `max_agents` the rounds that may
run at once. Each `[[dispatch]]` entry maps one label to what runs for it, with
a block per harness. The configuration section of
[the design](specs/2026-08-17-skeleton/design.md) covers the rest.

Start it from a repository's main checkout.

```sh
dreamcatcher run
```

One daemon watches one repo. A second `run` on the same repo refuses while the
first is alive.

Pass `--harness codex` to choose the harness for this run, rather than the one
the config names.

Use `scry` to peer into the crystal ball. It shows what the agent sessions are
doing.

```sh
dreamcatcher scry
```
