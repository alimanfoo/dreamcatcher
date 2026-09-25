# Handoff: Dreamcatcher status web frontend (two themes)

## Overview

A read-only web frontend for **Dreamcatcher**, a daemon that commissions coding
agents (Claude Code, Codex) to implement GitHub issues. The UI is a **status
report**: it lets the user spot assignments that need their review, watch
running agent rounds live, and see which backlog issues are available for
assignment. It never schedules or controls work.

Two **themes** share identical content, views, data and behaviour and differ
only in look & feel; the user switches between them via a small toggle in the
header (Matrix ↔ Nature). Implement the shared structure once and theme it
twice.

- **Matrix** — phosphor-green terminal on near-black. Spec: sections _Screens
  (Matrix)_, _Design tokens (Matrix)_.
- **Nature** — sand, sage and clay; soft, edgeless, outdoors, with a real-time
  sun and a gentle breeze. Spec: section _Nature theme_.

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

`Dreamcatcher Status.dc.html` (Matrix) and `Dreamcatcher Status Natural.dc.html`
(Nature) are **design references built in HTML** — a prototype with mock data
showing intended look and behaviour. Do not ship it. Recreate it in the target
web app's stack (or pick a sensible one — e.g. React/Vue + a small state store —
if none exists). Its inline styles are the source of truth for measurements and
colours; its logic class documents derivations and interactions. `support.js` is
the prototype runtime and is irrelevant to implementation.

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

## Screens (Matrix)

### Header (both views)

- Full-width, `padding: 12px 28px`, bottom rule
  `1px solid rgba(51,255,102,0.28)`, flex space-between, wraps.
- Left: tightly cropped mark `assets/dreamcatcher-mark-phosphor.png` at 48px
  wide with proportional height, `opacity: 0.8`, `alt="Dreamcatcher"` (no
  wordmark — keep it subtle); then repo and user in DIM. The 34px rendered
  height keeps the header no taller than the previous 36×36 canvas did.
- Right (DIM): `daemon RUNNING pid 48213` (state uppercase in `#33FF66`), then
  harness summary `Claude Code · Codex`, then the **theme switch**: a 1px
  RULE-bordered pair `MATRIX | NATURE` (active = inverse `#33FF66` block, other
  = `#33FF66` link, hover tint).

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
- Title row (top-aligned, two columns, gap 14px): `h1` 18px/1.3 700 BRIGHT with
  `#129` link prefix (`margin-right: 10px`) and a title that wraps in the
  flexible left column; status and PR chips stay at the top right in a fixed
  action column (same rules as Home).
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

## Design tokens (Matrix)

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

## Nature theme

Same DOM and behaviour as Matrix; everything below is style. Read
`Dreamcatcher Status Natural.dc.html` for exact values.

### Mood

Calm, natural, peaceful. Sand-coloured page with faint paper grain, a real sun
that follows the viewer's local time, and a light breeze: cards sway like
branches, chips drift like leaves on them. **No hard edges anywhere** — surfaces
are blurred into the page, chips glow instead of having borders, radii are
large. Materials-and-light, never iconography.

### Tokens

