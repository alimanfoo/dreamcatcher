# Design: cancel assignments

## What we're building

A user can cancel an assignment to take over its pull request and finish it by
hand. Dreamcatcher then runs no further rounds for the assignment and relays no
further posts from its pull request. The pull request stays open, and from then
on it claims the issue as work outside Dreamcatcher.

The assignment page offers a cancel control, and `dreamcatcher cancel GH<n>`
cancels the newest assignment at an issue. A cancelled assignment stays in every
view with the status **cancelled**. A cancel cannot be undone, posts nothing on
GitHub and leaves the issue's labels alone.

## How it works

### Cancelling is the second way an assignment ends

An assignment ends when a wrap-up round succeeds, which completes it, or when
the user cancels it. The assignment record gains `cancelled_at`, the time of the
cancel. An assignment is open until it has ended in either way.

Everything that asks whether an assignment is open follows from that one rule.
The scheduler inspects only open assignments, so a cancelled one is never a
candidate for a round. An issue with no open local assignment is not claimed
here, so its cancelled assignment's open pull request counts as a claim from
elsewhere, with the evidence "a pull request is open on it: #N".

If the user merges that pull request, GitHub closes the issue. If the user
closes it without merging, the issue can receive a new assignment once it is
otherwise available, which means it still carries its assignment label and is
still assigned to the user.

### A cancel stops a live round

A cancel asks the assignment's latest round to stop when that round has no
ending yet. It writes the stop request that the stop control already writes, so
the daemon kills the round within about a second. Without the request, a running
round would carry on and could push commits while the user works on the branch.

Unlike the stop control, a cancel needs no harness session, because no feedback
round will follow.

The scheduler reads assignments when a tick begins, then reads GitHub before it
launches anything, so a cancel can land after the read and before a round
starts. The cancel and the scheduler each write first and read second to cover
that case. The cancel writes the record, then reads the rounds again from disk.
The scheduler starts the round, which writes the round's record, then reads the
assignment record again and asks the round to stop if it finds a cancel. Either
the cancel sees the new round or the scheduler sees the cancel. A round started
this way ends as stopped within about a second.

### The worktree stays

A cancel leaves the worktree, branch and assignment directory in place, for two
reasons. The worktree is what makes an assignment exist, so removing it would
remove the assignment from every view. And git refuses to check out a branch in
two worktrees, so the assignment's own worktree is where the user carries on.
The hand-resume command stays on the assignment page, so the user can resume the
agent's session there by hand.

### Status

The new summary status **cancelled** sits beside **complete**. Both mean the
assignment has ended, so both end the live assignment and feed views. A round
still running after the cancel shows as **working** until it ends. A cancelled
assignment shows as cancelled even when its rounds would otherwise put it in
fault.

The web home page's section for complete assignments becomes the section for
ended assignments. It lists complete and cancelled assignments together, newest
ending first. A cancelled assignment ended when it was cancelled. The terminal
status view counts ended assignments in the same way.

### The two controls

Both controls call one function in the assignment boundary, which refuses an
assignment that has already ended, records the time and asks any live round to
stop. Neither needs the daemon to be running.

`dreamcatcher cancel GH<n>` acts on the newest assignment at the issue. It
refuses when the issue has no assignment, or when that assignment has ended.

The assignment page shows a cancel button while the assignment is open. The
button asks for confirmation, because a cancel cannot be undone. It posts to
`/assignments/<identifier>/cancel`, and the server refuses a post whose origin
is not the page's own, as it does for a stop request. A post for an assignment
that has already ended changes nothing. The web process still contacts GitHub
for nothing.

## Why a new concept

Concept economy (E3) asks whether existing concepts compose to this. They do
not. Stopping a round leaves the assignment open, so its next post starts
another round. Removing the assignment label changes nothing once an assignment
exists, because its pull request alone governs its rounds. Closing the pull
request starts a wrap-up round and gives up the user's work. No existing state
lets an assignment end while its pull request stays open.

Issue conversations get no cancel. A conversation has no pull request for the
user to take over, and the ontology gives it no ending. Removing its last
conversation label already makes its future batches and recovery ineligible.

## What changes

The assignment record gains one optional field. State format 5 is unreleased, so
the format keeps its number and needs no migration.

The ontology gains cancelling beside completing, and the cancelled status. The
web process gains a second write, the cancel, through the assignment boundary.
The command reference, the stop-and-recover guide and the review guide describe
the new control.
