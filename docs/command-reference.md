# Command reference

_dreamcatcher_'s command-line program is `dreamcatcher`. Run operational
commands from the repository checkout that they concern. `init` and
`run` require the main checkout; every other command requires the
checkout in which _dreamcatcher_ has already created local state.

```text
dreamcatcher [--version] <command> [options]
```

`-h` or `--help` shows help for the program or the command that precedes
it. `--version` prints the installed _dreamcatcher_ version. A command
returns status 1 for an operational error that _dreamcatcher_ can
explain, or status 2 for invalid command-line syntax.

Issue arguments use `GH<n>`, where `<n>` is a string of decimal digits.
The `GH` prefix is case-insensitive, so `GH123` and `gh123` both name
issue 123.

`retry`, `stop`, `cancel`, `view` and `feed` act on one piece of agent
work, and take either of two references to it:

- an issue argument, such as `GH123`, selects the one piece of agent
  work at the issue, of any kind, whether or not it has ended;
- an agent work identifier, such as `GH123-20260912-192458-assignment`,
  selects that exact work. It is case-insensitive like an issue
  argument, and it ends with the kind of the work.

Ended work counts, so an issue whose assignment has ended and that now
has a conversation has more than one piece of agent work. When the issue
has more than one piece of agent work, the command changes nothing and
returns status 1. It prints the command again for each piece, with the
identifier that selects it, in identifier order:

```text
$ dreamcatcher stop GH644
GH644 has more than one piece of agent work. Run one of these:
  dreamcatcher stop GH644-20261020-231849-conversation
  dreamcatcher stop GH644-20261021-005621-assignment
```

A reference that names no work is an error. `cancel` acts on an
assignment alone, so it reports that other selected work is not an
assignment.

| Command  | Purpose                                             |
| -------- | --------------------------------------------------- |
| `init`   | Prepare this repository's main checkout.            |
| `run`    | Run the daemon for this repository.                 |
| `retry`  | Allow one piece of faulted work to run again.       |
| `stop`   | Stop one running round of agent work.               |
| `cancel` | Cancel one assignment.                              |
| `web`    | Serve the local status report in a browser.         |
| `status` | Show the whole local status report in the terminal. |
| `view`   | Show one piece of agent work.                       |
| `feed`   | Follow one piece of agent work's output.            |

## `init`

```text
dreamcatcher init
```

Prepare the main checkout in the current directory for `run`. The
command takes these steps in order, and prints what it finds as it goes:

1. Check that the current directory is a repository's main checkout.
2. Check that `gh` can name the repository and the account it is signed
   in as, and that the account can push to the repository.
3. Check that Git has an identity to commit with, and fetch
   `origin main`.
4. Find which of `claude` and `codex` are on `PATH`, and refuse when
   neither is.
