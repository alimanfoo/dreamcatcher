# dreamcatcher

dreamcatcher watches a repository for labelled issues, answers configured issue
conversations, dispatches autonomous coding assignments, and carries each
assignment to a pull request for you to review and merge.

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

[conversation]
label = "agent:conversation"
harness = "claude"
prompt = "Answer questions on GH{issue}."
model = "opus[1m]"
effort = "high"

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

Point `prompt` at an [assignment skill](CONTRACT.md) that meets the contract.

The optional `[conversation]` block watches a separate label for questions on
open issues assigned to the account `gh` is signed in as. Issue conversations
currently support Claude only. Their prompt, model and effort are frozen into
each conversation record. The prompt says what answer to produce, so a plain
sentence is enough, though it can name a suitable skill when one is available.
The prompt may use `{issue}` and must follow the
[issue-conversation contract](CONTRACT.md#issue-conversation-instructions).

## Commands

`run` is the daemon. Start it from the repository's main checkout, and name the
harness requested for assignment rounds. Conversation rounds use the harness
saved from their separate configuration. The daemon keeps going in the
foreground, dispatching an assignment per labelled issue.

```sh
dreamcatcher run --harness claude
```

`--interval` sets the seconds between scheduler ticks and defaults to 120.
`--max-agents` sets how many agents may run at once, and defaults to 1. These
options apply to this run, so each person can choose them without changing the
repository's shared configuration.

For example, run every 30 seconds and allow four agents at once:

```sh
dreamcatcher run --harness claude --interval 30 --max-agents 4
```

The daemon runs one scheduler tick per interval and launches at most one round.
An issue is dispatched when it carries exactly one dispatch label, is assigned
to `assignee`, has no assignment here already, has no open pull request GitHub
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
shares it. All format-specific state lives under `.dreamcatcher/v3/` in the
checkout. The top-level directory ignores itself, so git never sees any of this
state. `scheduler.json` in the versioned root says what the most recent
completed scheduler tick observed and decided, including what the daemon did not
do and why. It also preserves any active global cooldown and the end of the most
recent one. A scheduler tick that cannot complete reports its failure in the
daemon output and leaves that last complete record in place.

This is an intentional format break. Version 3 does not migrate assignments from
an earlier format and starts with empty local state. Stop the daemon and upgrade
between dispatch batches, when no assignment needs another round.

Open assignments go before new assignments. A round that did not finish is
recovered, a merged or closed pull request gets a wrap-up round, and a pull
request you have posted on gets a round that addresses your feedback. When
assignment work and an issue conversation are both ready, the daemon alternates
which kind receives the next free agent slot.

With `[conversation]` configured, the daemon also watches assigned open issues
carrying its label. The issue title and body alone do not start an agent. Once
the signed-in account posts an ordinary, unmarked issue comment, Dreamcatcher
freezes the issue and trusted comment history, creates a detached worktree at
the fetched main revision, and runs one Claude round. The round shares the
daemon's agent cap and global cooldown with assignments. Its final Markdown is
saved, marked as Dreamcatcher output and posted back to the issue. `NO_REPLY`
finishes without a post. A failed post is retried from the saved answer without
running Claude again. A later eligible comment resumes the same Claude session
with the current issue title and body and only the comments after the saved
input of the latest round. The worktree stays at its initial revision for these
follow-up rounds.

Closing the issue, removing the conversation label or removing the signed-in
account as assignee stops comment collection. Dreamcatcher keeps the saved
conversation, and comments posted while it is inactive become available if the
issue becomes eligible again. A running round may finish and publish its answer.

Every round records its number, purpose, whether it is recovering an earlier
round, and its outcome (`running`, `successful`, `errored` or `interrupted`).
Purpose and recovery are independent for assignments: for example, a failed
wrap-up is followed by a recovery round whose purpose is still `wrap up`.

Rounds die with the daemon. When `run` starts, it records any round orphaned by
an earlier daemon as interrupted. An assignment's next round recovers that work
from where it stopped. One errored assignment round receives an ordinary
recovery opportunity and does not stop unrelated work. Two consecutive errored
rounds put that assignment in fault; an interrupted or successful round breaks
the sequence. Issue conversations record interrupted and failed rounds but do
not recover them automatically yet.

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

The `web` verb serves the status report on the loopback interface and opens it
in your default browser. It reads the local `.dreamcatcher/` directory, never
contacts GitHub and works whether or not the daemon is running.

```sh
dreamcatcher web
```

The default port is stable for each repository. Dreamcatcher hashes the recorded
`owner/name` into a range of 400 ports starting at 8100, then scans upward for
the first free port. A state directory with no repository record starts at 8100.
Use `--port` to require one port exactly; the command reports an error when that
port is already in use.

```sh
dreamcatcher web --port 8123
```

The CLI also has four terminal read-only views: `status`, `assignment`,
`conversation` and `feed`. Each view reads the local `.dreamcatcher/` directory
and never contacts GitHub.

Every view refreshes automatically in a terminal. `status` runs until you
interrupt it. Detail and feed views run until the selected work finishes or
needs attention, and you can interrupt either one sooner. If you pipe, redirect
or capture a view, it shows the current state once and returns.

```sh
dreamcatcher status
```

`status` starts with the repository name, then shows the instance, its issue
conversations and agent assignments, any failed assignment setups, the available
issues in dispatch order, and issues with open blockers.

`assignment` shows one issue's newest assignment: its issue identifier, agent
assignment identifier, harness session identifier, what its dispatch settled,
the rounds it has run newest first with each purpose, recovery flag and outcome,
the command that resumes its harness session by hand, and the older assignments
at the same issue.

```sh
dreamcatcher assignment GH123
```

`conversation` shows the issue conversation's chosen settings, harness session,
detached worktree, code revision, round outcome and current state.

```sh
dreamcatcher conversation GH123
```

`feed` shows what the selected agent said, as it said it. Name exactly one owner
so an issue with both kinds of work is unambiguous. A feed is a log rather than
a picture of a state, so it is printed as it is read and you keep your
scrollback.

```sh
dreamcatcher feed GH123 --assignment
dreamcatcher feed GH123 --conversation
```

`--round 2` narrows the feed to one round. One named round is all that view
shows, so it ends when that round ends rather than stay open for the round after
it. The selected assignment or conversation view lists its round numbers.

```sh
dreamcatcher feed GH123 --assignment --round 2
```
