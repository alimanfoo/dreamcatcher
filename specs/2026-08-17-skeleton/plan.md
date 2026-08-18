# Plan: the skeleton phase

This plan breaks the skeleton phase into implementation phases, one PR per
phase, in dependency order. It is the fourth document of this spec:
`requirements.md` says what must be true, `state.md` explains the machinery
this tool replaces, `design.md` says what we're building and how it works.

Each phase section stands alone: what's in scope, the demo that proves it
done, and what it deliberately leaves for a later phase. The implementing
session reads all four documents for context, then works from its phase
section here. Where a section names a mechanism without detail, the detail is
in `design.md`.

How the phases run: an umbrella issue tracks the skeleton, with one child
issue per phase. Each child issue's body is two lines — read the four
documents in `specs/2026-08-17-skeleton/`, then implement that phase's
section of this plan. Each child issue is marked blocked by its predecessor,
so a dispatcher working oldest-first through unblocked issues executes the
phases in order, one at a time.

## Phase 1: scaffold

Everything later phases inherit and nothing more: the package, the tooling,
and the conventions. No dreamcatcher behaviour at all.

In scope:

- The package: `pyproject.toml` (hatchling with hatch-vcs versioning), name
  `dreamcatcher`, `src/dreamcatcher/` layout, Python 3.11+, no runtime
  dependencies. A `dreamcatcher` console script whose CLI has `run` and
  `scry` as stub verbs (each prints that it is not yet implemented), bare
  invocation meaning `run`, and `--version`. uv is the workflow tool: a
  committed `uv.lock`, and CI resolving the environment with `uv run` via
  `astral-sh/setup-uv`, so agent sessions, developer machines, and CI all
  resolve identically.
- Tests: pytest with pytest-cov, branch coverage measured over `src`, gated
  at 100% (`fail_under = 100`). Platform-specific branches use explicit
  `pragma: no cover` marks so the gate holds on every OS. At least one real
  test (the CLI verbs and version), so the gate is meaningful from the first
  commit.
- Lint and format: ruff, with alimanfoo/uncoded's `pyproject.toml` as the
  model — its `select` list including the complexity rules (mccabe `C901`
  with `max-complexity = 8`, the `PLR09xx` size limits), pydocstyle pep257,
  flake8-annotations, bandit, pathlib enforcement, and
  `PLW1514`/`EncodingWarning`-as-error so unspecified encodings fail rather
  than drift. complexipy as a second complexity gate. Type checking with
  `ty` — hallucinated signatures are the classic agent failure, and a type
  gate catches them mechanically. Markdown lint and format:
  markdownlint-cli2 and prettier at 80 columns, as in the dream repo, plus
  link validation (remark-validate-links) so renamed headings can't silently
  break the spec documents' cross-references.
- Pre-commit: hooks running ruff (lint and format), complexipy, `ty`, the
  markdown checks, an invisible-character check (zero-width and bidi marks,
  which agents occasionally emit and reviewers cannot see), end-of-file and
  trailing-whitespace fixes, and `uncoded sync`.
- uncoded: `[tool.uncoded]` with `source-roots = ["src", "tests"]` and
  `doc-roots` covering `README.md`, `AGENTS.md`, and `specs/`. Commit the
  generated `.uncoded/` index and skills. `AGENTS.md` gains the standard
  "Before you start" lines loading the uncoded navigation skills, plus the
  project's one-paragraph orientation: what dreamcatcher is, where the spec
  documents live, and that pre-commit and the tests must pass before every
  commit.
- CI: one workflow running the test suite on Linux, macOS, and Windows, and
  the pre-commit checks once on Linux. UTF-8 is not assumed anywhere:
  `filterwarnings = ["error::EncodingWarning"]` from day one.

Done when: CI is green on all three platforms, pre-commit passes clean, and
`uvx --from git+https://github.com/alimanfoo/dreamcatcher dreamcatcher
--version` prints a version.

Deliberately out: config parsing, the state directory, anything that touches
git or GitHub, and any real verb behaviour.

## Phase 2: config and the state directory

`run` becomes startable: it reads the config, takes the lock, creates the
state directory, and idles. No GitHub, no worktrees, no processes.

In scope:

- Parse and validate `dreamcatcher.toml` from the repo root: `interval`,
  `max_agents`, `assignee`, the default `harness`, and the `[[dispatch]]`
  mappings, each with a label and per-harness settings blocks carrying
  `prompt`, `model`, and `effort`, plus the optional per-mapping `harness`
  pin (see design.md, Configuration). Every validation failure names the
  field and what's wrong with it in plain words.
