# Design: the web UI

## What we're building

One command and two pages:

```sh
dreamcatcher web                   # serve the pages and open the browser at them
```

`web` runs from a checkout, like every other view. It serves a home page that is
the status report, and one page per agent assignment that is the assignment view
and its feed together. Both pages keep themselves current while the browser is
open. The command opens the browser at the home page and stays in the foreground
until the user interrupts it.

Nothing about where a view gets its information changes. The pages read what the
daemon left under `.dreamcatcher/`, ask GitHub nothing, and work whether the
daemon is running or not, which is the property the skeleton and watch tower
designs protected and the reason the web UI is a view and not a part of the
daemon.

The design sketches under `design-v2/` were made with a design tool before this
document, as a way of seeing what the pages might be. Where this document and
those sketches differ, this document is the design. In particular, the sketch's
data model, its structured feed records, its "Queued" and "Backlog" wording, its
second theme and its browser-side rendering are not part of this phase.

## How it works

### Two pages and a tail

**The home page**, at `/`, is the status report. It shows the instance facts the
`status` view shows today, the agent assignments in the same attention order,
any failed assignment setups, the available issues in dispatch order, and the
issues with open blockers. Two things appear that the `status` view lacks: the
title of every issue and assignment, and the state of each assignment's pull
request, draft or ready, merged or closed, beside a link to it. Every working
assignment shows the last line its feed said, as the `status` view does. Every
issue reference uses `#N` and links to the issue on GitHub, including a
reference embedded in blocker evidence.

**The assignment page**, at `/assignments/GH142-20260916-180412`, shows one
agent assignment and nothing else. At the top is what the `assignment` view
shows: the issue and its title, the assignment identifier, the status, the pull
request with its state, the branch, the harness and its session identifier, the
model and effort the dispatch settled, the rounds it has run with each purpose,
recovery flag and outcome, and the command that resumes its harness session by
hand. Below that is the whole feed, every round in order, following live while
the assignment has more to say.

A page is addressed by agent assignment identifier rather than by issue. The TUI
takes an issue because that is what a person types, and picks the newest
assignment. On the web nobody types the address: they follow a link from a card,
and each card is one assignment, so the link can be exact. An older assignment
at the same issue has a page of its own that stays where it is.

**The tail**, at `/assignments/GH142-20260916-180412/tail`, is the one address a
person never visits. It answers the assignment page's question "what arrived
since here", and only the page asks it.

The words on the pages are the ontology's. An assignment is working, waiting,
needs user feedback, in fault, complete or unknown. Every compact web chip
shortens "needs user feedback" to "needs feedback"; the underlying status keeps
the full name. The issue sections are the available issues and the blocked
issues, as the `status` view names them. The sketch's "Queued" and "Backlog" are
not used, so a person moving between the terminal and the browser otherwise
reads one vocabulary and the ontology is untouched.

### The server renders and the browser reconciles

**All logic is Python and all markup is in templates.** `web.py` holds a Flask
application. Each route reads through the status and feed boundaries, builds a
view model with the words already chosen, and renders a Jinja2 template. The
templates, under `templates/` beside the module, hold every tag the pages
contain: a base layout, one template per page, and partials for the pieces that
repeat, such as an assignment card, an issue row, a round row and a feed line.
`web.py` never concatenates markup, and no other module renders a template. This
is the rule `AGENTS.md` states for rich and `tui.py`, applied a second time.

A view model carries plain values a template can lay out without deciding
anything: a status label, a duration in words, a sorted list, the text of a pull
request chip. The templates choose no headings and no classes from domain facts
they would have to interpret. That is the architecture document's rule for the
TUI, that presentation must not rediscover status, scheduling or lifecycle
rules, and it holds for the web the same way.

