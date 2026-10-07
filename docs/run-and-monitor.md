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
second daemon for the same checkout refuses to start.

`run` must start in the main checkout. _dreamcatcher_ stores its local state
under that checkout's `.dreamcatcher/` directory. Use this same checkout when
you continue saved work; another clone has separate local history.

## Open the web home page

In another terminal at the same checkout, run:

```sh
dreamcatcher web
```

_dreamcatcher_ opens the web home page in your browser and serves it on
`127.0.0.1` until you interrupt this command. The page reads the local state
directory and `dreamcatcher.toml`, and does not contact GitHub itself. It still
opens when the daemon is stopped, but then it can show only the last state the
daemon recorded.

Use an exact port when needed:

```sh
dreamcatcher web --port 8123
```

The home page shows daemon facts, any scheduler failures, active and ended
assignments, issue conversations, failed assignment setups, and available or
blocked issues. Open an assignment or conversation to see its rounds and live
feed.

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

The most useful assignment states are:

- **working**: an agent round is running;
- **waiting**: _dreamcatcher_ is waiting to start or decide the next round; the
  accompanying detail says which;
- **needs user feedback**: the pull request is open and no round is required;
- **fault**: repeated errors need attention;
- **complete**: the pull request is closed or merged and wrap-up succeeded; and
- **cancelled**: you took the pull request over, and _dreamcatcher_ no longer
  works on it.

An **idle** conversation has no round due until another eligible comment
arrives. A conversation marked **waiting** may have a round ready or may be
awaiting the next scheduler update; its detail says which. **Unknown** means
_dreamcatcher_ could not establish a current fact; the accompanying detail says
what it could not read.

The [command reference](command-reference.md) gives the complete syntax and
explains when each view ends. For interruption and failures, continue with
[Stop and recover work](stop-and-recover.md).
