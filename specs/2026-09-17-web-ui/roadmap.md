# Roadmap: the web UI

Every session that implements a stage should correct the specifications as
details change and say on its pull request what it corrected. It may change how
it delivers the stage when earlier work or implementation discoveries justify
that change. It should raise any change to the roadmap's stages, boundaries,
order or dependencies with the user instead of restructuring the roadmap itself.

The design this roadmap delivers is `design.md` beside this file. Where a stage
below says less than the design does, the design's word stands.

## Stage 1: The skeleton

**Delivery.** `dreamcatcher web` serves the home page at `/` with the facts the
`status` view shows today: the instance section, every agent assignment as a
card in the attention order the TUI uses, failed assignment setups, the
available issues in dispatch order and the blocked issues with their evidence. A
working card shows the last line its feed said. Times are shown as the TUI shows
them, in UTC. The page carries no polling and no link to any other page. Every
issue number is written as `#N` and links to that issue on GitHub; references in
blocker evidence receive the same treatment.

The scaffolding arrives with it. Flask joins `pyproject.toml`. `web.py` holds
`create_app`, which takes a `StateDirectory` and a clock and returns the Flask
application, and `serve_web`, which takes the state directory, a port or none,
an injected browser opener and an injected server runner. The templates live
under `src/dreamcatcher/templates/`, a base layout, the home page, and partials
for the instance facts, an assignment card, an issue row and a failed setup row.
The one stylesheet, the Matrix theme, lives under `src/dreamcatcher/static/`.
Every colour and spacing is a CSS custom property on the root. Autoescaping is
on. The templates and static files ship in the package: build the wheel once and
list it to confirm, and say so on the pull request.

The attention order lives in `tui.py` today as the key order of the styles
mapping. `web.py` must not import the TUI, so the order moves to `status.py` as
a constant both presentations read, and the TUI's styles mapping is keyed from
it.

The `web` verb in `cli.py` finds the state directory the way `status` does and
refuses with the same message when there is none. It chooses its starting port
from the repository's name, a CRC or hashlib digest of the `owner/name` the
state directory's `repository` file holds, mapped into a range of four hundred
ports above 8100, then scans upward for the first port that binds. `--port` pins
one port exactly, and a pinned port that is taken is refused with a
`ReportableError` naming the flag. The server listens on the loopback interface
only. Once it is listening the verb opens the default browser at the home page
through the injected opener, prints the address once, silences Werkzeug's
per-request logger, and runs until interrupted, ending without a message. It
runs whether or not a daemon is running, and the instance section says which.
The server handles one request at a time. When the state directory has no
`repository` file, the scan starts at the base port.

The application registers a handler for `ReportableError`: a page that cannot be
rendered because a record will not read answers with status 500 and a page
carrying the message, never a traceback. htmx swaps no error answer, so a page
that is already up keeps its last picture when a poll fails.

The documents change in the same pull request. `AGENTS.md` gains two rules: that
markup is written in templates alone and `web.py` is the one module that renders
them, and that Flask is imported in `web.py` alone, as rich is in `tui.py`.
`docs/architecture.md` gains a Web section beside the TUI section, saying it
renders status reports and feeds as HTML, owns presentation only, depends on the
status and feed models, and that neither depends on it. `README.md` gains the
command, its port choice and `--port`, that it opens the browser, and that it
reads the local state directory and never contacts GitHub.

**Proof.** HTML goldens under `tests/fixtures/web/` render the home page through
Flask's test client from the fabricated state directories the TUI goldens use,
one golden per fabrication. Those fabrications live in `tests/test_tui.py`
today; move them to a shared test helper module so both test modules read them.
Tests cover the command through the injected callables: the same repository name
always yields the same starting port, a starting port the test has bound itself
makes the scan move on, a pinned port that is taken is refused, the opener
receives the address the server listens on, and the Werkzeug logger is quiet. A
state directory holding an assignment record that will not read renders the
message page with status 500. A test in the style of the existing check that the
TUI imports no domain policy asserts that `web.py` imports neither `tui` nor any
module that performs an action. The coverage gate holds. By hand: run
`dreamcatcher web` in a checkout with a daemon running and read the page it
opens.

**Deferral.** Polling and the vendored scripts. The assignment page and the
links to it. Titles and pull request state. The feed label parse. Local time. A
second theme. Stable ids on cards and rows, which arrive with the stage that
needs them.

## Stage 2: Titles and pull request state

**Delivery.** The tick writes down two facts it already fetches, and the home
page shows them.