**The browser runs htmx and nothing else of note.** htmx is a single script that
adds attributes to HTML saying when to fetch what and where to put the answer.
The server answers with HTML fragments, never JSON, and htmx swaps them into the
page. Its idiomorph extension adds one way of swapping: rather than replacing an
element, it diffs the new HTML against the live element and edits only what
differs, so untouched elements keep their identity, their focus and their state.
Both files are vendored under `static/vendor/` with the version in each file's
name, the licence beside them, and a note of each file's source, version and
checksum, so a reviewer checks a file against its release rather than reading
it. They are pinned and never edited. A CDN would work as well, but a vendored
file cannot change under us and tells no third party who is looking at the page.

The one script of our own is a few lines that keep the feed scrolled to its end,
described below.

### The home page repaints

The home page is a picture of a state, so it repaints, the way the `status` view
repaints with rich's `Live`. Its main element declares its own refresh:

```html
<main
  id="home"
  hx-get="/"
  hx-trigger="every 2s"
  hx-select="#home"
  hx-swap="morph"
></main>
```

Every two seconds the browser fetches the page's own address, picks the main
element out of the answer, and morphs it into the one on screen. There is no
second address for the home page and no fragment of it: the page is its own
refresh. The server renders the same template for a poll as for a first visit
and knows nothing about who is polling.

Because the swap is a morph, a poll that finds nothing changed changes nothing
on screen. Chip text, a new card and a removed card are edited in place, and an
open disclosure or a focused link survives. Nothing on either side reasons about
which part of the page changes when. The `status` view settled the same question
the same way: repaint everything every second, and the cost of being wrong about
what changed is zero.

For a morph to be quiet, the same facts must render to the same HTML, and each
card and row needs a stable `id` so idiomorph matches it across polls. The
templates make that natural, and the goldens pin it.

### The feed appends

The feed is a log, so it appends, the way the `feed` view prints what arrived
since its last pass and leaves the reader their scrollback.

**A first visit renders everything.** The server reads the assignment, its round
records and every round's feed, and renders the whole page. Alongside the feed
it writes a cursor into a hidden input: an opaque string that says where the
reading stopped.

**The cursor is a byte position.** Feed files are append-only, and
`documents.read_lines_from` already reads on from a byte position and never
advances past a line with no ending on it. The cursor names the round the reader
is in and the position after the last complete line. A round records its ending
before its output stream fully lands, so the reader leaves a round behind only
once that round has recorded an ending and a read from the cursor returned
nothing. The server alone encodes and decodes the cursor. The browser echoes it.

**The page polls the tail.** The feed container declares the poll:

```html
<input type="hidden" id="cursor" name="cursor" value="…" />
<div
  id="records"
  hx-get="/assignments/GH142-20260916-180412/tail"
  hx-trigger="every 2s"
  hx-include="#cursor"
  hx-swap="beforeend"
></div>
```

Every two seconds the browser fetches the tail with the cursor. The server reads
what landed since it, renders it with the same feed line partial the page used,
and answers with the new lines, followed by a fresh cursor input and the rounds
section, each marked to swap out-of-band into the page by its `id`. So one
answer appends the lines, advances the cursor, and updates the round list and
status chip in place. If a new round has started, the answer opens with that
round's heading. A poll that finds nothing costs one directory listing and one
small read, which is what one pass of the `feed` view costs.

**It stops when there is nothing more to come.** The rule is the one the watch
tower settled for the `feed` and `assignment` views: follow through the gap
between rounds, and through a gap where the daemon has stopped, because the next
round may still arrive; stop when the assignment is complete or in fault,
because neither has another round coming. When the feed is over and a poll has
read nothing new, the tail answers with status 286, which is htmx's signal to
stop polling. Answering only on an empty read gives output that lands after the
last ending one more poll to arrive, which is the extra look the TUI's following
views take. A page of an assignment that is over is the same page, arriving at
its end immediately. There is no live marker: the status chip already says
working, and the rounds section already shows the latest round running.

**The reader's place is kept.** While the reader is at the bottom, every
appended line scrolls the container to the bottom. If they scroll up to read
something, appending leaves them where they are, until they return to the
bottom. This is the one behaviour htmx does not carry, and it is the one script
of our own: a listener on the swap that notes whether the container was at its
end before, and scrolls it after.

