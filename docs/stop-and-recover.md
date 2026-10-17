# Stop and recover work

Choose the control that matches what you want to stop. Closing a status view,
stopping one agent round and stopping the daemon have different consequences.

| Action                                                                       | What stops                                                | What happens next                                                              |
| ---------------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Interrupt standalone `web`, `status`, `assignment`, `conversation` or `feed` | Only that view                                            | The daemon and agents continue.                                                |
| Run `dreamcatcher stop` or select **stop round** on the web page             | The current agent round                                   | The work waits for input unless a merged or closed pull request needs wrap-up. |
| Run `dreamcatcher cancel` or select **cancel assignment** on the web page    | The assignment and any running round                      | You finish the pull request by hand. _dreamcatcher_ runs no further rounds.    |
| Press Ctrl-C in the terminal running `dreamcatcher run`                      | The daemon, its current rounds and the web page it serves | Work that still needs a round can run again after the daemon starts again.     |

## Stop one running round

Run the command that selects the work you want to stop:

```sh
dreamcatcher stop GH123 --assignment
dreamcatcher stop GH123 --conversation
```

Use `--assignment` for the newest assignment at the issue, or `--conversation`
for its issue conversation. You can instead open the assignment or conversation
in the web page that `run` opened, select **stop round**, and confirm. If you
ran the daemon with `--noweb`, start `dreamcatcher web` first. Both controls are
available only while the round is running and _dreamcatcher_ has learned its
harness session. The round normally stops within about a second.

After an assignment round is stopped, an open pull request waits for a new
comment or review from you. Add that feedback when you are ready to resume. If
you merge or close the pull request instead, its wrap-up can start without a new
post. If you stop the wrap-up round itself, the assignment stays open with no
round due; cancel it when you no longer want the agent on it.

After a conversation round is stopped, post a new eligible issue comment to
resume the discussion. The next round answers that input; the stopped round's
comments are not given again.

Removing an assignment label does not stop an active assignment. For a
conversation, removing its last matching label stops every future round, but
does not cancel a round already running.

## Take over an assignment's pull request

Cancel an assignment when you want to finish its pull request yourself. Run:

```sh
dreamcatcher cancel GH123
```

The command cancels the newest assignment at the issue. You can instead open the
assignment in the web page that `run` opened, select **cancel assignment**, and
confirm. If you ran the daemon with `--noweb`, start `dreamcatcher web` first. A
cancel cannot be undone.

_dreamcatcher_ asks a running round to stop, runs no further rounds for the
assignment, and stops relaying your comments and reviews on its pull request.
The assignment shows as **ended** with the detail cancelled on the web home page
and in `dreamcatcher assignment`, and `dreamcatcher status` counts it among the
ended assignments.

Carry on in the assignment's worktree, which still has the branch checked out.
Once no round is running, and when _dreamcatcher_ has learned the agent's
harness session, the assignment page shows the worktree and the command that
resumes that session by hand.

_dreamcatcher_ leaves the pull request as it is, and while it is open it claims
the issue as work outside _dreamcatcher_. If you merge it, GitHub closes the
issue. If you close it without merging, the issue can receive a new assignment
while it keeps its assignment label and stays assigned to you.

## Restart an interrupted daemon

Pressing Ctrl-C in the `dreamcatcher run` terminal shuts the daemon down, ends
the rounds it owns and stops the web page it serves. Start it again from the
same main checkout:

```sh
dreamcatcher run --harness claude
```

Repeat any non-default `--interval` and `--max-agents` values you want; those
are options for each daemon run, not saved configuration. On startup
_dreamcatcher_ also detects rounds orphaned by an earlier daemon. It records
them as interrupted, and when the work is eligible a later round is given the
interrupted round's input again. That round normally resumes the recorded
harness session; you do not need to use the hand-resume command.

## Recover from errors and faults

After one errored round, the next round is given the same input again, and
unrelated work can continue. A round can error before its agent starts, for
example when it cannot push an assignment's branch, and that counts the same
way. Two consecutive errored rounds put that assignment or conversation in
**fault** so _dreamcatcher_ does not repeat the same failure forever.

Read the detail and feed to find the cause:

```sh
dreamcatcher assignment GH123
dreamcatcher feed GH123 --assignment
```

For a conversation, replace `assignment` and `--assignment` with `conversation`
and `--conversation`.

Fix the underlying problem first: for example, restore a missing credential,
repair a project setup command or make a required service available. Then clear
the fault so that the work can run again:

```sh
dreamcatcher retry GH123
```

`retry` preserves the failed rounds for diagnosis and clears the fault of the
newest faulted assignment and faulted conversation at that issue. It does not
start an agent itself; on a later scheduler update the daemon may start the
work's next round, given the failed round's input again.

You can instead open the faulted assignment or conversation in the web page that
`run` opened, and select **Retry**. If the daemon is stopped or ran with
`--noweb`, start `dreamcatcher web` first. The control is available while the
page shows that work's status as fault, and it clears the fault of that one
assignment or conversation in the same way. The page records the request even
while the daemon is stopped, and the next round can start once the daemon runs
again.

Repeated failures across multiple work items can trigger a 15-minute global
cooldown. _dreamcatcher_ keeps reporting status but starts no agent rounds
during the cooldown. It survives a daemon restart and clears the current faults
when it ends. A manual retry request still waits until an active cooldown is
over.

For exact retry syntax and error conditions, see the
[`retry` command reference](command-reference.md#retry).
