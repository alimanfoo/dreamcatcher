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

`assignee` is whose issues to pick up, as a GitHub login. It defaults to `@me`,
the account `gh` is signed in as, so you can leave it out.

If an existing `dreamcatcher.toml` contains `interval` or `max_agents`, remove
those settings. Add `--interval` or `--max-agents` to the `run` command to keep
any non-default values; the configuration file no longer accepts them.

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

`--interval` sets the seconds between one look at GitHub and the next, and
defaults to 120. `--max-agents` sets how many agent rounds may run at once, and
defaults to 1. These options apply to this run, so each person can choose them
without changing the repository's shared configuration.

For example, run every 30 seconds and allow four agent rounds at once:

```sh
dreamcatcher run --harness claude --interval 30 --max-agents 4
```

The daemon looks once per interval and launches at most one round. An issue is
dispatched when it carries exactly one dispatch label, is assigned to
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

The daemon lock lives at `.dreamcatcher/daemon.pid`, where every state format
shares it. Everything else the daemon owns lives under `.dreamcatcher/v3/` in
the checkout. The top-level directory ignores itself, so git never sees any of
this state. `scheduler.json` in the versioned root says what the most recent
completed look observed and decided, including what the daemon did not do and
why. It also preserves any active global cooldown and the end of the most recent
one. A look that cannot complete reports its failure in the daemon output and
leaves that last complete record in place. When state from an earlier format
remains at the top level, startup says that it can be deleted.

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

If one assignment remains in fault because of a problem specific to that work,
fix the problem and request another recovery attempt:

```sh
dreamcatcher retry GH123
```

This keeps the failed round records for diagnosis, clears the current fault, and
makes the assignment eligible for recovery on the next scheduler tick outside a
global cooldown. If its next two rounds both fail, it enters fault again.

Only a successful wrap-up completes an assignment. A failed or interrupted
wrap-up remains open for recovery. Once the wrap-up succeeds, the assignment no
longer claims its issue, so an issue whose pull request closed unmerged is free
to dispatch again while the label is still on it.

Removing the label is how you say stop.

One daemon watches one repo. A second `run` on the same repo refuses while the
first is alive.

The CLI has three read-only views: `status`, `assignment` and `feed`. Each view
reads the local `.dreamcatcher/` directory and never contacts GitHub.

Every view refreshes automatically in a terminal. `status` runs until you
interrupt it. `assignment` and `feed` run until the assignment completes or
enters fault, and you can interrupt either one sooner. If you pipe, redirect or
capture a view, it shows the current state once and returns.

```sh
dreamcatcher status
```

`status` starts with the repository name, then shows the instance, its agent
assignments, any failed assignment setups, and the available issues in dispatch
order.

`assignment` shows one issue's newest assignment: its issue identifier, agent
assignment identifier, harness session identifier, what its dispatch settled,
the rounds it has run newest first with each purpose, recovery flag and outcome,
the command that resumes its harness session by hand, and the older assignments
at the same issue.

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
