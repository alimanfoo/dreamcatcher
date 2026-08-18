# Design: the skeleton phase

## What we're building

A Python package, `dreamcatcher`, with two verbs. `run` (the default: bare
`uvx dreamcatcher` means `run`) is a foreground daemon started from a
repository's main checkout. It polls GitHub for open issues that carry a
configured label and are assigned to the user, dispatches each into its own
worktree under `.dreamcatcher/`, runs agent rounds as its own child processes, relays what the user
posts on the pull request into resumed rounds, and gives a merged or closed
pull request one final round. `scry` is the watch tower: bare `scry` shows the
board (one line per session and per queued issue, sorted by whose turn it is),
`scry GH123` shows one session (vitals, then the round list with each round's
cause), and `scry GH123 --follow` tails the session's live feed. Both verbs
run on the same machine; `scry` never talks to the daemon, it reads what the
daemon leaves on disk.

One process watches one repository. Configuration is a committed
`dreamcatcher.toml` at the repo root; the only personal choice is the harness,
selected with `--harness` (default named in the config). Supported harnesses
this phase: Claude Code and Codex, behind one adapter boundary.

## How it works

### Configuration

`dreamcatcher.toml`, committed, carries what the repo agrees on: the polling
interval, the concurrent-round cap (default 1), the assignee filter (default
`@me`), the default harness, and a list of dispatch mappings. Each mapping is
identified by its label and carries one settings block per harness — the
prompt template included, because the two harnesses invoke skills differently
(`/dream:smith` under Claude Code, `$dream:smith` under Codex, as the ported
`first_round_prompt` testifies):

