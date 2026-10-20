# Reading guide for the state format 6 phase

This guide reads the code behind `requirements.md` in this folder. Read
that brief first. Every section below says what to open and what you
will find there. The route at the end says what order to take them in.

## The big picture

dreamcatcher is a loop with two worlds on either side of it. One world
is GitHub, which the tool does not own and reads only through
`github.py`: issues, labels, assignees, linked pull requests, comments
and posts. The other is the local state under `.dreamcatcher/v5/`, which
the tool does own: a directory per assignment and per conversation, each
holding a record written once and then a file per fact that changes
later, plus a numbered directory per round. `state.py` names the
top-level paths, and `documents.py` is the only way a record is read or
written. A `DreamcatcherDocument` refuses a key it does not expect,
which is why any change to a persisted record needs a new state format.

The daemon in `daemon.py` runs one scheduler tick per interval, and the
tick in `scheduler/tick.py` is the only place where the two worlds meet.
It reads both, starts rounds, and returns what it saw as a
`SchedulerRecord`, which the daemon's `run_scheduler_tick` writes to
`scheduler.json`. Everything a person looks at, the terminal views under
`tui/`, the web pages under `web/` and the status report under
`status/`, reads local state alone and never touches GitHub. The one
exception is the status report's read of `dreamcatcher.toml`, which is
issue #483.

So there are four layers, and the dependency runs one way through them:

1. Durable records: `agent_assignments.py`, `issue_conversations.py`,
   `agent_rounds.py` and `agent_work.py` own what is on disk.
2. Observation and decision: the `scheduler/` package reads GitHub and
   the records, decides what to launch, and returns the record that the
   daemon writes as `scheduler.json`.
3. Derivation for display: the `status/` package turns records plus the
   last tick's observations into one summary status per piece of work.
4. Presentation: `tui/` and `web/` render what status derived.
   `tests/test_architecture.py` checks the import rules that keep these
   apart.

The brief's remodel lives mostly in layers 1 and 2. Its new rounds live
in layer 2 and the GitHub boundary. Its "views read only what the daemon
recorded" rule is a statement about layers 3 and 4.

## One scheduler tick

Open `Scheduler.tick` in `scheduler/tick.py`. It does four things in
order. It forgets any round that has ended, so the capacity count is
honest. It asks the two kind-specific schedulers to inspect:
`AssignmentScheduler.inspect` in `scheduler/assignments.py` and
`ConversationScheduler.inspect` in `scheduler/conversations.py`. Each
returns an `AgentWorkInspection`, defined in `scheduler/models.py`:
ranked candidates, observations, a fault count and a list of failure
strings. The tick then decides on a global cooldown from the two fault
counts, builds the `SchedulerRecord`, and, unless a cooldown is on,
calls `_launch_ready_candidates`, which alternates between the kinds
until capacity is full or nothing is left.

Inspection is where all the GitHub reading happens. Launching is where
all the writing to Git and GitHub happens. A failed read makes a fact
unknown and the tick carries on. A failed launch is caught in
`_launch_ready_candidates` as a `ReportableError`, appended to the
record's `failures` list as a string, and clears every remaining
candidate of that kind for the tick. That catch block is where #496
lives, and it is the "failed launch" rule that the brief's one failure
rule replaces.

## How the assignment side observes an issue

Open `observe_issues` in `scheduler/issues.py`. It lists open issues
assigned to the user under each assignment label, one `gh issue list`
per route through `list_route_issues` in `scheduler/agent_work.py`, then
adds any issue with an open local assignment or a leftover setup that
the listing did not return, with a `read_issue` each. For every issue it
builds an `IssueObservation` from `scheduler/models.py`, whose fields
are each an `ObservedFact`: true, false or unknown, with a sentence of
evidence.

Where each fact comes from:

- open and assigned: the listing;
- claimed here: local state alone, through `observe_claimed_here`;
- claimed elsewhere: `read_issue_pull_request_context` in `github.py`,
  which is one `gh issue view` plus one `gh pr view` per linked pull
  request;
- blocked: `list_blocking_issues`, one paged `gh api` call;
- routing conflict: a count of the matched assignment labels;
- setup failure: the leftover-setup inspection described under creating
  an assignment.

Availability is not stored. `derive_issue_availability` in
`scheduler/models.py` derives it, and the status report calls the same
function.

