# Run and monitor dreamcatcher

Run one _dreamcatcher_ daemon from the ordinary main checkout of each repository
you want to watch. Keep it in the foreground so its update reports and failures
remain visible.

Before starting, make sure `dreamcatcher.toml` is present, `gh` is signed in,
and every harness named by the configuration is installed. The setup walkthrough
is in [From issue to pull request](tutorial.md).

## Start the daemon

```sh
dreamcatcher run --harness claude
```

The daemon looks for work immediately, then again every 120 seconds. For a
shorter interval or more concurrent rounds:

```sh
dreamcatcher run --harness claude --interval 30 --max-agents 2
```

The agent capacity is shared by assignments and issue conversations. Start with
one until you know how much agent activity and review work you want at once. A
second daemon for the same checkout refuses to start. The command opens the web
home page in your browser and serves it until the daemon ends. The page reads
the local state directory alone, and does not contact GitHub itself.

`run` must start in the main checkout. _dreamcatcher_ stores its local state
under that checkout's `.dreamcatcher/` directory. Use this same checkout when
you continue saved work; another clone has separate local history.

## Run without the web home page

Use `--noweb` when you want to run only the daemon:

```sh
dreamcatcher run --harness claude --noweb
```

The standalone command gives you manual control of the web server. It also works
when the daemon is stopped, but then it can show only the last state the daemon
recorded:

```sh
dreamcatcher web
```

Use an exact port when needed:

```sh
dreamcatcher web --port 8123
```

The home page shows daemon facts, any scheduler failures, active and ended
assignments and issue conversations, and the labelled issues that have no work
yet, with why: available, blocked by an issue or claimed by a pull request,
waiting for a comment, carrying conflicting labels, or unknown because a read
failed. Open an assignment or conversation to see its rounds and live feed.

## Monitor from the terminal

Use `status` for the whole repository:

```sh
dreamcatcher status
```

Use a detail view for one issue:

```sh
dreamcatcher assignment GH123
dreamcatcher conversation GH123
```

Use `feed` when you want the agent's actions and output in terminal scrollback:

```sh
dreamcatcher feed GH123 --assignment
dreamcatcher feed GH123 --conversation
```

These views refresh automatically in an interactive terminal. Interrupting a
view closes only that view; it does not stop the daemon or the agent. When a
view is piped or redirected, it prints one snapshot and returns.

Assignments and conversations share these statuses:

- **working**: an agent round is running;
- **waiting**: a round is ready to start, and the detail says why;
- **idle**: no round is known to be due; the detail says when the work awaits
  the next update, for an assignment whether its pull request is ready for
  review, still a draft, failing its checks after two attempts, or merged or
  closed after its wrap-up round, and for a conversation how its latest round
  ended, or why the conversation is paused;
- **fault**: repeated errors need attention;
- **unknown**: _dreamcatcher_ could not read what it needed, or the latest
  update has not seen the work; the accompanying detail says which; and
- **ended**: the work is over, and the detail says why: an assignment completed
  after a successful wrap-up or you cancelled it, or a conversation's issue was
  closed.

The [command reference](command-reference.md) gives the complete syntax and
explains when each view ends. For interruption and failures, continue with
[Stop and recover work](stop-and-recover.md).