The whole feed is always there. A capped feed with a "show earlier" link was
considered and rejected: being able to scroll back through everything an
assignment has said is what the feed is for.

### What the pages read

**The status report, as the TUI reads it.** `status.read_status_report` gives
the home page what it shows, and the assignment statuses give the assignment
page its top. The pages reuse the descriptions the status model composes, such
as a round's duration, wherever they say what the page needs. Where a page needs
a fact that no description gives, the fact is promoted into the model and the
TUI keeps composing its description from it, so the terminal goldens hold.

**The feed, as it is written.** The feed on disk stays the plain text it is
today: a timestamp, then either a bracketed label and its detail or a line of
prose, indented when a subagent produced it. `feed.py` writes that format, and
this phase makes it read the format back: `read_feed_line` returns the label,
the detail and the subagent flag beside the timestamp and text, and the regex
that picks the label out moves from `tui.py` into `feed.py` where the format is
owned. The web feed row is a timestamp, the label as a tag, and the text. The
TUI reads the same parse.

What the text cannot give back is accepted for now. A note's detail is flattened
to one line and clipped as it is written, so a long command or error reaches the
page as it reaches the terminal. Prose that happens to begin with a bracketed
word reads as a label, which costs a wrongly styled line. A structured feed, one
JSON record per event with its full detail, is filed as a follow-up rather than
built here, because it changes what a round writes and so bumps the state
format, and because the web page is the thing that will show whether it is
wanted. The projection it would persist already exists: each adapter turns a raw
line into harness-neutral events, and the round renders those to text. The
structured feed would write the events down instead of only their rendering, and
the terminal feed would become a rendering of it.

**A state directory held for the life of the server.** The `web` process holds
one `StateDirectory`, so its round-record cache lives as long as the server
does, and a poll opens only the records that are still incomplete, as a
following TUI view does. The server handles one request at a time. That cache
was not built for concurrent readers, and one person's browser making quick
requests of a local server has no need of them.

### Two facts the tick writes down

The pages show two facts the state directory does not hold today: the title of
an issue, and the state of an assignment's pull request. Both are fetched on
every scheduler tick already. This phase writes them into records the tick
already writes, as optional fields with defaults, so no existing record becomes
unreadable and the state format stays at version 3.

**Titles.** The GitHub issue projection gains a `title`, and the listing and the
read ask `gh` for one more field. Each `IssueObservation` in `scheduler.json`
records it. The assignment record records it too, written once at creation,
where the title is already fetched to name the pull request; that also covers a
complete assignment whose issue is closed and no longer observed.

**Pull request state.** The assignment record gains a `pull_request_observation`
holding the pull request's open, merged or closed state, its draft flag, and the
time it was observed:

```json
  "pull_request_observation": {
    "state": "OPEN",
    "is_draft": true,
    "observed_at": "2026-09-16T18:04:12Z"
  }
```

Assignment creation writes the first, since it opened the pull request as a
draft. The scheduler writes it again whenever a tick reads the pull request and
finds the state or the draft flag changed, through an operation of the
assignment module, the way the harness session identifier and the delivery
cursor are recorded. `observed_at` therefore reads as "in this state since".

It lives on the assignment rather than in the tick's assignment observations
because those observations have gaps exactly where the fact is most wanted. A
tick skips an assignment whose round is running, so a working assignment has no
observation, and a tick removes the observation of the assignment it launched,
an absence the status reader relies on to say "awaiting next scheduler tick"
when that round ends before the next tick. A durable observation on the
assignment has no gap: a working card shows the state as of the last read before
its round launched.

Scheduling never reads this field. It keeps reading the pull request from
GitHub, and a failed read still produces an unknown fact and conservative
inaction. The architecture document's sentence that an assignment persists its
pull request's identity and not a cached copy of its state is amended to say:
and, separately, the latest observed state, for reporting only.

