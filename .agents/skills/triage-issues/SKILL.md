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

After resolving an issue and accepting is as something to be worked on,
assign it to me and add an assignment label for dispatch via
dreamcatcher, ask me which. Then move automatically to the next issue.

Read current GitHub state when resuming. Do not maintain a session
checkpoint.

## Judgments

Be skeptical of agent-raised issues. Do not invent a supported workflow
to justify one. For example, the maintainer rejected redirected `init`
output as a requirement: setup is intended to be interactive.

Be clear about what is a bug, where a documented user story does not
work as promised, versus what is handling of a user error or external
fault. When deciding issues which propose changes to how user errors or
external faults should be handled, consider the promises in the user
stories.

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

Use GitHub and the current project documents for the latest product
decisions.
