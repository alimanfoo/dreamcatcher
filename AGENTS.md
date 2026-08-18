# dreamcatcher agent guide

This guide grounds a fresh agent session before it works on this repo.

## What this is

dreamcatcher watches a repository for labelled issues, dispatches an
autonomous coding session for each, and carries each issue to a pull request
for the user to review and merge. It is the standalone, cross-platform
successor to the dream plugin's dream:catcher skill.

## Read the spec first

The project is spec-first. Before working, read the four documents in
`specs/2026-08-17-skeleton/`, in this order:

1. `requirements.md` — what must be true, in the owner's voice.
2. `state.md` — how the machinery this tool replaces works.
3. `design.md` — what we're building and how it works. This is the
   authority on every mechanism.
4. `plan.md` — the implementation phases, one PR each. If your task names a
   phase, that phase's section is your work order.

When the code you're writing has to diverge from `design.md`, say so plainly
in your PR rather than diverging silently. The spec is corrected by review,
not by drift.

## Conventions

- Write prose and code comments in plain English: common words, short
  sentences, one idea per sentence.
- Run the checks the repo defines before every commit. From the scaffold
  phase onward that means pre-commit (lint, format, types, markdown) and
  pytest with branch coverage gated at 100%.
- Keep changes lean. Add nothing a requirement or the design doesn't call
  for; prefer deleting over adding. One way to do each thing, always.
- Every path is cross-platform: Windows, macOS, and Linux are all
  first-class. Force UTF-8 on every subprocess and file operation.