The GitHub `Issue` projection gains a required `title`, and `list_issues` and
`read_issue` add `title` to the fields they ask `gh` for. No recorded `gh`
answer under the fixtures is an issue; every issue listing or view a test feeds
`gh` is built in Python, by the `listing` helper in `tests/conftest.py` and by
inline answers in the test modules, so those gain a title. `IssueObservation`
gains an optional `title`, which `_observe_issue` fills from the response;
optional because a `scheduler.json` written before this stage lacks it.

`AgentAssignmentRecord` gains an optional `title` and an optional
`pull_request_observation`, a new `DreamcatcherDocument` holding the pull
request's `state`, its `is_draft` flag and `observed_at`. Creation writes both:
the helper that finds or creates the pull request already reads the issue's
title to name the pull request, so it hands the title back beside the number,
and the first observation is open, draft, at the creation time the scheduler
passed in. The assignment module gains `record_pull_request_observation`, which
reads the record, compares the state and the draft flag with what is recorded,
and rewrites the record atomically only when one differs, in the pattern of
`record_harness_session_identifier`. The scheduler calls it in
`_inspect_assignment_pull_request` after a successful `read_pull_request`, with
the tick's time, which that function does not receive today and must be given.
Scheduling never reads the field.

On the home page every card and issue row shows its title, and each card's pull
request number links to the pull request on GitHub with a chip saying draft,
ready, merged or closed: open and draft is draft, open and not draft is ready,
and merged and closed are themselves. A record with no observation shows the
number alone. The TUI does not change.

`docs/architecture.md` is amended where it says an assignment persists its
pull-request identity and not a cached copy of mutable state: it also persists
the latest observed state, for reporting only, and the persistent information
list gains the title and the observation.

**Proof.** A created assignment reads back with its title and an open draft
observation stamped at its creation time. A tick that reads a pull request whose
state or draft flag differs from the record rewrites the record, and one that
finds no difference leaves the file untouched. An assignment record written
without the two fields reads and renders. An issue observation carries the title
the listing returned. A guard test asserts that `scheduler.py` never reads the
observation field, matching the attribute access `.pull_request_observation`
rather than the bare name, since the module must call the recording operation
whose name contains it; so "scheduling never reads it" is checked. The web
goldens carry the titles and chips. By hand: with a daemon running, every card
and row shows its title; mark a draft pull request ready on GitHub and after the
next tick its chip says ready; a record from before this stage still renders
until a tick fills it in.

**Deferral.** Titles and pull request state in the TUI. Evidence remains prose;
the web presentation recognises its issue references only to link them.

## Stage 3: The home page goes live

**Delivery.** htmx and its idiomorph extension are vendored under
`src/dreamcatcher/static/vendor/`, each file named with its version, each
licence beside it, and a short `README.md` there giving each file's source URL,
version and SHA-256 so a reviewer can check the file against the release rather
than read it. The base template loads both and enables the morph extension. The
home page's main element declares its refresh: `hx-get` of `/`, `hx-trigger` of
every two seconds, `hx-select` of itself and `hx-swap` of morph. Every card and
row gains a stable `id` built from the identifier it shows, so the morph matches
elements across polls.

`.pre-commit-config.yaml` excludes the vendor directory from every hook, as it
excludes the fixtures, and `.gitattributes` pins the vendor files' line endings.
`AGENTS.md` gains the rule that vendored files are never edited, carry their
version in their name, and are replaced whole when updated.

**Proof.** The goldens carry the attributes and ids. A test renders the same
fabricated state twice and gets byte-identical HTML. A test asserts every `id`
in a rendered home page is unique. The hooks pass over the vendored files
unchanged. By hand: open the page beside a running daemon and watch a card
change without the page flickering, open the complete disclosure if the page has
one and see it survive a poll, and select some text and see the selection
survive.

**Deferral.** Everything about the assignment page.

## Stage 4: The assignment page as a snapshot

**Delivery.** The route `/assignments/<identifier>` renders one agent
assignment. Its top carries what the `assignment` view shows: the issue number
and title linked to GitHub, the assignment identifier, the status chip and its
detail, the pull request chip, the branch, the harness and its session
identifier, the model and effort, a table of the rounds it has run with each
round's number, purpose, recovery flag, start, duration and outcome, and the
hand-resume command when the status model provides one. The round descriptions
are the strings the status model already composes; this stage promotes nothing,
and the design says promotion happens only where a page needs a fact no
description gives. Below the top is the whole feed: every round in order, each
opened by the heading `compose_agent_round_boundary` produces, each line
rendered as its stamp, its label as a tag when it has one, and its text with a
subagent's indent preserved. Home cards link to the page. An identifier no
assignment here has renders a page carrying a reportable message with
status 404. The page polls nothing; the reader reloads it by hand.

