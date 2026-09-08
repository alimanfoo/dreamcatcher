# Requirements: the watch tower

## What this phase is for

Dreamcatcher dispatches agents and they work unattended, which means the only
way to know what is happening is to look. This phase is about looking: making
the views easy to reach, keeping them on the screen while the work goes on, and
making them cheap enough to keep there.

The skeleton phase built the views and proved they show the right things. This
phase is feedback from actually using them.

## What's wrong with what we have

**One verb is doing four jobs.** `dreamcatcher scry` shows the board.
`scry GH123` shows one session. `scry GH123 --round 2` shows one round's feed.
`scry GH123 --follow` follows the live feed. Those are four different views, and
the flags that select them don't all apply to each other — `--follow` without an
issue means nothing, so the CLI carries a hand-written function whose only job
is to refuse that combination. One `--help` lists flags that apply to only part
of what it documents. The code already knows these are four things: `scry.py`
has `show_board`, `show_session`, `show_round` and `show_feed`. Only the command
line pretends otherwise.

**Every view is a snapshot.** You run it, you read it, it exits. But the moment
you most want a board is while an agent is working, and then what you want is a
board that stays up and keeps current. Today you get that with
`watch dreamcatcher scry`, which is fine on macOS and Linux and has no
equivalent on Windows. Dreamcatcher treats Windows as first-class, so a view
that only refreshes for some of us is a view that doesn't refresh.

**The reads are too expensive to repeat.** Building the board reads every
session's record and every round record beneath it — every session the repo has
ever run, finished or not. Following a feed re-reads every round's feed file
from the start each second, rebuilds the rendering for every line in it, and
then prints only the few at the end that are new. Once per invocation this is
invisible. Once per second it is the thing that decides whether a live view
works at all.

## What it has to do

- **Three commands, one view each**, named for what they show. Each command's
  arguments all apply to that command, so its own `--help` is a complete
  description and argparse's own errors are enough.

- **Live without asking.** Running a view is enough to get one that keeps up. No
  flag to remember, no `watch` to wrap it in, no difference between platforms.

- **A view left open stays useful.** A feed that stops when the current round
  ends makes you run the command again every time the next round starts, which
  is the whole complaint in #94. A view should outlive the round it opened on
  and end only when the session it is watching has.

- **Still usable when nothing is watching.** A view that never returns can't be
  piped, redirected, captured in a log, or pasted into an issue. There has to be
  a way to get a snapshot, and it shouldn't cost the reader a decision.

- **Refresh cost proportional to what changed**, not to what the repo has ever
  done. A repaint on a repo with a hundred finished sessions should cost roughly
  what a repaint on a repo with one costs.

- **Leave nothing to reach for.** The point of doing this in the tool is that a
  colleague on Windows gets the same thing without a shell trick.

## What limits this

The views read what the daemon left on disk and ask GitHub nothing. That is what
lets them answer while the daemon is wedged or long dead, and it stays true —
the answer to expensive reads is to read less, not to ask someone else.

There is no channel between the daemon and a view, and this phase doesn't add
one. A local socket was considered and cut in the skeleton phase; nothing here
changes that reasoning.

The terminal is the whole interface. Rich is already a dependency and is enough;
this phase adds no TUI framework, no mouse, no panes.

`scry` goes away rather than surviving as an alias. This is a personal tool
before its first release, nobody's scripts depend on the name, and keeping two
ways to run one view is the sort of thing that never gets removed later.

## How we'll know it worked

The board is left open on a second screen while sessions run, because it is the
thing you look at rather than the thing you invoke. Nobody types `watch`. A
colleague on Windows gets the same view without being told a workaround. And a
repo with a long history of finished sessions refreshes as fast as a fresh one.

## What's still open

- **Whether the session view earns a separate command.** Once the board is live,
  a good deal of what the session view adds is detail that a wider board could
  carry. Keeping it is the conservative choice for this phase, but it's worth
  asking again afterwards.

- **How fast to refresh.** One second is what the following feed uses today and
  is the obvious starting point for all three. The board can only change as fast
  as the daemon ticks, except for the live-round detail it shows, which changes
  faster — so a single interval may not be right for both.

- **Retiring a finished session** touches the daemon as well as the views, since
  both walk the same records. This phase has to decide it for both, and it is
  the part most likely to be got wrong first.

- Multi-repo — one place to see every repo's work — stays a later phase, and
  nothing here should make it harder.
