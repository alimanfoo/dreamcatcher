# Testing

_dreamcatcher_'s test suite combines small behaviour tests with checks
at real process and presentation boundaries. Each technique answers a
different question; no single number is treated as proof that the
program is correct.

## What the tests establish

### Branch coverage

The default suite measures branch coverage over `src/` and fails below
100%. This establishes that it executes every measured branch in the
application source on each supported operating system and Python
version. It helps expose untested alternatives and dead code. It does
not establish that the assertions are sufficient, that every possible
input was tried, or that an external service behaves as expected.

### Encoding failures

The interpreter is armed to emit `EncodingWarning`, and pytest treats
that warning as an error. Pytest refuses to start when the gate is not
armed. This catches an exercised file or subprocess operation that
relies on the platform's default text encoding. It says nothing about a
path the suite did not execute.

### Recorded harness streams

Recordings under `tests/fixtures/claude/` and `tests/fixtures/codex/`
contain JSON-line streams from the two harnesses. The tests read them
through the production adapters and compare the rendered events with
checked-in golden feeds. This establishes that known harness events
remain readable and render the expected output. It does not contact
Claude or Codex or test a newly changed upstream event that has not been
recorded.

### Real subprocesses with stand-in programs

Tests install executable stand-ins for `gh`, `claude`, `codex` and other
child programs at the front of `PATH`. _dreamcatcher_ launches them as
real subprocesses, so arguments, working directories, UTF-8 standard
input, streamed output, exit statuses and process-tree shutdown cross
the operating-system boundary. The stand-ins answer deterministically;
these tests do not run paid AI agents or prove the live programs and
services are available.

### Rendered-view goldens

Terminal and HTML views are compared as exact rendered text with files
under `tests/fixtures/`. These goldens make intended presentation
changes explicit and catch missing, reordered or unexpectedly escaped
content. They do not by themselves prove browser layout or interaction.
Separate browser tests cover layout and interaction in Chromium.

## Separate test groups

The default suite excludes tests marked `browser` and `integration`.
Browser tests run the local fabricated web server and drive Chromium
with Playwright.

Live GitHub integration tests call the real `gh` CLI against this
repository. They are read-only, require `gh` authentication, and are
deliberately outside the default suite and CI. They establish that the
GitHub commands and response projections still match the live service,
but only for the repository facts they read.

## Hung tests

Every test in every group has two minutes to finish, counting its
fixture setup and teardown. A session-scoped fixture counts against the
first test that uses it. The limit is there to end a run that has hung,
not to measure speed: the slowest test takes well under a minute on
every platform that CI runs.

Ten seconds before the limit, pytest writes the stack of every thread to
standard error. When the limit passes, `pytest-timeout` ends the test.

On Linux and macOS it fails the test with the stack where the test hung.
The fixture teardown then runs with no limit, and the run carries on
unless the teardown hangs as well.

On Windows it ends the process that runs the test. In the default run
that process is an xdist worker, and the report says that the worker
crashed while it ran the hung test, which the report names. The stack
that pytest wrote ten seconds before is the only one that shows. The run
carries on in a new worker, but the fixture teardown of the hung test
never runs, and the coverage gate fails as well, because the
measurements of the ended worker are lost. With `-n 0` the process is
pytest itself, so the whole run ends there.

Don't rely on any cleanup after a timeout. A timeout is a last resort
for a run that is already broken, and a hung test can leave a child
process or a temporary directory behind.

To debug a test without the limit, pass
`--timeout=0 -o faulthandler_timeout=0`.

## What CI runs

For every push and pull request to `main`, the
[CI workflow](https://github.com/alimanfoo/dreamcatcher/blob/main/.github/workflows/ci.yml)
runs the default suite on Linux, macOS and Windows with the encoding
gate and 100% branch coverage. A separate Linux job runs the browser
tests in Chromium. CI also runs the repository checks on Linux and
Windows and builds and invokes the installed command on all three
operating systems. The checks include a strict build of the
documentation site. CI does not run the live GitHub integration tests.

For every push to `main`, the
[docs workflow](https://github.com/alimanfoo/dreamcatcher/blob/main/.github/workflows/docs.yml)
builds the documentation site and publishes it to GitHub Pages.

## Run the tests

The
[agent guide](https://github.com/alimanfoo/dreamcatcher/blob/main/AGENTS.md#commands)
gives the setup and commands for the default suite, focused tests,
browser tests, live GitHub integration tests, golden regeneration and
repository checks.
