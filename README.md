# dreamcatcher

dreamcatcher watches a repository for labelled issues and dispatches agents to
configured issue conversations and coding assignments. It carries each
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

[[conversation]]
label = "agent:conversation"

[conversation.claude]
prompt = "Answer questions on GH{issue}."
model = "opus[1m]"
effort = "high"

[conversation.codex]
prompt = "Answer questions on GH{issue}."
model = "gpt-5.6-sol"
effort = "high"

[[assignment]]
label = "dream:smith"
[assignment.claude]
prompt = "/dream:smith GH{issue}"
model = "opus[1m]"
effort = "xhigh"
[assignment.codex]
prompt = "$dream:smith GH{issue}"
model = "gpt-5.6-sol"
effort = "xhigh"
```

`assignee` is whose issues to pick up, as a GitHub login. It defaults to `@me`,
the account `gh` is signed in as, so you can leave it out.

If an existing `dreamcatcher.toml` contains `interval` or `max_agents`, remove
those settings. Add `--interval` or `--max-agents` to the `run` command to keep
any non-default values; the configuration file no longer accepts them.

An `[[assignment]]` entry defines one assignment route. Give it an assignment
label, then a dispatch recipe for each harness that can run it. Every route
needs its label and at least one recipe.

- `prompt` is what the harness is asked to do. `{issue}` becomes the issue's
  number, so `/dream:smith GH{issue}` reaches the assignment as
  `/dream:smith GH123`.
- `model` and `effort` are passed to the harness as it starts.

Write both recipes for a label either harness can run. Write one recipe for a
label that belongs to one harness, and issues carrying it always go there.

Point `prompt` at an [assignment skill](CONTRACT.md) that meets the contract.

Each optional `[[conversation]]` entry defines one conversation route. It
watches a conversation label for questions on open issues assigned to the
account `gh` is signed in as. Give each route one or more dispatch recipes with
the same `prompt`, `model` and `effort` fields. When both recipes exist,
`run --harness` chooses one; when only one exists, that harness runs regardless
of the command-line choice. Repeat the entry to offer different conversation
labels, prompts, models, or harnesses.

Assignment routes and conversation routes are both dispatch routes. Each
dispatch route maps one dispatch label to one dispatch recipe per harness that
the route configures. A label can belong to only one route, so the same label
cannot configure both an assignment and a conversation.

An issue carrying more than one configured assignment label or more than one
configured conversation label has a routing conflict for that kind of work.
Dreamcatcher reports the conflict and starts or recovers nothing of that kind
until you remove all but one of those labels. One assignment label and one
conversation label may coexist. Route order gives no label precedence.

The label, harness, and settings that start a conversation are frozen into its
record. Replacing that label with another configured conversation label makes
the saved session eligible again without changing its route or recipe. The
prompt says what answer to produce, so a plain sentence is enough, though it can
name a suitable skill when one is available. The prompt may use `{issue}` and
must follow the
[issue-conversation contract](CONTRACT.md#issue-conversation-instructions).

A conversation agent can investigate the code and make issue changes that the
signed-in user's comment requests, such as filing and linking a subissue. It
cannot implement a change, mutate Git, open or change a pull request, or post
its conversation reply itself. Dreamcatcher publishes that reply after the round
finishes.

## Commands

`run` is the daemon. Start it from the repository's main checkout, and name the
harness requested for new agent work. An existing assignment or conversation
keeps its saved harness. The daemon keeps going in the foreground, scheduling
conversations and assignments.

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

The daemon runs one scheduler tick per interval and starts rounds until the
agent cap is full, no ready work remains, or a launch failure stops that kind
until the next tick. An issue receives an assignment when it carries exactly one
assignment label, is assigned to `assignee`, has no assignment here already, has
no open pull request GitHub links to it, and has no open issue blocking it. The
oldest such issue goes first. Assignment setup cuts a branch and a worktree
under `.dreamcatcher/`, makes and pushes an empty commit, and opens a linked
draft pull request before it runs the assignment's first round there.

Assignment setup is recoverable. If Dreamcatcher stops after making the
worktree, commit, remote branch, or pull request, the next assignment setup
attempt reuses those artifacts and finishes the same assignment instead of
opening another pull request. If setup completes but the first round cannot
start, the recorded assignment keeps its branch and pull request, and the next
tick tries that first round again before it schedules ordinary work.

The daemon lock lives at `.dreamcatcher/daemon.pid`, where every state format
shares it. All format-specific state lives under `.dreamcatcher/v4/` in the
checkout. The top-level directory ignores itself, so git never sees any of this
state. `scheduler.json` in the versioned root says what the most recent
completed scheduler tick observed and decided, including every round that it
started in launch order and what the daemon could not do. It also preserves any
active global cooldown and the end of the most recent one. A scheduler tick that
cannot complete reports its failure in the daemon output and leaves that last
complete record in place.

This is an intentional format break. Version 4 starts with empty local state.
Stop the daemon and upgrade only when no saved agent work needs preserving.

Open assignments go before new assignments. A round that did not finish is
recovered, a merged or closed pull request gets a wrap-up round, and a pull
request you have posted on gets a round that addresses your feedback. Issue
conversation recovery goes before new conversation comments. When assignment
work and an issue conversation are both ready, the daemon alternates which kind
receives each free agent slot.

With one or more `[[conversation]]` entries configured, the daemon also watches
assigned open issues carrying exactly one matching label. The issue title and
body alone do not start an agent. Once the signed-in account posts an ordinary,
unmarked issue comment, Dreamcatcher freezes the issue and trusted comment
history, creates a detached worktree at the fetched main revision, and runs one
round. The round shares the daemon's agent cap and global cooldown with
assignments. The round marks its final Markdown as Dreamcatcher output and posts
it back to the issue. `NO_REPLY` finishes without a post. A failed post makes
the round errored. A later eligible comment resumes the same session with only
the new comments and updates its worktree to current main without asking the
user to clean up investigation files.

Closing the issue, removing every matching conversation label, adding a second
matching label, or removing the signed-in account as assignee stops comment
collection. Dreamcatcher keeps the saved conversation, and comments posted while
the issue is ineligible become available if it becomes eligible again. A running
round may finish and publish its answer.

Every round records its number, purpose, whether it is recovering an earlier
round, and its outcome. Purpose and recovery are independent: for example, a
failed wrap-up is followed by a recovery round whose purpose is still `wrap up`,
while every issue conversation round has the `discuss` purpose.

Rounds die with the daemon. When `run` starts, it records any round orphaned by
an earlier daemon as interrupted. The next assignment round recovers that work
from where it stopped. While its issue remains eligible, an issue conversation
recovery reuses the interrupted or errored round's saved comments and revision
without collecting new comments or updating its worktree. It resumes the same
harness session when one was recorded; if the first invocation ended before
recording one, it starts again with the configured prompt and that same saved
input.

One errored round receives an ordinary recovery opportunity and does not stop
unrelated work. Two consecutive errored rounds put that assignment or
conversation in fault; any non-errored round breaks the sequence. When two
pieces of agent work that remain in the status report are in fault, in either
combination, the scheduler starts a fifteen-minute global cooldown and starts no
agent work during it. The scheduler keeps observing and reporting while it
waits. The cooldown survives a daemon restart, and its end clears the faults so
that recovery can continue.

If work remains in fault because of a problem specific to its issue, fix the
problem and request another recovery attempt:

```sh
dreamcatcher retry GH123
```

This keeps the failed round records for diagnosis and clears any current fault
on the newest assignment and issue conversation. The affected work becomes
eligible for recovery on the next scheduler tick outside a global cooldown. If
its next two rounds both fail, it enters fault again.

Only a successful wrap-up completes an assignment. A failed or interrupted
wrap-up remains open for recovery. Once the wrap-up succeeds, the assignment no
longer claims its issue, so an issue whose pull request closed unmerged may
receive another assignment while the assignment label is still on it.

Removing the label prevents another assignment after the current one completes.

One daemon watches one repo. A second `run` on the same repo refuses while the
first is alive.

The `web` verb serves the status report on the loopback interface and opens it
in your default browser. It reads the local `.dreamcatcher/` directory, never
contacts GitHub and works whether or not the daemon is running.

While a round runs, its assignment or conversation page offers a stop control
once the harness session is known. The running round stops within about a
second. An open assignment then waits for a new pull-request post, and a
conversation waits for a new issue comment, before it starts another round in
the same session. Merging or closing the assignment's pull request starts its
wrap-up round without waiting for a post.

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
interrupt it. Detail and feed views run until the selected work completes,
enters fault or leaves the status report, and you can interrupt either one
sooner. If you pipe, redirect or capture a view, it shows the current state once
and returns.

```sh
dreamcatcher status
```

`status` starts with the repository name, then shows the instance, its issue
conversations and agent assignments, any failed assignment setups, the available
issues in dispatch order, and issues with open blockers.

An issue conversation is working, waiting, idle, fault or unknown. It is listed
from the first tick that sees its issue eligible, before its first round, and
leaves the list once the issue is ineligible and no round runs. A conversation
that has answered its comments is idle, since it asks nothing of you.

`assignment` shows one issue's newest assignment: its issue identifier, agent
assignment identifier, harness session identifier, what its assignment dispatch
settled, the rounds it has run newest first with each purpose, recovery flag and
outcome, the command that resumes its harness session by hand, and the older
assignments at the same issue.

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
