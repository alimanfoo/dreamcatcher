# Roadmap: campaigns on a branch of their own

Every session that implements a stage should correct the specifications
as details change and say on its pull request what it corrected. It may
change how it delivers the stage when earlier work or implementation
discoveries justify that change. It should raise any change to the
roadmap's stages, boundaries, order or dependencies with the user
instead of restructuring the roadmap itself.

## 1. Consumed requests

**Delivers.** For assignments and campaigns, each application of the
dispatch label is one request, and the work it starts consumes it. New
work of either kind starts only on a label applied after every
application already consumed by work of that kind at the issue. A
request already consumed is held, and its card says the label's request
has been used and to re-apply the label for another attempt. A
conversation's label is unchanged: a switch that starts, pauses and
resumes it.

The change touches `github.py`, where the labelling events query asks
for each event's `createdAt`; `scheduler/labelling.py`, which returns
when the label was applied beside who applied it; `scheduler/tick.py`,
whose label checks compare that time with the latest GitHub application
time recorded by work of the kind at the issue, ended or not, and so are
given all the work, and whose `_launch` hands the time to the new work;
`scheduler/inspection.py`, where a candidate for new work carries the
time; `agent_work.py`, where the work record holds it, empty for a
conversation; a new hold finding and its words; and
`STATE_FORMAT_VERSION`, which rises to 9. Today's campaign input prompt
gains a line telling the lead to dispatch a sub-issue by removing its
assignment label if it is there and then adding it, because a lead that
only adds a label already present makes no new request. The concepts
page redefines an assignment or campaign request as one application of
its label; the stories that a label left on changes are corrected; the
`dreamcatcher about` text lists the new hold; the changelog and the
compatibility page record format 9.

**Proof.** Tests cover each case in the requirements' "What a label
means": an assignment's pull request closed with the label on is held,
and re-applying the label starts a new assignment; a parent reopened
after its campaign ended, label still on, is held; a conversation's
issue reopened with its label on still starts a new conversation on the
next comment; an issue with no earlier work starts as today. The suite
and every check pass.

**Defers.** Everything about branches.

**Needs.** Nothing.

## 2. Pull request work

**Delivers.** `agent_assignments.py`, with
`agent_assignment_pull_requests.py` folded in, becomes
`pull_request_work.py`, and its exported functions drop "assignment"
from their names, for example `cancel_pull_request_work` and
`open_work_pull_request`. Behaviour does not change.
`AssignmentRoundInput` keeps its name, since only assignments use it
yet. The concepts page gains **pull request work**, work whose channel
is its pull request, beside issue work.

The change touches the module, the source modules that import from it,
the tests that import from it, the import-linter layers in
`pyproject.toml`, and `docs/architecture.md`.

**Proof.** The suite and every check pass, with tests changed only in
imports and names.

**Defers.** Any generalising of the readers or the input, and the base
branch.

**Needs.** Nothing.

## 3. Assignments target a base branch

**Delivers.** An assignment can target any base branch, though nothing
sets one other than the default branch yet. The work record holds the
base branch; the opening round cuts the assignment's branch from the
base, makes the placeholder commit when nothing is past the base, and
opens the pull request into it; and the wrap-up round of work whose pull
request merged into a base other than the default branch closes its
issue as completed, with a comment naming the pull request and carrying
the agent marker, before it builds the input.

The change touches `agent_work.py`, where `create_agent_work` takes the
base; the candidate, which carries it, and `_launch`, which passes it
on; `git.py`, which cuts a branch from a given base and counts commits
past it; `pull_request_work.py`, which opens into the base and holds the
closing rule; `github.py`, which closes an issue with a comment; and
`scheduler/assignments.py`, whose wrap-up plan's preparation closes the
issue before it freezes the input. The concepts page gains the base
branch and corrects "Completing an assignment", which says that GitHub
closes the issue when the pull request merges, and the architecture
follows.

**Proof.** Tests take an assignment with a base other than the default
branch through its opening round and its wrap-up: its branch is cut from
the base, its pull request goes into the base, and its issue is closed
when the pull request merged. An assignment with the default branch as
base behaves as today. The suite and every check pass.

**Defers.** The parent check, which is what will set a base other than
the default branch.

**Needs.** Stage 2, because opening from a base and the closing rule
live in `pull_request_work.py`.

## 4. The parent check