An issue that already has an open assignment goes through all of this
every tick. The scheduler never uses the result, because an assignment's
rounds follow its pull request, and `_select_issue_observations` in
`status/report.py` then hides the row unless it is blocked or in
conflict. The brief now says those facts should be read only while no
work exists for the issue.

## How the conversation side observes an issue

Open `ConversationScheduler.inspect` and `_inspect_listed_issue` in
`scheduler/conversations.py`. There is no issue observation on this
side. The scheduler lists issues under each conversation label, loads
every saved conversation from disk into `conversations_by_issue`, and
walks the listed issues. Two or more matching routes is a routing
conflict and produces a `ConversationObservation` saying so. Exactly one
route goes to `_inspect_conversation`, which first checks a saved
conversation for fault or pending recovery through
`_inspect_conversation_recovery`, and otherwise reads every comment on
the issue with one paged call and keeps the user's comments after the
delivery position, in `_list_comments_to_answer`. Comments waiting means
a `ConversationBatchCandidate`, but only when
`is_conversation_ready_for_input` in `issue_conversations.py` agrees,
which it does for no conversation, no rounds, or a latest round that
ended successful or stopped. Comments that arrive while a round runs
produce an observation saying they wait, and no candidate.

The `ConversationObservation` in `scheduler/models.py` extends
`AgentWorkObservation` with the issue's title and a routing conflict
beside the one work fact, whether a round is required. It exists from
the first tick that sees the label, before any conversation does, and
`ConversationStatusReader` in `status/conversations.py` lists a
conversation from that observation alone with `conversation=None`. The
class is named for a conversation and for most of its life describes an
issue. That is the asymmetry #455 is about.

When the listing fails, `_carry_forward_unlisted_observations` copies
the previous tick's conversation observations with every fact unknown,
and `_count_carried_conversation_faults` keeps counting their faults
towards the cooldown. This is a second path that exists only so a failed
listing does not make a faulted conversation disappear.

## How a conversation is named and stored

Open `issue_conversations.py`. `compose_conversation_identifier` returns
`conversation-GH<n>`. The record is
`conversations/GH<n>/conversation.json`, the detached worktree is
`conversation-worktrees/GH<n>`, `read_conversation` takes an issue
number, and `_read_conversation` refuses a directory whose name
disagrees with the issue in its record. Upwards, everything uses the
same key: the scheduler's `conversations_by_issue`, the status reader's
observations keyed by issue, the web route `/conversations/<int:issue>`
in `web/app.py`, and the `GH<n>` argument that `cli.py` parses.

The #393 tangle, as the code does it: `ConversationRecord` stores the
`dispatch_label` the conversation started under, but nothing reads it
back to decide anything. Each tick works the route out afresh from the
labels on the issue now. Remove label A and the issue leaves the
listing, no observation is written, and `_find_ineligibility` in
`status/conversations.py` turns the missing observation into idle with
"issue is not eligible". Add label B and the issue is listed with B's
route, but `_prepare_round_start_request` in
`scheduler/conversations.py` does
`candidate.conversation or create_conversation(...)`, the conversation
for the issue already exists, and the round resumes A's harness session
with A's settings. No single line is wrong. The key is wrong, and the
brief puts the label into it.

## Creating an assignment, and the second path

Open `AssignmentCreator.create` in `agent_assignments.py` and read its
steps in order: refuse an issue with an open assignment, fetch main,
pick an identifier, add a worktree on a new branch, make an empty commit
if the branch has none, push, find or create the draft pull request
through `find_or_create_assignment_pull_request` in
`agent_assignment_pull_requests.py`, write the pull request observation,
and last of all write `assignment.json`.

Two things on disk say "exists" in different senses. `read_assignments`
walks the worktrees directory and keeps those whose record exists, so a
worktree declares an assignment and the record says its setup finished.
The gap between them is the second path:

- `_find_incomplete_assignment_identifiers` finds worktrees with no
  record;
- `inspect_incomplete_assignment_setups` checks each one's branch with
  git and its pull request through
  `validate_assignment_pull_request_setup`, every tick: one
  `gh pr list`, one `gh issue view`, and one `gh pr view` per linked
  pull request, unless the issue has several leftovers, which fails
  before any read;
- the result goes into `observe_issues` as `incomplete_setups`, and
  `_observe_external_claim` special-cases it twice;
- `IssueObservation.setup_failure` carries it to the report, which has a
  failed-setups section with its own template partial and terminal
  table;
- `_find_incomplete_assignment` lets the next `create` reuse the
  identifier.

