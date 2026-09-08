# dreamcatcher

dreamcatcher watches a repository for labelled issues, dispatches an autonomous
coding session for each, and carries each issue to a pull request for you to
review and merge.

## Install

You need [uv](https://docs.astral.sh/uv/). It fetches its own Python, so you
need nothing else.

You also need [gh](https://cli.github.com/), signed in to the account whose
issues you want picked up, and the CLI of every harness your config maps a label
to. `run` refuses to start when any of them is missing.

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

Point `prompt` at a skill that meets
[dreamcatcher's dispatchable skill contract](CONTRACT.md).

## Commands

`run` is the daemon. Start it from the repository's main checkout, and name the
harness to run rounds with. It keeps going in the foreground, dispatching a
session per labelled issue.

```sh
dreamcatcher run --harness claude
```

Every `interval` seconds it looks once and launches at most one round. An issue
is dispatched when it carries exactly one mapped label, is assigned to
`assignee`, has no session here already, has no open pull request GitHub links
to it, and has no open issue blocking it. The oldest such issue goes first. A
dispatch cuts a branch and a worktree under `.dreamcatcher/`, and runs the
session's first round there.

After every look, `run` prints one UTC-stamped line that says whether it
launched a session, was held and why, or launched nothing.

Everything the daemon owns lives under `.dreamcatcher/` in the checkout, which
ignores itself, so git never sees it. `last-tick.json` there says what the most
recent look observed and decided, including what the daemon did not do and why.

Open work goes before new work. Before it dispatches anything, the daemon reads
each session it already has and gives it whatever it needs next: a round that
did not finish is carried on, a merged or closed pull request gets one last
round, and a pull request you have posted on gets a round that answers what you
said. Only when no session needs anything does the daemon dispatch a new issue.

Rounds die with the daemon, so a `run` you stop takes its sessions' rounds with
it. The next `run` carries each of those rounds on from where it stopped. After
any round fails, the daemon holds every launch for fifteen minutes, so a usage
limit that lasts for hours costs a few failed rounds rather than a fresh
worktree every couple of minutes.

Removing the label is how you say stop. An issue whose pull request closes
unmerged is free to dispatch again while the label is still on it.

One daemon watches one repo. A second `run` on the same repo refuses while the
first is alive.

`scry` is the watch tower. It reads what the daemon left under `.dreamcatcher/`
and asks GitHub nothing, so it answers whether the daemon is running or long
dead. Run it from the same checkout.

```sh
dreamcatcher scry
```

That shows the board. The board is a section per standing, and the sections run
in the order of whose turn it is:

- `needs you` is a session with a pull request open that the agent has nothing
  left to do on, so it is ready for you to review.
- `agent working` is a live round, with the last thing it said and how long ago.
- `waiting` is a session the next tick will pick up, with what it is waiting on.
- `stuck` is a session no tick can move on, with where to read what happened.
- `queued` is the labelled issues not dispatched yet, each with the reason it
  has not gone.
- `done` is the sessions that have run their last round.

Three attempts at one issue read as three attempts at one thing, so a label you
forgot to remove shows as what it is rather than as three unrelated rows.

Name an issue to see one session: what its dispatch settled, the rounds it has
run, the command that takes the session over by hand, and the older attempts at
the same issue.

```sh
dreamcatcher scry GH123
```

Add `--follow` to watch the agent work. It shows every round's feed in order,
and keeps showing what arrives until no round is running. `--round 2` shows the
feed of one round alone, as it stands.

```sh
dreamcatcher scry GH123 --follow
```
