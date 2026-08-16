# Dreamcatcher: the skeleton phase

## What do I want to be able to do?

I want to label an issue on one of my repos, assign it to me, and have an agent
carry it to a pull request while I watch. I run one dreamcatcher process per
repo, from that repo's checkout, and it keeps going in the foreground. At any
point I can see what every session is doing, and I can attach to a live round
and read the agent's own words as it works — its narration, plus enough of the
tool activity to see what it's touching. I choose which harness handles which
label: some issues go to Claude Code, some to Codex. My colleagues can do the
same on their machines, including the ones on Windows, with their own GitHub
accounts and their own agent subscriptions, on their own repos or on shared
ones. On a shared repo, the label says "do this autonomously" and the assignee
says whose agent does it.

## What's wrong or missing today?

dream:catcher is a bash script wrapped in tmux. It won't run on Windows, so my
colleagues can't have it. Launching it is a permission dance because an agent
session has to escape its own sandbox to reach tmux. And I'm no bash expert, so
I find the scripts hard to review — I'm maintaining code I can't comfortably
read.

Watching is the sorest point. The first catcher ran an interactive claude
session and I could literally watch it work. The current one runs claude with
stream-json, and attaching shows raw JSON: I get some sense that something is
happening, but not what. That inadequacy is part of what triggered this whole
project. Codex is fine because it streams its plain turn output — that's my
floor.

There's no view of past sessions at all. I've been bitten by that: the same
issue got dispatched three times because I'd forgotten to remove the label, and
nothing showed me what was happening until I dug into it.

## What has to be true of anything I'd accept?

The whole lifecycle has to be there, each part in its simplest honest form:
dispatch a labelled, assigned issue into its own worktree and branch; run the
first round with a per-label prompt template that carries the issue reference
(the prompt, not the branch name, tells the session what to work on); relay
what I post on the pull
request (comments, review bodies, inline comments) into a resumed round, each
post exactly once, without the agent's own posts ever echoing back to it, and
without other accounts' posts relaying at all — remembering the agent and I
share one GitHub account; and give a merged or closed pull request one final
wrap-up round.

Both harnesses in the first slice. Many of my colleagues strongly prefer Codex,
and I'd like the choice myself.

Watching a live round has to show me the agent's words and what it's touching.
Codex's plain stream is the floor; the readability of an interactive session is
the target.

The status view has to show repeat attempts as attempts at one issue, not
unrelated rows, so the triple-dispatch surprise can't happen to me silently
again. And it stays true that a closed-but-unmerged pull request lets the issue
dispatch again — removing the label is how I say stop, and that wants
documenting prominently.

Finish open work before starting new: resume existing sessions before
dispatching new issues, one round launched per tick. Merging gets harder the
more PRs are in flight. A cap on concurrent rounds so I control token spend.

A session keeps the harness, model, and effort it was dispatched with, even if
I edit the config mid-flight. An issue carrying two mapped labels gets skipped
with a noisy complaint (I hold this one loosely).

The dispatcher-skill contract — adopt the branch, handle the resume prompt,
marking injected for you — written down as a key, visible document on the repo,
so any skill anywhere can be dispatched, not just dream's.

## What limits this?

My colleagues are on Windows, so it has to actually run there. Everyone
involved has one personal GitHub account — no machine accounts, no GitHub Apps.
The agents run on our own machines under our own subscriptions, so the tool
shells out to git, gh, and the harness CLIs we already have signed in. It has
no public endpoint, so it polls rather than listening for webhooks. And I have
to be able to review the code myself, which means Python, not bash.

## How will I know it worked?

The day I retire dream:catcher on a real repo and run dreamcatcher there
instead. Then I can remove the catcher from the dream plugin and focus that
project on what it should be about — the quality of the prompting for the
agents doing the development work. No more maintaining bash I can't review. And
when I attach to a live round, I know what the agent is doing, not just that
it's doing something.

## What's still open?

- Later, one central place to check in on all autonomously dispatched work
  across all my repos — one process, one place to look. This phase is one
  process per repo, but the design shouldn't nail that door shut.
- The noisy skip for double-labelled issues was a coin-toss; either behaviour
  would do.
- How much session history to keep and show beyond making repeat attempts
  visible — the richer ledger and status board belong to a later phase.
- Exactly where the config and state files live on disk (a design question,
  noted so it isn't lost).
- Robustness — retry with backoff, stall detection, pause — is deliberately
  deferred, and so are the HTTP API and any richer UI.
- Whether my Windows colleagues run the harness CLIs natively or inside WSL.
  It changes what "runs on Windows" has to prove, and proving it will need a
  few minutes on one of their real machines, since CI can't hold a signed-in
  harness session.
- How the dispatcher's injected marking lives alongside dream's own visible
  footer — and dream:watcher survives for hand-run sessions, so more than one
  filter is in play. Every filter has to recognise the marks agents actually
  leave, or an agent's post gets relayed back to it.
- Retiring dream:catcher takes changes on the dream side too, not just a
  deletion: smith and less learn their issue from the branch name today and
  name dream:catcher in their prose, so they'll need to take the issue from
  the dispatch prompt instead. Those become issues on the dream repo.
- "Each post exactly once" has a crack in the machinery I'm porting from: if
  the catcher dies at the wrong moment between reading my posts and the round
  acting on them, that batch is lost. The design has to decide what the relay
  actually promises across a crash.
- On a shared repo, nothing stops two machines dispatching the same issue in
  the window before its pull request exists, and nothing enforces a single
  assignee. Noted for the shared-repo door, not solved in this phase.
