# Handoff: Dreamcatcher status web frontend (terminal theme)

## Overview

A read-only web frontend for **Dreamcatcher**, a daemon that commissions coding
agents (Claude Code, Codex) to implement GitHub issues. The UI is a **status
report**: it lets the user spot assignments that need their review, watch
running agent rounds live, and see which backlog issues are available for
assignment. It never schedules or controls work.

Two views:

1. **Home** — status strip + Agents panel (open agent assignments) + Backlog
   panel.
2. **Feed** — one assignment: header, meta strip, rounds rail, and a continuous
   plain-text feed across all rounds that follows the live tail.

Domain language is fixed by the repo's `ontology.md`. Use its terms verbatim in
code and UI: _agent assignment, agent round, round purpose, round outcome,
recovery round, user post, relay, status report, issue status, global cooldown_.
One deliberate UI deviation: the ontology's assignment status "Waiting" is shown
as **Queued**.

## About the design files

`Dreamcatcher Status.dc.html` is a **design reference built in HTML** — a
prototype with mock data showing intended look and behaviour. Do not ship it.
Recreate it in the target web app's stack (or pick a sensible one — e.g.
React/Vue + a small state store — if none exists). Its inline styles are the
source of truth for measurements and colours; its logic class documents
derivations and interactions. `support.js` is the prototype runtime and is
irrelevant to implementation.

## Fidelity

**High-fidelity.** Colours, type, spacing, states and copy are final. Recreate
pixel-close.

## Data model (from the prototype and ontology)

```text
Instance        { repo, user, daemonState: 'running'|'stopped', pid, lastTickAgo, tickAccount,
                  capacity, running, cooldownActive, cooldownUntil, cooldownReason }
Assignment      { id: 'GH142-20260916-1804', issue: 'GH142', title, status, harness, model, effort,
                  route, pr, prState: 'draft'|'ready'|'merged'|'closed', branch, session,
                  activity, nextRound?, rounds: Round[] }
Round           { n, purpose: 'Implement'|'Address feedback'|'Wrap up', recovery: bool,
                  outcome: 'running'|'successful'|'errored'|'interrupted', when, events: Record[] }
Record          { kind: 'system'|'agent'|'tool'|'user'|'end', time: 'HH:MM:SS', body, head?, detail? }
Issue           { id: 'GH146', title, labels: string[], here, elsewhere, blocked, conflict   // each true|false|null (unknown)
                  blockedBy?: string[], elsewherePr?: { n, state } }
Assignment status: 'Working'|'Queued'|'Needs feedback'|'Fault'|'Complete'|'Unknown'
```

Derived values:

- `available` = every fact known false → **AVAILABLE**; any fact true → the
  first true reason (CLAIMED HERE / CLAIMED ELSEWHERE / BLOCKED / ROUTING
  CONFLICT); otherwise **UNKNOWN?**.
- Assignment sort order on Home: Needs feedback, Fault, Working, Queued,
  Unknown, Complete. Complete assignments are collapsed under a disclosure.
- Backlog = issues not claimed here, available ones first.
- Facts strip: `cap {working}/{capacity}`, `cooldown none|until HH:MM`,
  `fault {n}`, `avail {n}`, `tick {ago} · {account}`.
- Issue identifiers display as `#142` (link to `{repo}/issues/142`); assignment
  IDs display in full (`GH142-20260916-1804`).

## Screens

### Header (both views)

- Full-width, `padding: 12px 28px`, bottom rule
  `1px solid rgba(51,255,102,0.28)`, flex space-between, wraps.
- Left: mark `assets/dreamcatcher-mark-phosphor.png` at 30×30, `opacity: 0.8`,
  `alt="Dreamcatcher"` (no wordmark — keep it subtle); then repo and user in
  DIM.
- Right (DIM): `daemon RUNNING pid 48213` (state uppercase in `#33FF66`), then
  harness summary `Claude Code · Codex`.

### Home

`main`: max-width 1320, `padding: 22px 28px 56px`, column gap 26px.

1. **Cooldown banner** (only when `cooldownActive`):
   `border: 1px solid #FFB000; padding: 10px 14px; color: #FFB000`; bold
   `!! GLOBAL COOLDOWN until 19:10`, then reason at `rgba(255,176,0,0.75)`.
2. **Facts strip**: inline items, each `label value` with
   `padding-right: 12px; margin-right: 12px; border-right: 1px solid RULE`,
   `white-space: nowrap`. Labels DIM; values BRIGHT 600; cooldown/fault values
   turn AMBER when non-zero/active.
3. **Two panels** in
   `grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 28px`
   (stacks under ~950px).

**Panel** (AGENTS, BACKLOG):
`position: relative; border: 1px solid RULE; padding: 22px 16px 16px`; title
label absolutely positioned over the top border:
`top: -10px; left: 12px; background: #050806; padding: 0 8px; color: #33FF66; font-weight: 700; letter-spacing: 0.14em` +
glow; count after title in DIM, zero-padded (`05`).

