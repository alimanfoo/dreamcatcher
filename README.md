# dreamcatcher

dreamcatcher watches a repository for labelled issues, dispatches an autonomous
coding assignment for each, and carries each issue to a pull request for you to
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
- `max_agents` is how many agent rounds may run at once. It defaults to 1, so
  one issue reaches a pull request before the next one starts.
- `assignee` is whose issues to pick up, as a GitHub login. It defaults to
  `@me`, the account `gh` is signed in as.

A `[[dispatch]]` entry says what to run for one label. Give it the label, then a
block for each harness that can run it. Every entry needs its label and at least
one block.

- `prompt` is what the harness is asked to do. `{issue}` becomes the issue's
  number, so `/dream:smith GH{issue}` reaches the assignment as
  `/dream:smith GH123`.
- `model` and `effort` are passed to the harness as it starts.

Write both blocks for a label either harness can run. Write one block for a
label that belongs to one harness, and issues carrying it always go there.

Point `prompt` at a skill that meets
[dreamcatcher's dispatchable skill contract](CONTRACT.md).

## Commands

`run` is the daemon. Start it from the repository's main checkout, and name the
harness to run rounds with. It keeps going in the foreground, dispatching an
assignment per labelled issue.

```sh
dreamcatcher run --harness claude
```

Every `interval` seconds it looks once and launches at most one round. An issue
is dispatched when it carries exactly one dispatch label, is assigned to
`assignee`, has no assignment here already, has no open pull request GitHub
links to it, and has no open issue blocking it. The oldest such issue goes
first. A dispatch cuts a branch and a worktree under `.dreamcatcher/`, makes and
pushes an empty commit, and opens a linked draft pull request before it runs the
assignment's first round there.

Assignment setup is recoverable. If Dreamcatcher stops after making the
worktree, commit, remote branch, or pull request, the next dispatch attempt
reuses those artifacts and finishes the same assignment instead of opening
another pull request. If setup completes but the first round cannot start, the
recorded assignment keeps its branch and pull request, and the next tick tries
that first round again before it schedules ordinary work.

Everything the daemon owns lives under `.dreamcatcher/` in the checkout, which
ignores itself, so git never sees it. `scheduler.json` there says what the most
recent completed look observed and decided, including what the daemon did not do
and why. It also preserves any active global cooldown and the end of the most
recent one. A look that cannot complete reports its failure in the daemon output
and leaves that last complete record in place.

Open work goes before new work. Before it dispatches anything, the daemon reads
each assignment it already has and gives it whatever it needs next: a round that
did not finish is recovered, a merged or closed pull request gets a wrap-up
round, and a pull request you have posted on gets a round that addresses your
feedback. Only when no assignment needs anything does the daemon dispatch a new
issue.

Every round records its number, purpose (`implement`, `address feedback` or
`wrap up`), whether it is recovering an earlier round, and its outcome
(`running`, `successful`, `errored` or `interrupted`). Purpose and recovery are
independent: for example, a failed wrap-up is followed by a recovery round whose
purpose is still `wrap up`.

Rounds die with the daemon. When `run` starts, it records any round orphaned by
an earlier daemon as interrupted; the next round recovers that work from where
it stopped. One errored round receives an ordinary recovery opportunity and does
not stop unrelated work. Two consecutive errored rounds put that assignment in
fault; an interrupted or successful round breaks the sequence.

When two assignments are in fault, the scheduler starts a fifteen-minute global
cooldown and starts no agent work during it. The scheduler keeps observing and
reporting while it waits. The cooldown survives a daemon restart, and its end
clears the faults so that recovery can continue.

Only a successful wrap-up completes an assignment. A failed or interrupted
wrap-up remains open for recovery. Once the wrap-up succeeds, the assignment no
longer claims its issue, so an issue whose pull request closed unmerged is free
to dispatch again while the label is still on it.

Removing the label is how you say stop.

One daemon watches one repo. A second `run` on the same repo refuses while the
first is alive.

The watch tower is a command per view: `board`, `assignment` and `feed`. Each
one reads what the daemon left under `.dreamcatcher/` and asks GitHub nothing,
so each answers whether the daemon is running or long dead. Run them from the
same checkout.

Every view keeps up with what the daemon writes while you watch it, so there is
nothing to wrap it in.

`board` and `assignment` take the whole terminal while they are going, and give
it back when they end.

`board` is never over, so it stays until you interrupt it.

`assignment` and `feed` stay open for as long as the assignment has another
round coming, so you can leave one running for a whole assignment and see every
round of it arrive. They wait through every gap between one round and the next,
including a gap where you have stopped the daemon and not started it again yet.

Two states end them because neither currently has another round scheduled. One
is the assignment completing a wrap-up round successfully. The other is an
assignment in fault, which the current board presents as `stuck`. A later global
cooldown can clear that fault and permit recovery. An interrupted creation or
missing first round is not stuck: Dreamcatcher reconciles the creation and
retries the round.

Interrupt any view to end it sooner.

A view whose output is not a terminal, because you piped it, redirected it or
captured it, shows what is there once and returns. You need no flag either way.

```sh
dreamcatcher board
```

That shows the board. The board is a section per standing, and the sections run
in the order of whose turn it is:

- `needs you` is an assignment with a pull request open that the agent has
  nothing left to do on, so it is ready for you to review.
- `agent working` is a live round, with how long it has been running, the last
  thing it said and how long ago.
- `waiting` is an assignment the next tick will pick up, with what it is waiting
  on.
- `stuck` is the board's temporary presentation of an assignment in fault after
  two consecutive errored rounds, with where to read what happened.
- `queued` is the labelled issues not dispatched yet, each with the reason it
  has not gone.
- `done` is the assignments whose wrap-up round succeeded.

Three assignments at one issue read as three assignments at one thing, so a
label you forgot to remove shows as what it is rather than as three unrelated
rows.

`assignment` shows one issue's newest assignment: what its dispatch settled, the
rounds it has run newest first with each purpose, recovery flag and outcome, the
command that resumes its harness session by hand, and the older assignments at
the same issue.

```sh
dreamcatcher assignment GH123
```

`feed` shows what the agent said, as it says it. It shows every round's feed in
order. A feed is a log rather than a picture of a state, so it is printed as it
is read and you keep your scrollback.

```sh
dreamcatcher feed GH123
```

`--round 2` narrows the feed to one round. One named round is all that view
shows, so it ends when that round ends rather than stay open for the round after
it. The round list of the assignment view is where you find the number.

```sh
dreamcatcher feed GH123 --round 2
```