### Local time

Every time a page shows is in the viewer's local time. The `web` server runs on
the viewer's machine, so the machine's zone is theirs. The TUI adapts to local
time as well, in the same stage as the pages, so the terminal and the browser
never disagree about when something happened. What is stored stays UTC: the
feed's stamps and every record's times need an unambiguous instant that survives
daylight saving. Every place that shows a time converts to a zone the caller
passes, defaulting to the machine's, so a test pins a zone and renders the same
on every platform.

### The command

`web` finds the state directory the way `status` does, and refuses with the same
message when there is none. It runs whether or not a daemon is running, and the
page says which.

It listens on the loopback interface only. The pages show a repository's agent
activity and its feeds hold repository content, so nothing else on the network
should read them. A person who wants them elsewhere forwards the port.

It chooses its port from the repository's name: a stable hash of `owner/name`
mapped into a range of a few hundred ports above a base, then the first free
port scanning upward from there. Each repository thereby keeps the same address
across restarts, so an open tab or a bookmark keeps working, and two
repositories served at once need no flag to keep apart. `--port` pins one port
exactly, and a pinned port that is taken is refused rather than scanned past.
The hash is a CRC or a hashlib digest, never Python's own `hash`, which is
salted per process.

Once it is listening it opens the default browser at the home page, prints the
address once, and says nothing more. Werkzeug's per-request log is silenced.
Interrupting it ends it without a message, as interrupting a live view does. It
takes no other option. A `--no-browser` for a machine reached over SSH is the
obvious next one and can arrive when somebody needs it.

### One theme

The pages ship with one stylesheet, the Matrix theme of the sketches: monospace
text in phosphor green on near-black, with a scanline overlay done in CSS. It
loads no font and runs no script. The colours and spacing are CSS custom
properties on the root, so a second theme is a second stylesheet over the same
markup, and a theme switch would be a link that sets a cookie the template reads
to choose the stylesheet, with no script and nothing for a morph to disturb.
Neither is built in this phase. The Nature theme of the sketches, with its
fonts, its sun computed from the clock and its breeze animating every card, is
filed as a follow-up once there is a page to dress.

### Errors

A record that will not read produces a page carrying the reportable message,
never a traceback, as the TUI does today. The web module raises and catches the
same `ReportableError` the rest of the tool uses, and answers with status 500. A
poll that fails leaves the page as it was, because htmx swaps no error answer.
An assignment identifier nobody has answers with status 404 and a message.

### Cross-platform notes

Flask's development server runs on Windows, macOS and Linux, and the standard
library's `webbrowser` opens the default browser on each. Flask calls a view
function with keyword arguments, so the project's keyword-only rule holds for
routes.

The local zone is passed to whatever renders a time rather than set in the
environment, because Windows has no `time.tzset` and a test that set `TZ` would
render differently there.

The vendored scripts are minified single-line files. The pre-commit hooks
exclude `static/vendor/` so that no formatter or whitespace fixer rewrites them,
and `.gitattributes` keeps their line endings, as it does for the fixtures.

### Dependencies

Flask, which brings Werkzeug, Jinja2, MarkupSafe, itsdangerous, click and
blinker. Flask is taken for its routing, its static file route, its template
wiring and above all its test client, which lets a test call the application and
read the response with no socket, no thread and no port. The standard library's
HTTP server was considered: it would cost a hundred lines of path matching,
query parsing and content types, and tests that start a real server on a free
port, for plumbing that is not ours to be proud of.

htmx and its idiomorph extension, vendored and pinned, and not Python
dependencies at all.

## What changes, and what goes away

New: `web.py`; `templates/` and `static/` beside it, with `static/vendor/`; the
`web` verb and its `--port`; `title` on the issue observation and the assignment
record; `pull_request_observation` on the assignment record and the assignment
operation that records it; `title` in the GitHub issue projection and the two
`gh` calls that read issues; the feed line parse in `feed.py`; a zone parameter
wherever a time is shown; a documented way to regenerate the goldens, which
moving every shown time to the local zone needs and issue 104 asks for.

