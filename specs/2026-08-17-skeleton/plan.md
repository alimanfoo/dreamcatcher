# Plan: the skeleton phase

This plan breaks the skeleton phase into implementation phases, one PR per
phase, in dependency order. It is the fourth document of this spec:
`requirements.md` says what must be true, `state.md` explains the machinery this
tool replaces, `design.md` says what we're building and how it works.

Each phase section stands alone: what's in scope, the demo that proves it done,
and what it deliberately leaves for a later phase. The implementing session
reads all four documents for context, then works from its phase section here.

A section names each mechanism the phase builds and points at the `design.md`
section that says what that mechanism does. Don't restate it here, or a later
phase that changes the mechanism has two places to correct.

How the phases run: an umbrella issue tracks the skeleton, with one child issue
per phase. Each child issue's body is two lines — read the four documents in
`specs/2026-08-17-skeleton/`, then implement that phase's section of this plan.
Each child issue is marked blocked by its predecessor, so a dispatcher working
oldest-first through unblocked issues executes the phases in order, one at a
time.

Every phase is reviewed by a human, so every phase serves its reviewer:

- Generated and recorded files (`uv.lock`, the `.uncoded/` index, stream
  fixtures) land in their own commits, named as such, so the reviewer reads the
  hand-written diff and skips the rest with confidence. This holds for a bulk
  generation. An index delta cannot be separated, because pre-commit stashes
  unstaged changes, so `uncoded sync` regenerates them and fails the commit
  until they are staged with the change that caused them.
- Where a phase has golden outputs (the rendered feed, the board), the goldens
  are the review surface: read them as their user would and judge the result,
  rather than deriving it from the code.
- Every phase PR's description opens with a short reviewer's guide: what to read
  first, where the risk lives, and what is generated or mechanical and safe to
  skip.

## Phase 1: scaffold

Everything later phases inherit and nothing more: the package, the tooling, and
the conventions. No dreamcatcher behaviour at all.

In scope:

- The package: `pyproject.toml` (hatchling with hatch-vcs versioning), name
  `dreamcatcher`, `src/dreamcatcher/` layout, Python 3.12+, no runtime
  dependencies. A `dreamcatcher` console script whose CLI has `run` and `scry`
  as stub verbs (each prints that it is not yet implemented), a required verb so
  a bare `dreamcatcher` asks for one, and `--version`. uv is the workflow tool:
  a committed `uv.lock`, and CI resolving the environment with `uv run` via
  `astral-sh/setup-uv`, so agent sessions, developer machines, and CI all
  resolve identically.
- Tests: pytest with pytest-cov, branch coverage measured over `src`, gated at
  100% (`fail_under = 100`). Platform-specific branches use explicit
  `pragma: no cover` marks so the gate holds on every OS. At least one real test
  (the CLI verbs and version), so the gate is meaningful from the first commit.
- Lint and format: ruff, with alimanfoo/uncoded's `pyproject.toml` as the model
  — its `select` list including the complexity rules (mccabe `C901` with
  `max-complexity = 8`, the `PLR09xx` size limits), pydocstyle pep257,
  flake8-annotations, bandit, pathlib enforcement, and
  `PLW1514`/`EncodingWarning`-as-error so unspecified encodings fail rather than
  drift. complexipy as a second complexity gate. Type checking with `ty` —
  hallucinated signatures are the classic agent failure, and a type gate catches
  them mechanically. Markdown lint and format: markdownlint-cli2, prettier
  reflowing prose to 80 columns, and link validation (remark-validate-links) so
  renamed headings can't silently break the spec documents' cross-references.
- Pre-commit: hooks running ruff (lint and format), complexipy, `ty`, the
  markdown checks, an invisible-character check (zero-width and bidi marks,
  which agents occasionally emit and reviewers cannot see), end-of-file and
  trailing-whitespace fixes, and `uncoded sync`.
- uncoded: `[tool.uncoded]` with `source-roots = ["src", "tests", "tools"]` and
  `doc-roots` covering `README.md`, `AGENTS.md`, and `specs/`. Commit the
  generated `.uncoded/` index and skills. `AGENTS.md` (which already grounds
  fresh sessions, with `CLAUDE.md` importing it) gains the standard "Before you
  start" lines loading the uncoded navigation skills.
- CI: one workflow running the test suite on Linux, macOS, and Windows, and the
  pre-commit checks once on Linux. UTF-8 is not assumed anywhere:
  `filterwarnings = ["error::EncodingWarning"]` from day one.

