# dreamcatcher agent guide

This guide grounds a fresh agent session before it works on this repo.

## Before you start

Run `uv run uncoded sync` first. Git ignores the index it writes under
`.uncoded/`, so a fresh clone or worktree holds none of it, and both skills
below read the index.

- Load the `uncoded-code-navigation` skill once per session, before searching,
  reading or editing any code.
- Load the `uncoded-doc-navigation` skill once per session, before searching,
  reading or editing any docs.

## What this is

dreamcatcher dispatches autonomous agent conversations and coding assignments
from labelled issues. It carries each assignment to a pull request for review.

## Specs

The project is spec-first. Each phase of development has a dated folder under
`specs/`. Before working, find the spec your task belongs to — the task usually
names it. When the code you're writing has to diverge from that spec, correct it
in the same PR, so it keeps saying what the code really does. Say in the PR what
you changed and why, so the reviewer reads the divergence rather than finding
it. The spec is corrected by review, not by drift.

Leave every other spec as it stands, however far the code has moved since. Each
one is a historical record of what a completed phase set out to do, so bringing
it up to date would take that record away.

## The standard

[docs/standard.md](docs/standard.md) says how good the work has to be and how we
tell. Read it before you change code. Give every pull request description a
section headed "Definition of done" that answers each of its questions by
number. Where this guide's conventions and the standard's criteria cover the
same ground, the standard sets the bar and the conventions say how to meet it.

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
suite can satisfy, and `-n 0` runs the file in this process, because starting a
worker for each processor costs more than one file saves.

```sh
PYTHONWARNDEFAULTENCODING=1 uv run pytest tests/test_cli.py --no-cov -n 0
```

Run the integration tests. They ask the real `gh` about this repository, so you
need `gh` signed in. The default run leaves them out, which is how CI skips
them.

```sh
PYTHONWARNDEFAULTENCODING=1 uv run pytest -m integration --no-cov
```

Run every check CI runs:

```sh
uv run pre-commit run --all-files
```

### Browser tests and visual checks

Install Chromium once, then run the browser tests that the default suite leaves
out:

```sh
uv run playwright install --with-deps chromium
PYTHONWARNDEFAULTENCODING=1 uv run pytest -m browser --no-cov
```

On Windows PowerShell:

```powershell
$env:PYTHONWARNDEFAULTENCODING = "1"; uv run pytest -m browser --no-cov
```

To inspect the web UI without using real Dreamcatcher state, start the
fabricated web server in one terminal:

```sh
uv run python tests/serve_fabricated_web.py
```

The command prints the home, assignment and conversation page addresses and runs
until interrupted. Use one of those addresses with Playwright to exercise the
page or capture a screenshot:

```sh
uv run playwright screenshot --full-page --viewport-size="1280,800" ADDRESS SCREENSHOT.png
```

Open the PNG with the harness's image viewer. For interactions beyond the
Playwright command, put a throwaway Python script outside the repository and
drive the printed address with Playwright's synchronous API.

## Conventions

### Development workflow and fixtures

- Run the tests and the checks before every commit. The commit hook runs the
  checks, never the tests.
- Never commit with `--no-verify`. CI runs the same checks and fails the build.
- Re-stage and commit again when a hook rewrites a file. The formatters and
  `uncoded sync` repair what they find, then report the commit as failed, so the
  repair is already in your working tree.
- Never edit `.uncoded/` or the `uncoded-*` skills by hand. `uncoded sync`
  writes them from the source and the docs, and overwrites them on every commit.
- Never repair a file under `tests/fixtures/` by hand. Each one is a recording:
  of what a harness streamed, of what gh answered, or of what a view rendered.
  Tidying one makes a golden test assert something that was never produced.
  `.pre-commit-config.yaml` excludes that path from every hook, and
  `.gitattributes` keeps its line endings.
