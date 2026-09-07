# Plan: the watch tower

This is the third document of the spec. `requirements.md` says what has to be
true, `design.md` says what we're building and how it works, and this breaks
that into steps.

Each step is one working session and one pull request. A step section says what
is in scope, what proves it done, and what it deliberately leaves alone. Where a
step builds a mechanism, it names the mechanism and points at the `design.md`
section that describes it, rather than describing it again — otherwise a later
change has two places to correct and only one of them gets corrected.

The steps are worked interactively, with a person and an agent in the session
together, not dispatched unattended. Two of the five carry a judgement that is
easier to make with a person present than to specify in advance, and they are
marked.

Every step is reviewed, so every step serves its reviewer:

- Where a step changes rendering, the goldens under `tests/fixtures/` are the
  review surface. Read them as the person running the command would, and judge
  the result rather than deriving it from the code.
- Two steps are cost changes that must not alter a single byte of output. Say so
  in the pull request, and let the unchanged goldens carry the claim.
- Generated files — the `.uncoded/` index in particular — land in the commit
  that caused them, since pre-commit regenerates and fails until they are
  staged. Say which parts of a diff are generated so the reviewer can skip them.

## Step 1: read only what a view needs

The board and the daemon both read every session and every round record beneath
it, for every session the repo has ever run. This makes them read what they
actually use.

In scope:

- Sessions read their rounds on demand rather than eagerly (design.md, What a
  refresh reads).
- The board answers its three questions cheaply: the last record, the number of
  rounds, and whether any round was final.
- A session judged done is not judged again for the life of the reading process.

Done when: the whole existing suite passes unchanged, because nothing a user
sees has moved; and a test shows that reading a board twice does not reopen a
done session's records.

Deliberately out: everything about how the views look or are invoked.

**Wants a person in the session.** Answering "was any round final" cheaply is
the open part of this step, and it likely turns on what the daemon guarantees
about what can follow a completed final round. Work that out against the tick
rather than assuming it, and correct the design section to say whatever you
settle on.

## Step 2: follow a feed by what arrived

A following feed re-reads every round's feed file from the start each second and
rebuilds every line, to print the few that are new. This makes each pass read
and render only what arrived.

In scope:

- An offset-aware read in `feed.py`, and a following view that remembers a
  position per round (design.md, What a refresh reads).
- A round that has ended is read to its end once and not opened again.

Done when: the feed goldens are unchanged, a following view over a growing feed
reads only the tail on each pass, and a feed whose last line is still being
written shows that line whole once the rest of it lands.

Deliberately out: any change to what the feed renders or how it is coloured;
those are separate issues in the skeleton phase.

Two traps decide whether this is right, both in design.md (What a refresh reads,
and Cross-platform notes). The remembered position has to stop at the last
complete line ending rather than at end of file, or a half-written line is lost
when the rest of it lands. And it cannot be a count of characters, because
line-ending translation makes that a different number from a position in the
file.

## Step 3: three verbs

`scry` becomes `board`, `session` and `feed`.

In scope:

- The three verbs and their arguments (design.md, Three verbs).
- `show_round` folds into `show_feed` as a narrowing of it.
- The mutually exclusive group and `_refuse_a_feed_of_nothing` go, because every
  argument now belongs to the command that takes it.
- `README.md` updated to describe the three commands.

Done when: each command's `--help` is a complete description of that view; the
board and session goldens are unchanged, since only the way in has changed; and
`feed GH123` follows a live session, which it does by inheriting today's
`--follow` behaviour rather than by any new machinery.

Deliberately out: making the board and session views live — that is step 5. They
stay one-shot here.

Worth knowing: `--follow` disappears in this step at no cost. It selects
`show_feed` today, and after the split the verb's name does that instead.

## Step 4: views return renderables

The board and session views build something rather than printing it, which is
what the following view in step 5 needs to hold and redraw.

In scope:

- The `_show_*` helpers return a rich renderable; the command prints it
  (design.md, Views become renderables).

Done when: every golden is byte-identical and no test changes except where it
now renders a value instead of capturing a side effect.

Deliberately out: any behaviour change at all. If this step alters output, it
has gone wrong.

This is the largest diff of the five and the least risky. Say so in the pull
request, and point the reviewer at the unchanged goldens first.

## Step 5: live by default

The payoff. The board and the session view stay on the screen and keep up.

In scope:

- The terminal check that decides between following and rendering once
  (design.md, Live by default).
- The rule for when a following view returns (design.md, When a view returns).
- The following helper, and `Live` for the board and session views (design.md,
  Repainting and appending).

Done when: `dreamcatcher board` in a terminal stays up and keeps current until
interrupted; the same command redirected to a file writes one board and exits; a
session view of a finished session prints once and returns; and the feed still
appends rather than repainting, so its scrollback survives.

Deliberately out: a configurable refresh interval. One second for all three is
the starting point, and whether it is right is a question for after it can be
watched (requirements.md, What's still open).

**Wants a person in the session.** This is the step whose result is a judgement
about whether the thing is nice to watch, and that is not a test.

## Why this order

Steps 1 and 2 come first because they cost nothing to a user and make step 5
viable. A repainting board on a repo with a long history is only pleasant if the
refresh is cheap, and dogfooding means that history grows every week. Both steps
also stand on their own: step 1 speeds up the daemon's tick today, which is what
GH62 asked for in the first place, so nothing is banked waiting for a later step
to pay off.

Step 3 comes before step 4 so the command names are in front of a person early,
while they are still cheap to change, rather than after the internals have been
restructured around them.

Step 4 comes before step 5 because step 5 needs something to redraw.

The alternative order — the visible steps first, the cost steps after — gets the
new commands sooner at the price of shipping a board that gets slower the more
the tool is used. This order takes the opposite trade deliberately.

## How the steps are tracked

GH87 is the umbrella. Steps 1 and 2 are GH62 and GH80, already beneath it. Steps
3, 4 and 5 need child issues, each blocked by its predecessor, so the order is
carried by the dependency graph rather than by memory. Each child issue's body
is short: read the three documents in `specs/2026-09-08-watchtower/` and
implement that step's section of this plan.