```text
--ink:      #3B342E     primary text
--muted:    #7A6E63     secondary text, labels
--faint:    #A39789     feed timestamps
--sand:     #EFE6D6     page ground (bottom of sky gradient)
--surface:  rgba(251,247,239,0.85)   card surface (blurred)
--cream:    #FBF7EF     text on solid chips
--thread:   rgba(59,52,46,0.18)      hairline rules
--rule-2:   rgba(59,52,46,0.12)      section title rules
--tint:     rgba(59,52,46,0.05–0.06) neutral pills, feed buttons, hover
--clay:     #A8623F     issue-number links (hover #8C4B2E)
--moss:     #56704B     PR buttons (solid rgba(86,112,75,0.9) when Needs feedback; tint 0.10 otherwise)
--leaf:     #7E9A6C / rgba(126,154,108,0.85)   Working, Available, running
--leaf-young: rgba(170,190,140,0.45) Queued (text #5F7052)
--leaf-gold:  #C9A24A / rgba(201,162,74,0.9)   Needs feedback (text ink), Interrupted
--leaf-russet:#A65A3C / rgba(166,90,60,0.85)   Fault, Errored
--leaf-faded: rgba(150,140,110,0.28) Complete, unavailable issues
--sage:     #8A9A78     live dot, daemon dot
--sage-dark:#5F7052     'dreamcatcher' feed tag, label text

fonts: titles 'Newsreader' (Google) — h1 36px/1.2 weight 300; section titles 27px italic 400;
       card titles 19px/1.3 400; rounds/feed headings 22px italic.
       UI 'Alegreya Sans' 15px/1.5 (14px secondary lines, 13px chips); weights 400/500.
       feed records ui-monospace 12.5px/1.6.
       strip labels 12px uppercase letter-spacing 0.14em.
radii: cards 28px; pills 9999px; rail rows 20px; round numerals circles 32px.
```

### Sky & sun (fixed background layer, behind content)

- Sky gradient by solar elevation: day
  `linear-gradient(180deg,#E3DFE4,#ECE5DA 34%,#EFE6D6)`; twilight (−6°…6°)
  `#DCCBD1,#ECDDD0 34%,#EFE6D6`; night (< −6°) `#C3BECB,#D8D1CD 34%,#E5DED2`.
  Transition 2 s.
- Sun position from the viewer's **local clock** (DST-aware solar noon ≈ 12:00
  standard / 13:00 DST), day-of-year declination, latitude 51.75 for the arc
  shape. Azimuth → x from 6% (east, left) to 94% (west, right); elevation → y
  from 60vh (horizon) to −12vh (max ≈ 62°). Hidden below −6°, fades in over
  −6°…2°.
- Two layers centred on that point: a **corona** 170vmin radial gradient (halo
  colour α 0.6→0 by 66%) breathing `scale 1→1.08, opacity .8→1` over 22 s; a
  **disc** 38vmin radial (core → mid → transparent by 72%), `filter: blur(5px)`,
  breathing scale 1→1.07 over 14 s. Colours interpolate with elevation: low sun
  core `rgb(255,176,92)` / mid `rgb(255,150,70)` / halo `rgb(255,140,90)`; high
  sun core `rgb(255,250,232)` / mid `rgb(255,236,170)` / halo `rgb(255,226,150)`
  (t = elevation/28°, clamped).
- Two soft **light pools** drift across the page (46 s and 61 s ease-in-out
  loops, ±20vw) — sun through leaves.
- **Paper grain**: fixed overlay, SVG `feTurbulence` fractal noise,
  `opacity .35`, `mix-blend-mode: multiply`.
- A `timeOfDay` override (live / dawn / morning / noon / afternoon / dusk /
  night) exists for QA.

### Breeze

- **Cards** (assignments, backlog): `@keyframes dcSway` — translate up to ±3px /
  1.2px, rotate ±0.3°, `transform-origin: 50% 0`; duration 9–13 s, negative
  delay 0–8 s, both derived per card index so no two move together.
- **Chips & PR buttons**: `@keyframes dcDrift` — ±1.5px, ±0.6°; 6–10 s,
  staggered independently of the card. Leaves on a branch.
- **Mark**: hangs from a 1px × 16px thread below the header top, 54px,
  `drop-shadow(0 0 14px rgba(255,250,240,0.9))`, `opacity .85`, swings ±2.2°
  over 7 s from the thread's top. No containing circle, no wordmark.
- **Live dot**: 8px sage circle breathing (scale 1→1.25, 3.2 s) with a ripple
  ring expanding to 3.2× and fading over the same period. Used in the Feed title
  ("live"), after the last record of a running round, and in the Home card's
  live line. No caret.

### Surfaces (edgeless)

- Cards: element itself is `background: transparent`; a `::before` layer
  `inset: -6px; border-radius: 40px; background: var(--card-bg); filter: blur(14px); z-index: -1`
  provides the surface. `--card-bg` = `rgba(251,247,239,0.85)` for every card
  (Needs feedback is **not** tinted — the gold chip and moss PR button carry
  it). Padding 22px 26px.
