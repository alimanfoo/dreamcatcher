# dreamcatcher agent guide

This guide grounds a fresh agent session before it works on this repo.

## What this is

dreamcatcher watches a repository for labelled issues, dispatches an
autonomous coding session for each, and carries each issue to a pull request
for the user to review and merge. It is the standalone, cross-platform
successor to the dream plugin's dream:catcher skill.

## Specs

The project is spec-first. Each phase of development has a dated folder
under `specs/`. Before working, find the spec your task belongs to — the
task usually names it. When the code you're writing has to diverge from the
spec, say so plainly in your PR rather than diverging silently. The spec is
corrected by review, not by drift.

## Conventions

- Run the checks the repo defines before every commit. From the scaffold
  phase onward that means pre-commit (lint, format, types, markdown) and
  pytest with branch coverage gated at 100%.
- Keep changes lean. Add nothing a requirement or the design doesn't call
  for; prefer deleting over adding. One way to do each thing, always.
- Every path is cross-platform: Windows, macOS, and Linux are all
  first-class. Force UTF-8 on every subprocess and file operation.
