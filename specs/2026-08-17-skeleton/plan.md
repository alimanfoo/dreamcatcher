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
