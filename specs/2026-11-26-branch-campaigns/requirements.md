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
only costs me one extra merge click after a long piece of work. So
merging sub-issues straight into main goes.

Once a campaign has a pull request, I want it to behave like an
assignment wherever that makes sense. The campaign's pull request is
where the lead and I talk, as an assignment's pull request is where its
agent and I talk. That symmetry should add the new capability while
actually reducing complexity.

## How do I see it working?

This changes the campaign stories in `docs/stories.md`: "The user starts
a campaign on a parent issue", "The user talks to the lead on the parent
issue", "The user pauses a campaign by removing its label" (which goes)
and "The user queues one campaign behind another". It changes the
campaign card's first row in "The user comes back to see what needs
them", which says a campaign has no pull request, and the campaign parts
of "The user renames a dispatch label", "Two labels of one kind on one
issue", "Labelling an issue for a colleague" and "Naming work that is
not there", which says cancel refuses a campaign. It reverses "Talking
to the agent in the wrong place" for campaigns, and leaves "The lead
hears when a sub-issue needs it" and "The lead gives an assignment's
agent feedback" as they are. It changes what `docs/concepts.md` says a
campaign is, its channel, its signals and its rounds' preparation, how a
campaign starts, is held and ends, and which branch an assignment
targets. It changes the campaign skill contract to match. In
`docs/start-a-campaign.md`, the advice on keeping sub-issue pull
requests from updating one another becomes moot, and the advice to label
a queued campaign's sub-issues yourself goes.

### I run a campaign and a colleague merges its work

Goal: a planned body of work reaches main through one reviewed pull
request, without stalling on the way.

1. I assign the parent issue to myself and put a campaign label on it,
   as today.
2. _dreamcatcher_ starts the campaign on a branch of its own, cut from
   main as it stands then, with a draft pull request into main that will
   close the parent when it merges.
3. The lead works as a campaign's lead does today. It starts an
   assignment for each sub-issue, reviews each sub-issue's pull request,
   gives the agent feedback and merges it. Every sub-issue's pull
   request goes into the campaign branch, not into main, and needs no
   review from anyone but the lead.
4. A sub-issue closes when its pull request merges into the campaign
   branch, whether the lead merged it or I did by hand, just as it would
   on main. Within the campaign, that's what done means: no new
   assignment starts for it, the sub-issues it blocks are free to start,
   and the lead sees it finish. GitHub only closes an issue from a pull
   request into main, so this doesn't come for free. _dreamcatcher_ has
   to close each sub-issue itself. I see no alternative: it's a critical
   piece of new machinery, and only _dreamcatcher_ can make it hold
   every time.
5. The whole campaign builds on that snapshot of main to the end, so no
   sub-issue has to deal with conflicts with main along the way.
6. When the lead judges the campaign's work done, it marks the
   campaign's pull request ready for review, as an assignment's agent
   does.
7. A colleague reviews the campaign's pull request and merges it. That
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
3. The lead turns it into new sub-issues. It already asks me before it
   changes the plan. Their assignments merge into the campaign branch.
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
   would wake an assignment's agent. As with an assignment, the lead
   gets two attempts at a red build: if two fixes in a row leave it red,
   it stops and leaves it to me, even though each fix goes through a
   sub-issue and other rounds come in between.
3. The lead adds a sub-issue to fix it, such as one whose assignment
   merges main in and resolves the conflicts, or one that fixes the
   build. The lead doesn't commit the fix itself.
4. The fix merges into the campaign branch like any other sub-issue. The
   pull request stays ready meanwhile, as an assignment's does while its
   agent fixes a red build.

Outcome: conflicts and red builds are found at the end, and fixed the
same way as every other change in the campaign.

Fixing a conflict this way needs the fix's pull request to merge into
the campaign branch with a merge commit. In a repository that allows
only squash merging, the fix would land and the conflict would remain,
because the setting covers every branch, not just main. That's a
documented limit for now: in such a repository I resolve a conflict on
the campaign's pull request by hand, as I would on any feature branch.

### My colleague turns it down

Goal: stop a campaign whose work won't be merged.

1. If I don't want another attempt, I take the campaign label off the
   parent first.
2. I close the campaign's pull request without merging.
3. The campaign ends after its wrap-up round, as an assignment does when
   its pull request closes. The parent stays open.

