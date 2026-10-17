# Roadmap for the state format 6 phase

This roadmap sits beside `requirements.md`, `reading-guide.md` and `design.md`
in this folder. State format 6 is the on-disk layout the design describes. Each
stage below is one pull request, built in one agent session, reviewed and merged
before the next starts. The design holds the detail; a stage says what it
delivers, how we know it is done, and what it leaves for a later stage.

Every session that implements a stage should correct the specifications as
details change and say on its pull request what it corrected. It may change how
it delivers the stage when earlier work or implementation discoveries justify
that change. It should raise any change to the roadmap's stages, boundaries,
order or dependencies with the user instead of restructuring the roadmap itself.

No release is made from main between the first stage merging and the last, as
each stage changes the format 6 records. The last stage is the consistency
review that prepares the v6.0.0 release.

## Stage 1: one kind of agent work on disk

Delivers the format 6 layout, with the scheduler and status still running their
two paths over it.

- `STATE_FORMAT_VERSION` becomes 6, so the state root is `.dreamcatcher/v6/`.
- `assignments/`, `conversations/` and their two worktree collections become
  `work/` and `worktrees/`.
- Every piece of agent work has the identifier `GH<n>-<timestamp>-<kind>` and a
  `work.json` recording its issue, dispatch label, kind, title, harness settings
  and initial prompt. An assignment's branch is named from its identifier, so
  the record does not repeat it. The pull request number moves into the pull
  request observation.
- `ended.json`, holding the time and a reason, replaces `cancel.json` and the
  completion derived from rounds. The round that wraps up an assignment writes
  it with "completed" in its finishing step, `cancel` writes it with
  "cancelled", and agent work is open until it exists.
- The daemon writes the dispatch routes it loaded into its daemon run record,
  and the status report reads its labels from there and never opens
  `dreamcatcher.toml`.
- A shared reader in `agent_work.py` lists agent work of both kinds, and the
  scheduler, status, the commands and the views read one record shape through
  it.
- The web page for any agent work is `/work/<identifier>`, and the
  `/assignments/<identifier>` and `/conversations/<issue>` addresses go. A
  conversation the tick has found but not yet saved has no page.
- The collapsed list of ended work on the home page shows both kinds; until
  stage 4 only assignments can end.
- The ontology and architecture docs describe the layout, the identifier and the
  daemon run record.

Done when the suite passes; a daemon carries an assignment and a conversation
end to end under the new layout; nothing a user sees has changed except the work
identifiers, which now end in their kind, and the addresses of the work pages;
and the status report renders with `dreamcatcher.toml` missing. Closes #483 and
the naming half of #393.

Leaves for later every change to rounds, the tick, the scheduler record and the
signals, except that a conversation observation has no identifier until its
conversation exists, because the identifier carries the creation time. The pull
request observation keeps its state, draft flag and time until stage 4, once the
row from stage 3 carries them. The two inspect paths and the two status chains
stay.

## Stage 2: everything is a round

Delivers the round as one attempt to take a turn, with the work record written
before any Git or GitHub step.

- The scheduler writes `work.json` the moment it picks an issue and starts round
  one in the same tick.
- The round record is written before any preparation, with no process id until
  the harness spawns.
- Each kind supplies a preparation step. For an assignment whose pull request
  observation does not exist: fetch main, add the worktree on the assignment's
  branch, make the empty commit, push, find or create the draft pull request on
  that branch, and write the observation. For every conversation round: reset
  the detached worktree to fetched main, adding it when missing. Each step does
  nothing when its result exists.
- A failure in preparation records an errored outcome with the reason and no
  exit status, and the views word it without one.
- The cursor is read from the latest round whose outcome is not errored or
  interrupted, so a round that errored or was interrupted has its input given
  again, with the did-not-finish line prefixed to the prompt as the stopped line
  is today. A running round's input counts as relayed, so what it holds is not
  new while it runs.
- The recovery prompts, the recovery flag, the purpose field and
  `resolve_harness_session` go. The feed's round line and the rounds table say
  what woke the round, from its input.
- The incomplete assignment setup and its path go in full, with the
  failed-setups section in the report, the terminal and the web.
- The daemon's startup sweep skips the kill for a record with no process id.
- The ontology redefines the agent round and removes round purpose, the recovery
  round and the incomplete assignment setup. `docs/contract.md` drops its
  sections on recovery rounds.

Done when the suite passes; an assignment whose first round fails at the push
leaves nothing outside its directory and recovers on the next tick by running
the same preparation; a round that errors after its harness started is given its
input again; two consecutive errors still put the work in fault; the feed and
views say what woke each round; and no module references an incomplete setup.
Closes #425 and #496.

Leaves for later the tick, which still has two inspect paths and still observes
issues the old way, the scheduler record's shape, and the signals.

## Stage 3: rows as data

Delivers the scheduler record as one row per request, written by the two inspect
paths as they are, and read by one status derivation.

- A row names the issue, its title, the dispatch label, the kind and the open
  agent work if any.
- For open work the row holds what the tick found as typed values: the count of
  user posts or issue comments, the round the tick started, and for an
  assignment the pull request's number, state and draft flag, which is what the
  read gives until stage 5 grows it.
- For a request with no open work the row holds why nothing started: the open
  linked pull requests, the open blocking issues, or the conflicting labels.