Done when: CI is green on all three platforms, pre-commit passes clean, and
`uvx --from git+https://github.com/alimanfoo/dreamcatcher dreamcatcher --version`
prints a version.

Deliberately out: config parsing, the state directory, anything that touches git
or GitHub, and any real verb behaviour.

## Phase 2: config and the state directory

`run` becomes startable: it reads the config, takes the lock, creates the state
directory, and idles. No GitHub, no worktrees, no processes.

In scope:

- Parse and validate `dreamcatcher.toml` from the repo root (design.md,
  Configuration). Validation is pydantic v2 models, and every model refuses a
  key that it does not expect, so a typo'd key is a named error rather than a
  silently ignored setting. Most models reach that with `extra="forbid"`. A
  dispatch mapping cannot, because its harness blocks sit beside its label and
  so arrive as extra keys. It types those keys as the `Harness` enum instead,
  which keeps the set of harnesses in one home. Failures report as pydantic's
  own message under the path it names, which the reader can follow into the file
  ("dispatch.0.claude.model: Field required"); a phrasing of our own would be
  machinery this phase does not need. The same model convention then covers
  every JSON document the tool owns in later phases (`round.json`,
  `session.json`, `last-tick.json`), so serialization is schema'd everywhere
  rather than hand-rolled.
- Runtime dependencies arrive here: pydantic, and psutil for pid semantics (the
  lock's staleness check, and later the orphan sweep) — with rich following in
  phase 11. design.md's Dependencies section names all three.
- `--harness`, required, on the `run` subparser alone, which is where it is
  used. The config holds no harness to resolve it against: which harnesses can
  run a label is already in the blocks that label carries. Don't also declare
  the flag on the top-level parser: argparse then accepts
  `dreamcatcher --harness codex run` and silently drops the value, because the
  subparser's own default overwrites what the top-level parser captured.
- The main-checkout test (design.md, Sessions, worktrees, branches).
- The `.dreamcatcher/` bootstrap on first run (design.md, The state directory).
- The `daemon.pid` lock (design.md, The state directory), taken on start. A dead
  pid is stale, so the next run reclaims it.
- A stub tick loop: sleep on the interval, write a minimal `last-tick.json` each
  tick, exit cleanly on Ctrl-C releasing the lock.

Done when: in a repo with a valid config, `dreamcatcher run` starts, locks,
creates the state directory, and idles through empty ticks; a second `run`
refuses with a message naming the live pid; a config-error test suite shows
every mistake producing a named, readable error; and killing the daemon then
restarting reclaims the stale lock.

Deliberately out: anything touching GitHub, worktrees, or child processes; the
real tick body.

## Phase 3: the git/gh layer

Thin typed wrappers over the external commands, and the fake-executables test
rig that makes every later phase testable in CI.

In scope:

- Wrappers: `gh` issue listing by label and assignee, the open pull requests
  GitHub links to an issue, the pull requests of a branch head, the blocked-by
  query (the one page GitHub answers with, as the port reads it), `gh api user`
  (the authenticated login), repo identity, and git fetch, worktree add,
  worktree remove, branch delete. Each read hands back what gh answered, so a
  branch with two pull requests comes back with both. Each git command is one
  command, so no wrapper hides half of a failure. Every call forces UTF-8. Every
  failure surfaces the command and its stderr, never a guess.
- The error contract carries the fail-toward-inaction doctrine (see design.md,
  The tick): a read failure returns "unknown", and the caller decides what
  unknown means for its check. The wrappers never invent an answer.
- Two decisions phase 2 left for the phase that shells out. Ruff's bandit rules
  for subprocess (`suspicious-subprocess-import`,
  `subprocess-without-shell-equals-true`, `start-process-with-partial-path`) are
  waived for `tests/**` only, so the first wrapper in `src` fails the check:
  decide the waiver here, where the code that earns it lives, and say why in
  `pyproject.toml`. And every failure a wrapper raises derives from
  `ReportableError`, so the command line reports it as a message and never as a
  traceback.
- The fake-executables rig: stand-in `gh` and `git` the tests put first on PATH,
  scriptable per test to return canned responses or fail on cue. Solve the
  Windows shim question here, once — executables on Windows need an extension (a
  `.cmd` shim or similar), and every later phase inherits the answer. The answer
  is that the runner looks the program up on the PATH itself, which takes every
  extension PATHEXT names, so a `.cmd` stand-in is reachable where Windows would
  only have added `.exe`. It carries a second half for the phase that passes
  prompt text: Windows runs a `.cmd` through cmd.exe, which reads the arguments
  again.
- A small integration test suite, marked and skipped in CI, that exercises the
  real `gh` read-only against this repository for local confidence.

Done when: the `gh` wrappers round-trip against the fake rig in CI on all three
platforms, the git wrappers do the same against real git in a real checkout with
a real origin, and the marked integration tests pass locally against the real
`gh`. Real git is on every CI runner, so it proves the git commands work rather
than proving the arguments were passed.

Deliberately out: any interpretation of what the wrappers return — eligibility
rules and dispatch decisions live in phase 8.

## Phase 4: the Claude adapter and the feed

The harness boundary, the event vocabulary, and the rendering pipeline, as pure
functions over recorded streams — proven against the first harness. Dreamcatcher
spawns no processes yet.

In scope:

- The adapter interface (design.md, The harness adapters). The never-stall flag
  sets are the adapters' own data.
- The event vocabulary between parser and renderer, settled here. It was the
  last thing design.md left open about the feed.
- The Claude parser: render-claude.sh's policy as Python (design.md, The harness
  adapters).
