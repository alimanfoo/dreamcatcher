# Design: the skeleton phase

## What we're building

A Python package, `dreamcatcher`, with two verbs, both of which must be named:
there is no default verb, so a bare `dreamcatcher` asks for one. `run` is a
foreground daemon started from a repository's main checkout. It polls GitHub for
open issues that carry a configured label and are assigned to the user,
dispatches each into its own worktree under `.dreamcatcher/`, runs agent rounds
as its own child processes, relays what the user posts on the pull request into
resumed rounds, and gives a merged or closed pull request one final round.
`scry` is the watch tower: bare `scry` shows the board (one line per session and
per queued issue, sorted by whose turn it is), `scry GH123` shows one session
(vitals, then the round list with each round's cause), and `scry GH123 --follow`
tails the session's live feed. Both verbs run on the same machine; `scry` never
talks to the daemon, it reads what the daemon leaves on disk.

One process watches one repository. Configuration is a committed
`dreamcatcher.toml` at the repo root. The harness is the personal choice, so it
lives nowhere in that file: `run` takes it as `--harness`, and takes it always.
Supported harnesses this phase: Claude Code and Codex, behind one adapter
boundary.

## How it works

### Configuration

`dreamcatcher.toml`, committed, carries what the repo agrees on: the polling
interval (default 120 seconds), the concurrent-round cap (default 1), the
assignee filter (default `@me`), and a list of dispatch mappings. Each mapping
is identified by its label and carries a settings block per harness — the prompt
template included, because the two harnesses invoke skills differently
(`/dream:smith` under Claude Code, `$dream:smith` under Codex, as the ported
`first_round_prompt` testifies):

```toml
interval = 120
max_agents = 1

[[dispatch]]
label = "dream:smith"
[dispatch.claude]
prompt = "/dream:smith GH{issue}"
model = "opus[1m]"
effort = "xhigh"
[dispatch.codex]
prompt = "$dream:smith GH{issue}"
model = "gpt-5.6-sol"
effort = "xhigh"
```

The blocks a mapping carries are the harnesses that can run its label, and every
mapping carries at least one. A block's key has to name a harness, so a mapping
that carries `[dispatch.gemini]` is a fault the tool reports. A label with both
blocks runs on the harness the run named. A label with one block always runs on
that harness, whatever the run named, which is how the requirements' "some
issues go to Claude Code, some to Codex" reaches one process. There is no
separate pin: what the repo agrees about a label is already in which blocks it
wrote. The prompt always lives in the harness block — one way, even when the two
prompts happen to read the same.

`{issue}` is the only substitution the dispatcher owns. The label is a dispatch
mapping's identity everywhere: in config, on the board, in the noisy-skip rule.
An issue carrying two mapped labels is skipped with a visible complaint (in
`last-tick.json`, so the board shows it). There is no personal config file in
this phase; `--harness` is the whole personal layer.

### The state directory

`.dreamcatcher/` in the main checkout. On first run the daemon writes
`.dreamcatcher/.gitignore` containing `*`, so the directory ignores itself and
never touches the repo's own files. Contents:

- `daemon.pid` — the running daemon's pid. Doubles as the single-instance lock:
  a second `run` on the same repo refuses to start while the pid is alive.
  `scry` checks it to mark liveness and staleness.
- `last-tick.json` — overwritten each tick: when the tick ran, and what the
  daemon observed and decided, including what it did not do and why (queued
  behind others, blocked by an open issue, skipped for double labels, deferred
  at the cap, posts seen but not yet relayed). Every session that no round is
  running for is written down with what it is waiting on, which is the resume
  the tick found and had no slot for, or the reason it can give the session
  none: a read that could not tell, a session whose first round never started, a
  session with no pull request open on it. An eligible issue that the tick did
  not dispatch carries no reason of its own: the candidates are written in the
  order they would go, and that order is where its turn is recorded, so the
  board reads "behind N others" off the position. The board's queue and waiting
  sections render this file. The time it records, with `daemon.pid`, tells
  `scry` whether the daemon is alive: the tick writes its own time rather than
  leaning on the file's mtime, which copying a state directory would freshen.
- `worktrees/<session-key>/` — the session worktrees themselves (next section).
- `sessions/<session-key>/` — one directory per attempt, named by the session
  key (below): `session.json` (issue, label, branch, worktree path, harness,
  model, effort, rendered first prompt — frozen at dispatch), `watermark` (the
  relay high-water mark), and `rounds/<n>/` per round.
- `rounds/<n>/` holds `round.json` (started and ended timestamps, exit status,
  the child's pid, and the round's cause), `prompt.txt` (what the round asked
  the harness to do, which the harness reads as its stdin), `feed.txt`
  (rendered, timestamped), `raw.jsonl` (the harness's own stdout stream), and
  `inbox.json` (the batch that caused the round, kept forever). A round records
  its start as it spawns and its ending as it ends, and a round that the daemon
  killed records no ending at all, so one the daemon stopped reads as
  interrupted, which is what it is.

Every whole document the tool writes lands in one step: the text goes to a file
beside the target and then takes the target's place. A round records how it
ended on a thread of its own while a tick is reading every round's record, so a
reader really does arrive mid-write, and this is what keeps it from reading half
a document. A feed and a raw stream grow by a line at a time instead, and
whoever reads one reads the lines that have landed.

The round records are the story of record: a `round.json` with no end recorded
is the interrupted detector, a final round's completed record is the final-round
guard, and the startup sweep reads its pid field. There is no separate event log
in this phase — an earlier draft carried an append-only `ledger.jsonl`, and
review showed it recorded nothing the session and round files don't already
hold; a later phase that wants a cross-session timeline can emit events
alongside the same writes, additively. `scry` builds every view by reading
session directories, round records, and `last-tick.json`.

Dispatch decisions read live state — git worktrees, the process table, GitHub —
plus the tool's own acknowledgement records: the watermark, the round records,
the lock. Never a saved copy of external state.

### Sessions, worktrees, branches

A dispatched issue gets a session key `GH<n>-<timestamp>`, a branch
`dreamcatcher-GH<n>-<timestamp>`, and a worktree at
`.dreamcatcher/worktrees/<session-key>/` inside the main checkout. Git is happy
to put a worktree in an ignored directory of its own working tree — Claude
Code's worktree feature nests the same way — and this is the only layout:
everything dreamcatcher ever makes lives inside `.dreamcatcher/`, whatever the
user's directory habits. Ownership is by path — a session worktree is one under
`worktrees/` — which is stronger than the old basename-pattern test. A worktree
with no `session.json` beside it is not a session: the dispatch cuts the
worktree and then writes the record, so a daemon that died between the two
leaves one behind, and it stands for a session that ran nothing and opened no
pull request. Reading it as no session leaves its issue free to go again. A
record that is there and will not read is a named error instead. The branch name
stays dispatcher-internal namespace, and carries no job in the eligibility
check: GitHub's own link from an issue to its open pull requests answers that,
and the issue reference the _skill_ acts on travels in the prompt. (The branch
still contains a `GH<n>` token, so today's smith and less boot by branch-scan
unchanged until the dream-side prompt argument lands.)

The new branch prefix means dreamcatcher never mistakes old `dream-catcher-*`
work for its own — and, the same coin's other face, never _sees_ it: an issue
with an in-flight old-catcher PR reads as unhandled here and would re-dispatch.
The crossover rule is therefore: retire the old catcher with nothing in flight,
or expect doubled attempts on whatever was.

Two costs of nesting, accepted: tools that ignore gitignore (`find`, some
indexers) see repo copies inside the checkout — git, ripgrep, and the harnesses'
own search skip them — and the extra path depth nudges toward Windows
path-length limits on deep repos. The dispatch builds a worktree path from the
state directory and the session key and takes none from a caller, so the path is
under `.dreamcatcher/worktrees/` by construction and no check has to say so.
`run` refuses to start anywhere but a main checkout (a linked worktree's `.git`
is a file, the same test as today).

The dispatch fetches origin's main before it cuts the branch, so a session
starts from main as it is now rather than from whatever the checkout last heard
about. A creation that fails from the worktree onwards takes the worktree and
the branch away again. git names the branch before it reaches the worktree, so a
failed `worktree add` has one to take away.

### The tick

At startup, once: check that every harness CLI a mapping can settle a label on
is installed, read the repository GitHub knows the checkout as and the account
`gh` is signed in as, acquire the lock, sweep orphans — the pid of any round
record with no end recorded is ended, and ending one that has already gone does
nothing — and treat every round record with no end as interrupted. `run` refuses
when a CLI is missing or when `gh` can name neither the repository nor the
account, because none of them can change under a running daemon, a run without
the repository dispatches nothing, and the relay reads every post against the
account before the marker tells the user's posts from the session's own.

Each tick, in order, launching at most one round per tick:

1. If live rounds fill the cap, defer — the daemon knows its own children, so a
   capped tick spends no GitHub calls at all. The board shows "at cap" honestly
   rather than pretending it checked.
2. Reconcile: enumerate session worktrees, read GitHub state per session, peek
   each session's new posts (a read-only relay query — see below). The peek runs
   whatever state the pull request is in, so the final round of a merged pull
   request still carries whatever the user said before merging it. A session
   whose final round has already run is not peeked at again.
3. Resume the most-open work first: interrupted and errored rounds (a fixed
   "carry on" resume, no inbox — interrupted means no end recorded, errored
   means the latest round exited non-zero, which a usage-limit failure is
   expected to produce; verifying that is on the open list), then sessions whose
   PR is merged or closed and whose final round has not completed (the final
   round), then sessions with new user posts (an inbox resume).

Failure handling is one rule: after any round fails, the daemon holds all
launches — retries and dispatches alike — for a fixed cooldown of fifteen
minutes. No cause detection, no per-session backoff, no escalation schedule: a
usage limit that persists for hours costs about three failed rounds an hour and
no tokens, since a harness spends a few minutes on its own retries before it
gives up; a transient blip costs at most fifteen idle minutes. The hold is
global because the expensive failure (account usage limits) is global, and
resume-before-dispatch plus one-launch-per-tick already contains the blast
radius by construction — a persistent failure is the same session retrying,
never a pile of fresh worktrees, because the errored retry always outranks a new
dispatch. The hold lands in `last-tick.json` with the evidence, not a diagnosis:
"the last round failed (exit 1) — next attempt at HH:MM UTC". The board shows
the same words, without the next attempt, against the session waiting on that
round.

The true wedge is narrower than the port's: a round that exited _zero_ without
opening a PR — the skill ran to completion and chose to yield without one.
Today's smith does exactly this when it finds no issue reference: it asks the
user a question and ends its turn cleanly, which headless means nobody answers
and no PR ever appears. No retry can advance that, so the board surfaces it as
stuck. 4. Otherwise dispatch the oldest eligible labelled issue. 5. Write
`last-tick.json`.

Eligibility keeps the ported doctrine, and one ported rule is replaced. An issue
is eligible when it carries exactly one mapped label, is assigned to the
configured assignee, has no active session worktree, has no open pull request
GitHub links to it, and has no open blocking issues. Every read failure biases
toward inaction: a failed handled-check answers "handled", a failed
blocker-check answers "blocked", a failed listing skips the tick. A tick's own
work can fail too — a fetch that could not reach origin, a record the disk would
not take — and that failure lands in `last-tick.json` as the reason the tick
launched nothing, so the daemon ticks again rather than ending and leaving the
sessions it holds to nobody.

The two claims on an issue answer different questions, which is why both are
asked. A session worktree says this daemon is working on it, and covers the
window before any pull request exists. GitHub's link says somebody has a pull
request open on it, and covers every attempt whose worktree is not here — a
second checkout of the same repository, or one rebuilt since. The port answered
that second question by listing five hundred pull requests and matching head
branch names against its own naming pattern; the link needs one read, has no
limit to fall out of, and rests on no naming convention. GitHub lists only open
pull requests there, so a declined attempt drops out and its issue is free
again, and a merged one closes the issue out of the listing altogether. It also
counts a pull request you opened yourself, which is the intended reading: an
issue somebody is already working on is not up for grabs.

The final-round guard improves on the port: the final round's completed record
is the marker, so "final completed" rather than "final started". A final round
that is killed mid-flight is interrupted like any other and its carry-on resume
is itself the final round.

### Rounds and processes

A round is a child process of the daemon, built by the harness adapter and run
in the session's worktree. The daemon holds the pipes and pumps them on reader
threads: each stdout line goes to `raw.jsonl` verbatim and through the adapter's
parser to become events, which the renderer appends to `feed.txt` as timestamped
lines; stderr lines flow into the same feed as pass-through lines, interleaved
where they happened — the port's behaviour, one sink, and failures surface in
the view you're already watching. `raw.jsonl` stays pure stdout for parser
debugging. Inside the daemon a round is alive until its record says how it
ended, which the round writes as soon as its child process has gone. The feed
can still be catching up when the record lands: a pipe reaches its end only when
every process holding it has closed it, and a process the harness left behind
can hold one for as long as it likes, so a record that waited for the readers
could wait for ever. For `scry` liveness is `daemon.pid` plus the round records
(rounds cannot outlive the daemon).

Children die with the daemon, by design. Each round leads a process group of its
own on POSIX and sits in a Job Object of its own on Windows, so one call ends
the round and everything that the round started. The round makes that call for
itself as soon as its child process has gone, and the daemon makes it for every
round it still holds as it goes down. Windows adds a guarantee that the daemon
cannot lose: the job is set to empty itself when the daemon's last handle on it
closes, which happens however the daemon ends. POSIX has a gap that Windows has
not: a process that starts a session of its own has left the round's group by
then, so the signal never reaches it and it outlives the round. A `kill -9`
orphan on POSIX self-limits — its next write to the dead pipe fails — and the
startup sweep catches stragglers.

Recovery is resume-from-transcript: both harnesses persist their session context
incrementally, so an interrupted round's carry-on resume picks up where it left
off, losing at most the work since the last event.

### The harness adapters

One adapter per harness, the only code that knows a harness exists — the
`round_command` boundary grown into a class, in the shape audacious proved: a
small frozen object that builds a first round and a resume, names its CLI so a
startup check can look it up, and parses one stream line into events. What it
builds is an argv and the prompt to go with it: a harness reads its prompt from
stdin, and the round writes the prompt to `prompt.txt` for it to read, so no
prompt ever reaches a command line. That is what lets a prompt run to any length
and hold anything, a percent sign and a line ending included, which cmd.exe
would otherwise act on.

Claude Code: first round
`claude --print --output-format stream-json --verbose --permission-mode auto --allowedTools <the recurring writes> --name <session-key> --model <model> --effort <effort>`;
resume the same base plus `--continue` (Claude recovers model and effort itself;
`--name` is kept from the ported command, naming the session after the session
key). Neither names a prompt, which is how Claude knows to read one from stdin.

The allowed writes list is the ported one:
`gh pr create/comment/edit/ready/close`, `gh issue create/comment`,
`git commit`, `git push`.

The parser is `render-claude.sh`'s jq program as Python: init events carry the
harness session id, assistant text passes whole, tool calls become one line via
the most-telling-input fallback chain, failed tool results surface, a retried
request says what it is waiting on, and successful tool results and the rest of
the housekeeping are dropped.

A `result` event closes the round with what it spent, in money and in tokens,
and then with how it ended. Its subtype reads `success` even on a round that
failed, so the ending reports the event's own error flag instead.

A thinking block is marked in the feed and nothing more: Claude streams the
block with the thinking itself withheld, so the feed can say the agent thought
and cannot say what it thought.

Codex: first round
`codex exec --json --approve-for-me --model <model> -c model_reasoning_effort=... -c sandbox_workspace_write.network_access=true -`;
resume `codex exec resume --last --json` plus the replayed settings and the
ported resume permissions (`sandbox_mode="workspace-write"`, network access,
`approval_policy="on-request"`, `approvals_reviewer="auto_review"`), and the
same `-`. Codex takes that word where a prompt would go, to read the prompt from
stdin instead.

`--last` is scoped by Codex's own working-directory filter — an inherited
contract with Codex's session store, stated here so nobody rediscovers it.

The parser reads `--json` JSONL, lifted from audacious's `codex.py` and moved
from post-hoc to line-at-a-time. audacious took the `agent_message` text alone.
The feed also wants the round's landmarks and what the agent did, so the parser
reads `thread.started` for the session id, `item.completed` for the agent's
words or one action line, `turn.completed` for what the round used, and
`turn.failed` for why it stopped. Every round of one session carries the same
session id.

A command's action line carries the command Codex ran. When the command did not
complete, a second line follows it, labelled with the status Codex gave it.

Codex reports every file of one patch in a single item, so the parser gives each
file its own action line. Each line names what happened to the file, and the
file's path is all the rest of the line.

Codex sends each item three times, as it starts, changes and finishes, and only
the last is complete, so the parser drops the other two.

Codex gives no prices, so its spend line counts tokens alone where Claude's also
carries money.

A failed turn arrives twice, once on its own and again as the turn's ending, and
only the ending reaches the feed. Codex spends no retries on a usage limit: the
round fails on the first answer and exits non-zero, where Claude retries ten
times first.

These flag sets are each harness's never-stall answer, written down: Claude
answers with a pre-approved allowlist under auto mode, Codex with its automatic
reviewer. Both are the current catcher's field-proven stances.

The resume and final-round prompt texts port verbatim from `catch.sh`'s
`resume_prompt`. The carry-on prompt is new prose ("your previous round was
interrupted, carry on"), low-risk because the resumed transcript carries the
context.

Any line either parser cannot read passes through to the feed unchanged, and so
does any line the feed cannot then render — a broken line costs one line, never
the log. The two are separate steps and fail separately: reading turns a line
into events, and rendering turns an event into text.

### The feed

One format regardless of harness: a timestamp, then a sentence the agent said or
a bracketed action — `[Edit] src/theme.css`, `[Bash] pytest`, `[failed] ...` —
with subagent activity indented, and round boundaries marked with their cause
("round 3: new posts"). A cause is one of a fixed few words, and the batch that
woke the round is in the `inbox.json` beside the record rather than in them.
Timestamps make silence legible: the follow view shows the age of the last
event, which is the "working or stuck" answer and the seed of later stall
detection.

The bracketed words divide in two. `[session]`, `[usage]`, `[failed]`,
`[thinking]`, `[retry]`, `[report]` and `[result]` are the feed's own, and mean
the same thing whichever harness ran. An action's label is the harness's own
word for what it did, so Claude's tool name gives `[Bash] pytest` and Codex's
item type gives `[command_execution] /bin/zsh -lc ls`. Translating one into the
other would mean inventing Claude's names for Codex's things, and would cost the
reader the word that appears in `raw.jsonl` beside it.

The feed puts an action's detail on one line, whatever shape the harness
reported it in: it cuts the session's worktree off the front of a path,
collapses the whitespace, and clips what is left at 200 characters. So
`[Edit] src/theme.css` reads as a path inside the worktree, though the harness
reported the whole absolute path.

`scry GH123 --follow` shows the whole session: every round's feed concatenated
in order, boundaries between them, following at the tail while a round is live.
One completed round is an entry point from the round list —
`scry GH123 --round 2` — same rendering, static. Storage stays one directory per
round (the round is the unit that has a cause); the concatenation is the
viewer's stitch of sorted round directories. Reading a dead session and watching
a live one are the same view in different tenses.

### The relay

`watch.sh` ports as a function, with one deliberate change in sequencing.

The query is a read-only peek: read the three sources — conversation comments,
reviews, and inline comments, each its own paginated REST list via `gh api`, the
shape upstream normalised to in dream#900, so the relay never reconciles two
JSON dialects — keep what is newer than the watermark, and return, writing
nothing.

Each list comes back whole, and the watermark filters what came back, rather
than the fetch asking narrowly. GitHub takes a `since` on the two comment lists
but not on the reviews, so asking narrowly would be a special case for two
sources out of three, and one process watching one repository spends few enough
calls to leave that for a later phase.

The PR's own state is not the peek's to fetch. The tick reads it per session,
and that read is where the peek's PR number comes from, so a state read of the
peek's own would be one fact read twice by two reads that can disagree.

The watermark advances only when a round actually launches with that batch as
its inbox. The port's advance-on-read sequencing lost any batch whose round
never ran. Advance-on-launch means a crash before launch re-reads the same posts
next tick, the "posts waiting" board state becomes real observed data (the
peek's results land in `last-tick.json`), and two sessions with posts contending
for one slot both keep their batches until each actually runs.

The residual window — crash after launch, before the round acts — stays, and
stays accepted: you can see the PR and say it again.

One narrower window stays open for the same reason. GitHub records a post to the
second, and the watermark is the newest post of the batch that just launched, so
a post written in that same second, and landing after the peek that made the
batch, is never newer than the watermark and no later tick brings it back. That
is the requirements brief's "I can see that on the pull request and say it
again", and closing it would mean remembering every post id ever relayed, which
is the recovery machinery the brief turns down.

The filter keeps `watch.sh`'s two rules: a post is the user's when its author is
the _authenticated_ account (`gh api user`, nothing configured) and its body
lacks the dreamcatcher marker prefix; and a post must say something — a
non-empty body, or an APPROVED or CHANGES_REQUESTED verdict — which drops
GitHub's empty review wrappers, including the ones wrapping the agent's own
inline replies. Timestamps are ISO-8601 strings compared as strings; an absent
watermark means the beginning of time, so a session's first peek returns the
PR's whole history. A review nobody has submitted yet — a draft the user has
started and left, which GitHub answers with no submitted time at all — reads as
written at the beginning of time by the same comparison, so it never passes a
watermark and needs no rule of its own.

The projection widens per dream#891: inline comments carry `path`, `line` (with
the `original_line` fallback), `start_line` (with `original_start_line`),
`side`, `id`, `subject_type`, and `diff_hunk`, so a range suggestion reaches the
agent with the text it replaces, and a comment on a whole file reads as one
rather than as a comment on line 1, which is where GitHub reports it. Each
round's inbox is written to that round's directory and kept.

The inbox is dreamcatcher's own document, so it names each field for what that
field is rather than for GitHub's own word: a post says who wrote it under
`author` and when under `written_at`, and a review says what it said under
`verdict`. That last one earns its name twice over, since the inbox already says
`state` about the pull request itself.

The marker: every prompt the daemon composes ends with a postscript instructing
the session to end every GitHub post — PR bodies, comments, replies on diff
lines, issues — with the exact line `<!-- dreamcatcher -->`. HTML comments don't
render on GitHub. The marker is a fixed literal, the same in every prompt, and
the filter matches it exactly — no payload, no prefix-matching rule, nothing to
vary. Dream's visible footer coexists harmlessly; each system owns its own mark.
Commits are not marked; the relay only filters posts.

### The board

`scry` sorts sessions and queued issues by whose turn it is:

- needs you: PR open, no live round, nothing waiting — with idle age.
- agent working: live round — with the last feed event and its age.
- waiting: posts peeked but another launch took this tick's slot, or an
  interrupted or errored round awaiting its carry-on retry — with the last exit
  status, so a run of usage-limit failures reads as what it is. (While the
  daemon sits at the cap it doesn't peek, and the board says "at cap" rather
  than guessing.)
- stuck: a session in a state the daemon cannot advance — a round exited cleanly
  without opening a PR — surfaced instead of silently skipped, with a pointer to
  the feed.
- queued: eligible issues in dispatch order, each with its reason not yet —
  behind N others, blocked by `GH<x>`, skipped for double labels.
- done: merged or closed with the final round completed, most recent first.

Repeat attempts group under their issue: three sessions for one issue read as
three attempts at one thing, current one first. `scry GH123` shows the newest
attempt, older attempts listed beneath it. The session view shows vitals (issue,
PR, branch, harness and model, the literal first prompt), the round list with
causes and durations, and — when no round is live — the exact command to resume
the session interactively by hand (`claude --continue` from the worktree, or the
matching `codex exec resume`), built from `session.json`.

### The contract page

`CONTRACT.md` at the repo root, a deliverable of this phase: what a skill must
do to be dispatchable. Adopt the branch you wake up on and open your PR from it
— before you change anything, so the user can watch commits arrive and you have
a channel to ask questions from the start. Act on the issue reference in your
prompt, and make the PR say it closes that issue, since GitHub's link from the
issue to that PR is how the dispatcher knows the issue is claimed. Handle the
resume prompts (the inbox shape, the carry-on, the final round's
merged-or-closed state). Yield by ending your turn; the PR is the only channel.
Marking is injected by the dispatcher; the skill needs no knowledge of it.

### Cross-platform notes

Windows native is the target; CI runs the test suite on Windows, macOS, and
Linux from the first commit, with a fake harness binary standing in for
signed-in CLIs.

All subprocess and file IO forces UTF-8 explicitly, and reads a byte that is not
UTF-8 as the replacement character rather than failing, since a localised git
can put one in a message.

A write keeps the line endings it was given rather than the platform's, so a
round's copy of what a harness streamed holds what the harness sent.

Programs are looked up on the PATH before they run, which is what reaches a
`.cmd` on Windows, the form the harness CLIs take when npm installs them.

The current directory is no part of that lookup. Windows searches it ahead of
the PATH, and the daemon's current directory is the watched checkout for its
whole life, so a file named `git.exe` at that checkout's root would otherwise
run in place of the real tool. The daemon takes the current directory back out
of the search by setting `NoDefaultCurrentDirectoryInExePath` in its own
process.

Every child inherits the name. Windows itself, cmd.exe and Python each read it,
so a lookup the harness makes reads the PATH alone too. That carries a cost the
design accepts: a command in a watched repository that runs a program from the
current directory by its bare name stops finding it.

Windows runs a `.cmd` through cmd.exe, which reads the command line a second
time under its own rules, after Python has quoted it for the program's own
reader. So a batch file's line is built for both readers: every part of it
quoted, and a quote inside a part doubled.

A percent sign and a line ending get past the quoting, though. cmd.exe expands
`%NAME%` inside double quotes as well as outside, and it reads a newline as the
end of a statement, so neither reaches a batch file as it was written. A prompt
is the text most likely to hold one, and it goes to the harness as a file the
harness reads rather than as an argument, so it never meets cmd.exe at all.

What is left on a command line is short: a model, an effort, and flags the tool
writes itself. So the tool refuses a model or an effort holding either character
as it reads the config, which is what lets the message name the setting that the
repo's owner has to fix. The repo's owner commits the `dreamcatcher.toml`, so
everyone watching that repo reads the same one, and a config that reads on Linux
and fails on Windows would be worse than one that fails the same way everywhere.
So the refusal stands on every platform.

It also follows that the process the daemon starts is often not the one doing
the work, since a `.cmd` is a shim and Windows has shims for other things too.
Process teardown is therefore a whole tree, not a child: a process group on
POSIX and a Job Object on Windows, isolated in one module.

Paths flow through `pathlib` end to end.

The known pid-reuse wrinkles are accepted, because each window is small: the
orphan sweep runs once at startup against pids the daemon itself recorded, and a
round ends its own tree in the moment after it has waited for its child and let
go of its pid.

### Dependencies

Python 3.12+ (`tomllib` in the standard library). The runtime shells out to
`git`, `gh`, and the harness CLIs, which the user already has and has signed in.
No `jq`, no `tmux`. Beyond that, three runtime dependencies on every platform,
each mature and wheeled everywhere: pydantic validates every document the tool
owns, psutil answers whether a pid is alive, and rich renders `scry`'s views.
Windows adds a fourth, pywin32, which is how teardown reaches the Job Object
that holds a round there. Nothing else in this phase; a richer UI can add its
own later.

## What changes, and what goes away

Gone:

- tmux, and with it the launch ceremony, the sandbox-escape permission dance,
  the session-name liveness convention, and the dots-to-plus-signs scar.
- `jq` as a prerequisite.
- The plugin-snapshot machinery and the stable-path renderer publish — they
  existed only because the catcher lived inside a plugin that upgrades under it;
  a pinned package cannot lose its own code.
- `--once` and the cron-restart pattern; the foreground loop is the run story.
- Branch names as the message channel — the prompt carries the issue; the branch
  pattern remains only as dispatcher-internal reconciliation namespace.
- The clobbered single `inbox.json`; each round keeps its own.
- The sibling-worktree layout and its assumption that the checkout lives in a
  dedicated container directory — worktrees nest under
  `.dreamcatcher/worktrees/`, and there is only one way.

Changed:

- The final-round guard, from "final started" to "final completed".
- The watermark advances at round launch, not at read — a strictly smaller loss
  window than the port.
- The inline-comment projection carries the range and the hunk.

New, with no counterpart today: the round records, the board, the session view,
the per-round feeds, the interrupted state and its automatic carry-on resume,
the contract page.

On the dream side, later and tracked there: smith and less take the issue from
the prompt (branch scanning stays as their interactive fallback), their prose
stops naming `dream:catcher`, and the catcher and its skills retire.

## Why it's this and not something else

A local socket or early HTTP API for `scry`: cut. Everything `scry` needs is on
disk already, same machine was the stated scope, and files keep working when the
daemon is dead — which is when you most want to look. The deferred API can sit
on the same files later. Putting it back costs a protocol, versioning, and a
Windows socket story, and buys push-instead-of-poll on a local file.

An append-only ledger file: cut in review. It recorded nothing the session and
round files don't already hold, and two stores of one story means one of them
drifts. A later phase wanting a cross-session timeline emits events alongside
the same writes, additively.

Sibling worktrees (the port's layout): cut, with no config option to bring them
back — one way, always. Nesting under `.dreamcatcher/` assumes nothing about the
user's directory habits, strengthens ownership from name-pattern to path, and
makes cleanup one deletion. The costs (gitignore-blind tools see nested repo
copies; Windows path depth) are named in the worktree section.

A supervisor that holds the truth in memory: cut. The reconcile-first crash
story is the most proven part of the old catcher, and the requirements demand
it. The daemon holds pipes and handles, never the authoritative state.

The two-layer personal config: cut for this phase. Per-harness settings blocks
in the committed config, plus a required `--harness` flag, collapse the personal
choice to one word on the command line. A default harness in the committed file
was cut with it, in review: the flag overrode it anyway, and a file the repo
shares is the wrong home for the one choice that belongs to whoever runs the
daemon. Putting the personal file back is additive if someone eventually needs a
personal model rather than a personal harness.

Codex `approval_policy="never"` (audacious's stance): superseded. It predates
the auto-approval features; the catcher's auto-reviewer stance is field-proven
to never stall with these skills, and stalls are the failure mode that kills
unattended operation.

Orphan adoption (letting rounds survive a daemon crash and re-attaching): cut.
Both harnesses persist context incrementally, so kill-and-resume loses almost
nothing, and adoption would need cross-process pipe recovery for marginal
benefit.

WSL-first Windows support: rejected in requirements; the colleagues this serves
run native CLIs.

`raw.jsonl` retention was challenged in review and kept deliberately: it is the
debugging evidence for exactly this phase's open parser questions, and a
candidate trim once the adapters are verified, not before.

## What's still open

- Reading a usage limit's reset time out of Claude's own `rate_limit_event` is a
  possible later refinement of the cooldown. The fixed hold doesn't need it.
  Both harnesses are now known to exit non-zero on a limit, which is what the
  errored retry keys on, and `tests/fixtures/*/rate-limited.jsonl` records each.
- Multi-repo (one place to watch all repos) stays a later phase; nothing here
  forecloses it — another repo is another state directory.
- The personal config layer, if personal models turn out to matter.
- `scry`'s name is charming and opaque; if colleagues stumble, `status` can
  arrive as an alias without cost.