**Assignment card**: `border: 1px solid RULE` (becomes `#33FF66` and
`background: rgba(51,255,102,0.06)` when Needs feedback); `padding: 10px 14px`;
column gap 6px.

- Row 1: `#142` link (`#33FF66`, underline on hover, `margin-right: 8px`) +
  title (BRIGHT, 600, `text-wrap: pretty`); status chip right-aligned.
- Row 2 (DIM, single line, ellipsis): `round 2 · implement · running` in BRIGHT,
  then `· {activity} · {harness}`.
- Row 3 — **only when the last round is running**: `[AGENT]` tag (tag
  colour, 700) + latest record text (BRIGHT, ellipsis) + blinking caret.
- Row 4, right-aligned, gap 8px: PR chip and feed button.

**Status chip**: text `[LABEL]`, 700, `letter-spacing: 0.06em`,
`padding: 0 6px`, no radius. | status | bg | fg | extra | |---|---|---|---| |
WORKING | transparent | `#33FF66` | glow text-shadow | | QUEUED | transparent |
DIM | | | NEEDS FEEDBACK | `#33FF66` | `#050806` | inverse video | | FAULT |
`#FFB000` | `#050806` | inverse video | | COMPLETE | transparent | DIM | | |
UNKNOWN? | transparent | DIM | |

**PR chip** (`<a>` to `{repo}/pull/{n}`): `PR #151 draft` — number 700, state
400 at 0.8 opacity; `padding: 2px 10px; border: 1px solid`. Default: transparent
bg, `#33FF66` text, RULE border; hover
`background: rgba(51,255,102,0.1); color: #D6FFE0`. Needs feedback: inverse
block — bg `#33FF66`, text `#050806`, border `#33FF66`; hover bg `#D6FFE0`.

**Feed button**: `>` — `#33FF66` 700, transparent,
`border: 1px solid RULE; padding: 2px 10px`; hover
`background: rgba(51,255,102,0.1)`; `aria-label="Open feed"`.

**Complete disclosure**: `<details>` summary `+ 1 complete` in DIM (hover
`#33FF66`), cards inside identical to above.

**Backlog card**: border `rgba(51,255,102,0.18)`, same padding. Row 1: `#146` +
title; availability chip right (AVAILABLE = inverse `#33FF66`; every other label
= transparent/DIM). Row 2 (DIM, wrapping, gap 10px): dispatch labels at
`rgba(51,255,102,0.75)`; if `elsewherePr`, an outlined chip `PR #149 draft`; if
`blockedBy`, `blocked by #145` with linked ids.

Empty states: `-- no open assignments --`,
`-- no labelled issues without an assignment --` (DIM).

### Feed view

`main`: max-width 1320, `padding: 18px 28px 56px`, gap 20px.

- Back button `< HOME` — `#33FF66`, 700, `letter-spacing: 0.06em`, hover BRIGHT.
- Title row (baseline-aligned, wraps, gap 14px): `h1` 18px/1.3 700 BRIGHT with
  `#129` link prefix (`margin-right: 10px`); status chip; PR chip (same rules as
  Home).
- Meta strip (same style as facts strip):
  `assignment GH129-20260915-0912 │ branch … │ harness … │ session … │ recipe claude-opus-4 · high │ route agent:implement`.
  Values BRIGHT, labels DIM.
- Body grid:
  `grid-template-columns: minmax(240px, 320px) minmax(0, 1fr); gap: 24px`.

**Rounds rail** (`aside`, `position: sticky; top: 16px`): panel titled ROUNDS,
`padding: 18px 0 6px`. Each row is a button:
`grid-template-columns: 28px 1fr; gap: 10px; padding: 8px 14px; border-left: 2px solid transparent`;
active row `background: rgba(51,255,102,0.08); border-left-color: #33FF66`;
hover `rgba(51,255,102,0.08)`. Cells: zero-padded number (`01`, active `#33FF66`
else DIM, 700); purpose (BRIGHT 600) + `(recovery)` in DIM; outcome chip; `when`
in DIM.

**Outcome chip** (same shape as status chip): RUNNING `#33FF66` on transparent;
SUCCESSFUL DIM; ERRORED inverse `#FFB000`; INTERRUPTED `#FFB000` text.

Below the rail, if `nextRound`: `border: 1px dashed RULE; padding: 8px 12px`,
`next>` in `#33FF66` 700.

**Feed panel**: panel titled FEED; when the current round is running append a
pulsing 7×7 square dot + `LIVE` in the title.

- Scroll container:
  `height: 72vh; min-height: 380px; overflow: auto; padding: 14px 18px 18px`.
- Per round: sticky header
  (`top: -14px; background: #050806; padding: 8px 0 6px`, DIM, nowrap/ellipsis)
  reading `── ROUND 2 · IMPLEMENT · Started 18:05 · 14 min so far ─────…` with
  `ROUND n` in `#33FF66` 700.