**Delivers.** Before an assignment request starts, and after the claim
and blocker questions find nothing, the tick reads the issue's parent
and decides the request's base, as the design's tick algorithm
describes. A campaign's sub-issue goes into its parent's open campaign
pull request's branch, and is held, naming the parent, while the parent
has none. Every other assignment goes into the default branch.

The change touches `github.py`, which reads an issue's parent with three
outcomes, a parent, no parent, or unknown, and never takes a failed read
for no parent; `scheduler/tick.py`, which gives request inspection all
the work on disk, ended work included; `scheduler/assignments.py`, which
runs the check and sets the base through stage 3; and the new hold
finding and its words. A parent in another repository counts as no
parent. The concepts page gains a campaign's sub-issue, and the stories
gain "Which sub-issues go into a campaign branch".

**Proof.** Tests built on fabricated campaign records cover each of the
six cases in the requirements' "Which sub-issues go into a campaign
branch", a parent in another repository, and a parent read that fails,
which starts nothing. The suite and every check pass.

**Defers.** Campaigns that have pull requests. Until stage 5, no
campaign has one, so every sub-issue of a campaign is held; nothing is
released between the stages, so this window is accepted.

**Needs.** Stage 3, because the check sets the base through it.

## 5. Campaigns on a branch

**Delivers.** Campaigns leave issue work and become pull request work. A
new campaign's opening round cuts its branch from the default branch and
opens a draft pull request into it that closes the parent, then builds
the input. Its pull request drives it from then on: the user's posts,
sub-issue notifications and recovery after an unfinished round wake the
lead; a merged or closed pull request brings the wrap-up round, which
records the campaign as completed. The parent's comments, labels,
assignee and state no longer decide anything for an open campaign. A
parent has one campaign at a time. An ended campaign's worktree and
local branch are removed, and a cancelled one's kept.

The [reading guide](reading-guide.md) follows the implementation from
the two scheduler passes through the shared pull request machinery,
campaign round input, cleanup and status.

**Proof.** A test walks the design's motivating use case with stand-ins
for `gh` and the harness, from the label on the parent through the
opening, the first sub-issue going into the campaign branch, its merge
closing it, the lead hearing of it, the campaign's pull request merging,
the wrap-up and the cleanup. Further tests show that a post on the
campaign's pull request wakes the lead, that a comment on the parent, a
removed label and a closed parent change nothing, that a second campaign
label starts no second campaign, and that a campaign pull request closed
with the label on starts no new campaign. The suite and every check
pass.

**Defers.** The lead's prompt, which still describes the old input, to
stage 6; the signal wording, which a ready campaign gets as an
assignment's, to stage 7; cancel to stage 8; the user guides to stage 9.

**Needs.** Stage 1, so that a campaign pull request closed with the
label on starts no new campaign; stage 2, for the machinery campaigns
join; stage 4, for sub-issues to go into the campaign branch, and
through it stage 3's closing rule, which the walk-through relies on.

**Implementation.** The parent check shares its base decision within the
assignment pass. Both passes share the pull request observation for the
tick.

## 6. The coordinating lead

**Delivers.** The lead's instructions match its new channel. The
coordinating input prompt follows the design's lead interface contract.
Every lead round on Claude gets the assignment's allowed list, including
`gh pr ready`, together with the coordination tools, such as
`gh pr merge`, `gh pr review`, `gh issue edit` and `gh api`. A
coordinating campaign's card shows its pull request, idle and waiting
words, and sub-issue count. The campaign skill contract reaches version
2: a campaign skill must tell the lead to mark the campaign's pull
request ready for review when it judges every sub-issue done, and must
not tell it to add sub-issues or to merge the campaign's own pull
request. The contract confines the ban on editing project source,
committing and pushing to the coordinating phase, which the concepts
page defines.

The change touches `prompts.py` and its golden, `claude.py`, where the
campaign's own allowed and disallowed lists go, the status words and the
web and terminal views with their rendered-view goldens,
`docs/contract.md`, the concepts and compatibility pages, the changelog,
and the stories about starting, talking to and checking on the campaign.

**Proof.** The prompt golden shows the coordinating prompt, Claude's
arguments for a lead show the single permission set, and the
rendered-view goldens show a coordinating campaign's card with its draft
pull request. The suite and every check pass.

**Defers.** The finishing phase.

**Needs.** Stage 5, for the input and channel that the prompt describes.

