# Run and monitor dreamcatcher

Run one _dreamcatcher_ daemon from the ordinary main checkout of each
repository you want to watch. Keep it in the foreground so its update
reports and failures remain visible.

Before starting, make sure `dreamcatcher.toml` is present, `gh` is
signed in, and every harness named by the configuration is installed.
The setup walkthrough is in [Run your first assignment](tutorial.md).

## Start the daemon

```sh
dreamcatcher run --harness claude
```

The daemon looks for work immediately, then waits 120 seconds after each
look before the next. For a shorter interval or more concurrent rounds:

```sh
dreamcatcher run --harness claude --interval 30 --max-agents 2
```

The agent capacity is shared by every kind of agent work. Start with one
until you know how much agent activity and review work you want at once.
A second daemon for the same checkout refuses to start. The command
opens the web home page in your browser and serves it until the daemon
ends. The page reads the local state directory alone, and does not
contact GitHub itself.

`run` must start in the main checkout. _dreamcatcher_ stores its local
state under that checkout's `.dreamcatcher/` directory. Use this same
checkout when you continue saved work; another clone has separate local
history.

## Run without the web home page

Use `--noweb` when you want to run only the daemon:

```sh
dreamcatcher run --harness claude --noweb
```

The standalone command gives you manual control of the web server. It
also works when the daemon is stopped, but then it can show only the
last state the daemon recorded:

```sh
dreamcatcher web
```

Use an exact port when needed:

```sh
dreamcatcher web --port 8123
```

The home page shows daemon facts, any scheduler failures, active and
ended assignments, campaigns and issue conversations, each kind on a tab
of its own, and the dispatch labels that no open work answers, with why:
available; held because an issue blocks it, a pull request is linked to
it, someone else applied the label, the issue carries conflicting
labels, or earlier work used the label's request; idle while it waits
for a comment; or unknown because a read failed or GitHub could not yet
tell. Open a piece of work to see its rounds and live feed.

## Monitor from the terminal

Use `status` for the whole repository:

```sh
dreamcatcher status
```

Use `view` for one piece of agent work:

```sh
dreamcatcher view GH123
```

Use `feed` when you want the agent's actions and output in terminal
scrollback:

```sh
dreamcatcher feed GH123
```

An issue reference selects the one piece of agent work at the issue, of
any kind, whether or not it has ended. When the issue has more than one,
such as an ended assignment and a later conversation, the command prints
a command for each piece, with the agent work identifier that selects
it. Each identifier ends with the kind of its work. Run the one you
want:

```sh
dreamcatcher view GH123-20260912-193000-conversation
dreamcatcher feed GH123-20260912-193000-conversation
```

These views refresh automatically in an interactive terminal.
Interrupting a view closes only that view; it does not stop the daemon
or the agent. When a view is piped or redirected, it prints one snapshot
and returns.

Every kind of agent work shares these statuses:

- **working**: an agent round is running;
- **waiting**: a round is ready to start, and the detail says why;
- **idle**: no round is known to be due. The detail may say that the
  work awaits the next update. For a conversation it can describe the
  latest round. For an assignment or campaign it can describe the pull
  request. An idle draft campaign awaits feedback or sub-issue changes;
- **held**: the detail says how to unblock a conversation or request;
- **fault**: repeated errors need attention;
- **unknown**: _dreamcatcher_ could not read what it needed, or the
  latest update has not seen the work; the accompanying detail says
  which; and
- **ended**: the work is over. In place of the status, the work shows
  how it ended. An assignment or campaign shows **completed** after
  successful wrap-up or **cancelled** after you take over. A
  conversation whose issue closed shows **ended**.

The [command reference](command-reference.md) gives the complete syntax
and explains when each view ends. For interruption and failures,
continue with [Stop and recover work](stop-and-recover.md).
