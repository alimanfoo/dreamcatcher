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

## Configuration

dreamcatcher reads `dreamcatcher.toml` from the root of the repository it
watches. Commit it, so everyone watching that repo dispatches the same way.

```toml
interval = 120
max_agents = 1
assignee = "@me"

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

Every setting outside a `[[dispatch]]` entry has a default, so you can leave it
out:

- `interval` is the seconds between one look at GitHub and the next. It defaults
  to 120.
- `max_agents` is how many agent sessions may run at once. It defaults to 1, so
  one issue reaches a pull request before the next one starts.
- `assignee` is whose issues to pick up, as a GitHub login. It defaults to
  `@me`, the account `gh` is signed in as.

A `[[dispatch]]` entry says what to run for one label. Give it the label, then a
block for each harness that can run it. Every entry needs its label and at least
one block.

- `prompt` is what the harness is asked to do. `{issue}` becomes the issue's
  number, so `/dream:smith GH{issue}` reaches the session as
  `/dream:smith GH123`.
- `model` and `effort` are passed to the harness as it starts.

Write both blocks for a label either harness can run. Write one block for a
label that belongs to one harness, and issues carrying it always go there.

## Commands

`run` is the daemon. Start it from the repository's main checkout, and name the
harness to run rounds with. It keeps going in the foreground, dispatching a
session per labelled issue.

```sh
dreamcatcher run --harness claude
```

One daemon watches one repo. A second `run` on the same repo refuses while the
first is alive.

Use `scry` to peer into the crystal ball and see what the agent sessions are
doing.

```sh
dreamcatcher scry
```
