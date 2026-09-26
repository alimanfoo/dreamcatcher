# Reading guide: issue conversations

## The big picture

Start with `AgentWorkScheduler.tick` in `src/dreamcatcher/scheduler.py`. It
decides whether an existing implementation assignment needs another round or
whether a new issue can be dispatched. Follow the sections below in order:
discovery, ownership, comment delivery, session resumption, launch settings,
recovery, and reporting.

Three things have different lifetimes. An assignment is Dreamcatcher's durable
record of implementation work. A harness session is the conversation identified
by Claude or Codex. A round is one process invocation of that session. The
process can finish while the assignment and session identifier remain available
for another round.

The requirements in `specs/2026-09-21-issue-conversations/requirements.md`
introduce a different commission: answer the user's questions on an issue,
independently of implementation. This guide describes the existing code and the
boundaries that matter to that work; it does not choose its design.

Read `docs/ontology.md`, `docs/architecture.md`, and `CONTRACT.md` for the
intended vocabulary and responsibilities, then verify behaviour in the code
named below. The inbox-field discrepancy described under sharp edges is one
place the contract and code disagree.

## Discovering issues and continuing existing work

Read `DreamcatcherConfig` and `DispatchRoute` in `src/dreamcatcher/config.py`,
then `_list_considered_issues`, `observe_issues`, and
`derive_issue_availability` in `scheduler.py`.

Each configured dispatch label maps to harness-specific recipes containing a
prompt, model and effort. Every tick searches once per route. `list_issues` in
`src/dreamcatcher/github.py` asks GitHub for open issues with that label and the
configured assignee. Closing an issue or removing either condition takes it out
of that search; restoring the conditions makes it discoverable again. This query
reads issue metadata, not comments.

Implementation has further gates: another open local assignment, an open linked
PR, an open dependency blocker, or multiple dispatch labels prevents a new
assignment. Unknown required facts also prevent dispatch. Available issues are
ordered oldest first.

Continuing work follows a separate path. `observe_issues` individually reads
issues belonging to open local assignments or incomplete setups when the search
did not return them. `_inspect_assignments` considers idle open assignments, and
`_inspect_assignment_pull_request` checks their PR and feedback without checking
issue-label or assignee eligibility. Removing a label therefore prevents new
dispatch but does not stop an existing assignment receiving PR feedback. The
conversation requirement to stop watching ineligible issues is distinct from
this existing behaviour.

## What an assignment owns

Read `AgentAssignmentCreator.create`, `AgentAssignmentRecord`, and
`AgentAssignment` in `src/dreamcatcher/agent_assignments.py`.

Creation fetches main, creates a branch and worktree, makes and pushes an empty
commit, opens a linked draft PR, and writes the assignment record before the
first round starts. The record binds the issue, branch, worktree, PR, harness,
model, effort and initial prompt. Changing the prompt alone would not remove
those setup operations.

Follow `_find_incomplete_assignment` and `_find_or_create_pull_request` for
interrupted setup. Creation can reuse the expected worktree, branch and linked
draft rather than start another assignment. `create` refuses a second open local
assignment for the issue.

`AgentAssignment.is_complete` requires the last round to be a successful
wrap-up. Closing or merging the PR calls for wrap-up; it does not immediately
complete the assignment. This ownership model differs from the independent
conversation partner we specified.

## Reading and filtering comments

Read `list_user_posts` and `GITHUB_USER_POST_ENDPOINTS` in `github.py`, then
`list_undelivered_user_posts` and `_is_undelivered_user_post` in
`src/dreamcatcher/relay.py`.

The existing reader is for PR feedback. It gathers conversation comments,
reviews and inline comments from three endpoints. Ordinary PR conversation
comments use GitHub's `issues/.../comments` endpoint, but the operation as a
whole also reads PR-only endpoints. `_read_github_pages` fetches all pages. A
failed source makes the whole read unknown.

The relay keeps posts authored by the signed-in account, newer than the delivery
cursor, with something to say, and without the `<!-- dreamcatcher -->` marker.
It sorts them oldest first. `AGENT_POST_INSTRUCTIONS` in
`src/dreamcatcher/prompts.py` asks the agent to add that marker so its own
replies are not relayed back. Reviews can count through an approval or
changes-requested verdict even without text.

`tests/test_relay.py` demonstrates the empty-cursor history, author filter,
marker exclusion and timestamp boundary.

## Delivered does not mean answered

Read `AgentWorkScheduler._launch_required_round` in `scheduler.py`, then
`advance_user_post_delivery_cursor` in `agent_assignments.py`.

The scheduler starts a round with a batch of posts, then writes the newest
post's timestamp to the assignment's `watermark` file. It does not wait for an
answer to appear on GitHub. If launching fails before the cursor advances, the
posts remain available; if the round launches and later fails, recovery
continues the existing session. A failure between launch and cursor persistence
can cause delivery to repeat.

An empty cursor admits the existing history through the same filters. There is
no check here that distinguishes an unanswered question from an answered one.
The tests `test_an_assignment_receives_a_batch_only_once` and
`test_a_batch_no_round_ever_launched_is_read_again_next_tick` in
`tests/test_scheduler.py` show the normal delivery boundary.

## Resuming a saved conversation

Read `start_agent_round`, `AgentRoundOutputReader.read`, and
`AgentRound.__init__` in `src/dreamcatcher/agent_rounds.py`, then
`find_harness_session_identifier` and `record_harness_session_identifier` in
`agent_assignments.py`.

The adapter extracts the harness session identifier from output, and the
assignment records it. A later round supplies that identifier to the adapter's
resume operation. If the assignment record lacks it, Dreamcatcher can recover it
from the first round's raw output. If neither source supplies it, resumption
reports an error.

