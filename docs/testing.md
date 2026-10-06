# Testing

Dreamcatcher's test suite combines small behaviour tests with checks at real
process and presentation boundaries. Each technique answers a different
question; no single number is treated as proof that the program is correct.

## What the tests establish

### Branch coverage

The default suite measures branch coverage over `src/` and fails below 100%.
This establishes that it executes every measured branch in the application
source on each supported operating system. It helps expose untested alternatives
and dead code. It does not establish that the assertions are sufficient, that
every possible input was tried, or that an external service behaves as expected.

### Encoding failures

The interpreter is armed to emit `EncodingWarning`, and pytest treats that
warning as an error. Pytest refuses to start when the gate is not armed. This
catches an exercised file or subprocess operation that relies on the platform's
default text encoding. It says nothing about a path the suite did not execute.

### Recorded harness streams

Recordings under `tests/fixtures/claude/` and `tests/fixtures/codex/` contain
JSON-line streams from the two harnesses. The tests read them through the
production adapters and compare the rendered events with checked-in golden
feeds. This establishes that known harness events remain readable and render the
expected output. It does not contact Claude or Codex or test a newly changed
upstream event that has not been recorded.

### Real subprocesses with stand-in programs

Tests install executable stand-ins for `gh`, `claude`, `codex` and other child
programs at the front of `PATH`. Dreamcatcher launches them as real
subprocesses, so arguments, working directories, UTF-8 standard input, streamed
output, exit statuses and process-tree shutdown cross the operating-system
boundary. The stand-ins answer deterministically; these tests do not run paid AI
agents or prove the live programs and services are available.

### Rendered-view goldens

Terminal and HTML views are compared as exact rendered text with files under
`tests/fixtures/`. These goldens make intended presentation changes explicit and
catch missing, reordered or unexpectedly escaped content. They do not by
themselves prove browser layout or interaction. A separate browser test covers
interaction in Chromium.

## Separate test groups

The default suite excludes tests marked `browser` and `integration`. Browser
tests run the local fabricated web server and drive Chromium with Playwright.

Live GitHub integration tests call the real `gh` CLI against this repository.
They are read-only, require `gh` authentication, and are deliberately outside
the default suite and CI. They establish that the GitHub commands and response
projections still match the live service, but only for the repository facts they
read.

## What CI runs

For every push and pull request to `main`, the
[CI workflow](https://github.com/alimanfoo/dreamcatcher/blob/main/.github/workflows/ci.yml)
runs the default suite on Linux, macOS and Windows with the encoding gate and
100% branch coverage. A separate Linux job runs the browser tests in Chromium.
CI also runs the repository checks on Linux and Windows and builds and invokes
the installed command on all three operating systems. It does not run the live
GitHub integration tests.

## Run the tests

The
[agent guide](https://github.com/alimanfoo/dreamcatcher/blob/main/AGENTS.md#commands)
gives the setup and commands for the default suite, focused tests, browser
tests, live GitHub integration tests, golden regeneration and repository checks.