- Per record:
  `grid-template-columns: auto 15ch minmax(0, 1fr); gap: 0 12px; align-items: baseline`:
  - timestamp `YYYY-MM-DD HH:MM:SS` at `rgba(51,255,102,0.45)`, nowrap
  - tag, 700, `padding: 0 4px`: `[DREAMCATCHER]` `#33FF66` · `[AGENT]` BRIGHT ·
    `[TOOL]` DIM · `[USER]` inverse `#33FF66` · `[END]` DIM
  - text (`white-space: pre-wrap; overflow-wrap: anywhere`): agent/system/end →
    `head — body` (head omitted if empty); tool → `body head` (e.g.
    `Edit src/dreamcatcher/github.py`); colour BRIGHT for agent/user,
    `rgba(51,255,102,0.8)` for system/tool, DIM for end
  - optional `detail` (tool output) as a `<pre>` in column 3:
    `margin: 2px 0 6px; color: rgba(51,255,102,0.75); border-left: 1px solid RULE; padding-left: 10px`
  - the last record of a running round ends with the blinking caret.

## Interactions & behaviour

- **Open feed**: `>` button → Feed view for that assignment, current round = its
  last round, scrolled to the bottom.
- **Back**: `< HOME` → Home.
- **Round select**: clicking a rail row highlights it and scrolls the feed
  container so that round's header is at the top
  (`container.scrollTop = roundEl.offsetTop`); disables tail-following until the
  user scrolls back to the bottom.
- **Tail following**: while following, every new record scrolls the container to
  the bottom. Following turns off when the user scrolls more than 24px above the
  bottom and back on when they return within 24px. Opening a feed re-enables it.
- **Live updates**: poll/stream new records for running rounds (prototype: every
  4 s). Each newly arrived record is revealed **typewriter-style** — ~3
  characters per 16 ms frame until complete. The same record also appears as the
  Home card's row 3, typed identically.
- **Blinking caret**: `0.6em × 1em` block in `#33FF66` with the glow,
  `animation: 1s steps(1) infinite` toggling opacity at 50%. Shown after the
  latest record on running rounds (Home row 3 and feed tail).
- **LIVE dot**: 7×7 square, `#33FF66`, glow, opacity 1→0.25→1 over 1.6 s
  ease-in-out.
- **Hover**: cards/rows tint `rgba(51,255,102,0.08–0.1)`; links underline; chips
  as specified. No transitions beyond colour.
- **Keyboard**: rail rows are `role="button" tabindex="0"`, Enter/Space
  activate. Focus ring `outline: 1px solid #33FF66; outline-offset: 2px` on
  everything focusable.
- **Selection**: `::selection { background: #33FF66; color: #050806 }`.
- **Responsive**: panels stack below ~950px; card rows wrap; long lines
  ellipsise rather than wrap except feed record text.
- **Scanline overlay**: fixed, full-viewport, `pointer-events: none`, `z-index`
  above content:
  `repeating-linear-gradient(0deg, rgba(0,0,0,0.24) 0 1px, transparent 1px 3px)`
  plus vignette
  `radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.6) 100%)`.

## State

- `view: 'overview' | 'detail'`, `selectedAssignmentId`, `selectedRoundN | null`
  (null = last round), `follow: bool` (tail following), `typedChars` (typewriter
  progress for the newest record).
- Data: instance, assignments (with rounds and records), issues — fetched from
  Dreamcatcher's status report plus a live record stream for running rounds.
- Dates in the feed: records carry `HH:MM:SS`; the prototype derives the date
  from the round start. Real data should carry full timestamps.

## Design tokens

```text
--bg:      #050806            page ground
--bright:  #D6FFE0            primary text
--phos:    #33FF66            accent / phosphor
--dim:     rgba(51,255,102,0.55)   secondary text
--faint:   rgba(51,255,102,0.45)   timestamps
--rule:    rgba(51,255,102,0.28)   borders, rules
--rule-2:  rgba(51,255,102,0.18)   inner card borders
--tint:    rgba(51,255,102,0.08)   hover / active rows
--amber:   #FFB000            fault, errored, interrupted, cooldown
--glow:    0 0 8px rgba(51,255,102,0.55)

font: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; 13px / 1.5
  title (feed view) 18px/1.3 700 · everything else 13px · weights 400/600/700
  uppercase labels: letter-spacing 0.14em (panel titles), 0.06em (chips)
radius: 0 everywhere
spacing: 2 4 6 8 10 12 14 16 18 22 24 28 px as listed above
```

## Assets

- `assets/dreamcatcher-mark-phosphor.png` — the mark, recoloured to `#33FF66` on
  transparent (216×216, from the user's icon).
- `assets/dreamcatcher-mark.png`, `assets/dreamcatcher-lockup.png` — original
  dark-on-light marks (not used in this theme).
- No icon font; `>`, `<`, `↗`, `──` are plain characters.

## Files

- `Dreamcatcher Status.dc.html` — the prototype (template + mock data + logic in
  one file).
- `screenshots/` — Home and Feed views as rendered by the prototype.
- `assets/` — marks listed above.