- The renderer, which turns the parser's events into the feed's lines
  (design.md, The feed).
- The fake harness binary for the test rig: replays a recorded stream file with
  configurable delays and exit code. Later phases test process handling with it,
  no signed-in CLI needed.
- Recorded fixtures: capture real `claude --print --output-format stream-json`
  streams once, commit them, and golden-file test the parser and renderer
  against them. Keep every hook off the fixtures' path, and mark the path as not
  text so no checkout rewrites its line endings. A fixture is a verbatim
  recording, so a hook that repairs it makes the golden test assert something
  the harness never emitted. Real agent output also carries the zero-width
  characters the invisible-character check exists to reject.
- Verification: does `claude` exit non-zero on a usage-limit failure? If the
  implementing session cannot verify it headless, it becomes a named checklist
  item on this phase's PR for the user to confirm.

Done when: golden-file tests for the Claude parser and the renderer are green on
all three platforms, the fixtures are committed, and the verification result (or
its checklist item) is recorded on the PR.

Deliberately out: the Codex adapter; dreamcatcher spawning any process;
worktrees; prompts composed for real sessions.

## Phase 5: the Codex adapter

The second harness, which tests whether the adapter boundary holds. Anything
this phase changes outside an adapter should be something the second harness
showed the boundary itself ought to do.

In scope:

- The Codex parser (design.md, The harness adapters).
- The Codex command builders: first round and resume with the ported never-stall
  flags (design.md, The harness adapters), `--json` added.
- `-C <worktree>` is dropped, so `Launch` keeps the session, the model, the
  effort and the prompt it already had. Phase 6 runs every round in the
  worktree, and Codex scopes `--last` by that same directory, so the directory a
  round runs in is the one place the worktree is named.
- Recorded fixtures: capture real `codex exec --json` streams once, commit them,
  and golden-file test the parser against them.
- The design's open-list verifications, answered against codex-cli 0.148.0, so a
  later phase does not have to ask again. `codex exec resume` takes `--json`,
  and a recorded resume proves it. Its command, patch and search items each
  carry the field an action line needs.

Done when: golden-file tests for the Codex parser are green on all three
platforms, the fixtures are committed, the verification results (or their
checklist items) are recorded on the PR — and every file changed outside the
adapter and its tests is named on the PR with what the second harness showed.

The second harness showed one such thing. Both adapters read a line the same
way: parse it as JSON, hand a mapping to the harness's own reader, and send
anything else to the feed as it came. That rule belongs to the boundary, so
`Adapter.read` now holds it, and each adapter only reads its own events.

Deliberately out: everything phase 4 left out, and the item types
`codex exec --json` never streamed for a session to record: an MCP tool call and
a reasoning block. Codex counts reasoning tokens and streams no reasoning item,
so the feed reports the count and nothing else.

## Phase 6: rounds

The process layer. A round here is "argv plus directory in, records and feed
out" — nothing decides when a round runs yet.

In scope:

- Spawn a round as a child process from an adapter's argv in a given directory,
  and pump what it writes onto the round's records and the feed (design.md,
  Rounds and processes).
- Run every round in the session's worktree, which phase 5 leaves this phase to
  do. Phase 5's Codex first round names no directory of its own, and its resume
  finds the session by the directory it ran in, so a round run anywhere else
  resumes the wrong session or none.
- Give the child its prompt as a file to read on stdin, and give a child with no
  prompt a stdin already at an end. Each harness reads its prompt from stdin,
  and a harness handed a pipe the daemon holds open waits on it for ever.