The status module gains a read of one assignment's status by identifier, beside
the existing read by issue, since the page is one assignment and not an issue's
newest.

The label parse moves into `feed.py`. `FeedLine` gains the label, the detail and
the subagent flag, and `read_feed_line` fills them from the text: the subagent
indent, then an optional bracketed label, then the rest. `tui.py` drops its
label regex and styles the label from the parsed field, printing exactly what it
prints today.

**Proof.** Page goldens from fabricated states: a working assignment, a faulted
one, a complete one, one waiting for its first round, and one whose live round
has said nothing. The TUI feed goldens are unchanged. Unit tests for the parse
cover a labelled line, a prose line, a subagent line, and prose that begins with
a bracketed word, which reads as a label. A test covers the unknown identifier.
By hand: follow a card's link, read the page, and reload it to see what arrived.

**Deferral.** The tail. A live top. Local time.

## Stage 5: The tail

**Delivery.** The assignment page follows its feed. The route
`/assignments/<identifier>/tail` takes a cursor and answers with what arrived
since it. The server encodes the cursor as the round number the reader is in and
the byte position after the last complete line, and decodes it on the next poll;
a cursor it cannot decode is answered with status 400 and a message, which htmx
does not swap. An assignment that has run no round yet has a cursor before any
round, round zero at position zero, and the tail opens round one from it when
that round's record appears. A tail reads on from the cursor with
`read_lines_from`. When the round it is in has recorded an ending and the read
returns nothing, it moves to the next round, opens it with that round's heading,
and reads it in the same answer, so a line that lands after a round's ending is
still picked up on the poll after the ending is seen.

The answer is the new lines rendered with the feed line partial, followed by a
fresh cursor input and the top's rounds section and status chip, each marked
`hx-swap-oob` so one answer appends the lines and updates the top in place. When
the assignment's status is one with no round coming, complete or fault, and the
poll read nothing new, the tail answers with status 286, which stops htmx
polling. A poll that finds the assignment over but still reads new lines answers
200 with them, and the next poll answers 286; that is the extra look the TUI's
following views take, so output landing after the last ending still arrives.
That set of statuses is the TUI's `STATUSES_THAT_END_A_VIEW`; it moves to
`status.py` so both presentations read it.

The page carries a hidden cursor input, the poll attributes on the records
container with `hx-include` of the cursor and `hx-swap` of `beforeend`. There is
no live marker; the status chip and the rounds section already say a round is
running. One script of our own, under `static/`, listens for htmx's swap events
on the records container: before a swap it notes whether the container was
scrolled to its end, and after one it scrolls to the end if it was.

**Proof.** A tail from a cursor returns only the lines that landed since it, and
the cursor it returns reads on from there. A line with no ending is neither
returned nor passed. Entering a new round produces its heading exactly once. A
line appended after a round's ending is returned by the poll after the ending is
recorded. A complete assignment and a faulted one answer 286 once a poll reads
nothing new, and 200 with the lines on a poll that still reads some. A cursor
that will not decode answers 400. An assignment with no round yet answers its
first round's heading and lines once that round starts. Goldens cover a tail
fragment. By hand: watch a live round scroll, scroll up and see the page leave
you there, return to the bottom and see it follow, and see the status chip turn
to complete when the assignment does.

**Deferral.** Local time.

## Stage 6: Local time

**Delivery.** Every time the tool shows is in local time, and every time it
stores stays UTC. `words.describe_time` today does both jobs. It splits: the
storage format keeps `UTC_TIMESTAMP_FORMAT` and a function whose name says it
formats a UTC timestamp, used by `FeedLine.render` and `read_feed_line`; and a
display function takes a time and a zone and renders `2026-09-16 18:04:12`, the
date and time separated by a space with no zone suffix. Every presentation entry
point takes a zone that defaults to the machine's: the three TUI views, the web
application, and the daemon's own report lines, reading the design's "every
place that shows a time" to include the daemon's output, so the terminal never
disagrees with itself. Tests pass a fixed-offset zone, never a named one,
because named zones on Windows need the tzdata package.

Every golden is regenerated: status, assignment, feed and web. Issue 104 records
that there is no documented way to regenerate a golden; this stage deliberately
picks that up, since it regenerates every one, and leaves a script or a
documented command behind, named in `AGENTS.md`.

**Proof.** A feed line written and read back is byte-identical to one written
before this stage. Every regenerated golden differs from its predecessor only in
its stamps. The daemon's report lines carry local time. By hand: run
`dreamcatcher status` beside the web page and check both agree with the clock on
your wall.

**Deferral.** Nothing in the design. Once this stage lands, file the follow-ups
the design lists under "Documents to file".
