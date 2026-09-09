# Design: the watch tower

## What we're building

Three commands where there was one, each showing a single view, each live by
default:

```sh
dreamcatcher board                 # every session and every queued issue
dreamcatcher session GH123         # one issue's newest session, in detail
dreamcatcher feed GH123            # what the agent said, as it says it
dreamcatcher feed GH123 --round 2  # one round of it
```

`scry` goes away. So does `--follow`, because following is what these do.

Nothing about where the views get their information changes. They read what the
daemon left under `.dreamcatcher/` and ask GitHub nothing, which is what lets
them answer when the daemon is wedged or gone. What changes is how the reader
reaches a view, how long it stays, and how much work each refresh costs.

## How it works

### Three verbs

The three verbs map one-to-one onto three functions that already exist:
`show_board`, `show_session`, and `show_feed` — with `show_round` folded into
`show_feed`, since a round is a narrowing of a session's feed rather than a
different view of it.

`board` takes no arguments. `session` and `feed` take an issue, written `GH123`
as today. `feed` additionally takes `--round N`, which narrows it to one round;
the session view's round list is where the reader finds the number.

Every argument now belongs to the command that takes it, which means argparse
can do all the refusing. The mutually exclusive group goes, and so does
`_refuse_a_feed_of_nothing` — the function that exists today only to catch
`--follow` with no issue to follow. A reader who gets an argument wrong gets the
usage line for the one view they asked about, rather than for all four.

Retiring `scry` also settles the note the skeleton design left open, that the
name is charming and opaque. `board`, `session` and `feed` say what they show.

### Live by default

**A view run in a terminal follows. A view whose output is not a terminal
renders once and returns.**

Following is the default because watching is the point. The snapshot was never
what anyone wanted; it was what a one-shot command happened to give. Requiring a
flag to get the useful behaviour puts the cost on the common case.

But a view that follows forever cannot be piped, redirected, or captured, so
something has to distinguish the two situations. The terminal is exactly that
distinction, and using it costs the reader no flag and no thought: interactively
you get a live view, and in a script or a log you get a snapshot, both without
asking. `--once` would be a flag that only ever gets typed when the terminal
check would have been right anyway.

This also happens to be well covered already. Every golden test builds its
console with `force_terminal=False` (`tests/test_scry.py`), precisely so the
output doesn't vary with the shell or the platform — so the whole existing suite
already exercises the render-once path, unchanged. The following path is tested
the way `show_feed` is tested today, with an injected wait.

### When a view returns

**A view follows while there is something to follow, and returns when there
isn't.**

For the board, there is always something: a daemon can start, a tick can
dispatch, a round can begin. So the board follows until the reader interrupts
it.

For `session` and `feed`, there is something to follow until the session can
produce nothing more. Not until the current round ends — a session between
rounds is waiting for its next one, and a reader who left the view open wants to
see that round arrive rather than to run the command again. So these follow
while the session is unfinished, showing each new round as it starts, and stay
open through every gap between rounds, including a gap where the daemon has been
stopped and not started again.

Two standings end such a view, because neither has another round coming: a
session that has run its final round, and a stuck session, which only a person
can move on.

Reading a finished session is not a special mode. It is the same view, arriving
at its end immediately.

`feed --round N` is narrower and returns sooner: one named round is all it
shows, so it returns when that round ends.

**The feed already works this way.** #94 asked for it and landed it in
`show_feed`, whose docstring is where the gaps and the two ending standings are
set out. So this section describes what the feed does and what the board and
session view have yet to do, and part 5 extends the rule rather than inventing
it.

A reader ends a live view by interrupting it, which is how they say they have
seen enough, so it ends without a message.

### Repainting and appending

The board and the session view are pictures of a state, so they are redrawn in
place with rich's `Live`. The feed is a log, so it appends: each pass prints
what arrived since the last one, and the reader keeps their scrollback. Under
`Live` a long feed would be clipped to the height of the screen and everything
above it lost, which is the opposite of what a feed is for.

These are two mechanisms because they are two kinds of thing, not two ways of
doing one thing. A state has a current value. A log has an end.

### Views become renderables

Most `_show_*` helpers print straight to the console. `Live` needs something it
can hold and redraw, so the board and session views become functions that build
a rich renderable holding the sections they compose today — and one small helper
does the following: build, hand to `Live`, wait, build again.

