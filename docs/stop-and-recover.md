# Stop and recover work

Choose the control that matches what you want to stop. Closing a status
view, stopping one agent round, pausing or ending work, and stopping the
daemon have different consequences.

| Action                                                                         | What stops                                                | What happens next                                                                      |
| ------------------------------------------------------------------------------ | --------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Interrupt a standalone view, such as `web`, `status` or `feed`                 | Only that view                                            | The daemon and agents continue.                                                        |
| Run `dreamcatcher stop` or select **stop round** on the web page               | The current agent round                                   | The work waits for something new unless a merged or closed pull request needs wrap-up. |
| Run `dreamcatcher cancel` or select **cancel assignment** on the web page      | The assignment and any running round                      | You finish the pull request by hand. _dreamcatcher_ runs no further rounds.            |
| Remove a conversation's or campaign's label, or unassign its issue             | No new round starts; a running round finishes             | Put back what you removed to resume the work in the same session.                      |
| Close a conversation's issue or a campaign's parent issue                      | The work, once a running round finishes                   | Nothing more. Reopening the issue with its label starts new work.                      |
| Press Ctrl-C in the terminal running `dreamcatcher run`, or end it with `kill` | The daemon, its current rounds and the web page it serves | Work that still needs a round can run again after the daemon starts again.             |

## Stop one running round

Run `stop` with the issue:

```sh
dreamcatcher stop GH123
```

When the issue has more than one piece of agent work, such as a
conversation under a label you switched away from, the command stops
nothing and prints a command for each piece, with the agent work
identifier that selects it. Run the one for the work you want to stop.
You can instead open the work in the web page that `run` opened, select
**stop round**, and confirm. If you ran the daemon with `--noweb`, start
`dreamcatcher web` first. Both controls are available only while the
round is running and _dreamcatcher_ has learned its harness session. The
round normally stops within about a second.

After an assignment round is stopped, an open pull request waits for a
new comment or review from you. Once it is ready for review, it also
waits for its branch to fall behind or a check to fail at a new commit.
Add that feedback when you are ready to resume. If you merge or close
the pull request instead, its wrap-up can start without a new post. If
you stop the wrap-up round itself, the assignment stays open with no
round due; cancel it when you no longer want the agent on it.

After a conversation round is stopped, post a new eligible issue comment
to resume the discussion. The next round answers that input; the stopped
round's comments are not given again.

After a campaign round is stopped, the lead waits. Comment on the parent
issue with fresh direction to resume it. A sub-issue that changes in a
way the lead needs to hear of also wakes it, for example when a
sub-issue's pull request is ready for review. Either way, the next round
tells the lead that you stopped its previous round.

Removing an assignment label does not stop an active assignment. To
pause or end a conversation or a campaign, follow
[Pause, resume or end a conversation](discuss-an-issue.md#pause-resume-or-end-a-conversation)
or
[Pause or end a campaign](start-a-campaign.md#pause-or-end-a-campaign).

## Take over an assignment's pull request

Cancel an assignment when you want to finish its pull request yourself.
Run:

```sh
dreamcatcher cancel GH123
```

When the issue has more than one piece of agent work, the command
cancels nothing and prints a command for each piece, with the agent work
identifier that selects it. Each identifier ends with the kind of its
work, so run the one for the assignment that you want to cancel. You can
instead open the assignment in the web page that `run` opened, select
**cancel assignment**, and confirm. If you ran the daemon with
`--noweb`, start `dreamcatcher web` first. A cancel cannot be undone.

_dreamcatcher_ asks a running round to stop, runs no further rounds for
the assignment, and stops relaying your comments and reviews on its pull
request. The assignment's card on the web home page, its page and
`dreamcatcher view` show **cancelled**, and `dreamcatcher status` counts
it among the ended assignments.

Carry on in the assignment's worktree, which still has the branch
checked out. Once no round is running, and when _dreamcatcher_ has
learned the agent's harness session, the assignment page shows the
worktree and the command that resumes that session by hand.

_dreamcatcher_ leaves the pull request as it is, and while it is open it
claims the issue as work outside _dreamcatcher_. If you merge it, GitHub
closes the issue. If you close it without merging, the issue can receive
a new assignment while it keeps its assignment label and stays assigned
to you.

## Restart an interrupted daemon

Pressing Ctrl-C in the `dreamcatcher run` terminal shuts the daemon
down, ends the rounds it owns and stops the web page it serves. On macOS
and Linux, closing that terminal, ending the daemon with `kill`, or
shutting the machine down does the same. A daemon started under `nohup`
keeps running when its terminal closes.

The daemon also stops by itself when an update cannot read or write a
file under `.dreamcatcher/` that it needs, for example because the disk
is full or a record is damaged. It prints the file and what is wrong
with it, and ends its rounds and its web page as Ctrl-C does. Fix the
cause before you start it again.

Start the daemon again from the same main checkout:

```sh
dreamcatcher run --harness claude
```

Repeat any non-default `--interval` and `--max-agents` values you want;
those are options for each daemon run, not saved configuration. On
startup _dreamcatcher_ also detects rounds orphaned by an earlier daemon
and records them as interrupted.

Unless the work is held, the interrupted work carries on in a later
round, normally in the same harness session, so you do not need to use
the hand-resume command. That round also takes up any comments or
reviews you posted meanwhile, and a lead sees the current state of its
sub-issues and what changed among them. You don't need to repeat
anything that happened while the work was interrupted.

## Recover from errors and faults

After one errored round, the next round carries on the work in the same
way as after an interrupted round, and unrelated work can continue. A
round can error before its agent starts, for example when it cannot push
an assignment's branch, and that counts the same way. Two consecutive
errored rounds put that piece of work in **fault** so _dreamcatcher_
does not repeat the same failure forever.

A conversation round that errored is given its comments again only while
they are still on the issue. If you delete them before the next update,
the conversation becomes idle once that update finds nothing to answer,
and a new comment starts its next round.

Read the detail and feed to find the cause:

```sh
dreamcatcher view GH123
dreamcatcher feed GH123
```

Fix the underlying problem first: for example, restore a missing
credential, repair a project setup command or make a required service
available. Then clear the fault so that the work can run again:

```sh
dreamcatcher retry GH123
```

`retry` preserves the errored rounds for diagnosis. It clears the fault
of the one piece of agent work that it selects, as `stop` selects it,
and reports work that is not in fault. It does not start an agent
itself; on a later scheduler update the daemon may start the work's next
round, which carries on the work as after an interrupted round.

You can instead open the faulted work in the web page that `run` opened,
and select **Retry**. If the daemon is stopped or ran with `--noweb`,
start `dreamcatcher web` first. The control is available while the page
shows that work's status as fault, and it clears the fault of that one
piece of work in the same way. The page records the request even while
the daemon is stopped, and the next round can start once the daemon runs
again.

Repeated failures across multiple work items can trigger a 15-minute
global cooldown. _dreamcatcher_ keeps reporting status but starts no
agent rounds during the cooldown. It survives a daemon restart and
clears the current faults when it ends. A manual retry request still
waits until an active cooldown is over.

For exact retry syntax and error conditions, see the
[`retry` command reference](command-reference.md#retry).
