# Campaigns on a branch of their own

Seed: [#894](https://github.com/alimanfoo/dreamcatcher/issues/894).

## What do I want and why?

In several teams and workplaces it's policy that a human reviews
anything before it merges to main. Today a campaign's lead merges each
sub-issue's pull request straight into main, and the lead, every
assignment's agent and I all work under my GitHub account. GitHub won't
let an account approve its own pull request, so a colleague would have
to approve every sub-issue before the lead could merge it. The campaign
stalls at each one, waiting on someone outside it. That defeats the
point of a campaign, which is autonomy over a long horizon.

I want every campaign to run on a branch of its own, with one pull
request into main that carries the campaign's whole body of work. A
person reviews that one pull request at the end and decides whether to
merge it. That's safer in two ways: a campaign works in any repository
and never stalls on a review rule for main, and nothing an unattended
lead merges reaches main until a person has looked at the whole.

One big review at the end is the price, and it's worth paying. It's the
only way to make long-horizon autonomous work possible, and the reviewer
can use AI to help them review.

I don't want two kinds of campaign. Even in an exploratory, greenfield
project, where I've deliberately taken main's protections off, a branch
only costs me one extra merge click after a long piece of work.

Once a campaign has a pull request, I want it to behave like an
assignment wherever that makes sense. The campaign's pull request is
where the lead and I talk, as an assignment's pull request is where its
agent and I talk. That symmetry should add the new capability while
actually reducing complexity.

A campaign has two phases. While its pull request is a draft, the lead
coordinates: it dispatches the sub-issues and merges their work into the
campaign branch, and it doesn't touch code. Once every sub-issue is
done, the lead marks the pull request ready for review and finishes it,
the way an assignment's agent carries its pull request to merge, much as
Claude Code's `/ship` does. The lead's job is to build the thing that
the parent issue and its sub-issues describe. The plan is mine, so the
lead never adds sub-issues.

## How do I see it working?

This changes these stories in `docs/stories.md`:

- the campaign stories: "The user starts a campaign on a parent issue",
  "The user talks to the lead on the parent issue", "The user queues one
  campaign behind another", and "The user pauses a campaign by removing
  its label", which goes;
- the campaign card's first row in "The user comes back to see what
  needs them", which says a campaign has no pull request;
- the campaign parts of "The user renames a dispatch label", "Two labels
  of one kind on one issue", "Labelling an issue for a colleague" and
  "Naming work that is not there", which says cancel refuses a campaign;
- "Talking to the agent in the wrong place", which reverses for
  campaigns;
- "The user closes a pull request they do not want", "Closing a pull
  request and leaving the assignment label on the issue" and "Deleting
  an assignment's worktree", which change because a label left on no
  longer starts new work. In `docs/concepts.md`, a request becomes one
  application of a dispatch label, which the work it starts consumes.

"The lead hears when a sub-issue needs it" and "The lead gives an
assignment's agent feedback" stay as they are. In `docs/concepts.md`,
this changes what a campaign is, its channel, its signals, and how it
starts, is held and ends, and which branch an assignment's pull request
goes into. It changes the campaign skill contract to match. In
`docs/start-a-campaign.md`, the advice on keeping sub-issue pull
requests from updating one another, and the advice to label a queued
campaign's sub-issues yourself, both go.

### I run a campaign and a colleague merges its work

Goal: a planned body of work reaches main through one reviewed pull
request, without stalling on the way.

1. I assign the parent issue to myself and put a campaign label on it,
   as today.
2. _dreamcatcher_ starts the campaign on a branch of its own, cut from
   main as it stands then, with a draft pull request into main that will
   close the parent when it merges.
3. The lead starts an assignment for each sub-issue, choosing among the
   assignment labels that the running daemon offers, which
   _dreamcatcher_ tells it. It reviews each sub-issue's pull request,
   gives the agent feedback and merges it. Every sub-issue's pull
   request goes into the campaign branch, not into main, and needs no
   review from anyone but the lead.
4. A sub-issue closes when its pull request merges into the campaign
   branch, whether the lead merged it or I did, just as it would on
   main, as long as the sub-issue's assignment is still open. Within the
   campaign, that's what done means: no new assignment starts for it,
   the sub-issues it blocks are free to start, and the lead sees it
   finish. GitHub only closes an issue from a pull request into main, so
   _dreamcatcher_ closes each sub-issue itself. That's a critical piece
   of new machinery.
5. The sub-issues all build on that snapshot of main, so none of them
   has to deal with conflicts with main along the way.
6. When the lead judges every sub-issue done, it marks the campaign's
   pull request ready for review.
7. From then on the lead finishes the pull request as an assignment's
   agent would. If main has moved on and conflicts, or the checks fail,
   the lead merges main in, or fixes the cause, and pushes to the
   campaign branch itself.
8. A colleague reviews the campaign's pull request and merges it. That
   closes the parent, and after a wrap-up round the campaign ends.

Outcome: the work is on main, reviewed once, by a person, as the policy
asks. On the home page, the campaign's card shows its pull request and
where it stands, as an assignment's card does.

### I talk to the lead

Goal: steer the campaign, or ask how it stands.

1. I post on the campaign's pull request: a comment, an inline comment
   or a review.
2. At the next update the lead is given what I posted, in the same
   session, and answers on the pull request.

Outcome: I talk to the lead where I'd talk to an assignment's agent.
Comments on the parent issue reach nobody.

### My colleague asks for changes

Goal: the reviewer's changes get made without me making them.

1. My colleague reviews the campaign's pull request and asks for
   changes. Their comments reach me, never an agent, as with any
   colleague's comments.
2. I relay what I want done in a post of my own on the same pull
   request.
3. The lead makes the changes and pushes them, as an assignment's agent
   would. If I think a change deserves a sub-issue of its own, I add the
   sub-issue to the parent myself, and the lead dispatches it.
4. My colleague reviews it again.

Outcome: I keep the safety that only my words reach an agent, and I'm
happy to do the relaying.

### Main moves, or the build goes red, after the lead marks it ready

Goal: the pull request my colleague comes to merges cleanly and passes
its checks.

1. While the campaign's pull request is a draft, nothing wakes the lead
   when main moves or the checks fail.
2. Once the lead has marked it ready, the pull request falling behind
   main, conflicting with it or failing its checks wakes the lead, as it
   would wake an assignment's agent.
3. The lead merges main in and resolves any conflicts, or fixes the
   failing checks, and pushes to the campaign branch. That works however
   the repository lets pull requests merge, because the lead merges main
   by pushing.
4. As with an assignment, the lead gets two attempts at a red build. If
   two fixes in a row leave it red, it stops and leaves it to me.

Outcome: the pull request stays mergeable however long it waits, and no
"bring main in" work piles up as sub-issues.

### My colleague turns it down

Goal: stop a campaign whose work won't be merged.

1. I close the campaign's pull request without merging.
2. The campaign ends after its wrap-up round, as an assignment does when
   its pull request closes. The parent stays open.

Outcome: rejecting a campaign's work is the same close button as
rejecting an assignment's. The sub-issues it closed stay closed, though
their work never reached main. I can't see any alternative to that.

Leaving the campaign label on the parent doesn't start a new campaign by
itself. For a fresh attempt, I reopen the sub-issues I want done again,
then take the parent's label off and put it back. The new lead
dispatches the reopened sub-issues afresh.

### I take the campaign over

Goal: finish the campaign by hand.

1. I cancel the campaign, from its page or the command line, as I'd
   cancel an assignment.
2. The lead stops, and the campaign's pull request and branch are mine.
   While that pull request is open, no new campaign starts on the
   parent.
3. Assignments already under way for sub-issues are separate work, so
   they carry on, and their pull requests still go into the campaign
   branch.
4. I act as the lead. I label the remaining sub-issues as I would any
   assignment, their pull requests go into the campaign branch, and I
   review and merge them there. Each sub-issue still closes as it
   merges. Sub-issues I don't want done, I leave unlabelled.
5. When I'm done, the campaign's pull request goes to my colleague as
   before.

Outcome: taking over means swapping the lead for me, with everything
else unchanged, and nothing is lost. The cancelled campaign moves to the
ended list on the home page, so I follow its sub-issues on the
Assignments tab while I finish.

### Which sub-issues go into a campaign branch

A campaign's sub-issue is a direct sub-issue of a parent that has a
campaign label, or that has had a campaign in my _dreamcatcher_
instance, however that campaign ended. Its assignment's pull request
goes into the parent's open campaign pull request's branch. While the
parent has no open campaign pull request, the request is held, and its
card says why. Every other assignment goes into main, as now. An
assignment's target is fixed when it starts, so anything already in
motion carries on where it was going.

Through a campaign's life, that works out like this:

1. **The parent has a campaign label and is awaiting dispatch.** Held.
   The campaign may be waiting for a slot, or held: blocked by another
   parent, its label applied by someone else, a routing conflict, or a
   label whose request an earlier campaign already consumed. The request
   stays held until the campaign starts and opens its pull request, and
   from then on case 3 applies.
2. **The parent has an open campaign whose pull request isn't open
   yet.** Held. This is the short moment before the campaign's first
   round has opened its pull request, or after a first round that failed
   partway. The request stays held until the pull request is open, and
   from then on case 3 applies.
3. **The parent has an open campaign whose pull request is open.**
   Available. The assignment branches from the campaign branch and its
   pull request goes into it.
4. **The parent's campaign was cancelled, and its pull request is still
   open.** Available. The assignment branches from that campaign branch
   and its pull request goes into it, with me acting as lead.
5. **The parent's campaign pull request was merged.** Held. The
   campaign's work is on main and the parent is closed. The request
   stays held until the issue leaves the parent or its label comes off.
   If I reopen the parent and re-apply a campaign label, a new campaign
   starts, and case 3 applies once its pull request is open.
6. **The parent's campaign pull request was closed without merging.**
   Held. The parent stays open. The request stays held until I re-apply
   a campaign label to the parent and a new campaign opens its pull
   request, the issue leaves the parent, or its label comes off.

This matters most when I make a mistake. If I close a campaign's pull
request and forget to take the labels off its sub-issues, I don't end up
with a stack of assignment pull requests against main. The sub-issues
sit visibly on the home page as held until I deal with them. Labelling a
campaign's sub-issues by hand before the campaign starts isn't something
I want to support, and if I do it anyway, they're held too.

### A label left on starts nothing new

Each time I apply a dispatch label to an issue, that's one request. When
work starts for it, an assignment, a campaign or a conversation, the
work consumes the request. A label that stays on after its request was
consumed asks for nothing more. So if I close a pull request, or close
and reopen an issue, with its label left on, nothing new starts by
itself, and the card says that the label's request has already been used
and that I re-apply it for another attempt. Taking the label off and
putting it back is how I ask for another attempt. If I re-apply a label
while work is still open, for example to resume a paused conversation,
that's a new request, and it starts another attempt once that work ends.
An issue with no earlier work of the kind starts as it does today.

### Like an assignment

Once a campaign exists, its label no longer decides anything, as an
assignment's doesn't. Taking the label off doesn't pause the campaign,
and there's no pausing. I stop a round, or cancel. A parent has one
campaign at a time: an open campaign answers every campaign label on its
parent, and while a campaign's pull request is open it holds the parent,
so no second campaign starts. Closing the parent by hand while the
campaign's pull request is open changes nothing; the pull request
decides. The lead has a wrap-up round when its pull request is merged or
closed, as an assignment's agent does. The lead still hears when a
sub-issue changes, because that's what a campaign is for.

### Queues

A later parent blocked by an earlier one waits until the earlier parent
closes, which happens when my colleague merges the earlier campaign's
pull request. So the queue waits on each review, and the next campaign's
branch is cut from a main that already holds the earlier work. Campaigns
are big pieces of work, and running them one after another is sensible
practice, with the dependency doing the queueing. _dreamcatcher_ doesn't
enforce it.

### When things go wrong

- **A sub-issue's assignment is in fault when its pull request merges.**
  The sub-issue stays open, and the sub-issues it blocks stay blocked,
  until I retry the assignment and its wrap-up round closes it. Nothing
  else starts for it meanwhile.
- **I merge a cancelled sub-issue's pull request by hand.** If I cancel
  a sub-issue's assignment and merge its pull request into the campaign
  branch myself, nothing closes the sub-issue. That's mine to close, as
  part of taking the work over.
- **The campaign's pull request merges early**, while a sub-issue's pull
  request into the campaign branch is still open. That work goes
  nowhere, or GitHub moves it onto main when it deletes the campaign
  branch. Nothing reaches main without a person, so that's accepted for
  now.

## What limits this?

- Keep the machinery as simple and elegant as possible. Anything that
  implies additional machinery needs careful inspection and thought, and
  where an existing mechanism already does the job, I'd rather use it.
- The lead doesn't edit code until it marks the campaign's pull request
  ready, and never adds sub-issues. Lead agents coordinate work and
  assignment agents edit code, and that clear division of labour helps
  with prompting and managing complexity.
- Only instructions stop the lead from editing code while it
  coordinates, and from merging the campaign's own pull request in a
  repository where I've taken main's protections off. Instructions are
  enough for now.
- The workplaces I have in mind protect main only. A campaign branch
  that _dreamcatcher_ creates is fine to merge into without review, and
  the setup guide says the campaign branch must not require review.
- Whether checks run on pull requests into the campaign branch is
  determined by the rules of the repository. The setup guide only needs
  to say so.
- In a repository that requires review, GitHub is reported to show a
  pull request that awaits review and is merely behind main as blocked,
  though its documentation doesn't say so. So the lead hears of main
  moving through a conflict, or, where branches must be up to date, once
  the pull request is approved.
- An agent only ever hears me. A colleague's comments, on any pull
  request, reach me and no agent.
- Campaigns and assignments stay two kinds of work. Unifying them, so
  that an assignment on an issue with sub-issues coordinates them, is
  something to reflect on once this rework is done.
- Out of scope: assignments that target any other branch, conversations
  on a campaign branch, nested campaigns, and keeping the campaign
  branch current with main while the sub-issues are worked on.
- This needs a companion change in the dream plugin's `dream:big` skill,
  alimanfoo/dream#1046, which will have to follow this shape.

## What's still open?

- What an upgrade does to campaigns already running. This changes the
  state format, so saved work doesn't carry across, as for any change of
  format, and it changes the campaign skill contract, so the dream
  plugin has to follow.