- `--harness` resolution: the flag wins, else the config default; a mapping's
  pin overrides both for that label.
- The main-checkout test: `run` refuses to start anywhere but a main
  checkout — a linked worktree's `.git` is a file, not a directory.
- `.dreamcatcher/` bootstrap: create it on first run with a `.gitignore`
  containing `*`, so the directory ignores itself and `git status` stays
  clean from the first tick.
- The `daemon.pid` lock: take it on start, refuse a second `run` on the same
  repo while the pid is alive, and treat a dead pid as stale and reclaim it.
- A stub tick loop: sleep on the interval, write a minimal `last-tick.json`
  each tick, exit cleanly on Ctrl-C releasing the lock.

Done when: in a repo with a valid config, `dreamcatcher run` starts, locks,
creates the state directory, and idles through empty ticks; a second `run`
refuses with a message naming the live pid; a config-error test suite shows
every mistake producing a named, readable error; and killing the daemon then
restarting reclaims the stale lock.

Deliberately out: anything touching GitHub, worktrees, or child processes;
the real tick body.

## Phase 3: the git/gh layer

Thin typed wrappers over the external commands, and the fake-executables
test rig that makes every later phase testable in CI.

In scope:

- Wrappers: `gh` issue listing by label and assignee, PR lookup by branch
  head, the blocked-by query, `gh api user` (the authenticated login), repo
  identity, and git worktree add and remove, fetch. Every call forces UTF-8.
  Every failure surfaces the command and its stderr, never a guess.
- The error contract carries the fail-toward-inaction doctrine (see
  design.md, The tick): a read failure returns "unknown", and the caller
  decides what unknown means for its check. The wrappers never invent an
  answer.
- The fake-executables rig: stand-in `gh` and `git` the tests put first on
  PATH, scriptable per test to return canned responses or fail on cue. Solve
  the Windows shim question here, once — executables on Windows need an
  extension (a `.cmd` shim or similar), and every later phase inherits the
  answer.
- A small integration test suite, marked and skipped in CI, that exercises
  the real `gh` read-only against this repository for local confidence.

Done when: the wrappers round-trip against the fake rig in CI on all three
platforms, and the marked integration tests pass locally against the real
`gh`.

Deliberately out: any interpretation of what the wrappers return —
eligibility rules and dispatch decisions live in phase 6.

## Phase 4: adapters and the feed

The harness boundary and the rendering pipeline, as pure functions over
recorded streams. Dreamcatcher spawns no processes yet.

In scope:

- The adapter interface: one small frozen object per harness that builds the
  first-round argv, builds the resume argv, validates the binary is on PATH,
  and parses one stream line into events. The never-stall flag sets from
  design.md (The harness adapters) are the adapters' data.
- The event vocabulary between parser and renderer, settled here — this is
  the "first slice" the design's open list points at.
- The Claude parser: render-claude.sh's policy as Python — session id from
  the init event, assistant text whole, thinking rendered and on by default,
  tool calls as one line via the most-telling-input fallback chain, failed
  tool results surfaced, result events closing the round, subagent lines
  indented, and any unparseable line passed through unchanged.
- The Codex parser: `--json` JSONL, `item.completed` items — `agent_message`
  text, command and patch items as tool lines — lifted from audacious's
  codex.py and moved from post-hoc to line-at-a-time.
- The renderer: timestamped feed lines, round-boundary lines carrying the
  round's cause.
- The fake harness binary for the test rig: replays a recorded stream file
  with configurable delays and exit code. Phases 5 through 7 test process
  handling with it, no signed-in CLI needed.
- Recorded fixtures: capture real `claude --print --output-format
  stream-json` and `codex exec --json` streams once, commit them, and
  golden-file test both parsers against them.
- The design's open-list verifications: does `codex exec resume` accept
  `--json`; do its tool items carry enough shape for the feed's action
  lines; do both CLIs exit non-zero on a usage-limit failure. Whatever the
  implementing session cannot verify headless (a signed-in run, a real
  limit) becomes a named checklist item on this phase's PR for the user to
  confirm.

Done when: golden-file tests for both parsers are green on all three
platforms, the fixtures are committed, and the verification results (or
their checklist items) are recorded on the PR.

Deliberately out: dreamcatcher spawning any process; worktrees; prompts
composed for real sessions.
