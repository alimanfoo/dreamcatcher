# Design: campaigns on a branch of their own

This design answers [requirements.md](requirements.md) and builds on the
code that [reading-guide.md](reading-guide.md) describes.

## The solution

Every campaign runs on a branch of its own, the **campaign branch**. The
campaign branch is cut from the default branch when the campaign starts.
The **campaign's pull request** goes from the campaign branch into the
default branch, and closes the parent issue when it merges. This pull
request is the lead's channel, as an assignment's pull request is its
agent's channel. A campaign behaves as an assignment does wherever that
makes sense, and shares the assignment's machinery rather than copying
it.

A campaign has two phases, which the pull request's draft flag decides:

- In the **coordinating phase**, while the pull request is a draft, the
  lead dispatches the parent's sub-issues, then reviews and merges their
  pull requests into the campaign branch. It never edits code.
- When the lead judges every sub-issue done, it marks the pull request
  ready for review, and the campaign enters its **finishing phase**.
  From then on its rounds run as an assignment's do. The lead merges the
  default branch in, fixes failing checks and makes the changes the user
  relays, and commits and pushes to the campaign branch itself.

A person reviews and merges the campaign's pull request. The lead never
adds sub-issues, because the parent and its sub-issues are the user's
plan.

A **campaign's sub-issue** is a direct sub-issue of a parent that has a
campaign label, or that has had a campaign in this _dreamcatcher_
instance, however that campaign ended. Its assignment's pull request
goes into the campaign branch while the parent's campaign pull request
is open. While the parent has no open campaign pull request, the request
is held. A mistake therefore never sends a stack of pull requests to the
default branch. GitHub closes an issue only from a pull request into the
default branch, so when a campaign's sub-issue's pull request merges,
the assignment's wrap-up round closes the sub-issue. A cancelled
assignment has no wrap-up round, so the user closes its sub-issue.

For assignments and campaigns, each application of the dispatch label to
an issue is one **request**, and the work it starts **consumes** it. A
label that stays on after its request was consumed asks for nothing
more, so closing a pull request with the label left on never starts a
repeat by itself; re-applying the label makes a new request. Concretely,
new work of either kind starts only on a label applied after every
application already consumed by work of that kind at the issue. GitHub
supplies every application time, so a correction to the local clock does
not affect which application is latest. When a label is re-applied and
GitHub still returns the consumed application, the request stays held
until a later application appears. An issue with no earlier work of the
kind is not affected. A conversation's label stays what it is today, a
switch: on, the agent answers the user's comments; off, the conversation
is paused.

## Design models

These models are a starting point. Planning and implementation may
revise them.

### Campaign state machine

There are two machines, one inside the other. The campaign's own states
are what _dreamcatcher_ records. Its pull request's states are what
GitHub holds, and they decide what wakes the lead and what it may do.

```text
The campaign, as dreamcatcher records it

  REQUESTED ──(free slot, nothing holds the request)──► OPEN ──► ENDED
  (a campaign label on the parent,                      │      completed: the wrap-up round succeeded
   and no campaign answers it)                          │      cancelled: the user cancelled
                                                        │
The campaign's pull request, while the campaign is open ▼

  NOT YET OPENED ──(the opening preparation records it)──► DRAFT ◄──────► READY FOR REVIEW
                                                           coordinating   finishing
                                                           phase          phase
                                                             │                │
                                                             └─ merged or closed ─┐
                                                                                  ▼
                                                               MERGED OR CLOSED, AWAITING WRAP-UP
```

- **Requested.** The request is held, as an assignment request is, in
  any of these cases: an open pull request claims the parent, an open
  issue blocks it, someone other than the user applied the label, the
  parent carries two campaign labels, or the label's request was already
  consumed. Otherwise it is available.
- **Open, pull request not yet opened.** The opening round is due. Its
  preparation opens the campaign branch and pull request if none is
  recorded, then builds the input as it does for any lead round.
- **Draft: the coordinating phase.** A round is due for the user's posts
  on the campaign's pull request, for sub-issue notifications, and after
  a round that did not finish. Signals do not fire for a draft.
