# dreamcatcher agent guide

This guide grounds a fresh agent session before it works on this repo.

## Before you start

- Load the `uncoded-code-navigation` skill before searching, reading or editing
  any code.
- Load the `uncoded-doc-navigation` skill before searching, reading or editing
  any docs.

## What this is

dreamcatcher watches a repository for labelled issues, dispatches an autonomous
coding session for each, and carries each issue to a pull request for the user
to review and merge. It is the standalone, cross-platform successor to the dream
plugin's dream:catcher skill.

## Specs

The project is spec-first. Each phase of development has a dated folder under
`specs/`. Before working, find the spec your task belongs to — the task usually
names it. When the code you're writing has to diverge from the spec, say so
plainly in your PR rather than diverging silently. The spec is corrected by
review, not by drift.

## Dev setup

Install the tools and the commit hooks:

```sh
uv sync --extra dev
uv run pre-commit install
```

Develop on Python 3.12 or newer. The package itself supports 3.11 and CI proves
that floor. uncoded needs 3.12, so the commit hooks cannot run on 3.11.

## Commands

Run the tests. `PYTHONWARNDEFAULTENCODING=1` makes the interpreter emit
EncodingWarning, which the suite turns into a failure.

```sh
PYTHONWARNDEFAULTENCODING=1 uv run pytest
```

On Windows PowerShell:

```powershell
$env:PYTHONWARNDEFAULTENCODING = "1"; uv run pytest
```

Run one test file. `--no-cov` turns off the coverage gate, which only the whole
suite can satisfy.

```sh
uv run pytest tests/test_cli.py --no-cov
```

Run every check CI runs:

```sh
uv run pre-commit run --all-files
```

## Conventions

- Run the tests and the checks before every commit. The commit hook runs the
  checks, never the tests.
- Never commit with `--no-verify`. CI runs the same checks and fails the build.
- Keep changes lean. Add nothing a requirement or the design doesn't call for;
  prefer deleting over adding. One way to do each thing, always.
- Every path is cross-platform: Windows, macOS, and Linux are all first-class.
  Force UTF-8 on every subprocess and file operation. Ruff's
  `unspecified-encoding` rule catches a missing `encoding=` at commit time, and
  the test suite fails on any EncodingWarning a test reaches at runtime.
- Cover both arms of every branch. The suite gates branch coverage over `src` at
  100%. When an arm looks unreachable it is dead code, so remove it rather than
  reach for a pragma. Mark a genuinely platform-specific branch with
  `pragma: no cover`, so the gate holds on every OS.
- A complexity violation means the function is too complex. Split it. Never
  suppress the violation and never raise the threshold.
