# Command reference

_dreamcatcher_'s command-line program is `dreamcatcher`. Run operational
commands from the repository checkout that they concern. `init` and `run`
require the main checkout; every other command requires the checkout in which
_dreamcatcher_ has already created local state.

```text
dreamcatcher [--version] <command> [options]
```

`-h` or `--help` shows help for the program or the command that precedes it.
`--version` prints the installed _dreamcatcher_ version. A command returns
status 1 for an operational error that _dreamcatcher_ can explain, or status 2
for invalid command-line syntax.

Issue arguments use `GH<n>`, where `<n>` is a string of decimal digits. The `GH`
prefix is case-insensitive, so `GH123` and `gh123` both name issue 123.

| Command        | Purpose                                              |
| -------------- | ---------------------------------------------------- |
| `init`         | Prepare this repository's main checkout.             |
| `run`          | Run the daemon for this repository.                  |
| `retry`        | Allow faulted work at one issue to recover again.    |
| `stop`         | Stop one running assignment or conversation round.   |
| `cancel`       | Cancel one issue's newest assignment.                |
| `web`          | Serve the local status report in a browser.          |
| `status`       | Show the whole local status report in the terminal.  |
| `assignment`   | Show one issue's newest assignment.                  |
| `conversation` | Show one issue conversation.                         |
| `feed`         | Follow an assignment or conversation's agent output. |

## `init`

```text
dreamcatcher init
```

Prepare the main checkout in the current directory for `run`. The command takes
these steps in order, and prints what it finds as it goes:

1. Check that the current directory is a repository's main checkout.
2. Check that `gh` can name the repository and the account it is signed in as,
   and that the account can push to the repository.