- **Ready for review: the finishing phase.** A round is due for all of
  those, and also for the out-of-date and check-failure signals, under
  the assignment's relay rule. If the lead or the user marks the pull
  request as a draft again, the campaign returns to coordinating.
- **Merged or closed, awaiting wrap-up.** The lead's wrap-up round is
  due. Its finishing step records the campaign as completed.
- **Cancel** moves an open campaign to ended, cancelled, from any pull
  request state, as it does an assignment.
- **Fault** spans every open state, as for an assignment. After two
  errored rounds in a row, no round starts, the wrap-up included, until
  the user retries.

Once a campaign exists, the parent issue's state, labels and assignee no
longer decide anything. Closing the parent by hand changes nothing;
merging the campaign's pull request closes it.

### Data model

- **Work record**, `work.json` (`AgentWorkRecord`). _Changed._ It gains
  the time at which GitHub records the label that started the work as
  applied, which is the request an assignment or campaign consumed; a
  conversation holds none. It also gains the **base branch**: the branch
  the work's pull request goes into. An empty base means the default
  branch. The assignment of a campaign's sub-issue holds the campaign
  branch's name, and every other piece of work holds none. The tick
  decides the base while it inspects the request, before the record is
  written.
- **Pull request record**, `pull-request.json`. _Unchanged._ The opening
  round writes the pull request's number once. Campaigns now write one
  too.
- **Branch name.** _Unchanged rule._ `dreamcatcher-` and the work's
  identifier, as in `dreamcatcher-GH200-20261126-101500-campaign`. It is
  derived, never stored.
- **Round input**, `input.json`. _Changed._ A shared part holds the four
  fields of today's `AssignmentRoundInput`, `pull_request_state`,
  `pull_request_head`, `signals` and `user_posts`, and gains
  `pull_request`, the pull request's number. The round's prompt is
  composed before its preparation runs, so the opening round's prompt
  cannot name a pull request that the preparation opens; the input,
  which the preparation writes, can. A campaign's input adds a campaign
  part: `children`, `notifications` and `assignment_routes`. It drops
  today's `issue`, `comments`, `cursor` and `revision`. The relay's
  readers read the shared part from either kind's input. The opening
  preparation takes `pull_request_head` from the commit it pushed, since
  no tick has yet read the pull request.
- **Ending**, `ended.json`. _Changed._ A campaign ends completed or
  cancelled. "Issue closed" remains for conversations alone.
- **Request row finding**, in `scheduler/models.py`. _Changed._ An open
  campaign's finding becomes the pull request finding with the count of
  changed sub-issues, in place of today's `CampaignFinding`. There are
  two new hold findings: a campaign's sub-issue waiting for its parent's
  campaign pull request, naming the parent; and a request already
  consumed.
- **State format.** _Changed._ `STATE_FORMAT_VERSION` rises from 8 to 9.

### Tick algorithm

The order of `Scheduler.tick` is unchanged. These are the steps that
concern campaigns and sub-issues.

1. **Set up.** _Unchanged._ Forget ended rounds, read every piece of
   work, and list the open issues assigned to the account.
2. **First pass: open assignments and conversations.** _Unchanged._
3. **First pass: requests.** The label checks in
   `_inspect_requests_of_kind`, which every request passes through in
   both passes, gain the consumed-request rule for assignment and
   campaign requests. Conversation requests are unchanged. They already
   read the labelling events, to find who applied the label, and the
   same events give the time it was applied. The tick compares that time
   with the latest GitHub application time recorded by work of the kind
   at the issue, ended or not. Open work answers its own label before
   this check. Then, for each assignment request that nothing holds:
   1. Ask the start-time questions, about claims and blockers.
      _Unchanged._ If either holds the request, nothing more is read.
   2. Run the **parent check**. Read the issue's parent. The read has
      three outcomes: a parent, no parent, or unknown. Unknown leaves
      the request unknown and starts nothing. It is never taken as no
      parent.
      - No parent, a parent in another repository, or a parent with no
        campaign label and no campaign on record: available, with the
        default branch as base. A parent in another repository can never
        be one of this instance's campaigns, and comparing its number
        with local records would confuse it with a local issue.
      - The parent's newest campaign has an open pull request:
        available, with that campaign's branch as base. The pull
        request's state is read once, and only when that campaign is
        open or cancelled.
      - Otherwise: held, naming the parent.