- The answer to the Windows `.cmd` question that `commands.py` left to the phase
  that runs a harness (design.md, Cross-platform notes). A test asserts it on
  all three platforms.
- Keep the pump running when a line will not render (design.md, The harness
  adapters). Reading a line and rendering what was read are two steps, so the
  pump has to catch both, not just the read.
- The round record: the daemon writes `round.json` at spawn and again at exit,
  through a pydantic model per the phase 2 convention, so a corrupt record fails
  with a named error (design.md, The state directory).
- The teardown module, the one place where platform process semantics live
  (design.md, Rounds and processes).
- Tests against the fake harness on all three platforms, including the ugly
  cases: a round killed mid-stream leaves a `round.json` with no end; teardown
  really kills the child tree; a nonzero exit is captured.

Done when: those tests are green on all three platforms, and — with the clock
injected and pinned, the convention every timing test in this project uses — a
feed produced by a live fake round is byte-identical to the same stream parsed
purely in phase 4's tests: the pipeline adds nothing and loses nothing.

The stand-in harness gained what this phase needed of it: a scripted line says
which of the two streams it belongs to, so a test can put a stderr line between
two lines of stdout.

Deliberately out: worktrees, sessions, prompt composition, and any decision
about when a round runs. A round's cause waits for the phase that decides one,
so `round.json` carries no cause yet.

## Phase 7: sessions

Session creation and prompt composition: everything a dispatch produces, without
yet deciding when to dispatch.

In scope:

- Session creation: the session key, the branch, the nested worktree under
  `.dreamcatcher/worktrees/`, and `session.json` frozen at dispatch (design.md,
  Sessions, worktrees, branches). A failed creation backs out worktree and
  branch together, leaving neither behind. Phase 3's git wrappers each raise, so
  the back-out composes them and handles their failure itself.
- The harness that a dispatch runs on (design.md, Configuration). Phase 2 parses
  the blocks and leaves the choice to the phase that dispatches. A harness first
  becomes an adapter here, so this phase writes the lookup from one to the
  other, with both adapters in hand.
- First-round prompt composition: the chosen harness's template rendered with
  `{issue}`, the marker postscript appended (design.md, The relay, for the
  marker).

Done when: tests cut a real worktree and branch in a temporary git repository,
the records land and validate, a failed creation leaves no worktree and no
branch, and the prompt each harness's template composes to is pinned in full.

Deliberately out: eligibility, the tick, and any GitHub read — creation here is
invoked directly by tests.

## Phase 8: the dispatch tick

The skeleton first touches a real issue: label in, worktree cut, first round
run, pull request out.

In scope:

- Eligibility (design.md, The tick), built on phase 3's "unknown" contract.
- The real tick (design.md, The tick), replacing phase 2's stub and dispatching
  through phase 7's session creation.
- The round's cause, which phase 6 left to the phase that decides one
  (design.md, The state directory). A dispatch is the first cause there is, so
  `round.json` carries one from here on.
- The repository the tick asks GitHub about, read once as the run starts
  (design.md, The tick). It cannot change under a running daemon, and a run that
  cannot name it dispatches nothing, so `run` refuses rather than failing every
  tick.
- The failure cooldown (design.md, The tick).
- The daemon holding its own rounds, which is what the cap counts and what it
  ends as it goes down, Ctrl-C included (design.md, Rounds and processes). Phase
  6 built the teardown and left the daemon with no rounds to end.
- The startup orphan sweep (design.md, The tick). The carry-on resume of those
  sessions is phase 10's; until then they appear in `last-tick.json` as waiting.
- The startup check that every harness a run might dispatch to has its CLI
  installed: `run` refuses at once when any of them is not on the PATH, rather
  than dispatching a round that cannot start. The set is not just the harness
  `--harness` named: phase 7's `DispatchMapping.choose_harness` runs a label on
  whichever harness its own blocks settle on, so a single-block label can send a
  round to a harness the run never named. The check gathers the harnesses named
  by the blocks of every dispatch mapping, plus the one `--harness` gave, and
  `harnesses.ADAPTERS` turns each into the adapter that names its CLI. Phase 4
  left this to the phase with a caller for it: phase 3's `commands.locate` is
  the lookup. Without the check a missing CLI reads as a round that fails every
  fifteen minutes, since the cooldown cannot tell a misconfiguration from a
  blip.