**Implementation.** An idle coordinating lead shows "awaiting feedback
or sub-issue changes". Waiting for posts shows how many new posts are
for the lead, beside any sub-issue changes. The terminal status view
uses the same closed sub-issue count as the web.

## 7. The finishing phase

**Delivers.** Once the campaign's pull request is ready for review, the
lead carries it to merge as an assignment's agent does. The out-of-date
and check-failure signals wake it with the signal lines that assignments
use; it merges the default branch in or fixes the checks and pushes; it
makes the changes the user relays. After two consecutive attempts at a
red build, another check failure leaves the lead waiting for a different
trigger. Marking the pull request a draft again returns the lead to
coordinating.

The change touches the campaign's round preparation, which chooses the
coordinating or the finishing input prompt from the draft flag the tick
read; `prompts.py`, which gains the finishing input prompt; the status
words of a finishing campaign, which are the assignment's; the contract,
which adds carrying the pull request to merge within version 2; the
concepts page, which names the finishing phase; and the stories "Main
moves, or the build goes red, after the lead marks it ready" and "My
colleague asks for changes".

**Proof.** Tests take a ready campaign pull request through a conflict,
red builds until the third is withheld under the relay rule, and a
relayed post, and each round gets the finishing prompt; a draft pull
request's round still gets the coordinating prompt. The suite and every
check pass.

**Defers.** Cancel and the user guides.

**Needs.** Stage 5, for the signals that the shared inspection raises
for a campaign; stage 6, for the coordinating prompt that the finishing
prompt alternates with, and the contract at version 2.

## 8. Cancelling a campaign

**Delivers.** The user can cancel an open campaign from its page or with
`dreamcatcher cancel`. The lead's running round stops, the campaign ends
cancelled, and its pull request, branch and worktree are kept. While its
pull request is open it holds the parent, and a sub-issue labelled
afterwards goes into the campaign branch.

The change touches `cli.py` and `web/app.py`, which accept any pull
request work where they accept assignments alone today; the endpoint and
handler names; the cancel control's label and confirmation text in
`templates/partials/agent-work-control.html`, which follow the kind; the
rendered-view goldens; the concepts page's section on cancelling; the
stories "I take the campaign over" and "Naming work that is not there";
and `docs/command-reference.md` for `cancel`.

**Proof.** Tests cancel a campaign from the command line and from the
web page, with a round running and between rounds: its ending is
cancelled, its worktree and branch are kept, its parent is held while
its pull request is open, and a sub-issue labelled afterwards starts
into the campaign branch. Cancelling a conversation is still refused.
The suite and every check pass.

**Defers.** The user guides.

**Needs.** Stage 4, for a sub-issue of a cancelled campaign to go into
its branch; stage 5, for cancelling as pull request work and the claim
that holds the parent.

## 9. User guides

**Delivers.** Every user guide describes campaigns and labels as they
now work: `src/dreamcatcher/about.md`, `docs/start-a-campaign.md`,
`docs/campaign-tutorial.md`, `docs/run-and-monitor.md`,
`docs/stop-and-recover.md`, `docs/index.md`, `docs/customise-skills.md`,
`docs/configure.md`, `docs/configuration-reference.md`,
`docs/review-an-assignment.md`, which also links to a section of
`docs/start-a-campaign.md` that goes, and the `view` section of
`docs/command-reference.md`. `docs/start-a-campaign.md` says that the
campaign branch must not require review and that the repository decides
whether checks run on pull requests into it, and drops the advice to
label a queued campaign's sub-issues by hand and the advice on keeping
sub-issue pull requests from updating one another. The two tutorials,
`docs/tutorial.md` and `docs/campaign-tutorial.md`, are retitled "Run
your first assignment" and "Run your first campaign", keeping their file
names. The compatibility page's upgrade notes say what to do before
upgrading to format 9 and contract version 2, and name the dream plugin
version that leads need. This last pull request of the phase adds
`2026-11-26-branch-campaigns` to the completed phases in
`specs/AGENTS.md`.

**Proof.** The strict documentation build passes. No guide describes a
campaign's parent comments as its channel, pausing a campaign, or a
label left on starting a new assignment or campaign, and each guide's
walk-through matches a story in `docs/stories.md`.

**Defers.** Nothing.

**Needs.** Stage 7 and stage 8, so that the guides describe the finished
feature; and the release of the dream plugin's `dream:big` rewrite,
alimanfoo/dream#1046, whose version the upgrade notes name.
