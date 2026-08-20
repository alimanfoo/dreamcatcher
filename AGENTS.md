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
to review and merge.

## Specs

The project is spec-first. Each phase of development has a dated folder under
`specs/`. Before working, find the spec your task belongs to — the task usually
names it. When the code you're writing has to diverge from the spec, say so
plainly in your PR rather than diverging silently. The spec is corrected by
review, not by drift.

## Dev setup

Install the tools and the commit hooks:

```sh
uv sync
uv run pre-commit install
```

`.python-version` names the interpreter, and CI reads the same file, so every
machine runs the same Python. `uv sync` installs the `dev` dependency group
without being asked.

## Commands

Run the tests. `PYTHONWARNDEFAULTENCODING=1` makes the interpreter emit
EncodingWarning, which the suite turns into a failure. pytest refuses to run
without it.

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
- Re-stage and commit again when a hook rewrites a file. The formatters and
  `uncoded sync` repair what they find, then report the commit as failed, so the
  repair is already in your working tree.
- Never edit `.uncoded/` or the `uncoded-*` skills by hand. `uncoded sync`
  writes them from the source and the docs, and overwrites them on every commit.
- Give every document the tool reads or writes a pydantic model, and read and
  write it through `documents.py`. That covers `dreamcatcher.toml` and the
  records under `.dreamcatcher/`, but not a one-value file like `daemon.pid`. A
  mistake in a document then reads as a named error in plain words, not as a
  setting the tool quietly ignores.
- Read what GitHub answers through a `Projection` in `github.py`. It keeps the
  fields we declare and lets every other key pass, because GitHub owns that
  document and adds to it as it pleases. A `Document` forbids a key it doesn't
  declare, which is right only for a document the tool owns itself.
- Shell out from `commands.py` alone. `pyproject.toml` waives ruff's subprocess
  rules for that one module, so any other module that imports `subprocess` fails
  the check.
- Keep changes lean. Add nothing a requirement or the design doesn't call for;
  prefer deleting over adding. One way to do each thing, always.
- Every path is cross-platform: Windows, macOS, and Linux are all first-class.
  Force UTF-8 on every subprocess and file operation. Ruff's
  `unspecified-encoding` rule catches a file opened without `encoding=`. Ruff
  cannot see subprocess calls, so the test suite catches those: it fails on any
  EncodingWarning a test reaches.
- Cover both arms of every branch. The suite gates branch coverage over `src` at
  100%. When an arm looks unreachable it is dead code, so remove it rather than
  reach for a pragma. Mark a genuinely platform-specific branch with
  `pragma: no cover`, so the gate holds on every OS.
- A complexity violation means the function is too complex. Split it. Never
  suppress the violation and never raise the threshold.