The `AssignmentRecord` holds the pull request number, so an assignment
cannot exist without one. #425 writes the record first and makes every
setup step one that does nothing when its work is done. The brief goes
further and says setup is not a thing apart from the first round.

## Rounds

Open `AgentRound.__init__` in `agent_rounds.py`. Making a round starts
it. The constructor writes the input file and the prompt, spawns the
harness through `commands.spawn_command` with the prompt as stdin, and
writes `round.json` with number, purpose, recovery flag, start time and
pid. If that write fails it kills the process it started. The round then
runs on its own threads and the daemon asks only `is_alive`. When the
harness exits, `_record_ending_and_join_streams` writes `round.json`
again with an ending. The ending is one of four typed documents,
`SuccessfulAgentRoundEnding`, `ErroredAgentRoundEnding`,
`InterruptedAgentRoundEnding` and `StoppedAgentRoundEnding`. A record
with no ending reads as running, and `DreamcatcherDaemon._sweep_orphans`
in `daemon.py` turns such records into interrupted, or stopped when a
stop request is on disk, at startup.

A conversation round is given a finisher, `post_conversation_answer` in
`issue_conversations.py`, which posts the answer before the ending is
recorded. A finisher that raises makes the round errored with a reason
and a clean exit status.

This is the record-first pattern the brief wants for assignments,
already working for rounds. The reason it was not done for assignments
is that an assignment's start was five Git and GitHub steps long. A
failure in those steps, which run in `AssignmentScheduler.launch` before
this constructor, never reaches a round record, so it has nowhere to go
but the scheduler's failures list. That is why "a failed launch" and "an
errored round" are different things today.

## Faults, recovery and the cooldown

Open `scheduler/faults.py`. Fault is never written down.
`derive_agent_work_fault` says fault when the last two round records
both ended errored, and both endings are at or after a boundary, which
is the later of the user's last retry request and the end of the last
global cooldown. A retry, `request_agent_work_retry` in `agent_work.py`,
only writes a timestamp, so it moves the boundary and old errors stop
counting. `start_cooldown_if_required` starts a cooldown when a tick
counts two faults, and `read_scheduler_record` ends one by the clock and
keeps `most_recent_cooldown_ended` as the other boundary. The fault
function is called from five places: both schedulers,
`_count_carried_conversation_faults`, `has_fault` in
`status/agent_work.py` and `_retry_agent_work` in `cli.py`. Scheduling
and reporting agree by sharing the function.

`is_awaiting_recovery` is its sibling: the latest round errored or was
interrupted, or has no ending and no daemon is running. For an
assignment that makes an `AssignmentRoundCandidate` with `is_recovery`,
and `launch` resumes the session with `ASSIGNMENT_RECOVERY_PROMPT` from
`prompts.py` while the pull request is open, or with the ordinary input
prompt once it is merged or closed. For a conversation,
`_prepare_recovery_round` rereads the failed round's saved input and
resumes with `CONVERSATION_RECOVERY_PROMPT`. Both assume a round to
recover and a session to resume, and `resolve_harness_session` in
`scheduler/agent_work.py` starts a replacement session when no
identifier was ever recorded. These are the assumptions the brief's
"trying the next step again" loosens.

## Status derivation and the views

Open `read_status_report` in `status/report.py`. It reads whether the
lock is held, `daemon.json`, `scheduler.json` with its cooldown advanced
by the clock, every assignment and conversation directory, and
`dreamcatcher.toml` for the labels the empty-section guidance names.
That last read is the one place a view reads something the daemon did
not write, and it is #483.

Each kind has a reader that turns records plus the last tick's
observation into one summary status, and both are chains of "is it this,
else is it this". `AssignmentStatusReader.derive` in
`status/assignments.py` goes working, ended, fault, awaiting recovery,
unobserved, then the observation: a required round is waiting, none is
needs user feedback, unknown is unknown.
`ConversationStatusReader.derive` in `status/conversations.py` goes
working, fault, eligibility from the observation, awaiting recovery,
then the observation. Same idea, different order, different words.

Two details matter for the batch. `_refresh_issue_observations` in
`status/report.py` recomputes claimed-here from local state, overwriting
what the tick wrote, which shows that claimed-here was never really an
observed fact. And the issue rows are the one status the report does not
derive: it hands `IssueObservation` objects through, so
`_compose_issue_row` in `web/views.py` and `_describe_issue_observation`
in `tui/status.py` each decide "routing conflict, blocked or available"
for themselves, and the web one re-parses the blocked evidence text with
`_ISSUE_REFERENCE_PATTERN` to recover issue numbers, which is #457.