Outcome: rejecting a campaign's work is the same close button as
rejecting an assignment's. The sub-issues it closed stay closed, though
their work never reached main. I can't see any alternative to that.

If I leave the label on, a new campaign starts at the next update, as a
new assignment would. For a fresh attempt I reopen the sub-issues I want
done again, because the new lead reads a closed sub-issue as done.

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
else unchanged, and nothing is lost.

### Which sub-issues go into a campaign branch

A campaign's sub-issue is a direct sub-issue of a parent that has a
campaign label, or that has had a campaign in my _dreamcatcher_
instance, however that campaign ended. Its assignment goes into the
parent's open campaign pull request, and while the parent has none, it's
held, and its card says why. Every other assignment goes into main, as
now. An assignment's target is fixed when it starts, so anything already
in motion carries on where it was going.

Through a campaign's life, that works out like this:

1. **The parent has a campaign label and is awaiting dispatch.** Held.
   The campaign may be waiting for a slot, or held: blocked by another
   parent, its label applied by someone else, or a routing conflict. The
   request stays held until the campaign starts and opens its pull
   request, and from then on case 3 applies.
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
   If I reopen the parent with a campaign label on it, a new campaign
   starts, and case 3 applies once its pull request is open.
6. **The parent's campaign pull request was closed without merging.**
   Held. The parent stays open. With a campaign label still on it, a new
   campaign starts at the next update, and case 3 applies once its pull
   request is open. Otherwise the request stays held until I put a
   campaign label back on, the issue leaves the parent, or its label
   comes off.

This matters most when I make a mistake. If I close a campaign's pull
request and forget to take the labels off its sub-issues, I don't end up
with a stack of assignment pull requests against main. The sub-issues
sit visibly on the home page as held until I deal with them. Labelling a
campaign's sub-issues by hand before the campaign starts isn't something
I want to support, and if I do it anyway, they're held too.

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
closes, which now happens when my colleague merges the earlier
campaign's pull request. So the queue waits on each review, and the next
campaign's branch is cut from a main that already holds the earlier
work. Campaigns are big pieces of work, and running them one after
another is sensible practice, with the dependency doing the queueing.
_dreamcatcher_ doesn't enforce it.

## What limits this?

- Keep the machinery as simple and elegant as possible. Anything that
  implies additional machinery needs careful inspection and thought, and
  where an existing mechanism already does the job, I'd rather use it.
  That's why I relay my colleague's review, why the lead marks its own
  pull request ready, and why conflicts and red builds on the campaign's
  pull request are fixed through sub-issues.
- The lead never edits code, for the whole life of the campaign. Lead
  agents coordinate work and assignment agents edit code, and that clear
  division of labour helps with prompting and managing complexity.
  Everything reaches the campaign branch through a sub-issue.
- The workplaces I have in mind protect main only. A campaign branch
  that _dreamcatcher_ creates is fine to merge into without review.
- Whether checks run on pull requests into the campaign branch is
  determined by the rules of the repository. There's not much we can do
  about that, and the setup guide only needs to say so.
- An agent only ever hears me. A colleague's comments, on any pull
  request, reach me and no agent.
- In a repository where I've taken main's protections off, only the
  lead's instructions stop it from merging the campaign's own pull
  request into main. Instructions are enough for now.
- If the campaign's pull request merges early, while a sub-issue's pull
  request into the campaign branch is still open, that work goes
  nowhere, or GitHub moves it onto main when it deletes the campaign
  branch. Nothing reaches main without a person, so that's accepted for
  now.
- Campaigns and assignments stay two kinds of work. Unifying them, so
  that an assignment on an issue with sub-issues coordinates them, is
  something to reflect on once this rework is done.
- Out of scope: assignments that target any other branch, conversations
  on a campaign branch, keeping the campaign branch current with main
  while the sub-issues are worked on, and resolving conflicts by
  ourselves in a squash-only repository. Removing a dispatch label once
  its work starts, so that a second attempt always needs me to add it
  again, is a separate idea for later.
- This needs a companion change in the dream plugin's `dream:big` skill,
  alimanfoo/dream#1046, which will have to follow this shape.

## What's still open?

- What an upgrade does to campaigns already running. If this changes the
  state format, saved work doesn't carry across anyway, as for any
  change of format.
- Whether GitHub reports a pull request that lacks a required review as
  blocked rather than behind or conflicting. If it does, the campaign's
  pull request may not wake the lead for main moving until someone
  approves it. That needs checking before design.
