# Campaigns

This brief develops
[GH593](https://github.com/alimanfoo/dreamcatcher/issues/593) and its
comments.

## What do I want to be able to do?

I want to hand a planned body of work to an agent that carries it
through without me coordinating every stage. A campaign is that
commission, alongside assignments and conversations, and its agent is
the lead. The parent issue holds the campaign's goal; its sub-issues are
the stages.

## What's wrong or missing today?

_dreamcatcher_ carries each stage to a pull request, but I still review
and merge each one, carry what changed into later stages, and decide
when the plan needs changing. An agent did that coordination in an
interactive session for the state format 6 phase. I want _dreamcatcher_
to run that agent itself.

## What has to be true of anything I'd accept?

I start a campaign by labelling the parent issue. The campaign skill is
called `dream:lead`. The lead works through GitHub as I would,
coordinating child assignments, answering their questions, reviewing
their pull requests and merging them into main.

I want the lead to use GitHub for collaboration as it was intended. Its
feed provides a detailed view of everything it did, so it needs no
separate continuing record of the campaign. The parent issue is for
communication with me when needed and should not become a noisy action
log.

The lead assigns children to my account and gives each unlabelled child
an assignment label. It keeps any assignment label I have already
chosen. It uses judgment to choose among the configured routes and asks
me when the choice is unclear, including when I have customised the
configuration.

Before merging a stage, the lead checks its proof itself against the
roadmap's “done when”. It reads what has landed on main, gets any
specification corrections made on the stage's pull request, and updates
downstream issues to reflect what has changed. It checks main again just
before merging. Merging a stage closes its issue and lets the dependency
chain advance.

The lead asks me on the parent issue before changing requirements,
settled design decisions, or the roadmap's stages, order or
dependencies. It also asks when it cannot tell what an event means, such
as a pull request closed without merging. While it needs my decision, it
stops merging; work already in progress can continue.

I can intervene directly on GitHub. The lead adapts to my comments,
merges, closes, cancellations and label changes, and never reverses my
decisions. Removing the campaign label pauses the lead alone: no new
lead rounds start, and a running round finishes. Restoring the label
resumes it. Child assignments keep their own rules, so a manual merge
can unblock the next stage while the lead remains paused.

The lead hears about my parent comments, children being added or
starting work, stage agents handing back for review or questions, checks
finishing after their turns, stages ending, and repeated round failures.
My posts on a child's pull request reach it through the stage agent's
response. It need not wake while that agent is working or merely because
main moved.

When a child assignment is in fault, the lead investigates. If it finds
an obvious solution that the stage agent can carry out, it puts
directions on the child's pull request. It reports the problem and any
proposed resolution on the parent issue, and asks me when the solution
is unclear. Retrying the assignment is mine to do.

I want a campaigns tab in the web UI. Each campaign card shows how many
sub-issues are closed out of the total. I can expand it to see
assignment cards for every sub-issue, including those whose assignments
have not started.

## What limits this?

The lead carries out the agreed plan; changes to that plan remain mine
to decide. Stages merge into main. Only I close the parent issue, which
ends the campaign. Until then I can add sub-issues for follow-on work.

## How will I know it worked?

An agreed chain of stages progresses through review and merge without me
coordinating every handoff. I am asked when a decision needs me, and I
can see progress across the whole campaign. For now, all sub-issues
being closed is enough of a completion signal; I decide whether I am
satisfied.

## What's still open?

I have no remaining requirements questions.
