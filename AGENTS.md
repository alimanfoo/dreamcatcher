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
names it. When the code you're writing has to diverge from the spec, correct the
spec in the same PR, so it keeps saying what the code really does. Say in the PR
what you changed and why, so the reviewer reads the divergence rather than
finding it. The spec is corrected by review, not by drift.

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

Run the integration tests. They ask the real `gh` about this repository, so you
need `gh` signed in. The default run leaves them out, which is how CI skips
them.

```sh
uv run pytest -m integration --no-cov
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
- Never repair a file under `tests/fixtures/`. Each one is a recording: of what
  a harness streamed, of what gh answered, or of what a view rendered. Tidying
  one makes a golden test assert something that was never produced.
  `.pre-commit-config.yaml` excludes that path from every hook, and
  `.gitattributes` keeps its line endings. Write a golden that a hook would
  otherwise repair under there, as a rendered table is, since its rows end in
  the spaces that pad them.
- For a failure that the user needs to read, raise a `ReportableError`.
  `cli.main` catches that one class and prints the message, and anything else
  reaches the user as a traceback, which means a bug in the tool. A failed write
  is never a bug, so write every file through `documents.py`, whose
  `write_text`, `append_text` and `write_json` each raise a `ReportableError`
  when the write fails. An error class earns its place only when some code
  catches it by name and does something other than report it, as `github._read`
  catches `CommandError` to answer "unknown".
- Give every document the tool reads or writes a pydantic model, and read and
  write it through `documents.py`. That covers `dreamcatcher.toml` and the
  records under `.dreamcatcher/`. A mistake in a document then reads as a named
  error in plain words, not as a setting the tool quietly ignores. A one-value
  file like `daemon.pid` needs no model, though `lock.py` still writes it
  through `documents.write_text`.
- Read what GitHub answers through a `Projection` in `github.py`. It keeps the
  fields we declare and lets every other key pass, because GitHub owns that
  document and adds to it as it pleases. A `Document` refuses a key that it
  doesn't expect, which is right only for a document the tool owns itself.
- Shell out from `commands.py` alone. `pyproject.toml` waives ruff's subprocess
  rules for that one module, so any other module that imports `subprocess` fails
  the check.
- Render with rich in `scry.py` alone. It is the one module that shows anything
  to a person, and everything the daemon writes stays plain text, so a colour
  code can never reach a file. `pyproject.toml` waives no rule for this, so any
  other module that imports rich is a mistake a reviewer has to catch.
- Give a harness its prompt as a file to read, never as an argument. A round
  writes `prompt.txt` and `commands.spawn` hands it over as the child's stdin,
  so a prompt can run to any length and hold anything. On Windows cmd.exe acts
  on a percent sign or a line ending in a command line rather than passing it to
  the harness, and quoting carries neither.
- Pass any other text the tool puts on a harness's own command line through
  `commands.refuse_unquotable` first, for that same reason.
  `config.QuotableText` does this for the model and the effort a dispatch holds,
  where pydantic turns the `ValueError` into a named error. Anywhere else, catch
  the `ValueError` and raise a `ReportableError`, or the user reads a traceback.
- Name a method or a function for what it does, with a verb: `render`, `stop`,
  `strip_worktree`. A name like `rendered` or `holder` reads as a value, so a
  reader takes it for a property and not for something that runs.
- Name a boolean for the question it answers: `is_alive`, `is_subagent`, not
  `alive` or `subagent`. `if round.is_alive:` then reads as English.
- Name a class or a function that a module exports so that it still says what it
  is when another module imports it bare: `create_session`, not `create`;
  `compose_first_round_prompt`, not `first_round`. The module name qualifies it
  where it is defined and nowhere else, so a name that leans on the module reads
  as nothing at the call site. A method needs no such help, because its receiver
  says what it belongs to.
- Keep changes lean. Add nothing a requirement or the design doesn't call for;
  prefer deleting over adding. One way to do each thing, always.
- Give every issue you file its type label, `bug`, `enhancement` or
  `maintenance`, and no other label. Leave it unassigned. Which skill picks an
  issue up, and who works on it, are the user's to say, and a label or an
  assignee you add takes that choice away: a dispatch label sends a session at
  the issue before the user has read it.
- Ask of every issue you file whether an issue that is already open has to wait
  for it. When one does, mark that issue as blocked by the new one, so a
  dispatcher working through unblocked issues takes them in the right order.
  GitHub's issue dependencies carry that. Read what already blocks an issue with
  `gh api repos/{owner}/{repo}/issues/<N>/dependencies/blocked_by`, and add to
  it by posting the blocking issue's `id`, which is its own API id and not its
  number.
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
