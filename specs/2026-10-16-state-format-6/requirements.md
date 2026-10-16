# State format 6

## What do I want to be able to do?

I want one phase of work that moves the state format from v5 to v6 and pays for
that bump with two things.

The small win is new behaviour. When an assignment's pull request is ready for
review and GitHub says it can't be merged as it stands, because it's behind main
or conflicts with it, I want dreamcatcher to wake the agent to bring the branch
up to date. When CI fails on that pull request, I want dreamcatcher to wake the
agent to fix it. I do both of those by hand today.

The big win is a simpler architecture with a sensible domain model. An issue, an
assignment and a conversation should be modelled as distinct entities, with the
links between them stated explicitly rather than implied. After this phase the
codebase should have fewer cracks where faults can arise, and it should be
easier for agents to maintain because the code surface is consistent and aligned
with that model.

## What's wrong or missing today?

The faults aren't biting me as a user. They're biting me as a maintainer. Coding
agents surface potential faults early, which is good, but the reports are hard
to understand when they arrive, and they need architectural fixes rather than
patches. Both of those are smells of knots in the architecture.

Issue #425 is the clearest case. Several separate fault reports turned out to
come from one design choice: an assignment's record is written last, so an
interrupted setup leaves artifacts no record names, and a second path exists to
recover them. #455 is a different kind of knot. It started as a naming
inconsistency, and I couldn't find better names because the underlying model was
wrong: an issue observation carries assignment facts, and a conversation is
observed before it exists.

Issue #393 is a behaviour tangle from the same cause. An issue can be labelled
with conversation label A, a conversation starts, A is removed which stops it,
then label B is added and A's conversation resumes with A's settings. Nothing
ties a running conversation to the label that started it.

Issue #483 is the same kind of gap in a smaller place. The status report and
home page read dreamcatcher.toml as it is now, while the daemon runs the
configuration it loaded at launch, so the two can disagree and a broken file
takes the views down.

## What has to be true of anything I'd accept?

Simplicity and elegance, always. Reduce branching, separate concepts, and reduce
the number of concepts overall. No special cases and no new conditionals. If a
change needs a second path or a new case beside an existing rule, it's the wrong
change.

An issue, an assignment and a conversation are distinct entities. An issue is
observed once per tick, the same way for both kinds of work, and the observation
holds issue facts only. Only work that exists is observed as work.

A dispatch label on an issue links to at most one live piece of agent work, and
at most one piece of work of each kind is live on an issue. An issue may carry
an assignment label and a conversation label together. Two labels of one kind is
a routing conflict, and nothing of that kind starts while it lasts. Each
conversation label maps to one conversation. Removing the label pauses that
conversation, and putting the label back resumes it where it left off. A
conversation started under a second label is a fresh conversation on the issue.
It receives the issue's comments exactly as any new conversation does today,
with nothing carried over from, and nothing withheld because of, the earlier
conversation. A conversation gets a generated identifier, as assignments already
have, and the commands, web routes and state directories that name a
conversation by its issue change to match. I barely use the terminal views now
and mostly use the web UI, so keep the naming simple rather than typeable.

Assignments and conversations don't need to behave alike, because an assignment
belongs to its pull request once launched and a conversation belongs to its
issue. They do need to be modelled in the same shape.

An assignment exists from the moment the scheduler picks the issue. Its first
round brings the branch, worktree and pull request into being, before the
harness starts, so the promise in the agent contract still holds. Setup is not a
concept apart from a round.

There is one rule for a piece of agent work failing, whatever stage it failed
at. A failure is recorded against the work, not as a scheduler failure and not
as a round. Two in a row put the work in fault, and a retry clears it, as now.
Recovery means trying the next step again: where a harness session exists it's
resumed, and where none exists yet the first-round steps run again, which they
can because each does nothing when its work is already done. The scheduler's
failure list keeps only failures that belong to no piece of work, such as a
failed issue listing. #496 should become a non-issue as a result.

The fault and error handling model as a whole is in scope. It has never had a
hard look, it's what's generating most of the complexity now, and I want any of
it combed out that can be. #425 is the way in.

A view reads only what the daemon recorded under .dreamcatcher/. It never opens
the configuration file, so a view can't disagree with the daemon that's running.
Issue #483 is the case that proves it.

Blocking issue numbers are recorded as data, not recovered from text (#457).

Once an assignment exists, dreamcatcher can ignore its issue. The facts about an
issue that decide whether work may start, such as what else claims it and what
blocks it, are read only while no work exists for it. Today they are read every
tick for every issue with an open assignment, and the answers decide nothing.

For the new rounds (#550 and #551): a ready pull request that GitHub reports as
behind main or conflicting wakes the agent once per head commit, with one prompt
line, and the agent merges main in. Drafts are left alone. A failed CI check
wakes the agent the same way, once per head commit. Every check counts, not only
the required ones. An agent that keeps pushing red fixes has to stop somewhere,
and that's the one failure rule's job: an automatic CI round whose push comes
back red again counts as the work failing, so two in a row put the assignment in
fault and it waits for my retry. There is no separate cap or counter. While
checks are still running the status says nothing special. A pull request that
goes stale without a push, in a repository that doesn't require branches to be
up to date, is documented rather than handled.

## What limits this?

A format bump throws away everyone's local state, so I want to pay it once for
all of these. Everything that changes a persisted record goes in this phase, and
nothing that does goes in on its own.

The append-only journal (#492) waits for a future phase, probably v7. There's
too much moving in this one already.

I accept the harness spend. In a repository that requires branches to be up to
date, every move on main wakes the agent on every ready pull request. That's
work I do by hand today.

Observing every issue the same way means an issue that only conversation routes
list also gets its blockers and linked pull requests read. That's two or three
more GitHub reads per such issue per tick, and I'd pay that to keep one shape.
But reading those facts for an issue that already has an assignment is a cost
with no decision behind it, and the design should not keep paying it.

## How will I know it worked?

I stop merging main and chasing CI by hand on assignment pull requests.

Agents file fewer issues overall, and in particular fewer that speculate about
or raise the possibility of a failure or error. The issues they do file are
easier for me to understand, because the architecture underneath is simpler.

Some of the issues that are open today either become easier to resolve or stop
being issues at all once this lands.

## What's still open?

Two of the issues need amending to match this brief. #550's design reads only
GitHub's conflict field, and waking on "behind main" needs the merge state field
as well. #425 keeps a failed launch as a scheduler failure, where this brief
records it against the work.

The web UI shows ended assignments but not ended conversations. That's a
presentational asymmetry worth fixing once the model is straight, probably as a
separate issue.

The issues in the batch are #550, #551, #483, #455, #425, #393 and #457. Whoever
reads any of them should read all the comments, because on several the thread
settled something the title and body don't say. Whether #455 and #393 should
close in favour of one design for the batch, as the thread on #455 suggests, is
not decided.