## The GitHub reads behind the new rounds

Open `_read_pull_request` in `github.py`. It asks `gh pr view` for three
fields, number, state and isDraft, and the `PullRequest` projection
holds those three. `AssignmentScheduler._inspect_pull_request` makes
that read once per tick for each open assignment that has a round, is
not running and is not in fault, since `_inspect_assignments` and
`_inspect_assignment` return before it otherwise. It calls
`record_pull_request_observation` to write a `PullRequestObservation`
only when state or draft changed, then `_inspect_pending_round` decides
whether a round is needed. Today there are three reasons: the last round
needs recovering, `list_undelivered_user_posts` in `relay.py` found user
posts after the delivery position, or the pull request is no longer
open, since the method returns no candidate only for an open pull
request with no posts. The relay is three more paged reads per pull
request per tick, through `list_user_posts`.

The conflict and CI rounds add a fourth reason. The read grows to carry
`mergeable`, `mergeStateStatus`, `headRefOid` and `statusCheckRollup`.
Nothing in the code asks for those today; that `gh pr view --json`
answers all four was checked against gh on this repository, not against
the code. The once-per-head rule compares the current head against the
last head at which a signal was relayed, which #550 keeps in
`round-input.json` beside the user posts and reads back the way
`read_user_post_delivery_position` walks the round inputs. The prompt
line goes through `compose_assignment_input_prompt` in `prompts.py`,
which already prefixes a line when the previous round was stopped. The
observation on disk gains the mergeable state so the views can show it
beside draft or ready.

## The route

1. Read the brief, then this guide's big picture.
2. `scheduler/tick.py`, `Scheduler.tick` and `_launch_ready_candidates`.
3. `scheduler/issues.py`, `observe_issues`, then `IssueObservation` and
   `derive_issue_availability` in `scheduler/models.py`.
4. `scheduler/conversations.py`, `inspect`, `_inspect_listed_issue`,
   `_inspect_conversation` and `_prepare_round_start_request`.
5. `issue_conversations.py`, `compose_conversation_identifier`,
   `read_conversation` and `create_conversation`.
6. `agent_assignments.py`, `AssignmentCreator.create`,
   `read_assignments` and `inspect_incomplete_assignment_setups`.
7. `agent_rounds.py`, `AgentRound.__init__` and
   `_record_ending_and_join_streams`.
8. `scheduler/faults.py` whole, then `AssignmentScheduler.launch` and
   `_inspect_pending_round` in `scheduler/assignments.py`.
9. `status/report.py`, `read_status_report`, then the two `derive`
   chains.
10. `github.py`, `_read_pull_request` and
    `read_issue_pull_request_context`, then `relay.py`.

## The sharp edges

- Two things on disk say an assignment exists. `read_assignments` walks
  the worktrees directory and then requires the record. The
  leftover-setup path exists in the gap, and it reaches into
  `observe_issues`, the status report, a template partial and a terminal
  table.
- A launch failure and a round error are different kinds of thing. The
  first is a string on `SchedulerRecord.failures` with no link to the
  work; the second is a typed ending on a round record. The fault rule
  reads only the second.
- The `IssueObservation` carries claimed-here, which the status report
  recomputes from local state anyway, and a setup failure, which is a
  fact about local artifacts. Neither is an observation of the issue.
- Every issue with an open assignment costs three GitHub reads per tick,
  or four when the listing did not return it, for facts that decide
  nothing once the assignment exists. Its own pull request is linked, so
  the claimed-elsewhere read views it before dropping it.
- A `ConversationObservation` exists before its conversation does and
  carries the issue's title. The status reader lists a conversation from
  it with no saved conversation.
- A conversation is keyed by issue alone, so the label that started it
  is stored but never read, and a second label resumes the first label's
  session.
- A conversation's fault counts towards the cooldown only while its
  issue is listed, so a second path carries observations across a failed
  listing to keep counting.
- The two status derivation chains do the same job in different orders
  with different words, and the issue rows are derived twice more, once
  in the terminal view and once in the web view, with the web one
  parsing evidence text for issue numbers.
- The status report reads `dreamcatcher.toml`, the only place a view
  reads something the daemon did not write.
- The pull request projection holds three fields and the read asks for
  exactly those, so the new rounds need the read and the projection to
  grow together.