The goldens keep working: rendering that to the same pinned console produces the
same text. They also improve, in that they become assertions about a value
rather than about a side effect.

Some of this has already arrived from another direction: #86 added
`_render_detail`, which returns a renderable rather than printing one, and
brought `Group` into the module with it. So this is extending a pattern the
module already has, not introducing one.

### What a refresh reads

This is where the phase's two other issues live, and they are the same problem
seen twice: both views re-derive everything on every pass.

**The board reads every round the repo ever ran.** `read_sessions` reads each
session's record and, through `_read_session`, eagerly reads every round record
beneath it. Then the board uses almost none of that. On a repo that has run a
hundred sessions, a one-second repaint reads every round record of every session
once a second to answer a question about the newest one.

What makes this fixable is that a round record is written twice and no more.
`RoundRecord` says so itself: it is "written at each end of the round" — once
when the round starts, and once by `Round._close` when its child has gone,
carrying the ending. A round the daemon interrupts is given no ending at all,
and since #50 that means only a round whose child was still running; one that
had already finished keeps the ending `_close` wrote for it. Either way the work
is carried on by a new round, which takes `next_workspace` and so a directory of
its own, never the one an earlier record sits in.

**A round record is complete once it carries an ending. It has had both of its
writes, and nothing writes it again.** `RoundRecord.is_complete` is where that
is written down, and the word is the one to use for it everywhere.

So a reading process keeps every complete record it reads, and on every later
pass reads only:

- a listing of the session's rounds directory, which is what says whether a new
  round has started; and
- the incomplete record of each round of the session.

An incomplete record is read again because the record does not say whether its
ending is still to come. A round that is running will record one, a round that
nothing let finish never will, and both read the same.

That is one directory listing and one small read per session while a round of it
is running, and a listing alone once every one of its rounds is complete,
independent of how many rounds the repo has ever run.

Keeping every record but a session's newest was the other way to read the same
fact, and it is worse on both counts. It never keeps the last record of a
finished session, since no later round displaces it, so a repo of finished
sessions would go on reading one record per session for ever, which is most of
what this is here to stop. And it rests on the order the records read in, so two
rounds that recorded the same start time could leave a running round's record
kept as one still going, for as long as the process lived. Completeness is a
property of the record itself, and rests on nothing else.

A session's rounds are read with the session rather than on demand, because
every view goes through the board, and the board reads where each session stands
from that session's own rounds. Reading them on demand would save nothing while
that holds.

`StateDirectory` is what a process reads the directory through, so that is what
holds the records it has read, in `round_reader`. Whoever holds the directory
holds them, and holds them for as long: the daemon holds one for its whole run,
a view holds one for as long as it stays on the screen, and a process that looks
once lets both go together. So `read_sessions` and `read_board` take what they
always took, nothing has a reader threaded through it, and nothing about how
long to keep one has to be remembered.

This deliberately does not lean on a session being finished. It is tempting to
say that a session whose final round has completed and whose pull request is
merged or closed can never change, and to stop reading it entirely. That is not
quite true: `wakeups._judge_pull_request` only treats a final round as the end
while the pull request is not open, and a closed pull request can be reopened,
which would wake the session for another round. Caching what cannot change needs
no such claim, and is why this design makes none.

For the same reason, `has_run_final_round` — which scans every record for a
final cause — stays as it is. It is answered from records the process already
holds, so the scan costs nothing after the first pass, and its meaning does not
have to be narrowed to make it cheap.

Both the daemon and the views go through `read_sessions`, so both get this. The
daemon's tick has the same complaint for the same reason.

**A following feed re-read every feed file from the start.** `read_feed_lines`
read a whole file and split it, `_compose_feed` did that for every round on
every pass and rebuilt a `Text` for every line, and the pass then printed only
the handful past what it had already shown.

Feed files are append-only, so a following view remembers where it stopped and
reads on from there. `documents.read_lines_from` is that read, and `scry._Feed`
is what holds a position for each round of the session, so a pass reads only
what arrived and paints only what it will print. A round that has ended is read
to its end once, and every pass after that reads nothing from it.

A pass still opens each round's feed rather than closing the ones that have
ended, because nothing a reader can see says that a feed has stopped growing. A
round records its ending as soon as its own child has gone and its feed catches
up afterwards, so a reader that stopped opening a complete round's feed would
lose whatever landed last. An open that reads nothing costs a handful of system
calls, and the reading is what this is here to stop.

