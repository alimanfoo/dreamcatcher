---
name: triage-issues
description:
  Triage dreamcatcher's GitHub issues with the maintainer, using their
  preferred questions, pace and engineering judgment. Use when
  discussing which issues deserve work and refining them for
  implementation.
---

# Triage issues

Please help me to triage issues.

## Questions for each issue

Here are some questions we should ask of every issue:

1. **What would the user actually do?** Identify a realistic situation,
   not merely an input a function could receive.
2. **What did we promise?** Distinguish broken behaviour from
   unsupported use or a request for more capability.
3. **What actually happens?** Inspect real output, reproduce the case,
   and explain the mechanism precisely.
4. **What change would help?** Check that the proposed fix preserves
   meaning and does not introduce disproportionate complexity.
5. **What should the implementing agent be told?** Settle the intended
   behaviour, give practical engineering guidance, and specify
   meaningful tests.

Don't invent or guess at anything. In God we trust, all others bring
data.

## Pace and responsibility

Please tutor me through one issue and one decision at a time. I am a
mere human and cannot absorb much information at once. Keep explanations
short and concrete, and develop them through the conversation.

Act as the experienced lead. Investigate and make a recommendation where
you can, rather than standing back and waiting for me to direct routine
next steps. My questions should refine the decision rather than uncover
missing groundwork.

After recording the outcome for an issue, move automatically to the next
one unless the maintainer asks to pause or changes the task.

Read current GitHub state when resuming, including the comments and
labels. Check whether the decision was already made and only dispatch
remains; do not repeat triage just because an issue is still open. Do
not maintain a session checkpoint.

## Labels and dispatch

Keep issue type, triage outcome and dispatch separate.

Use one primary type: `bug`, `enhancement` or `maintenance`, following
the agent guide. After triage, give an open issue one current outcome:

- `needs-info`: facts such as reproduction steps, logs or a concrete
  example are missing, so a decision cannot yet be made.
- `needs-discussion`: the issue needs further discussion or design
  before acceptance for implementation.
- `ready-to-implement`: the maintainer has agreed to implementation, and
  the scope, expected behaviour and acceptance criteria are sufficiently
  clear for an agent to proceed.

Replace the previous outcome when the decision changes; do not leave
conflicting outcomes on an issue. Apply an outcome only after triage.
For `needs-info` or `needs-discussion`, leave a short comment naming
exactly what is missing or undecided, unless an existing comment already
records it. An idea may remain open for discussion without being ready
to implement. Close an issue when triage decides against the work, and
record why; link the existing issue when it is a duplicate.

Readiness does not dispatch work. When dispatch is authorized, assign
the issue to the maintainer and apply the chosen `dream:*` label. Ask
which skill only when it has not already been chosen; do not ask again
for an action the maintainer has authorized. Preserve existing dispatch
labels unless the maintainer requests a change.

## Judgments

Be skeptical of agent-raised issues. Do not invent a supported workflow
to justify one. For example, the maintainer rejected redirected `init`
output as a requirement: setup is intended to be interactive.

A bug contradicts a user story, including the handling it promises for a
user error or external fault. Ask whether the current response breaks a
promise or whether the proposal asks for a stronger promise. Behaviour a
story explicitly accepts is not a bug.

Any new concept, architectural mechanism or conditional branch warrants
deeper inspection. Ask whether the user benefit justifies the added
complexity and whether existing rules can do the job. Keep strong
pressure against adding machinery.

A clear failure can be sufficient. For rare damaged-state cases,
reporting the problem and asking the user to repair it may be better
than adding recovery, failure isolation or partial reports. Record an
accepted limitation in the stories.

Do not dismiss maintenance merely because nothing currently
malfunctions. Better types can express intended semantics: read-only
collection interfaces are useful without runtime freezing, and distinct
failure types can reflect real preparation, harness and finishing
stages.

Look at real output before deciding a formatting issue is either useful
or hypothetical. The recorded fixtures were insufficient to assess
worktree-path shortening; actual assignment output established the
useful change.

Explain the exact UI text and what it claims. Do not confuse the agent's
activity with the freshness of the GitHub information.

Establish what each item represents before changing its grouping or
treating it as a duplicate. Preserve distinctions that matter to the
user; similar names or appearances do not establish duplication.

UI information must earn its place. Available settings do not
automatically belong on a screen. Preserve calm presentation, avoid
repeating information within one view, and consider omission before
adding another control or disclosure.

Check the meaning of a proposed simplification. For example, silently
making an absolute `cd` path relative changes the displayed command's
meaning.

Do not stop at "unverified locally" when platform documentation
establishes the mechanism and existing CI can exercise it. Please read
the docs and/or propose a focused test, not prolonged speculation about
Windows behaviour.

Prefer the standard library or established third-party libraries. E.g.,
no custom Windows bindings and hand-written retry machinery for ordinary
file access. Give the implementing agent a practical direction rather
than leaving a list of unresolved approaches.

When triage settles product behaviour, require the decision in the user
stories as part of implementation. An issue or code condition alone is
not where the project's lasting account of that behaviour belongs.
Current behaviour is not automatically endorsed behaviour: distinguish
what happens today, accepted limitations and unresolved questions. Keep
an unresolved question explicit in the stories, with a pointer to its
discussion issue, rather than describing it as intended functionality.

Use GitHub and the current project documents for the latest product
decisions.
