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

The watch tower is a command per view: `board`, `session` and `feed`. Each one
reads what the daemon left under `.dreamcatcher/` and asks GitHub nothing, so
each answers whether the daemon is running or long dead. Run them from the same
checkout.

Every view stays on the screen and keeps up while you watch it, so there is
nothing to wrap it in.

`board` is never over, so it stays until you interrupt it.

`session` and `feed` stay open for as long as the session has another round
coming, so you can leave one running for a whole session and see every round of
it arrive. They wait through every gap between one round and the next, including
a gap where you have stopped the daemon and not started it again yet.

Two things end them, because after either one no round is coming. One is the
session running its final round, which winds it up. The other is the session
getting stuck, which means no tick can move it on however long it waits: either
its dispatch never ran a first round, or its rounds ran and no pull request was
ever opened on its branch. Only you can take a stuck session from there, so a
view left open on one would wait for ever.

Interrupt any view to end it sooner.

A view whose output is not a terminal, because you piped it, redirected it or
captured it, shows what is there once and returns. You need no flag either way.

```sh
dreamcatcher board
```

That shows the board. The board is a section per standing, and the sections run
in the order of whose turn it is:

- `needs you` is a session with a pull request open that the agent has nothing
  left to do on, so it is ready for you to review.
- `agent working` is a live round, with how long it has been running, the last
  thing it said and how long ago.
- `waiting` is a session the next tick will pick up, with what it is waiting on.
- `stuck` is a session no tick can move on, with where to read what happened.
- `queued` is the labelled issues not dispatched yet, each with the reason it
  has not gone.
- `done` is the sessions that have run their last round.

Three sessions at one issue read as three sessions at one thing, so a label you
forgot to remove shows as what it is rather than as three unrelated rows.

`session` shows one issue's newest session: what its dispatch settled, the
rounds it has run, the command that takes the session over by hand, and the
older sessions at the same issue.

```sh
dreamcatcher session GH123
```

`feed` shows what the agent said, as it says it. It shows every round's feed in
order. A feed is a log rather than a picture of a state, so it is printed as it
is read and you keep your scrollback.

```sh
dreamcatcher feed GH123
```

`--round 2` narrows the feed to one round. One named round is all that view
shows, so it ends when that round ends rather than stay open for the round after
it. The round list of the session view is where you find the number.

```sh
dreamcatcher feed GH123 --round 2
```