4. **Observations.** _Unchanged._ Collect what the first pass found of
   each assignment, for the campaigns.
5. **Second pass: open campaigns**, through the assignment's pull
   request inspection.
   - In fault: no round starts, and the fault counts.
   - No pull request recorded: observe the sub-issues, and the opening
     round is due, unless they cannot all be observed.
   - Otherwise: read the pull request, the user's posts past the cursor
     and the signals. Observe the sub-issues, and compare them with the
     newest delivered input. A round is due for posts, a signal, a
     merged or closed pull request, a notification, or after an
     unfinished round. If the sub-issues cannot all be observed, no
     round starts, as today.
   - The draft flag that this read found decides the round's phase, and
     so its input prompt. Its permissions do not depend on the phase.
6. **Second pass: campaign requests.** An open campaign answers every
   campaign label on its parent. The start-time questions now include
   claims, so an open campaign pull request holds the parent. If nothing
   holds the request, observe the sub-issues, and the opening round of a
   new campaign is due, unless they cannot all be observed.
7. **Finish.** The cooldown and launching are unchanged. Cleanup removes
   an ended campaign's worktree and local branch, as it does an
   assignment's, and keeps a cancelled campaign's.

The round preparations, which run inside the rounds, change in three
ways:

- A lead round's preparation opens the pull request if none is recorded,
  then builds the input. It never resets the worktree: like an
  assignment's, the lead's worktree stays on the campaign branch from
  the opening round on, with whatever the lead left in it.
- The wrap-up round of work whose base is not the default branch, and
  whose pull request merged, first closes the issue as completed. This
  is a rule about the base, not the kind: a campaign's base is always
  the default branch, so only a campaign's sub-issues meet it. Its
  comment names the pull request and carries the agent marker. Then it
  builds the input. Closing an issue that is already closed changes
  nothing.
- Every Git operation that assumes the default branch today takes the
  base from the work record instead: where a branch is cut, where the
  placeholder check counts commits from, and what a pull request goes
  into.

### Lead interface contract

`compose_round_prompt` builds every lead round's prompt from these
parts, in this order:

1. the instructions, such as `/dream:big GH200`, for a round that starts
   a new harness session;
2. the previous-round line, after a stopped, errored or interrupted
   round;
3. the signal lines, in the finishing phase;
4. the phase's input prompt;
5. the campaign posting instructions, unchanged.

| Round            | `pull_request_state` | `signals`                           | `user_posts` | `notifications` | Phase        |
| ---------------- | -------------------- | ----------------------------------- | ------------ | --------------- | ------------ |
| Opening          | open                 | none                                | none         | none            | coordinating |
| Posts or changes | open                 | none                                | new posts    | new changes     | either       |
| Signal           | open                 | out-of-date, check-failure, or both | any          | any             | finishing    |
| Wrap-up          | merged or closed     | none                                | any          | any             | either       |

Every input also holds `pull_request`, the campaign's pull request's
number, `pull_request_head`, `children` and `assignment_routes`.

The **coordinating input prompt** says:

- read `pull_request_state` first, and wrap up if it is merged or
  closed;
- act on `user_posts`, the user's posts on the campaign's pull request,
  and on `notifications`;
- dispatch the parent's sub-issues, and add none. To dispatch a
  sub-issue, assign it to the user, remove its assignment label if it is
  there, then add the label, so that GitHub records the label as applied
  now, which is a new request that the assignment can consume. This
  matters when a sub-issue was reopened for a fresh attempt with its old
  label still on;
- the worktree is on the campaign branch, and is not reset between
  rounds;
- do not commit, push or open a pull request;
- run each `gh pr merge` as a command of its own;
- do not merge the campaign's own pull request;
- do not close the parent, because merging the pull request closes it.

The **finishing input prompt** adapts the assignment's:

- read `pull_request_state` first, and wrap up if it is merged or
  closed;