- Never edit a vendored browser dependency or licence. Follow
  `src/dreamcatcher/static/vendor/README.md` when updating one. The repository
  excludes that directory from hooks and line-ending rewrites.
- Put every golden under `tests/fixtures/`, and nowhere else, because that is
  the one path no hook rewrites. A rendered table's rows end in the spaces that
  pad them, and the trailing-whitespace hook would take those away anywhere
  else, so the test would then assert what the view never wrote.

Regenerate every rendered-view golden after a presentation change with the
encoding warning variable set as described above:

```sh
PYTHONWARNDEFAULTENCODING=1 uv run pytest --regenerate-view-goldens
```

On Windows PowerShell:

```powershell
$env:PYTHONWARNDEFAULTENCODING = "1"; uv run pytest --regenerate-view-goldens
```

### Errors and documents

- For a failure that the user needs to read, raise a `ReportableError`.
  `cli.main` catches that one class and prints the message, and anything else
  reaches the user as a traceback, which means a bug in the tool. A failed write
  is never a bug, so write every file through `documents.py`, whose
  `write_text`, `append_text` and `write_json` each raise a `ReportableError`
  when the write fails. An error class earns its place only when some code
  catches it by name and does something other than report it, as the GitHub
  command fallbacks catch `CommandError` to answer "unknown".
- Give every document the tool reads or writes a pydantic model, and read and
  write it through `documents.py`. That covers `dreamcatcher.toml` and the
  records under `.dreamcatcher/`. A mistake in a document then reads as a named
  error in plain words, not as a setting the tool quietly ignores. A one-value
  file needs no model, though its writer must still use `documents.write_text`.
- Read what GitHub answers through a `GitHubResponseProjection` in `github.py`.
  It keeps the fields we declare and lets every other key pass, because GitHub
  owns that document and adds to it as it pleases. A `DreamcatcherDocument`
  refuses a key that it doesn't expect, which is right only for a document the
  tool owns itself.

### Module and process boundaries

- Give a package one face: its `__init__.py` imports what modules outside the
  package import, straight from the submodule that defines each name, and lists
  those names in `__all__`. Nothing is exported because a test wanted it; a test
  imports from the submodule. Ruff reports an import that the list leaves out,
  so a new export cannot go unlisted.
- Shell out from `commands.py` alone. `pyproject.toml` waives ruff's subprocess
  rules for that one module, so any other module that imports `subprocess` fails
  the check.
- Render with Rich in the TUI modules alone, so everything the daemon writes
  stays plain text and a colour code can never reach a file. The architecture
  import check enforces the Rich and Flask presentation boundaries.
- Write HTML markup in the templates under `src/dreamcatcher/templates/` alone,
  and render those templates in the web interface alone. The web modules own
  presentation and must not become another home for status, scheduling or
  lifecycle rules.
- Give a harness its prompt as a file to read, never as an argument. A round
  writes `prompt.txt` and `commands.spawn_command` hands it over as the child's
  stdin, so a prompt can run to any length and hold anything. On Windows cmd.exe
  acts on a percent sign or a line ending in a command line rather than passing
  it to the harness, and quoting carries neither.
- Pass any other text the tool puts on a harness's own command line through
  `commands.refuse_unquotable` first, for that same reason.
  `config.QuotableText` does this for the model and the effort a dispatch holds,
  where pydantic turns the `ValueError` into a named error. Anywhere else, catch
  the `ValueError` and raise a `ReportableError`, or the user reads a traceback.

### API design

- Give every function and method keyword-only parameters, so a call says what
  each argument means and reordering a signature cannot change what a caller
  already passes. `tools/require_keyword_parameters.py` enforces this on every
  commit, and its own docstring says what it leaves alone. Where something
  outside dreamcatcher makes the call, declare the parameter positional-only
  with `/`, and say in the docstring what makes the call that way.