Each round starts a new process in the assignment's saved worktree. Dreamcatcher
retains the session identifier; the harness owns the transcript. This is the
existing basis for continuing a conversation without keeping an agent process
running between questions.

## Instructions and launch permissions

Read `compose_issue_conversation_prompt` and
`compose_issue_conversation_round_prompt` in `prompts.py`, then
`IssueConversationInput` and `AgentRound.__init__` in `agent_rounds.py`.

The first prompt substitutes the issue number into the configured recipe and
directs the harness to the saved issue input. A later round receives the new
issue comments in the same document type and a prompt naming that file. The
round writes its files before launching the harness and passes the prompt
through standard input.

Then read `ClaudeHarnessAdapter` and `CLAUDE_CONVERSATION_DISALLOWED_TOOLS` in
`src/dreamcatcher/claude.py`, and `CodexHarnessAdapter` and
`CONVERSATION_PERMISSION_OVERRIDES` in `src/dreamcatcher/codex.py`. Both
adapters select conversation-specific permissions from `AgentWorkKind`. Claude
denies direct editing and GitHub mutation tool families; Codex uses a read-only
sandbox with command network access off and rejects approval requests.

## Which code a round investigates

Return to `AgentAssignmentCreator.create`, then read `fetch_main` and
`add_worktree` in `src/dreamcatcher/git.py` and
`AgentAssignment.compose_round_paths` in `agent_assignments.py`.

Creation runs `git fetch origin main` and creates the assignment branch from
`origin/main`. Later rounds reuse the saved worktree, including work left there
by earlier rounds. There is no main-refresh step in the existing resumed-round
path. Answering against current main on every conversation round is therefore
additional behaviour, whose design remains open.

## Restart, recovery and capacity

Read `DreamcatcherDaemon.run` and `_sweep_orphans` in
`src/dreamcatcher/daemon.py`, then `inspect_agent_assignment`,
`_inspect_assignment_pull_request`, `derive_assignment_fault`, and
`_start_cooldown_if_required` in `scheduler.py`.

The daemon stops active rounds on exit. At startup it attempts to end process
trees for recorded rounds without endings and marks those rounds interrupted.
The scheduler can then resume their saved harness sessions. For an unfinished
round on an open PR, it uses `RECOVERY_PROMPT`; a terminal PR instead calls for
wrap-up input.

Two consecutive errored rounds put an assignment in fault. A successful or
interrupted round breaks that sequence. Two faulted assignments trigger a
fifteen-minute global cooldown. Observation continues, but launches stop. The
persisted cooldown survives a restart; expiry makes earlier errors stop counting
towards fault. The CLI's `_retry_assignment` also lets the user request recovery
after resolving an assignment-specific fault.

`AgentWorkScheduler.tick` removes ended rounds before checking capacity, so idle
saved sessions do not consume the agent cap. A tick launches at most one round.
Existing required rounds precede new dispatch, with an assignment that has not
started its first round ahead of recovery, wrap-up and feedback. A failed issue
listing prevents all launches for that tick.

## Persistence and reporting

Read `StateDirectory` in `src/dreamcatcher/state.py`, `read_agent_assignments`
in `agent_assignments.py`, and `read_status_report` and `_StatusReportReader` in
`src/dreamcatcher/status.py`.

State lives under `.dreamcatcher/v3/`, with separate worktree and assignment
directories. Assignment records hold durable identities, while numbered round
directories hold prompts, input, raw output, feeds and outcomes.
`documents.write_text` replaces files atomically through a neighbouring
temporary file; `write_json` uses it for structured records.

Assignment discovery currently starts by listing worktree directories. Reading
saved assignments also reads their records and delivery cursors, while
`AgentRoundReader` caches terminal round records. Retaining history therefore
avoids an idle agent process but does not eliminate local bookkeeping.

Status reporting reads local state and the scheduler's observations. It does not
itself poll GitHub or launch work. An idle assignment needing no round appears
as needing user feedback. `AgentAssignmentStatus.hand_resume_command` provides a
manual resume command when the session identifier is available and the
assignment is not reported as working.

## The sharp edges

Revisit `_observe_issue` in `scheduler.py` and `DreamcatcherDaemon.run` in
`daemon.py` for identity. The configured assignee selects issues, but the
signed-in GitHub account selects comments. They coincide with the default `@me`;
they can differ with an explicitly configured assignee.

Revisit `_is_undelivered_user_post` in `relay.py` and
`compose_first_round_prompt` in `prompts.py` for the filtering boundary. The
relay filters supplied posts, while the first prompt gives the agent an issue
number without filtered issue history. That filtering does not itself restrict
the agent's own tool reads. The conversation requirement excludes other people's
comments entirely, so the supplied inbox is only one part of that boundary.

Read `_UserPostProjection` in `github.py` alongside the relay predicate for
timestamp behaviour. Comments use creation time, not edit time, and delivery
requires a timestamp strictly greater than the cursor. Edits to delivered
comments do not reappear. Equal timestamps are accepted together in a fetched
batch, but a comment discovered later with a timestamp equal to the cursor is
excluded. IDs are present but not used by the cursor.

Compare `USER_POSTS_PROMPT`, `AgentRoundInput`, and `CONTRACT.md`: the prompt
and contract name `state` and `posts`, whereas the actual JSON has
`pull_request_state` and `user_posts`. The scheduler test inspecting
`inbox.json` confirms the latter. This mismatch is filed as
[GH196](https://github.com/alimanfoo/dreamcatcher/issues/196).

Finally, read `list_issues` and `list_user_posts` in `github.py` with scale in
mind. Issue discovery has a limit of 500 per route, and the PR post reader
fetches complete paginated histories before the relay filters them. Saving a
delivery cursor currently reduces what reaches an agent, not what GitHub is
asked to return.