- For a read that failed the row holds the failure reason in place of the facts.
- The row carries the round the tick started and, when that round errored in
  preparation, its reason. The scheduler failures then keep only listing
  failures, as the design says. Until this stage, the tick also appends a round
  that errored in preparation to the failures, so the daemon's output line can
  name it, and the views show it twice.
- `ObservedFact`, `Truth`, `IssueObservation`, `AgentWorkObservation` and
  `ConversationObservation` go.
- Status becomes one derivation for both kinds, with the values working, ended,
  fault, unknown, waiting and idle, and the request rows reach the views as
  data. A conversation whose issue the listing did not return reads as idle with
  that as its detail until stage 4 adds pausing.
- The terminal and the web render one row type each from that data, linking
  issue and pull request numbers, and the issue-row logic duplicated between
  them goes, with `_ISSUE_REFERENCE_PATTERN`.
- The ontology defines the request and the status values, and the architecture
  doc describes the record.

Done when the suite passes; the home page and the terminal show the same rows
from the same data; no view parses a sentence to recover a number; the statuses
needs user feedback, routing conflict, complete and cancelled are gone and their
cases read as idle with a detail, as a request row, or as ended with a reason;
and the scheduler record holds no sentence meant for a person. Closes #457.

Leaves for later how the tick decides: the two inspect paths, the per-issue
reads for issues with open work, the conversation's issue read, pausing and
ending by issue state, and the one-open-assignment check from the rows.

## Stage 4: one tick

Delivers the tick in its one shape.

1. Read every piece of agent work from disk and list the issues per dispatch
   label.
2. Build the requests from both sources.
3. Inspect each open piece of work's channel, reading a conversation's issue
   first to tell paused from ended and writing `ended.json` with "issue closed"
   when the issue is closed.
4. For a request with no open work: for an assignment label, check from the rows
   that the issue has no open assignment and no second assignment label, then
   ask the two start-time questions; for a conversation label, check that the
   issue has no second conversation label, then read the comments. A paused
   conversation under another label does not block a new one.
5. Rank existing work before new, alternate kinds, respect the cooldown and
   capacity, and launch as today.
6. Write the rows.

- The two inspect paths, the five candidate types and the two rank functions
  become one inspect, one candidate type and one rank. `scheduler/issues.py`
  goes.
- An issue with open work costs no read beyond its channel.
- The pull request observation becomes `pull-request.json`, holding the number
  written once by round one.
- The ontology and architecture docs describe the tick, the channel, the cursor,
  pausing and ending, and the ontology drops availability and conversation
  eligibility.

Done when the suite passes; a conversation pauses when its label comes off, when
its issue is unassigned, or when a second conversation label is added, resumes
in the same harness session when the cause is removed, and ends when its issue
closes; removing label A and adding label B starts a fresh conversation under B
while A's stays paused; an issue with an open assignment costs no GitHub read
beyond its pull request and user posts; and the scheduler package holds one
path. Closes #455 and the behaviour half of #393.

Leaves for later the signals.

## Stage 5: signals

Delivers the two new reasons an assignment takes a turn.

- The pull request read asks for the merge state, head commit and checks, and
  the projection holds them. The row carries the merge state and check result.
- The assignment round input records the head commit and the other signals
  relayed, and the cursor reads back the head at which each was last relayed.
- The tick raises out-of-date for a ready pull request whose merge state is
  `BEHIND` or `DIRTY` at a head not yet relayed, and check-failure for a ready
  pull request with a finished check that failed at a head not yet relayed. It
  withholds a check failure when the last two rounds whose input is behind the
  cursor both relayed one.
- The prompt gains one prefix line for each signal.
- The views show the merge state and check result beside draft or ready, with
  "checks running" and "checks failing after two attempts" as idle details.
- The assignment harness permissions gain the commands that read check output.
- `docs/contract.md` documents the two input keys and the two lines, and the
  ontology defines the signal and the relay rule.
- The batch's issues are amended or closed as the design's open list says.

Done when the suite passes against fabricated `gh` answers, built in the test
helpers in the shapes the design records, for a behind, a conflicting, a green,
a running and a red pull request; a ready pull request gets a round when main
moves under it and none while its checks run; a red check wakes the agent twice
and not a third time, and the row says why; a draft gets neither signal; and the
batch's issues are closed or amended. Closes #550 and #551.

Leaves nothing of the design for a later stage, only the consistency pass and
the release. The contract version is for this stage to settle: the input keys
are additive and the lines are instructions, so version 1 may stand.

## Stage 6: consistency review and release

Delivers a codebase and a set of enduring documents that agree with each other
after five stages of change, and the v6.0.0 release.

- Run the `uncoded-consistency-review` skill over the whole codebase and resolve
  every disagreement it reports: two names for one concept, one name for two, or
  a claim in code, docstring or document that another contradicts. Resolve each
  by changing the code or the document to the ontology's term and meaning, and
  record on the pull request what was found and how each was settled.
- Read `docs/ontology.md`, `docs/architecture.md` and `docs/contract.md` once
  through against the code as it now stands, and correct anything the five
  stages left behind.
- Add the folder to the completed list in `specs/AGENTS.md`.
- Write the v6.0.0 entries in `docs/compatibility.md` and `docs/changelog.md`,
  including the upgrade note that v6 starts with empty local state and that a v5
  daemon must be stopped first.

Done when the review reports no disagreement; the suite and every check pass;
the three enduring documents describe the code as it is; and main is ready to
tag as v6.0.0.

Leaves nothing for a later stage.