- act on `user_posts` and on any `notifications`;
- switch the worktree to the campaign branch and pull it before changing
  anything, because sub-issues may have merged since it was last
  current;
- make changes on the campaign branch, and commit and push them;
- do not merge the campaign's own pull request.

The signal lines are the assignment's, shared by both kinds: "merge the
base branch in and push", and "read the failing checks, fix the cause
and push".

Capabilities are the same in both phases; only the prompt follows the
phase. On Claude, every lead round gets the assignment's allowed list
together with the lead's coordination tools, such as `gh pr merge`,
`gh pr review`, `gh issue edit` and `gh api`, and no disallowed list.
Codex already gives a lead an assignment's settings. So in the
coordinating phase, "do not edit code" rests on the prompt on both
harnesses, as "do not merge the campaign's own pull request" does in
both phases.

The campaign skill contract, in `docs/contract.md`, narrows today's
prohibition on editing, committing and pushing to the coordinating
phase, and gains two requirements and two prohibitions. The change
raises the contract version from 1 to 2. A campaign skill must:

- tell the lead to mark the campaign's pull request ready for review
  when it judges every sub-issue done;
- tell the lead, once the pull request is ready, to carry it to merge as
  an assignment's agent does.

A campaign skill must not tell the lead to add sub-issues, or to merge
the campaign's own pull request.

### Component model

There is one structural move. `agent_assignments.py`, with
`agent_assignment_pull_requests.py` folded in, becomes
`pull_request_work.py`, because its machinery serves both kinds of
**pull request work**: work whose channel is its pull request, an
assignment or a campaign, beside issue work, which is now conversations
alone. Its exported functions drop "assignment" from their names. It
holds:

- opening the pull request from a base;
- the shared input part, and the relay-memory readers;
- completing and cancelling;
- removing the worktree and local branch;
- closing the issue of work whose pull request merged into a base other
  than the default branch.

Nothing is left that only assignments do, so `agent_assignments.py`
goes.