3. Check that Git has an identity to commit with, and fetch `origin main`.
4. Find which of `claude` and `codex` are on `PATH`, and refuse when neither is.
5. Write the
   [default configuration](configuration-reference.md#complete-example) to
   `dreamcatcher.toml` when the file does not exist, with the recipes of each
   harness that is not on `PATH` commented out. An existing file is never
   changed.
6. For each harness that `dreamcatcher.toml` uses, check that it is signed in,
   then install the [`dream` plugin](https://github.com/alimanfoo/dream) for the
   user.
7. Create each label in `dreamcatcher.toml` that the repository lacks, matching
   names case-insensitively. Existing labels are not changed.
8. Print the next steps, including the commands that commit and push
   `dreamcatcher.toml` when `origin/main` does not hold it as the checkout has
   it.

The command stops at the first step that fails, and says how to fix it. It also
refuses when `dreamcatcher.toml` uses a harness that is not on `PATH`. Every
step leaves alone what is already in place, so running the command again is
safe, and repeats the checks.

Installing the plugin changes the user's own Claude Code or Codex settings, not
the repository. The command never commits or pushes.

## `run`

```text
dreamcatcher run --harness {claude,codex} [--interval SECONDS] [--max-agents N]
```

Run the daemon in the foreground for the repository whose main checkout is the
current directory. A second daemon refuses to start while one already runs in
that checkout. Interrupting the command stops its running agent rounds and ends
the daemon.

The command reads `dreamcatcher.toml`, identifies the repository and the account
authenticated through `gh`, checks the required harness programs, and then runs
one scheduler update per interval. See the
[configuration reference](configuration-reference.md) for the file format and
harness-selection rules.

| Option               | Required | Default | Accepted value and effect                                                                                                                                    |
| -------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--harness`          | Yes      | None    | `claude` or `codex`. This is the preferred harness for routes that configure both. A route with only one dispatch recipe uses that recipe's harness instead. |
| `--interval SECONDS` | No       | `120`   | A positive integer number of seconds between checks for work. The maximum is platform-dependent; an out-of-range value reports the allowed maximum.          |
| `--max-agents N`     | No       | `1`     | A positive integer. This is the shared maximum number of assignment and conversation rounds that may run at once.                                            |

The named harness and every harness configured on any route must be installed on
`PATH`, even when a single-harness route would override the command's preferred
harness. Existing assignments and conversations keep the harness saved when they
were created; changing `--harness` affects only newly created agent work.

## `retry`

```text
dreamcatcher retry GH<n>
```

Record a retry request for any currently faulted work at the issue. The command
checks the newest assignment and the issue conversation independently and
requests another recovery for each one that is in fault. It preserves the failed
round records.

At least one of those two items must currently be in fault. Otherwise the
command reports that the issue has no agent work in fault. A successful request
makes the named work available for recovery on a later scheduler update, outside
any active global cooldown; it does not start a round itself. The web page's
retry control writes the same request for the one assignment or conversation it
shows.

## `stop`

```text
dreamcatcher stop GH<n> (--assignment | --conversation)
```

Request a stop for the current round of the selected agent work. The
`--assignment` option selects the newest assignment at the issue, and
`--conversation` selects the issue conversation.

The round must be running under the daemon, have a resumable harness session,
and have no pending stop request. The command writes the same local stop request
as the web control and does not contact GitHub.

## `cancel`

```text
dreamcatcher cancel GH<n>
```

Cancel the newest assignment at the issue, so that you can finish its pull
request by hand. _dreamcatcher_ runs no further rounds for the assignment and
relays no further posts from its pull request. If a round is running, the
command asks it to stop, without the conditions that `stop` requires.

_dreamcatcher_ leaves the pull request as it is, and while it is open it claims
the issue as work outside _dreamcatcher_. The worktree and branch stay in place,
so you can carry on in the assignment's worktree. The cancelled assignment shows
as **cancelled** on the web home page and in `dreamcatcher assignment`, and
`dreamcatcher status` counts it among the ended assignments.

The issue must have an assignment, and that assignment must not have ended. A
cancel cannot be undone. The command writes only local state, does not contact
GitHub, and works whether or not the daemon is running.

## `web`

```text
dreamcatcher web [--port PORT]
```

Serve the current checkout's local status on `127.0.0.1`, open the address in
the default browser, print the address, and continue serving until interrupted.
The server reads local _dreamcatcher_ state and does not contact GitHub. It
works when the daemon is stopped as well as while it is running.

With no option, _dreamcatcher_ derives a stable starting port in the range
8100–8499 from the recorded `owner/name` repository identity, then uses the
first free port at or above it, up to 65535. State with no repository record
starts at 8100.

`--port PORT` requires one exact port. `PORT` must be a positive integer no
greater than 65535. The command fails instead of choosing another port if that
port is already in use.

## `status`

```text
dreamcatcher status
```

Show the repository and daemon facts, issue conversations, assignments, failed
assignment setups, available issues in dispatch order, blocked issues, and
assignment routing conflicts.

In an interactive terminal the view refreshes and occupies the terminal until
interrupted. When output is piped, redirected or captured, it prints one
snapshot and returns.

## `assignment`

```text
dreamcatcher assignment GH<n>
```

Show the newest assignment at the issue. The view includes its settled route and
harness settings, its rounds, a hand-resume command when one is available, and
older assignments at the same issue.

In an interactive terminal it refreshes until the assignment ends, after a
successful wrap-up or a cancel. An ended assignment remains on screen. When
output is piped, redirected or captured, it prints one snapshot and returns.

## `conversation`

```text
dreamcatcher conversation GH<n>
```

Show the issue conversation's settings, harness session, worktree, code revision
and rounds, with a hand-resume command when one is available.

In an interactive terminal it refreshes while the status report lists the
conversation. When output is piped, redirected or captured, it prints one
snapshot and returns.

## `feed`

```text
dreamcatcher feed GH<n> (--assignment | --conversation) [--round N]
```

Show the agent actions and output recorded for one kind of work at the issue.
Exactly one owner selector is required:

- `--assignment` selects the newest assignment at the issue.
- `--conversation` selects the issue conversation.

Without `--round`, the command shows all of that work's rounds and follows later
output until an assignment ends or the status report stops listing a
conversation. `--round N` selects one exact integer round number and ends when
that round ends. The corresponding `assignment` or `conversation` view lists the
available round numbers; requesting a round that does not exist is an error.

A feed prints incrementally so terminal scrollback is preserved. When its output
is piped, redirected or captured, it prints the currently recorded output once
and returns.
