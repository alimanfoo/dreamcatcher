# dreamcatcher

dreamcatcher watches a repository for labelled issues, dispatches an autonomous
coding session for each, and carries each issue to a pull request for you to
review and merge.

Nothing works yet. This is the scaffold, so both verbs below are stubs that say
so when you run them.

## Install

You need [uv](https://docs.astral.sh/uv/). It fetches its own Python, so you
need nothing else.

```sh
uvx --from git+https://github.com/alimanfoo/dreamcatcher dreamcatcher --version
```

## Commands

`run` is the daemon. Start it from a repository's main checkout, and it keeps
going in the foreground, dispatching a session per labelled issue.

```sh
dreamcatcher run
```

`scry` is the watch tower. It shows what the agent sessions are doing, reading
what the daemon leaves on disk.

```sh
dreamcatcher scry
```