5. Write the
   [default configuration](configuration-reference.md#complete-example)
   to `dreamcatcher.toml` when the file does not exist, with the recipes
   of each harness that is not on `PATH` commented out. An existing file
   is never changed.
6. For each harness that `dreamcatcher.toml` uses, check that it is
   signed in, then install the
   [`dream` plugin](https://alimanfoo.github.io/dream/) for the user.
7. Create each label in `dreamcatcher.toml` that the repository lacks,
   matching names case-insensitively. Existing labels are not changed.
8. Print the next steps, including the commands that commit and push
   `dreamcatcher.toml` when `origin/main` does not hold it as the
   checkout has it.

The command stops at the first step that fails, and says how to fix it.
It also refuses when `dreamcatcher.toml` uses a harness that is not on
`PATH`. Every step leaves alone what is already in place, so running the
command again is safe, and repeats the checks.

Installing the plugin changes the user's own Claude Code or Codex
settings, not the repository. The command never commits or pushes.

## `run`

```text
dreamcatcher run --harness {claude,codex} [--interval SECONDS] [--max-agents N] [--noweb]
```

Run the daemon in the foreground for the repository whose main checkout
is the current directory. A second daemon refuses to start while one
already runs in that checkout. The command also opens and serves the web
interface until the daemon ends. Interrupting the command stops its
running agent rounds, ends the daemon, and stops the web server.

The command reads `dreamcatcher.toml`, identifies the repository and the
account authenticated through `gh`, checks the required harness
programs, and then runs scheduler updates, waiting the interval after
each one finishes. See the
[configuration reference](configuration-reference.md) for the file
format and harness-selection rules.

| Option               | Required | Default | Accepted value and effect                                                                                                                                                     |
| -------------------- | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--harness`          | Yes      | None    | `claude` or `codex`. This is the preferred harness for routes that configure both. A route with only one dispatch recipe uses that recipe's harness instead.                  |
| `--interval SECONDS` | No       | `120`   | A positive integer number of seconds to wait after each check for work before the next. The maximum is platform-dependent; an out-of-range value reports the allowed maximum. |
| `--max-agents N`     | No       | `1`     | A positive integer. This is the shared maximum number of agent rounds, of every kind, that may run at once.                                                                   |
| `--noweb`            | No       | Off     | Run the daemon without opening or serving the web interface.                                                                                                                  |

The named harness and every harness configured on any route must be
installed on `PATH`, even when a single-harness route would override the
command's preferred harness. Existing agent work keeps the harness saved
when it was created; changing `--harness` affects only newly created
agent work.

The companion web server uses the same automatic port selection as
`dreamcatcher web`. Use `--noweb` and run the standalone command when
you need an exact port or want the web interface to outlive the daemon.

## `retry`

```text
dreamcatcher retry (GH<n> | IDENTIFIER)
```

Record a retry request for the selected agent work, which clears its
fault. It preserves the failed round records.

The work must currently be in fault. Otherwise the command reports that
it is not in fault; ended work is never in fault. A successful request
lets the work's next round start on a later scheduler update, outside
any active global cooldown; it does not start a round itself. The web
page's retry control writes the same request for the one piece of agent
work it shows.

## `stop`

```text
dreamcatcher stop (GH<n> | IDENTIFIER)
```

Request a stop for the current round of the selected agent work.

The round must be running under the daemon, have a resumable harness
session, and have no pending stop request. The command writes the same
local stop request as the web control and does not contact GitHub.

## `cancel`

```text
dreamcatcher cancel (GH<n> | IDENTIFIER)
```

Cancel the selected assignment, so that you can finish its pull request
by hand. _dreamcatcher_ runs no further rounds for the assignment and
relays no further posts from its pull request. If a round is running,
the command asks it to stop, without the conditions that `stop`
requires.

_dreamcatcher_ leaves the pull request as it is, and while it is open it
claims the issue as work outside _dreamcatcher_. The worktree and branch
stay in place, so you can carry on in the assignment's worktree. An
assignment cancelled before any round opened a pull request has none to
finish; any worktree or branch that a round made also stays in place.
The cancelled assignment's card on the web home page shows
**cancelled**, `dreamcatcher view` shows it as **ended** with the detail
cancelled, and `dreamcatcher status` counts it among the ended
assignments.

The selected work must be an assignment that has not ended. If the
assignment's wrap-up round records its completion first, even as the
command runs, the command says that the assignment has already ended. A
cancel cannot be undone. The command writes only local state, does not
contact GitHub, and works whether or not the daemon is running.

## `web`

```text
dreamcatcher web [--port PORT]
```

Serve the current checkout's local status on `127.0.0.1`, open the
address in the default browser, print the address, and continue serving
until interrupted. The server reads local _dreamcatcher_ state alone,
and does not contact GitHub or read `dreamcatcher.toml`. It works when
the daemon is stopped as well as while it is running.

With no option, _dreamcatcher_ derives a stable starting port in the
range 8100–8499 from the recorded `owner/name` repository identity, then
uses the first free port at or above it, up to 65535. State with no
repository record starts at 8100.

`--port PORT` requires one exact port. `PORT` must be a positive integer
no greater than 65535. The command fails instead of choosing another
port if that port is already in use.

## `status`

```text
dreamcatcher status
```

Show the repository and daemon facts, assignments, issue conversations
and campaigns, and each dispatch label that no open work answers, in
dispatch order, with why no work has started.

In an interactive terminal the view refreshes and occupies the terminal
until interrupted. When output is piped, redirected or captured, it
prints one snapshot and returns.

## `view`

```text
dreamcatcher view (GH<n> | IDENTIFIER)
```

Show the selected agent work's status, recorded route and harness
settings, harness session, worktree and rounds, with a hand-resume
command when one is available. Ended work whose worktree _dreamcatcher_
has removed shows the worktree as removed, and no hand-resume command.
An assignment's view also shows its pull request and branch. A
campaign's `GH<n>` is its parent issue. A paused conversation or
campaign is idle, and its status detail says why.

In an interactive terminal it refreshes until the work ends, as an
assignment does after a successful wrap-up or a cancel. It stays on the
work it selected when it started, even if newer work arrives at the
issue. Ended work remains on screen. When output is piped, redirected or
captured, it prints one snapshot and returns.

## `feed`

```text
dreamcatcher feed (GH<n> | IDENTIFIER) [--round N]
```

Show the agent actions and output recorded for the selected agent work.

Without `--round`, the command shows all of that work's rounds and
follows later output until the work ends. It stays on the work it
selected when it started, even if newer work arrives at the issue.
`--round N` selects one exact integer round number and ends when that
round ends. The `view` of the same work lists the available round
numbers; requesting a round that does not exist is an error.

A feed prints incrementally so terminal scrollback is preserved. When
its output is piped, redirected or captured, it prints the currently
recorded output once and returns.