- Give a callback parameter a `Protocol` whose `__call__` is keyword-only, where
  this project implements the callback itself and it takes more than one
  argument. A `Callable` has no keyword-only form, so a callback typed as one is
  called by position. A callback that takes nothing has nothing to pass, and one
  whose value comes from outside has a shape this project does not own, so
  either of those keeps a `Callable`.

### Naming conventions

- Name a method or a function for what it does, with a verb: `render`, `stop`,
  `strip_worktree_path`. A name like `rendered` or `holder` reads as a value, so
  a reader takes it for a property and not for something that runs.
- Name a boolean for the question it answers: `is_alive`, `is_subagent`, not
  `alive` or `subagent`. `if round.is_alive:` then reads as English.
- Name a class or a function that a module exports so that it still says what it
  is when another module imports it bare: `create_assignment`, not `create`;
  `compose_first_round_prompt`, not `first_round`. The module name qualifies it
  where it is defined and nowhere else, so a name that leans on the module reads
  as nothing at the call site. A method needs no such help, because its receiver
  says what it belongs to.

### Docstring conventions

- Give every module, exported class, exported function and public method a
  docstring. Give a private object a docstring only when its name, signature,
  types and immediate context do not make its contract or intent clear.
- Follow PEP 257: begin a function or method docstring with an imperative
  summary sentence, then put any further contract information in paragraphs
  after a blank line. Let a module or class summary directly describe its
  responsibility or the thing it represents. A property's summary describes the
  value instead, as pydocstyle requires.
- Document side effects, invariants, ordering, selection rules, important
  failure conditions and constraints that a caller cannot safely infer from the
  signature. Do not narrate the implementation or repeat names, types, defaults
  and obvious return values.
- Let each source carry only what it owns: signatures and types describe shape,
  code describes the current mechanism, comments explain non-obvious
  implementation choices, specifications describe system-level behaviour, and
  tests demonstrate cases and boundaries.

### Change and issue conventions

- Keep changes lean. Add nothing a requirement or the design doesn't call for;
  prefer deleting over adding. One way to do each thing, always.
- Give every issue you file its type label, `bug`, `enhancement` or
  `maintenance`, and no other label. Leave it unassigned. Which skill picks an
  issue up, and who works on it, are the user's to say, and a label or an
  assignee you add takes that choice away: a dispatch label starts agent work on
  the issue before the user has read it.
- Ask of every issue you file whether an issue that is already open has to wait
  for it. When one does, mark that issue as blocked by the new one, so a
  dispatcher working through unblocked issues takes them in the right order.
  GitHub's issue dependencies carry that. Read what already blocks an issue with
  `gh api repos/{owner}/{repo}/issues/<N>/dependencies/blocked_by`, and add to
  it by posting the blocking issue's `id`, which is its own API id and not its
  number.

### Cross-platform code and tests

- Store every time in UTC and show every time in the viewer's local zone.
- Every path is cross-platform: Windows, macOS, and Linux are all first-class.
  Force UTF-8 on every subprocess and file operation. Ruff's
  `unspecified-encoding` rule catches a file opened without `encoding=`. Ruff
  cannot see subprocess calls, so the test suite catches those: it fails on any
  EncodingWarning a test reaches.
- If a test writes a file and then asserts a byte count or the exact text of a
  line in it, write the file with `write_bytes`. `path.write_text("a\nb\n")`
  turns each newline into the one the platform prefers, so on Windows the file
  holds `a\r\nb\r\n` and every count is two bytes larger. Nothing catches that:
  ruff cannot see it, and a run on macOS or Linux passes. Writing through
  `documents.write_text` or `append_text` is the other way, because both pin the
  line endings.
- Cover both arms of every branch. The suite gates branch coverage over `src` at
  100%. When an arm looks unreachable it is dead code, so remove it rather than
  reach for a pragma. Mark a genuinely platform-specific branch with
  `pragma: no cover`, so the gate holds on every OS.
- A complexity violation means the function is too complex. Split it. Never
  suppress the violation and never raise the threshold.