- Feed pane: same blurred layer behind an unmasked scroll container (72vh / min
  380px), so text stays crisp to the edge. Round headers inside are sticky on
  `#F7F1E6`.
- Cooldown banner: blurred `rgba(168,98,63,0.12)` layer; title in Newsreader
  18px rust `#8C3F2B`.
- No borders on cards, chips or buttons. Section titles and the strips use
  hairline rules only.

### Components

- **Status / availability chip**: pill, `padding 3px 12px`, 13px 500, leading
  7px dot, and a same-colour halo `box-shadow: 0 0 14px 3px <bg>`. Colours per
  the leaf tokens above (Working = solid leaf, cream text; Queued = young leaf
  tint; Needs feedback = gold, ink text; Fault = russet; Complete/unavailable =
  faded; Unknown = neutral tint). Labels are sentence case ("Needs feedback",
  "Claimed elsewhere").
- **PR button**: pill `padding 6px 16px`, moss; solid `rgba(86,112,75,0.9)` +
  cream text when Needs feedback, otherwise moss text on 0.10 tint; halo
  `0 0 16px 3px <bg>`; hover lightens.
- **Feed button**: 34px circle, neutral tint, chevron-right 14px 1.5px stroke,
  `aria-label="Open feed"`.
- **Dispatch labels**: small pills on `rgba(138,154,120,0.16)`, text `#5F7052`.
  Elsewhere-PR: same in moss. "blocked by #145" with clay links.
- **Facts / meta strips**: uppercase 12px labels (0.14em) in muted, values in
  ink 500, items separated by `thread` right-borders, 16px gutters. Capacity
  reads "2 of 2"; Faults/Cooldown values turn rust when non-zero/active.
- **Rounds rail**: rows `padding 10px 12px; radius 20px`; active row neutral
  tint; 32px circular numeral — active `rgba(59,52,46,0.78)` with cream digit,
  otherwise neutral tint with muted digit, each with a halo; purpose 500,
  "recovery" italic muted; outcome as dot + word in its leaf colour; `when`
  muted 14px. Next-round note: 20px radius, `rgba(251,247,239,0.45)`.
- **Feed records**: grid `auto 12ch 1fr`, gap 14px; timestamp faint; tag 600 in
  role colour (`dreamcatcher` sage-dark, `agent` ink, `tool` muted, `user post`
  clay, `ended` muted); text ink for agent/user, muted otherwise; tool detail as
  `<pre>` with a 1px thread left rule.
- **Theme switch** (header right): pill group on neutral tint with halo; active
  "Nature" on `rgba(251,247,239,0.9)` ink 500, "Matrix" link muted → ink on
  hover.
- **Header**: `padding 18px 32px 14px`, bottom rule `rgba(59,52,46,0.10)`;
  daemon state shown lowercase with an 8px sage dot.
- Focus ring `2px solid #8A9A78`, offset 2px. Selection `#D9C4A3` on ink. Links
  clay, hover `#8C4B2E`.

## Assets

- `assets/dreamcatcher-mark-ink.png` — the mark in `#3B342E` on transparent
  (Nature header).
- `assets/dreamcatcher-mark-phosphor.png` — the mark, recoloured to `#33FF66` on
  transparent (216×216, from the user's icon).
- `assets/dreamcatcher-mark.png`, `assets/dreamcatcher-lockup.png` — original
  dark-on-light marks (not used in this theme).
- No icon font; `>`, `<`, `↗`, `──` are plain characters.

## Files

- `Dreamcatcher Status.dc.html` — Matrix prototype (template + mock data + logic
  in one file).
- `Dreamcatcher Status Natural.dc.html` — Nature prototype (same data and logic,
  restyled; adds the sun/breeze code).
- `screenshots/` — `01-home.png`, `02-feed.png` (Matrix); `03-nature-home.png`,
  `04-nature-feed.png` (Nature, at local afternoon).
- `assets/` — marks listed above.