Done when: an end-to-end CI test drives a full dispatch against the fakes — the
scripted `gh` offers a labelled issue, the tick cuts a real worktree, the fake
harness runs, the records land, and a second tick judges the issue handled — and
the milestone sits as a checklist item on this phase's PR for the user: label an
issue on a real repository and watch `run` carry it to an actual pull request.

Deliberately out: the relay, resumes of any kind, final rounds, and scry.

## Phase 9: the peek

The relay's read half: what did the user newly say? Pure queries and filters;
nothing moves state yet.

In scope:

- The read-only peek, its projection and its two filter rules (design.md, The
  relay).
- The watermark as a value that the peek reads but never writes (design.md, The
  relay).

Done when: CI tests cover the filter's known traps by name — the empty wrapper
around an agent's own inline reply does not pass; a marker-bearing post does not
pass; a post from another account does not pass; a range suggestion arrives with
its `start_line` and hunk; review verdicts pass with empty bodies. A recording
of what gh answered for the three post lists of one real pull request on this
repository reads the projection against GitHub's own document. It carries the
first of those traps itself, the empty reviews GitHub wrapped the inline
comments in, and it carries the `original_line` fallback as well, since the code
four of its comments were written against has moved since. Every other trap is a
page the test composes. No recording of this repository could hold a post from
another account, a post carrying a marker no session here has written yet, an
approval of your own pull request, which GitHub refuses, or a suggestion over a
range, which nobody has left here.

The peek's own shape settled two things. The tick already reads each session's
pull request state, and that read is where the peek's pull request number comes
from, so the peek fetches no state of its own. design.md's relay section is
corrected to say so. And a post's kind is the class it reads back as, so it
carries no field of its own saying the same thing again. The field the port's
projection had belongs to the phase that writes `inbox.json`, where a kind has
to survive being written down.

Deliberately out: writing the watermark, inboxes, resumes, and any wiring into
the tick.

## Phase 10: resumes

The lifecycle closes: relayed posts, interruptions, and the final round all wake
the session.

In scope:

- The watermark advancing at round launch, and each round's own `inbox.json`
  (design.md, The relay).
- The three resume kinds joining the tick's priority order (design.md, The
  tick), each with its own prompt text (design.md, The harness adapters) plus
  the marker postscript.

Done when: CI tests against the fakes prove the sequencing — a batch peeked but
never launched is re-peeked intact next tick; a killed final round's retry is
itself the final round — and the full-lifecycle milestone sits as a checklist
item on this phase's PR for the user: post a review comment on a real dispatched
PR, watch the resumed round act on it, merge, and watch the final round run.

Deliberately out: scry — though everything it will read now exists on disk.

## Phase 11: scry

The watch tower. Reads only the disk; never calls GitHub.

In scope:

- The board (design.md, The board).
- The session view, `scry GH123` (design.md, The board).
- The feed views, `--follow` and `--round N` (design.md, The feed).
- Presentation uses rich, scoped to scry alone: tables, emphasis, feed
  colouring, VT enabling on legacy Windows consoles, and automatic markup
  stripping when output is not a tty. Storage stays plain: `feed.txt` and
  everything the daemon writes remains uncoloured text; rich colours only at
  display time. (rich is the third and last of the plan's runtime dependencies —
  see phase 2.)

Done when: CI renders every board state from fabricated state directories as
golden tests, with the clock and the console width pinned so ages and wrapping
are deterministic; a dead-daemon directory still renders fully, staleness
marked; and the checklist item on this phase's PR is the one the project was
for: scry a live session and watch your agent working.

Deliberately out: any GitHub call from scry; any richer UI.

## Phase 12: contract and release

The written contract, the newcomer documentation, and the proof that the tool
can take over from the one it replaces.

In scope:

- `CONTRACT.md` at the repo root: the dispatchable-skill contract as designed
  (design.md, The contract page).
- The README's last gap: the operational truths it has to place prominently —
  removing the label is how you say stop (an issue whose PR closes unmerged will
  dispatch again while the label remains), and the crossover rule (design.md,
  Sessions, worktrees, branches). Phase 2 wrote the rest for a newcomer, under
  review: install via `uvx`, a Configuration section carrying every setting and
  its default, and the two verbs.
- A packaging check: `uvx` installing and running from a fresh environment.

Done when: the documents are in and the release checklist sits on this phase's
PR for the user — the real-Windows verification pass on a colleague's machine,
and the retirement rehearsal: run dreamcatcher on a real repository where
dream:catcher used to run. That rehearsal is the success criterion the
requirements brief names.

Deliberately out: everything the design defers — the richer ledger and UI,
multi-repo, the personal config layer, backoff, and stall detection.
