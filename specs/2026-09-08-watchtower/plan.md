# Plan: the watch tower

This is the third document of the spec. `requirements.md` says what has to be
true, `design.md` says what we're building and how it works, and this breaks
that into parts.

Each part is one pull request. A part section says what is in scope, what proves
it done, and what it deliberately leaves alone. Where a part builds a mechanism,
it names the mechanism and points at the `design.md` section that describes it,
rather than describing it again — otherwise a later change has two places to
correct and only one of them gets corrected.

Every part is meant to be executable without stopping to ask. Where a decision
was needed it has been made and written into `design.md`; where a detail is
genuinely free — which container a renderable is, how a file position is
remembered — the part says so, and whoever builds it chooses. If a part turns
out to need a decision that isn't there, that is a gap in the design, and the
fix is to correct `design.md` in the same pull request and say so.

Every part is reviewed, so every part serves its reviewer:

- Where a part changes rendering, the goldens under `tests/fixtures/` are the
  review surface. Read them as the person running the command would, and judge
  the result rather than deriving it from the code.
- Two parts are cost changes that must not alter a single byte of output. Say so
  in the pull request, and let the unchanged goldens carry the claim.
- Generated files — the `.uncoded/` index in particular — land in the commit
  that caused them, since pre-commit regenerates and fails until they are
  staged. Say which parts of a diff are generated so the reviewer can skip them.

## Part 1: read only what a view needs

The board and the daemon both read every session and every round record beneath
it, for every session the repo has ever run. This makes them read once what
cannot change, and re-read only what can.

In scope:

- Sessions read their rounds on demand rather than eagerly (design.md, What a
  refresh reads).
- A reading process keeps the round records it has read, and on later passes
  reads only a listing of each session's rounds directory and that session's
  newest round record — the only one that can have changed.

Done when: the whole existing suite passes unchanged, because nothing a user
sees has moved; and a test shows that a second read of the same state directory
does not reopen a round record it has already read.

Deliberately out: everything about how the views look or are invoked. Also out:
any attempt to stop reading a finished session altogether. The design says why
that is unsound, and why it is unnecessary.

`has_run_final_round` stays as it is, scanning for a final cause. After the
first pass it scans records the process already holds, so it costs nothing, and
its meaning does not have to change to make it cheap.

## Part 2: follow a feed by what arrived

A following feed re-reads every round's feed file from the start each pass and
rebuilds every line, to print the few that are new. This makes each pass read
and render only what arrived.

In scope:

- An offset-aware read in `feed.py`, and a following view that remembers a
  position per round (design.md, What a refresh reads).
- A round that has ended is read to its end once and not opened again.

Done when: the feed goldens are unchanged; a following view over a growing feed
reads only the tail on each pass; and a feed whose last line is still being
written shows that line whole once the rest of it lands.

Deliberately out: any change to what the feed renders or how it is coloured, and
any change to when a following feed returns. That is part 5.

Two traps decide whether this is right, both in design.md (What a refresh reads,
and Cross-platform notes). The remembered position has to stop at the last
complete line ending rather than at end of file, or a half-written line is lost
when the rest of it lands. And it cannot be a count of characters, because
line-ending translation makes that a different number from a position in the
file. How the position is actually held is free.

## Part 3: three verbs

`scry` becomes `board`, `session` and `feed`.

In scope:

- The three verbs and their arguments (design.md, Three verbs).
- `show_round` folds into `show_feed` as a narrowing of it.
- The mutually exclusive group and `_refuse_a_feed_of_nothing` go, because every
  argument now belongs to the command that takes it.
- `README.md` updated to describe the three commands.

Done when: each command's `--help` is a complete description of that view; the
board and session goldens are unchanged, since only the way in has changed; and
`feed GH123` follows a live session for the whole session, which it does by
inheriting what `--follow` already does rather than through any new machinery.

Deliberately out: making the board and session views live, and changing when a
following view returns. Both are part 5.

Worth knowing: `--follow` disappears in this part at no cost. It selects
`show_feed` today, and after the split the verb's name does that instead.

## Part 4: views return renderables

The board and session views build something rather than printing it, which is
what the following view in part 5 needs to hold and redraw.

In scope:

- The `_show_*` helpers return a rich renderable; the command prints it
  (design.md, Views become renderables).

Done when: every golden is byte-identical, and no test changes except where it
now renders a value instead of capturing a side effect.

Deliberately out: any behaviour change at all. If this part alters output, it
has gone wrong.

This is the largest diff of the five and the least risky. Say so in the pull
request, and point the reviewer at the unchanged goldens first. It is also
extending a pattern the module already has: #86 added the helper now called
`_render_detail`, which returns a renderable rather than printing one.

## Part 5: live by default

The payoff. The board and the session view stay on the screen and keep up, and a
view left open outlives the round it opened on.

In scope:

- The terminal check that decides between following and rendering once
  (design.md, Live by default).
- The rule for when a following view returns (design.md, When a view returns),
  extended to the two views that do not yet honour it: the board follows until
  interrupted, and `session` follows for the whole session, as `feed` already
  does since #94. `feed --round N` returns when that round ends.
- The following helper, and `Live` for the board and session views (design.md,
  Repainting and appending).

Done when, each with a test that injects the wait and the clock rather than
sleeping:

- a board on a terminal console renders again on each pass and does not return
  while the wait keeps returning;
- the same board on a non-terminal console renders once and returns;
- a session view of a session whose round has ended keeps following, and shows
  the next round when one starts;
- a session view returns on a session that has run its final round, and on a
  stuck one;
- `feed --round N` of an ended round returns;
- the feed's own behaviour from #94 is unchanged, which its existing tests
  carry;
- the feed appends rather than repainting, so its output is still the whole
  history in order.

Deliberately out: a configurable refresh interval. One second for all three,
which is what the following feed uses today (requirements.md, What's still
open).

The feed already does this, since #94 landed: `show_feed` follows for a whole
session and ends on a final round or a stuck one. Take the rule from there
rather than writing it again; this part is about giving the board and the
session view the same rule, and about the terminal check, which no view has yet.

## Why this order

Parts 1 and 2 come first because they cost nothing to a user and make part 5
viable. A repainting board on a repo with a long history is only pleasant if the
refresh is cheap, and dogfooding means that history grows every week. Both parts
also stand on their own: part 1 speeds up the daemon's tick today, which is what
GH62 asked for in the first place, so nothing is banked waiting for a later part
to pay off.

Part 3 comes before part 4 so the command names are in front of a person early,
while they are still cheap to change, rather than after the internals have been
restructured around them.

Part 4 comes before part 5 because part 5 needs something to redraw.

The alternative order — the visible parts first, the cost parts after — gets the
new commands sooner at the price of shipping a board that gets slower the more
the tool is used. This order takes the opposite trade deliberately.

## How the parts are tracked

GH87 is the umbrella, and each part is one child issue of it: GH62, GH80, GH106,
GH107 and GH108, in that order. Each is marked blocked by its predecessor, so
the order is carried by the dependency graph rather than by memory, and a
dispatcher working through unblocked issues takes them one at a time. Each child
issue's body is short: read the three documents in
`specs/2026-09-08-watchtower/` and implement that part's section of this plan.