| Module                     | Change                                                                                                                                                                                                                                                                                   |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scheduler/assignments.py` | The request inspection gains the parent check and the base decision. Its pull request inspection is shared with campaigns.                                                                                                                                                               |
| `scheduler/campaigns.py`   | Open campaigns use the shared pull request inspection with the sub-issue observation. Requests ask the start-time questions.                                                                                                                                                             |
| `scheduler/issue_work.py`  | Serves conversations alone.                                                                                                                                                                                                                                                              |
| `scheduler/labelling.py`   | Also gives the time the label was applied, for the consumed-request rule.                                                                                                                                                                                                                |
| `scheduler/models.py`      | The campaign's pull request finding, and the two new hold findings.                                                                                                                                                                                                                      |
| `scheduler/tick.py`        | The label checks apply the consumed-request rule. Request inspection is given all the work on disk, ended work included, for the parent check. `_launch` creates new work with the base branch and label time that its candidate carries. Cleanup removes a campaign's local branch too. |
| `scheduler/inspection.py`  | A candidate for new work carries its base branch and the time its label was applied, from the request's inspection to the work's creation.                                                                                                                                               |
| `agent_work.py`            | The record's base branch and the time its label was applied. `answers_request` makes an open campaign answer every campaign label on its issue, as an assignment does.                                                                                                                   |
| `campaigns.py`             | The round input's campaign part. The preparation no longer refreshes a detached worktree.                                                                                                                                                                                                |
| `relay.py`                 | Raises signals and selects posts for either kind, through the relay-memory readers that move to the pull request work module. The relay rule is unchanged.                                                                                                                               |
| `git.py`                   | Cuts a branch from a given base, and counts commits past it. `refresh_detached_worktree` serves conversations alone.                                                                                                                                                                     |
| `github.py`                | Reads an issue's parent, with "none" as an answer. Closes an issue as completed with a comment. The labelling events also carry when each label was applied.                                                                                                                             |
| `prompts.py`               | The coordinating and finishing input prompts. Assignments and finishing leads share the signal lines.                                                                                                                                                                                    |
| `claude.py`                | A lead's permissions become the assignment's allowed list with the coordination tools, and today's campaign allowed and disallowed lists go.                                                                                                                                             |
| `status/`, `tui/`, `web/`  | A campaign's card shows its pull request. Campaigns get idle words of their own in the coordinating phase, and the assignment's in the finishing phase. "No pull request yet" applies to campaigns. Words for the two new holds. Round triggers read the new input.                      |
| `cli.py`, `web/app.py`     | Cancel accepts campaigns.                                                                                                                                                                                                                                                                |
| `state.py`                 | Format 9.                                                                                                                                                                                                                                                                                |

Unchanged: `daemon.py`, `agent_rounds.py`, `blockers.py`, `codex.py`,
`config.py`, and the conversation code apart from `issue_work.py`'s
narrower role.

## The motivating use case, walked through

The parent #200, "Add export", has two sub-issues: #201, "Export to
CSV", and #202, "Export to JSON", which #201 blocks. The user assigns
the parent to themselves and labels it `agent-campaign`.

1. **The request.** The second pass finds the campaign request. Nothing
   answers it, the user applied the label, its request is unconsumed,
   and nothing claims or blocks #200. The tick observes the sub-issues,
   creates `GH200-20261126-101500-campaign`, and starts its opening
   round.
2. **The opening round.** The preparation:
   1. cuts `dreamcatcher-GH200-20261126-101500-campaign` from the
      default branch;
   2. commits the placeholder "GH200", and pushes;
   3. opens draft #210 into the default branch, with "Closes #200", and
      records it;
   4. builds the input: state open, pull request #210, the placeholder
      as head, no posts, signals or notifications, the two sub-issues,
      and the routes.

   The lead, in its coordinating phase, reads #200 and its sub-issues,
   and assigns and labels #201 and #202.

3. **The sub-issues.** At the next tick, #201 passes the start-time
   questions. The parent check finds #200, which has an open campaign
   whose pull request #210 is open. So #201 is available, with the
   campaign branch as base. #202 is blocked by #201, so it is held, and
   its parent is never read. #201's opening round cuts its branch from
   the campaign branch, makes its placeholder because nothing is past
   that base, and opens draft #211 into the campaign branch.
4. **The first merge.** #201's agent marks #211 ready. A tick later #201
   is settled, and the lead is notified that it was handed back, its
   pull request changed, its checks finished, and it became mergeable.
   The lead reviews #211 and merges it.
5. **The closing.** At the next tick, #211 reads as merged, so #201's
   wrap-up round is due, and #201 is not settled while it is. The
   round's preparation closes #201 as completed, with a comment naming
   #211, and the wrap-up completes the assignment. A tick later, the
   lead hears that #201 closed and ended. #202 is no longer blocked, so
   it passes the parent check and starts into the campaign branch.
6. **Handing over.** #202 goes the same way. With both sub-issues
   closed, the lead runs `gh pr ready 210`, and the campaign enters its
   finishing phase.
7. **Finishing.** The default branch has moved and conflicts with the
   campaign branch. #210 shows `DIRTY`, and the out-of-date signal wakes
   the lead in its finishing phase. It merges the default branch in,
   resolves the conflicts, and pushes. The user's colleague reviews #210
   and asks for a change. The user relays it in a post on #210, and the
   lead makes the change and pushes.
8. **The merge.** The colleague merges #210, which closes #200. At the
   next tick, #210 reads as merged. The lead's wrap-up round runs, and
   its finishing step records the campaign as completed. The tick after
   that removes the campaign's worktree and local branch.

## What changes, and what's removed

Changes to the code, with what each removal gains:

- **Campaigns leave the issue-work shape.** For campaigns, this removes
  pausing by label or assignee, the held states of open campaigns, the
  parent's comments as input, the "issue closed" ending, and the
  worktree detached at the default branch. It gains one shape of channel
  for both kinds that have pull requests, and leaves `issue_work.py`
  with a single user.
- **The campaign round input drops `issue`, `comments`, `cursor` and
  `revision`.** The relay's memory then reads one shared part for both
  kinds. `pull_request_head` already names the worktree's commit, so
  `revision` is redundant.
- **The first round has no logic of its own.** The opening preparation
  opens the pull request if none is recorded, then builds the input as
  for any lead round. A failure part way through needs no special
  recovery.
- **Cancel loses its "assignments only" gates.** Cancel becomes one
  operation for both kinds that have a pull request.
- **The lead's separate Claude permission lists go.** A lead gets an
  assignment's permissions with the coordination tools in both phases,
  so the phase never reaches the harness adapter, and Claude and Codex
  treat leads alike. "Do not edit code while coordinating" then rests on
  the prompt on both harnesses.
- **The lead's worktree is never reset.** It behaves as an assignment's,
  so a lead's uncommitted work survives an interrupted round, and the
  wrap-up needs no exception for a deleted branch.

Changes to the enduring documents:

- `docs/concepts.md` gains the campaign branch, the campaign's pull
  request, the coordinating and finishing phases, a work's base branch,
  a campaign's sub-issue, and pull request work. It redefines an
  assignment or campaign request as one application of its label, which
  the work it starts consumes, and leaves a conversation's label a
  switch. It changes a campaign's composition, channel, signals, start,
  holds and ending, the requests that open work answers, and how
  completing an assignment closes its issue.
- `docs/stories.md` changes the campaign stories and the user errors
  that the requirements list, and, for consumed requests, "The user
  closes a pull request they do not want" and "Deleting an assignment's
  worktree", which both start a fresh assignment on a label left on.
- `docs/architecture.md` follows the component model.
- `docs/contract.md` gains the campaign skill's new requirements and
  prohibitions, and narrows its prohibition on editing, committing and
  pushing to the coordinating phase. An existing campaign skill has to
  change to conform, so the contract version rises from 1 to 2, which
  `docs/compatibility.md` records.
- `docs/start-a-campaign.md` describes the campaign branch and its pull
  request, drops the advice to label a queued campaign's sub-issues by
  hand and the advice on keeping sub-issue pull requests from updating
  one another, and says that the campaign branch must not require review
  and that the repository decides whether checks run on pull requests
  into it.
- Every other user document that describes campaigns or what a label
  left on does follows: `src/dreamcatcher/about.md`, the text of
  `dreamcatcher about`, whose list of what holds a request gains a
  request already consumed; `docs/campaign-tutorial.md`;
  `docs/run-and-monitor.md`; `docs/stop-and-recover.md`;
  `docs/command-reference.md`, where cancel accepts campaigns;
  `docs/index.md`; and `docs/customise-skills.md`.
- `docs/changelog.md` gains breaking entries for the state format and
  the contract version, and `docs/compatibility.md` says what to do
  before upgrading.

## Alternatives we rejected

- **A route setting choosing a branch campaign or a direct one.** A
  direct campaign keeps a second shape to maintain, for a gain of one
  merge click in a greenfield project.
- **A copy of the assignment machinery for campaigns.** A copy is two
  things to keep in step.
- **A lead that stays hands-off to the end, fixing everything through
  sub-issues.** It needs signal messages of its own and a rule to merge
  fixes with a merge commit, cannot fix conflicts in a repository that
  allows only squash or rebase merges, and costs a whole assignment per
  fix.
- **Reopening sub-issues when a campaign's pull request closes
  unmerged.** With the parent's label left on, the reopened sub-issues,
  still labelled, would all start again before the new lead had planned
  anything.
- **Reading every campaign parent's sub-issues before the first pass.**
  That reads GitHub for every campaign ever run, on every tick. The
  per-request parent check reads only for requests about to start.
- **Consuming a request when the last work's channel closed.** It needs
  GitHub's closing times for pull requests and issues, and has no answer
  for work that never opened a channel. Comparing label events needs
  neither.
- **Rereading `dreamcatcher.toml` every tick.** The lead's input already
  carries the running daemon's routes, and rereading would break the
  promise that configuration takes effect when the daemon restarts.

## Open questions

- Whether the parent check's read of the campaign's pull request and the
  campaign pass's read of it share one result.
- The idle words for a campaign in its coordinating phase, and the words
  for the two new holds.
- The concepts page's names for the new concepts.