One detail this has to get right: a round killed mid-write can leave a line with
no ending on it, and that line has not landed. An incremental read must not
advance its remembered position past such a line, or the line will be lost when
the rest of it arrives. So the position advances to just after the last complete
line ending, never to the end of file.

**The board read a whole feed to take one line off the end.** Every session
standing `agent working` or `needs you` has its row say what its round last
said, and `read_last_feed_line` read the whole file to find it. So a view of one
issue paid for every other session's history, and read the watched session's own
feed twice. `documents.read_last_line` reads the end of the file instead, a
window at a time backwards, so a line longer than one window is found all the
same.

### Cross-platform notes

Remembering a position in a feed file cannot be a count of characters. On
Windows a text-mode read translates line endings, so the number of characters a
reader has seen and the position it should resume from are different numbers. So
the position has to be something the file itself agrees with rather than
something counted while reading. It is a count of bytes, and every read that
takes a part of a file reads the bytes the file holds rather than the text a
text-mode read would make of them.

Rich's `Live` works on Windows terminals, and the console settings the tests
already pin (`legacy_windows=False` among them) keep the rendering identical
across platforms.

Interrupting a live view raises `KeyboardInterrupt` on all three platforms,
which is what ends it.

### Dependencies

None added. Rich is already a dependency and `Live` is part of it.

## What this supersedes in the skeleton design

The skeleton phase's spec stays as the record of what that phase built. Where
this phase changes what it describes, the newer document is the true one:

- `specs/2026-08-17-skeleton/design.md`, "What we're building" — the sentence
  describing `scry` and its three forms.
- The same file, "The feed" — the paragraph describing `--follow` and `--round`
  as the two tenses of the feed view.
- The same file, "The board" — which describes what the board shows but not how
  long it stays.
- The same file, "What's still open" — the note that `scry`'s name is opaque and
  that `status` could arrive as an alias. This phase answers it differently, by
  naming each view for itself.

`README.md` describes the tool as it behaves, so it is corrected when the code
changes rather than when this spec lands.

## What changes, and what goes away

Gone: the `scry` verb; the `--follow` flag; the mutually exclusive group in the
parser; `_refuse_a_feed_of_nothing`; `show_round` as a separate function.

New: three verbs; a terminal check; a following helper; renderable-returning
views; incremental feed reads.

Changed shape, same behaviour: what each view actually shows is unchanged by
this phase. The board still sorts by whose turn it is, the session view still
shows vitals, rounds, the hand-over command and older sessions, and the feed
still renders what the harness said. Several open issues in the skeleton phase
improve the content of those views, and they are independent of this.

## Why it's this and not something else

**Why not keep `scry` as a group of sub-verbs?** `scry board` reads no better
than `board`, costs a word on the thing typed most often, and keeps a name the
skeleton design had already flagged as opaque. The watch tower is a good idea to
have in the documentation and a poor thing to make someone type.

**Why not a `--once` flag instead of the terminal check?** Because it would be a
flag whose only correct uses are the cases the terminal check already covers.
Every situation that needs a snapshot — a pipe, a redirect, a log — is a
situation where the output is not a terminal.

**Why not `Live` for the feed as well, for consistency?** Consistency of
mechanism would cost the reader their scrollback on the one view where the
history is the content.

**Why not have the views ask the daemon, rather than reading files faster?** A
channel between the daemon and its views was considered and cut in the skeleton
phase, and the reason still holds: a view that depends on the daemon cannot
answer the question you most want answered when the daemon is stuck. Reading
less is the cheaper fix and keeps the property.

**Why not leave `watch` to the people who have it?** Because that is a tool that
works for some of us, and the project's first-class support for Windows is not a
preference to trade away for a smaller diff.

## What's still open

- **The refresh interval.** One second is what the following feed uses today. It
  is right for the feed and probably right for the live-round detail on the
  board, but the rest of the board can only change as fast as the daemon ticks.
  A single interval for all three is the simple choice; whether it is the right
  one is worth revisiting once it can be watched.

- **Whether `session` earns its own command.** Once the board is live and
  detailed, much of what the session view adds could be carried by a wider
  board. Keeping it is the conservative choice here.