```toml
interval = 300
max_agents = 1
harness = "claude"

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

A mapping may also pin `harness = "codex"` at its own level, committed, when
the repo agrees a label belongs to one harness; otherwise the run's harness
applies. That keeps the requirements' "some issues go to Claude Code, some to
Codex" available while the common case stays one flag. A bare natural-language
prompt with no skill syntax can sit at the mapping's top level as a shared
default when it needs no per-harness form.

`{issue}` is the only substitution the dispatcher owns. The label is a
dispatch mapping's identity everywhere: in config, on the board, in the
noisy-skip rule. An issue carrying two mapped labels is skipped with a visible
complaint (in `last-tick.json`, so the board shows it). There is no personal
config file in this phase; `--harness` is the personal layer.

### The state directory

`.dreamcatcher/` in the main checkout. On first run the daemon writes
`.dreamcatcher/.gitignore` containing `*`, so the directory ignores itself and
never touches the repo's own files. Contents:

- `daemon.pid` — the running daemon's pid. Doubles as the single-instance
  lock: a second `run` on the same repo refuses to start while the pid is
  alive. `scry` checks it to mark liveness and staleness.
- `last-tick.json` — overwritten each tick: what the daemon observed and
  decided, including what it did not do and why (queued behind others, blocked
  by an open issue, skipped for double labels, deferred at the cap, posts seen
  but not yet relayed). The board's queue and waiting sections render this
  file; its staleness (mtime plus `daemon.pid`) tells `scry` whether the
  daemon is alive.
- `worktrees/<session-key>/` — the session worktrees themselves (next
  section).
- `sessions/<session-key>/` — one directory per attempt, named by the session
  key (below): `session.json` (issue, label, branch, worktree path, harness,
  model, effort, rendered first prompt — frozen at dispatch), `watermark` (the
  relay high-water mark), and `rounds/<n>/` per round.
- `rounds/<n>/` holds `round.json` (started and ended timestamps, exit
  status, the round's cause, and the child pid while relevant), `feed.txt`
  (rendered, timestamped), `raw.jsonl` (the harness's own stdout stream),
  `stderr.log`, and `inbox.json` (the batch that caused the round, kept
  forever).

The round records are the story of record: a `round.json` with no end
recorded is the interrupted detector, a final round's completed record is the
final-round guard, and the startup sweep reads its pid field. There is no
separate event log in this phase — an earlier draft carried an append-only
`ledger.jsonl`, and review showed it recorded nothing the session and round
files don't already hold; a later phase that wants a cross-session timeline
can emit events alongside the same writes, additively. `scry` builds every
view by reading session directories, round records, and `last-tick.json`.

Dispatch decisions read live state — git worktrees, the process table,
GitHub — plus the tool's own acknowledgement records: the watermark, the
round records, the lock. Never a saved copy of external state.

### Sessions, worktrees, branches

A dispatched issue gets a session key `GH<n>-<timestamp>`, a branch
`dreamcatcher-GH<n>-<timestamp>`, and a worktree at
`.dreamcatcher/worktrees/<session-key>/` inside the main checkout. Git is
happy to put a worktree in an ignored directory of its own working tree —
Claude Code's worktree feature nests the same way — and this is the only
layout: everything dreamcatcher ever makes lives inside `.dreamcatcher/`,
whatever the user's directory habits. Ownership is by path — a session
worktree is one under `worktrees/` — which is stronger than the old
basename-pattern test. The branch name stays dispatcher-internal namespace:
the anchored pattern carries the issue number for the PR half of the
eligibility check, but the issue reference the *skill* acts on travels in the
prompt. (The branch still contains a `GH<n>` token, so today's smith and less
boot by branch-scan unchanged until the dream-side prompt argument lands.)

The new branch prefix means dreamcatcher never mistakes old `dream-catcher-*`
work for its own — and, the same coin's other face, never *sees* it: an issue
with an in-flight old-catcher PR reads as unhandled here and would
re-dispatch. The crossover rule is therefore: retire the old catcher with
nothing in flight, or expect doubled attempts on whatever was.

Two costs of nesting, accepted: tools that ignore gitignore (`find`, some
indexers) see repo copies inside the checkout — git, ripgrep, and the
harnesses' own search skip them — and the extra path depth nudges toward
Windows path-length limits on deep repos. One invariant is checked at
dispatch, not assumed: the worktree path is strictly under
`.dreamcatcher/worktrees/`. `run` refuses to start anywhere but a main
checkout (a linked worktree's `.git` is a file, the same test as today).

### The tick

At startup, once: acquire the lock, sweep orphans — any round record with no
end recorded whose pid is still alive gets killed — and treat every round
record with no end as interrupted.

Each tick, in order, launching at most one round per tick:

1. Reconcile: enumerate session worktrees, read GitHub state per session,
   peek each open session's new posts (a read-only relay query — see below).
2. If live rounds fill the cap, defer.
3. Resume the most-open work first: interrupted and errored rounds (a fixed
   "carry on" resume, no inbox — interrupted means no end recorded, errored
   means the latest round exited non-zero, which is what a usage-limit
   failure looks like), then sessions whose PR is merged or closed and whose
   final round has not completed (the final round), then sessions with new
   user posts (an inbox resume).

An errored round retries on a later tick with no backoff machinery: the tick
interval is the pace, a still-limited harness fails fast once per tick, and
when the account is limited every session is limited anyway, so nothing is
starved. Backoff stays deferred robustness. The true wedge is narrower than
the port's: a round that exited *zero* without opening a PR — the skill ran
to completion and yielded without one (the ask-the-user case) — which no
retry can advance and the board surfaces as stuck.
4. Otherwise dispatch the oldest eligible labelled issue.
5. Write `last-tick.json`.

Eligibility keeps the ported rules and the ported doctrine. An issue is
eligible when it carries exactly one mapped label, is assigned to the
configured assignee, has no active session worktree, has no open or merged PR
from an earlier dreamcatcher branch, and has no open blocking issues. Every
read failure biases toward inaction: a failed handled-check answers
"handled", a failed blocker-check answers "blocked", a failed listing skips
the tick.

The final-round guard improves on the port: the final round's completed
record is the marker, so "final completed" rather than "final started". A
final round that is killed mid-flight is interrupted like any other and its
carry-on resume is itself the final round.

### Rounds and processes

A round is a child process of the daemon, built by the harness adapter and
run in the session's worktree. The daemon holds the pipes and pumps them on
reader threads: each stdout line goes to `raw.jsonl` verbatim and through the
adapter's parser to become events, which the renderer appends to `feed.txt`
as timestamped lines; stderr goes to `stderr.log`, and when a round exits
nonzero its closing feed line quotes the last few stderr lines, so failures
surface in the view you're already watching. Liveness inside the daemon is
the process handle; liveness for `scry` is `daemon.pid` plus the round
records (rounds cannot outlive the daemon).

Children die with the daemon, by design. Ctrl-C reaches the process group on
POSIX; on Windows the daemon puts children in a Job Object configured to kill
them when the daemon's handle closes. A `kill -9` orphan self-limits — its
next write to the dead pipe fails — and the startup sweep catches stragglers.
Recovery is resume-from-transcript: both harnesses persist their session
context incrementally, so an interrupted round's carry-on resume picks up
where it left off, losing at most the work since the last event.

### The harness adapters

One adapter per harness, the only code that knows a harness exists — the
`round_command` boundary grown into a class, in the shape audacious proved: a
small frozen object that builds the argv for a first round and a resume,
validates the binary is on PATH, and parses one stream line into events.

Claude Code: first round `claude --print --output-format stream-json
--verbose --permission-mode auto --allowedTools <the recurring writes>
--name <session-key> --model <model> --effort <effort> <prompt>`; resume the
same base plus `--continue <prompt>` (Claude recovers model and effort
itself; `--name` is kept from the ported command, naming the session after
the session key). The allowed writes list is the ported one: `gh pr
create/comment/edit/ready/close`, `gh issue create/comment`, `git commit`,
`git push`. The parser is `render-claude.sh`'s jq program as Python: init
events carry the harness session id, assistant text passes whole, tool calls
become one line via the most-telling-input fallback chain, failed tool
results surface, `result` events close the round, thinking and successes are
dropped (thinking display is a later option — the blocks are in the stream
and the parser sees them).

Codex: first round `codex exec --json -C <worktree> --approve-for-me
--model <model> -c model_reasoning_effort=... -c
sandbox_workspace_write.network_access=true <prompt>`; resume `codex exec
resume --last --json` plus the replayed settings and the ported resume
permissions (`sandbox_mode="workspace-write"`, network access,
`approval_policy="on-request"`, `approvals_reviewer="auto_review"`). `--last`
is scoped by Codex's own working-directory filter — an inherited contract
with Codex's session store, stated here so nobody rediscovers it. The parser
reads `--json` JSONL (`item.completed` items: `agent_message` text, command
and patch items as tool lines), lifted from audacious's `codex.py` and moved
from post-hoc to line-at-a-time.

These flag sets are each harness's never-stall answer, written down: Claude
answers with a pre-approved allowlist under auto mode, Codex with its
automatic reviewer. Both are the current catcher's field-proven stances.

The resume and final-round prompt texts port verbatim from `catch.sh`'s
`resume_prompt`. The carry-on prompt is new prose ("your previous round was
interrupted, carry on"), low-risk because the resumed transcript carries the
context.

Any line either parser cannot render passes through to the feed unchanged — a
broken render costs one line, never the log.

### The feed

One format regardless of harness: a timestamp, then a sentence the agent said
or a bracketed action — `[Edit] src/theme.css`, `[Bash] pytest`,
`[failed] ...` — with subagent activity indented, and round boundaries marked
with their cause ("round 3: resumed on 2 posts — a review, an inline
comment"). Timestamps make silence legible: the follow view shows the age of
the last event, which is the "working or stuck" answer and the seed of later
stall detection.

`scry GH123 --follow` shows the whole session: every round's feed
concatenated in order, boundaries between them, following at the tail while a
round is live. One completed round is an entry point from the round list —
`scry GH123 --round 2` — same rendering, static. Storage stays one directory
per round (the round is the unit that has a cause); the concatenation is the
viewer's stitch of sorted round directories. Reading a dead session and
watching a live one are the same view in different tenses.

### The relay

`watch.sh` ports as a function with one deliberate change in sequencing. The
query is a read-only peek: fetch the PR state and everything newer than the
watermark from the three sources (conversation comments, review bodies,
inline comments via the REST endpoint), filter, and return — writing nothing.
The watermark advances only when a round actually launches with that batch as
its inbox. The port's advance-on-read sequencing lost any batch whose round
never ran; advance-on-launch means a crash before launch re-reads the same
posts next tick, the "posts waiting" board state becomes real observed data
(the peek's results land in `last-tick.json`), and two sessions with posts
contending for one slot both keep their batches until each actually runs.
The residual window — crash after launch, before the round acts — stays, and
stays accepted: you can see the PR and say it again.

The filter keeps `watch.sh`'s two rules: a post is the user's when its author
is the *authenticated* account (`gh api user`, nothing configured) and its
body lacks the dreamcatcher marker prefix; and a post must say something — a
non-empty body, or an APPROVED or CHANGES_REQUESTED verdict — which drops
GitHub's empty review wrappers, including the ones wrapping the agent's own
inline replies. Timestamps are ISO-8601 strings compared as strings; an
absent watermark means the beginning of time, so a session's first peek
returns the PR's whole history.

The projection widens per dream#891: inline comments carry `path`, `line`
(with the `original_line` fallback), `start_line` (with
`original_start_line`), `side`, `id`, and `diff_hunk`, so a range suggestion
reaches the agent with the text it replaces. Each round's inbox is written to
that round's directory and kept.

The marker: every prompt the daemon composes ends with a postscript
instructing the session to end every GitHub post — PR bodies, comments,
replies on diff lines, issues — with the exact line
`<!-- dreamcatcher session=<session-key> round=<n> -->`. HTML comments don't
render on GitHub. The filter matches on the `<!-- dreamcatcher` prefix alone,
never the whole marker, because the round number varies; the session and
round metadata rides along free for later attribution. Dream's visible footer
coexists harmlessly; each system owns its own mark. Commits are not marked;
the relay only filters posts.

### The board

`scry` sorts sessions and queued issues by whose turn it is:

- needs you: PR open, no live round, nothing waiting — with idle age.
- agent working: live round — with the last feed event and its age.
- waiting: posts peeked but the round deferred at the cap, or an interrupted
  or errored round awaiting its carry-on retry — with the last exit status,
  so a run of usage-limit failures reads as what it is.
- stuck: a session in a state the daemon cannot advance — a round exited
  cleanly without opening a PR — surfaced instead of silently skipped, with
  a pointer to the feed.
- queued: eligible issues in dispatch order, each with its reason not yet —
  behind N others, blocked by GH<x>, skipped for double labels.
- done: merged or closed with the final round completed, most recent first.

Repeat attempts group under their issue: three sessions for one issue read as
three attempts at one thing, current one first. `scry GH123` shows the newest
attempt, older attempts listed beneath it. The session view shows vitals
(issue, PR, branch, harness and model, the literal first prompt), the round
list with causes and durations, and — when no round is live — the exact
command to resume the session interactively by hand (`claude --continue` from
the worktree, or the matching `codex exec resume`), built from
`session.json`.

### The contract page

`CONTRACT.md` at the repo root, a deliverable of this phase: what a skill
must do to be dispatchable. Adopt the branch you wake up on and open your PR
from it. Act on the issue reference in your prompt. Handle the resume prompts
(the inbox shape, the carry-on, the final round's merged-or-closed state).
Yield by ending your turn; the PR is the only channel. Marking is injected by
the dispatcher; the skill needs no knowledge of it.

### Cross-platform notes

Windows native is the target; CI runs the test suite on Windows, macOS, and
Linux from the first commit, with a fake harness binary standing in for
signed-in CLIs. All subprocess and file IO forces UTF-8 explicitly. Process
teardown is process-group on POSIX and Job Objects on Windows, isolated in
one module. Paths flow through `pathlib` end to end. The known pid-reuse
wrinkle in the orphan sweep is accepted: the sweep runs once at startup
against pids the daemon itself recorded, and the window is small.

### Dependencies

Python 3.11+ (`tomllib` in the standard library). The runtime shells out to
`git`, `gh`, and the harness CLIs, which the user already has and has signed
in. No `jq`, no `tmux`. The package itself aims for the standard library in
this phase; a TUI or richer rendering can add dependencies later.

## What changes, and what goes away

Gone: tmux, and with it the launch ceremony, the sandbox-escape permission
dance, the session-name liveness convention, and the dots-to-plus-signs scar.
Gone: `jq` as a prerequisite. Gone: the plugin-snapshot machinery and the
stable-path renderer publish — they existed only because the catcher lived
inside a plugin that upgrades under it; a pinned package cannot lose its own
code. Gone: `--once` and the cron-restart pattern; the foreground loop is the
run story. Gone: branch names as the message channel — the prompt carries the
issue; the branch pattern remains only as dispatcher-internal reconciliation
namespace. Gone: the clobbered single `inbox.json`; each round keeps its own.
Gone: the sibling-worktree layout and its assumption that the checkout lives
in a dedicated container directory — worktrees nest under
`.dreamcatcher/worktrees/`, and there is only one way.
Changed: the final-round guard from "final started" to "final completed".
Changed: the watermark advances at round launch, not at read — a strictly
smaller loss window than the port. Changed: the inline-comment projection
carries the range and the hunk. New, with no counterpart today: the round
records, the board, the session view, the per-round feeds, the interrupted
state and its automatic carry-on resume, the contract page.

On the dream side, later and tracked there: smith and less take the issue
from the prompt (branch scanning stays as their interactive fallback), their
prose stops naming `dream:catcher`, and the catcher and its skills retire.

## Why it's this and not something else

A local socket or early HTTP API for `scry`: cut. Everything `scry` needs is
on disk already, same machine was the stated scope, and files keep working
when the daemon is dead — which is when you most want to look. The deferred
API can sit on the same files later. Putting it back costs a protocol,
versioning, and a Windows socket story, and buys push-instead-of-poll on a
local file.

An append-only ledger file: cut in review. It recorded nothing the session
and round files don't already hold, and two stores of one story means one of
them drifts. A later phase wanting a cross-session timeline emits events
alongside the same writes, additively.

Sibling worktrees (the port's layout): cut, with no config option to bring
them back — one way, always. Nesting under `.dreamcatcher/` assumes nothing
about the user's directory habits, strengthens ownership from name-pattern to
path, and makes cleanup one deletion. The costs (gitignore-blind tools see
nested repo copies; Windows path depth) are named in the worktree section.

A supervisor that holds the truth in memory: cut. The reconcile-first crash
story is the most proven part of the old catcher, and the requirements demand
it. The daemon holds pipes and handles, never the authoritative state.

The two-layer personal config: cut for this phase. Per-harness settings
blocks in the committed config plus a `--harness` flag collapse the personal
choice to one scalar. Putting the personal file back is additive if someone
eventually needs a personal model rather than a personal harness.

Codex `approval_policy="never"` (audacious's stance): superseded. It predates
the auto-approval features; the catcher's auto-reviewer stance is
field-proven to never stall with these skills, and stalls are the failure
mode that kills unattended operation.

Orphan adoption (letting rounds survive a daemon crash and re-attaching):
cut. Both harnesses persist context incrementally, so kill-and-resume loses
almost nothing, and adoption would need cross-process pipe recovery for
marginal benefit.

WSL-first Windows support: rejected in requirements; the colleagues this
serves run native CLIs.

`raw.jsonl` retention was challenged in review and kept deliberately: it is
the debugging evidence for exactly this phase's open parser questions, and a
candidate trim once the adapters are verified, not before.

## What's still open

- Verify both harnesses exit non-zero on a usage-limit failure — the errored
  retry keys on exit status, so a limit that exits zero would misread as the
  wedge. Check what the stream's closing event says in that case too; a
  "limited" cause on the board is a cheap later refinement.
- Verify Codex `--json` early in the build: that `codex exec resume` accepts
  it at all, and that tool-call items surface with enough shape for the
  feed's action lines (audacious proves `agent_message`; the rest needs a
  live round).
- The exact event vocabulary between parser and renderer — settle it in the
  build's first slice, it's internal.
- Whether the feed shows thinking (the parser sees the blocks; display is a
  choice, default off).
- The `{issue}` substitution is the whole template vocabulary this phase;
  `{title}` or similar waits for a real need.
- Multi-repo (one place to watch all repos) stays a later phase; nothing here
  forecloses it — another repo is another state directory.
- The personal config layer, if personal models turn out to matter.
- `scry`'s name is charming and opaque; if colleagues stumble, `status` can
  arrive as an alias without cost.