Changed: the TUI shows local time; the TUI reads the feed label through
`feed.py` instead of its own regex; the status model carries as fields what it
carried only as sentences where a page needs the field.

Documents: `docs/architecture.md` gains a Web section beside the TUI section
with the same dependency rule, that it depends on status and feed models and
neither depends on it, and its pull request sentence is amended as above.
`AGENTS.md` gains the rules that markup is written in templates alone, that
Flask is imported in `web.py` alone as rich is in `tui.py`, and that vendored
files are never edited and carry their version in their name. `README.md` gains
the command. The ontology is untouched.

Gone: nothing. The pages add a way of looking and take none away.

## Why it's this and not something else

**Why not a browser application?** A JSON endpoint and a JavaScript application,
hand-written or built with a framework, would put a second implementation of
every derivation in the status model into the browser, where the project's
tests, coverage gate and conventions do not reach, and a framework would bring a
toolchain, a lockfile and a build step for a two-page read-only view. Rendering
on the server keeps the centre of gravity in Python and gives the web view the
TUI's testing story.

**Why not hand-write the script instead of htmx?** The two behaviours, poll and
morph and poll and append, are perhaps forty lines. htmx puts them in the
templates as attributes beside the elements they affect, which is where a reader
who knows HTML and not JavaScript will look, and it names the solved problems:
polling, stopping on 286, out-of-band updates. If the script ever grows a third
behaviour the choice can be revisited.

**Why not push the tail over server-sent events?** The server would have to poll
the files anyway, since watching them on three platforms needs another
dependency, so events would only move the timer to the server and add long-lived
connections to manage.

**Why not have the pages ask the daemon?** The skeleton phase cut a socket or
HTTP API for the views and the watch tower kept it cut, for the reason that
still holds: a view that depends on the daemon cannot answer when the daemon is
stuck, which is when you most want to look. The skeleton design said a deferred
API could sit on the same files later. This is that.

**Why not serve rich's HTML export?** Rich can write its output as HTML, so the
TUI views could be served as they are with no templates at all. It would give a
terminal in a browser, with no links, no layout and no theme.

**Why not read the pull request state from GitHub when a page is rendered?**
Every view reads the local state directory and asks GitHub nothing. A page that
asked would be slow, would fail with the network, and would break the property
that a view answers when nothing else does.

**Why write the observation on the assignment rather than in the scheduler
record?** Because the scheduler record has no observation for a working or a
just-launched assignment, and those are where the fact is most wanted. See
above.

**Why not a fixed default port?** Two repositories served at once would need a
flag between them. Deriving the starting point from the repository's name costs
two lines and gives each repository a stable address without one.

**Why one theme?** The Nature theme is a stylesheet plus behaviour: fonts to
load, a solar position to compute and a breeze to animate. The Matrix theme is a
stylesheet. Shipping one first puts the structure in place and lets the second
be judged against a real page.

## Documents to file

- A structured feed: one JSON record per event with its full detail, written by
  the round beside or instead of the text, the terminal feed rendered from it,
  and a state format bump to version 4.
- The Nature theme, as a second stylesheet and whatever behaviour it keeps.
- `--no-browser`.
- Structured evidence on issue observations, so the blocked-by and claimed-
  elsewhere facts can carry issue and pull request numbers rather than prose.
- Whether the `assignment` verb still earns its place once the web page shows
  the same view. Issue 118 asks this already.

## What's still open

- **The refresh interval.** Two seconds for both pages is a guess that matches
  the TUI's one second in spirit. It is one constant and can be watched.
- **The port constants.** A base of 8100 and a range of 400 are proposed. Any
  uncommon range does.
- **What the status model promotes to fields.** The pages will show which
  sentences need to be facts. The rule is settled; the list is the plan's.
