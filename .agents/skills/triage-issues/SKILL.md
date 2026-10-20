---
name: triage-issues
description: Triage dreamcatcher's GitHub issues with the maintainer, using their preferred questions, pace and engineering judgment. Use when discussing which issues deserve work and refining them for implementation.
---

# Triage issues

These are lessons from the maintainer's steering during issue triage.

## Questions for each issue

1. **What would the user actually do?** Identify a realistic situation, not
   merely an input a function could receive.
2. **What did we promise?** Distinguish broken behaviour from unsupported use or
   a request for more capability.
3. **What actually happens?** Inspect real output, reproduce the case, and
   explain the mechanism precisely.
4. **What change would help?** Check that the proposed fix preserves meaning and
   does not introduce disproportionate complexity.
5. **What should the implementing agent be told?** Settle the intended
   behaviour, give practical engineering guidance, and specify meaningful tests.

## Pace and responsibility

- The maintainer wants tutoring through one issue and one decision at a time.
  They cannot absorb much information at once. Keep explanations short and
  concrete, and develop them through the conversation.
- Act as the experienced lead. Investigate and make a recommendation rather
  than making the maintainer direct routine next steps. Their questions should
  refine the decision rather than uncover missing groundwork.
- After resolving an issue, move automatically to the next. Pause when asked.
- Read current GitHub state when resuming. Do not maintain a session checkpoint.

## Judgments the maintainer corrected

- Be skeptical of agent-raised issues. Do not invent a supported workflow to
  justify one. For example, the maintainer rejected redirected `init` output as
  a requirement: setup is intended to be interactive.
- A user error or external fault can expose a bug in the handling we promised.
  Distinguish that from asking for stronger recovery than we promise.
- Do not dismiss maintenance merely because nothing currently malfunctions.
  Better types can express intended semantics: read-only collection interfaces
  are useful without runtime freezing, and distinct failure types can reflect
  real preparation, harness and finishing stages.
- Look at real output before deciding a formatting issue is either useful or
  hypothetical. The recorded fixtures were insufficient to assess worktree-path
  shortening; actual assignment output established the useful change.
- Explain the exact UI text and what it claims. Making two cases consistently
  say `waiting` is not enough if neither has a round known to be due. Do not
  confuse the agent's activity with the freshness of the GitHub information.
- Check the meaning of a proposed simplification. Silently making an absolute
  `cd` path relative changes the displayed command's meaning. An explicit
  abbreviation can communicate what was omitted.
- Do not stop at "unverified locally" when platform documentation establishes
  the mechanism and existing CI can exercise it. The maintainer expects a
  focused test, not prolonged speculation about Windows behaviour.
- Prefer the standard library or established third-party libraries. The
  maintainer pushed back on custom Windows bindings and hand-written retry
  machinery for ordinary file access. Give the implementing agent a practical
  direction rather than leaving a list of unresolved approaches.
- Check earlier decisions before presenting an issue as unresolved. A change
  that limits release measurements to recent PRs may already address the
  maintainer's concern about historical shortcomings counting forever.
- When triage settles product behaviour, require the decision in the user
  stories as part of implementation. An issue or code condition alone is not
  where the project's lasting account of that behaviour belongs.

The examples record the reasoning the maintainer had to steer. Use GitHub and
the current project documents for the latest product decisions.
