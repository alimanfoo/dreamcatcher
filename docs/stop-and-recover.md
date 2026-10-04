# Stop and recover work

Choose the control that matches what you want to stop. Closing a status view,
stopping one agent round and stopping the daemon have different consequences.

| Action                                                            | What stops                            | What happens next                                                              |
| ----------------------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------ |
| Interrupt `web`, `status`, `assignment`, `conversation` or `feed` | Only that view                        | The daemon and agents continue.                                                |
| Run `dreamcatcher stop` or select **Stop** on the web page        | The current agent round               | The work waits for input unless a merged or closed pull request needs wrap-up. |
| Press Ctrl-C in the terminal running `dreamcatcher run`           | The daemon and all its current rounds | Work that still needs a round can recover after the daemon starts again.       |

## Stop one running round

Run the command that selects the work you want to stop:

```sh
dreamcatcher stop GH123 --assignment
dreamcatcher stop GH123 --conversation
```

Use `--assignment` for the newest assignment at the issue, or `--conversation`
for its issue conversation. You can instead run `dreamcatcher web`, open the
assignment or conversation, and select **Stop**. Both controls are available
only while the round is running and Dreamcatcher has learned its harness
session. The round normally stops within about a second.

After an assignment round is stopped, an open pull request waits for a new
comment or review from you. Add that feedback when you are ready to resume. If
you merge or close the pull request instead, its wrap-up can start without a new
post.

After a conversation round is stopped, post a new eligible issue comment to
resume the discussion. The next round is an ordinary response to that input, not
an automatic recovery of the stopped attempt.

Removing an assignment label does not stop an active assignment. For a
conversation, removing its last matching label makes future batches and recovery
ineligible, but does not cancel a round already running.

## Restart an interrupted daemon

Pressing Ctrl-C in the `dreamcatcher run` terminal shuts the daemon down and
ends the rounds it owns. Start it again from the same main checkout:

```sh
dreamcatcher run --harness claude
```

Repeat any non-default `--interval` and `--max-agents` values you want; those
are options for each run, not saved configuration. On startup Dreamcatcher also
detects rounds orphaned by an earlier daemon. It records them as interrupted and
schedules the next required recovery or wrap-up when the work is eligible.
Recovery normally resumes the recorded harness session; you do not need to use
the hand-resume command.

## Recover from errors and faults

One errored round gets an automatic recovery opportunity, and unrelated work can
continue. Two consecutive errored rounds put that assignment or conversation in
**fault** so Dreamcatcher does not repeat the same failure forever.

Read the detail and feed to find the cause:

```sh
dreamcatcher assignment GH123
dreamcatcher feed GH123 --assignment
```

For a conversation, replace `assignment` and `--assignment` with `conversation`
and `--conversation`.

Fix the underlying problem first: for example, restore a missing credential,
repair a project setup command or make a required service available. Then
request another automatic recovery:

```sh
dreamcatcher retry GH123
```

`retry` preserves the failed rounds for diagnosis and requests recovery for the
newest faulted assignment and faulted conversation at that issue. It does not
start an agent itself; the daemon may recover the work on a later scheduler
tick.

You can instead run `dreamcatcher web`, open the faulted assignment or
conversation, and select **Retry**. The control is available while that work is
in fault, and it requests recovery for that one assignment or conversation in
the same way. It works whether or not the daemon is running.

Repeated failures across multiple work items can trigger a 15-minute global
cooldown. Dreamcatcher keeps reporting status but starts no agent rounds during
the cooldown. It survives a daemon restart and clears the current faults when it
ends. A manual retry request still waits until an active cooldown is over.

For exact retry syntax and error conditions, see the
[`retry` command reference](command-reference.md#retry).
