# Command reference

Dreamcatcher's command-line program is `dreamcatcher`. Run operational commands
from the repository checkout that they concern. `run` requires the main
checkout; every other command requires the checkout in which Dreamcatcher has
already created local state.

```text
dreamcatcher [--version] <command> [options]
```

`-h` or `--help` shows help for the program or the command that precedes it.
`--version` prints the installed Dreamcatcher version. A command returns status
1 for an operational error that Dreamcatcher can explain, or status 2 for
invalid command-line syntax.

Issue arguments use `GH<n>`, where `<n>` is a string of decimal digits. The `GH`
prefix is case-insensitive, so `GH123` and `gh123` both name issue 123.

| Command        | Purpose                                              |
| -------------- | ---------------------------------------------------- |
| `run`          | Run the daemon for this repository.                  |
| `retry`        | Allow faulted work at one issue to recover again.    |
| `stop`         | Stop one running assignment or conversation round.   |
| `web`          | Serve the local status report in a browser.          |
| `status`       | Show the whole local status report in the terminal.  |
| `assignment`   | Show one issue's newest assignment.                  |
| `conversation` | Show one issue conversation.                         |
| `feed`         | Follow an assignment or conversation's agent output. |

## `run`

```text
dreamcatcher run --harness {claude,codex} [--interval SECONDS] [--max-agents N]
```

Run the daemon in the foreground for the repository whose main checkout is the
current directory. A second daemon refuses to start while one already holds that
repository. Interrupting the command stops its running agent rounds and ends the
daemon.

The command reads `dreamcatcher.toml`, identifies the repository and the account
authenticated through `gh`, checks the required harness programs, and then runs
one scheduler tick per interval. See the
[configuration reference](configuration-reference.md) for the file format and
harness-selection rules.

| Option               | Required | Default | Accepted value and effect                                                                                                                           |
| -------------------- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--harness`          | Yes      | None    | `claude` or `codex`. This is the preferred harness for routes that configure both. A route with only one harness block uses that harness instead.   |
| `--interval SECONDS` | No       | `120`   | A positive integer number of seconds between checks for work. The maximum is platform-dependent; an out-of-range value reports the allowed maximum. |
| `--max-agents N`     | No       | `1`     | A positive integer. This is the shared maximum number of assignment and conversation rounds that may run at once.                                   |

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
makes the named work available for recovery on a later scheduler tick, outside
any active global cooldown; it does not start a round itself.

## `stop`

```text
dreamcatcher stop GH<n> (--assignment | --conversation)
```

Request a prompt stop for the current round of the selected agent work. The
`--assignment` option selects the newest assignment at the issue, and
`--conversation` selects the issue conversation.

The round must be running under the daemon, have a resumable harness session,
and have no pending stop request. The command writes the same local stop request
as the web control and does not contact GitHub. After the round stops, the work
waits for new feedback before the daemon starts another round.

## `web`

```text
dreamcatcher web [--port PORT]
```

Serve the current checkout's local status on `127.0.0.1`, open the address in
the default browser, print the address, and continue serving until interrupted.
The server reads local Dreamcatcher state and does not contact GitHub. It works
when the daemon is stopped as well as while it is running.

With no option, Dreamcatcher derives a stable starting port in the range
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
assignment setups, available issues in dispatch order, and blocked issues.

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

In an interactive terminal it refreshes while another round may be required. It
ends when the assignment completes a successful wrap-up or enters fault; a
completed assignment remains on screen. When output is piped, redirected or
captured, it prints one snapshot and returns.

## `conversation`

```text
dreamcatcher conversation GH<n>
```

Show the issue conversation's settled settings, harness session, worktree, code
revision and rounds.

In an interactive terminal it refreshes until the conversation enters fault, has
a routing conflict, or leaves the status report. When output is piped,
redirected or captured, it prints one snapshot and returns.

## `feed`

```text
dreamcatcher feed GH<n> (--assignment | --conversation) [--round N]
```

Show the agent actions and output recorded for one kind of work at the issue.
Exactly one owner selector is required:

- `--assignment` selects the newest assignment at the issue.
- `--conversation` selects the issue conversation.

Without `--round`, the command shows all of that work's rounds and follows later
output until the work completes, enters fault or leaves the status report. A
conversation's routing conflict also ends its feed view. `--round N` selects one
exact integer round number and ends when that round ends. The corresponding
`assignment` or `conversation` view lists the available round numbers;
requesting a round that does not exist is an error.

A feed prints incrementally so terminal scrollback is preserved. When its output
is piped, redirected or captured, it prints the currently recorded output once
and returns.
