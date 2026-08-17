# State: the dream:catcher machinery

How today's catcher works, read closely as background for the dreamcatcher
skeleton phase (see `requirements.md` beside this file). The code lives in the
dream repo (github.com/alimanfoo/dream); paths below are relative to its root.

## The big picture

The machinery is three parts and a contract. The engine is
`plugins/dream/skills/catcher/catch.sh`, about 640 lines of bash that turn a
labelled issue into a supervised agent session. Its ears are
`plugins/dream/skills/watcher/watch.sh`, one query that answers "what has the
user newly posted on this pull request?". Its identity system is
`plugins/dream/agent-written-marks.json`, a single footer string, "written by
an agent", that lets everything tell agent posts from user posts on a shared
GitHub account. The contract is two small patches of prose inside the smith
and less skills: the branch-name scan at boot, and the "Handle what the user
posts" section that knows what a PR-inbox prompt is. Those are the only places
the dispatched skills touch the catcher.

The design idea that organises the engine: `catch.sh` keeps almost no state of
its own. Its memory is three external systems. Git worktrees remember what was
dispatched, tmux remembers what is running right now, and GitHub remembers
what became of each issue and pull request. Every tick re-reads all three and
decides from scratch, which is why a crash costs it almost nothing. The small
state it does keep lives under `~/.dream/catcher/<repo>/<branch>`: a
`session.json` of harness settings, an `inbox.json` of relayed posts, a
`final-started` marker, and the round log `agent.log`. The watcher keeps one
watermark file per pull request under `~/.dream/watcher/<repo>`.

The life of one issue: label it "dream:smith" and assign it to yourself. A
tick of `catch.sh` picks it up, cuts a worktree and branch named
`dream-catcher-GH<n>-<timestamp>` beside the main checkout, records the
harness settings, and launches round one headless in tmux — the prompt is just
`/dream:smith`, because the issue number travels in the branch name. The round
adopts the branch, opens a draft PR from it, works, and ends its turn; the
process exits and the tmux session evaporates, which is the only "round
finished" signal there is. Later ticks find the worktree with no live round,
locate the PR by the branch's head, and ask `watch.sh` what you've said. New
posts get written to `inbox.json` and a resume round launches (`claude
--continue`, or `codex exec resume --last`). Merge or close the PR and the
same path runs one final round, guarded by the `final-started` marker. The
worktree and branch stay behind for debugging.

One scoping note: the dream team (`dream:team`) is deliberately not a
customer. It needs Claude Code's experimental agent-teams feature and keeps
its own interactive use of the watcher (Grace invokes `dream:watcher`
directly), and per the project owner it can't be resumed headless — nothing in
the team skill discusses resumption at all. It stays for manual use. The
catcher dispatches smith and less only, and nothing in `catch.sh` knows the
team exists. Getting smith working under standalone dreamcatcher is the
target.

The route, if you're reading fresh: start with the header comment of
`catch.sh`, then read it roughly bottom-up — `tick` and the run loop at the
end, then the recognition helpers, the eligibility rules, `dispatch`,
`round_command` and the per-harness command builders, and
`launch_agent_round`. Then `render-claude.sh` whole (it's 90 lines), then
`watch.sh` whole, then the smith SKILL.md sections named below. The sections
here follow that order.

## The launch, and code the port gets to delete

Where to read: `plugins/dream/skills/catcher/SKILL.md`, the README's
"Unattended runs" section, and the snapshot block near the top of `catch.sh`.

The catcher is started by an agent session running the catcher skill, and the
skill's job is mostly ceremony: derive a tmux session name from the repo,
launch `catch.sh` into a detached tmux session with host access, and handle
the permission dance — the catcher manages tmux, writes under `$HOME`, and
creates sibling worktrees, none of which works inside the harness sandbox, so
the skill carries escalation and refusal-handling instructions and the README
carries the troubleshooting. A standalone tool the user runs directly makes
this entire layer unnecessary.

Same for the snapshot machinery. Codex refreshes plugins installed from
GitHub on every launch, so an upgrade can pull the scripts out from under a
running catcher (dream#875, fixed in dream#879). `catch.sh` therefore copies
the whole plugin into a process-private snapshot under
`~/.dream/catcher/<repo>/runtime/session.XXXXXX` before polling, runs helpers
from the snapshot, and removes it on exit via a trap. `render-claude.sh` needs
a third lifetime — a round can outlive the catcher process, which deletes the
snapshot on exit — so it gets published to the stable path
`~/.dream/catcher/<repo>/render-claude.sh` with a copy-then-`mv`, atomic so a
running round never reads a half-written script. A pinned `uvx` install has no
"the ground moved" problem: the snapshot, the stable-path publish, and the
tmux launch ceremony are all code the port deletes rather than translates.

## Recognising its own work

Where to read: `is_session_branch`, `issue_number_of_branch`,
`session_worktrees`, `agent_tmux_session_name`, and `agent_round_is_live` in
`catch.sh`.

One anchored naming pattern, `dream-catcher-GH<n>-<timestamp>`, does three
jobs at once: it is the ownership test (a human branch never matches, so the
catcher can't mistake your work for its own), the issue-identity record
(`issue_number_of_branch` pulls the number back out), and the retry-uniqueness
mechanism (the timestamp makes each attempt's branch and PR distinct).
`session_worktrees` builds the working set by listing every worktree with
`git worktree list --porcelain` and keeping those whose directory basename
matches the pattern — so the branch name and directory name must stay equal,
which holds only because `dispatch` creates both from one variable, and
nothing checks it afterwards.

Liveness is the same trick against tmux: `agent_round_is_live` asks
`tmux has-session` for a name derived from repo plus branch. The scar: tmux
rewrites dots to underscores, so the repo's dots become plus signs (which
GitHub forbids in repo names) to keep similarly named repos from colliding. A
daemon holding real process handles replaces all of this.

## The eligibility rules

Where to read: `already_handled`, `dispatched_worktree_exists`, and
`unblocked` in `catch.sh`.

Three questions are asked of every candidate issue, each guarding against a
specific disaster. `already_handled`: does the issue have an active worktree,
or an open or merged PR from an earlier catcher branch? The PR half lists up
to 500 PRs of any state and matches head branch names against the pattern
with this issue's number; a closed-but-unmerged PR deliberately doesn't count,
so a declined attempt frees the issue for another go — removing the label is
how you say stop. (The 500 limit means attempts older than the newest 500 PRs
fall out of view on a very busy repo.) `dispatched_worktree_exists` guards
against a first round that died before opening a PR: the worktree alone claims
the issue, so the next tick doesn't re-dispatch under a fresh timestamp. A
worktree whose `final-started` marker exists and whose round isn't live is a
finished session and no longer claims its issue. `unblocked` reads GitHub's
issue-dependencies API and requires every blocker closed.

The doctrine all three share, worth stating as a rule in the new design
rather than rediscovering three times: every read failure biases toward doing
nothing. `already_handled` on a failed read answers "handled"; `unblocked` on
a failed read answers "blocked"; a failed issue listing skips the whole tick.
A transient GitHub error can delay work by a tick; it can never
double-dispatch or dispatch out of order.

## The tick and its priorities

Where to read: `tick` and `resume_existing_work` in `catch.sh`.

Each tick runs: cap check, then resume, then dispatch, and launches at most
one round before returning. `at_agent_cap` counts live rounds and defers when
they fill `--max-agents` (default one). `resume_existing_work` walks the
session worktrees in branch order and takes the first that needs a round, so
existing sessions always get first claim. The code establishes only the
ordering; the reason is the project owner's, recorded in the requirements
brief: finishing open work beats starting new, and merging gets harder the
more PRs are in flight. Only
when nothing needs resuming does `tick` list labelled issues, sort oldest
first across both labels, filter through the eligibility rules, and dispatch
one. An issue carrying both labels goes to smith today, by documented sort
order (the skeleton brief flips this to a noisy skip).

For each sleeping session, `resume_existing_work` reads the recorded settings,
finds the PR by branch head (`pr_number_for_branch` takes the newest PR from
this branch), and calls `watch.sh`. PR open with no new posts: skip, the
session sleeps on. Open with posts: write `inbox.json`, launch a resume round.
Merged or closed: launch the final round regardless of posts, with `final=1`.
A branch with no PR at all is skipped with a log line pointing at `agent.log`
— see the wedge under sharp edges.

## Dispatch and the harness boundary

Where to read: `dispatch`, `write_session_config`, `read_session_config`,
`round_command`, the four command builders above it, and `first_round_prompt`
in `catch.sh`.

`dispatch` is fetch `origin/main`, cut the worktree and branch, write
`session.json`, build the prompt, launch — and every failing step backs out
with `discard_worktree`, which removes worktree and branch together so a
failed dispatch leaves nothing to confuse the next tick. `session.json` is
written to a `.pending` file then atomically `mv`ed, and its absence is
treated as invalid state: `read_session_config` failing makes the tick skip
that branch.

`round_command` is the harness boundary: one function, a four-way case over
harness times first-or-resume, and the only place the lifecycle learns which
harness exists. The two harnesses answer "never stall waiting for a human"
differently. Claude runs `--print --permission-mode auto` with a narrow
`--allowedTools` list naming exactly the recurring unattended writes (`gh pr
create/comment/edit/ready/close`, `gh issue create/comment`, `git commit`,
`git push`). Codex starts with `--approve-for-me` in a workspace-write sandbox
with network access, and resumes with `approval_policy="on-request"` plus
`approvals_reviewer="auto_review"` — a robot approver instead of a
pre-approved allowlist.

An asymmetry in the resume paths explains why `session.json` exists: Codex
forgets its model and effort on resume, so `codex_resume_command` replays them
every round; Claude's `--continue` remembers, so `claude_resume_command`
passes no model at all. Codex resume is `codex exec resume --last`, where
"last" is scoped by Codex's own working-directory filter — the worktree is
what makes it pick the right session, an implicit contract with Codex's
session store that the new daemon inherits. And `first_round_prompt` is just
`/dream:smith` (or `$dream:smith` under Codex): no issue number, because the
branch name carries it. That is the coupling the dreamcatcher design moves
into the per-label prompt template.

## The round and its log

Where to read: `launch_agent_round` and `resume_prompt` in `catch.sh`, and
`plugins/dream/skills/catcher/render-claude.sh` whole.

`launch_agent_round` wraps the harness command in a logging pipeline: a
timestamped "starting" line, the round, a timestamped "exited with status"
line, all merged with stderr and appended (`tee -a`) to the session's one
`agent.log` — already the "feed file per session" in embryo. tmux exists only
to host this pipeline and answer `has-session`. The `final-started` marker is
written right after the final round launches, not when it succeeds: a final
round that crashes never runs again. The resume prompt (`resume_prompt`)
deliberately carries only the PR number and the inbox file path, so the
user's words never appear on a command line.

`render-claude.sh` is the seed of the new feed renderer. Claude Code under
`--print --output-format stream-json` emits JSON no one can read, so the
Claude command is wrapped in this script (Codex streams plain text and tees in
bare — the two harnesses' logs don't share a format). It runs the command
itself rather than filtering a pipe, so it can exit with the harness's own
status via `PIPESTATUS`, and pushes each line through one unbuffered jq
program. The editorial policy: the model's text comes through whole; each
tool call becomes one bracketed line, `[Bash] git push`, picking the most
telling input by a fallback chain (command, file path, pattern, url, skill,
description, prompt, then the raw input), with the worktree prefix stripped
and the line clipped at 200 characters; failed tool results appear as
`[failed]`; thinking, successful tool results, and housekeeping are dropped as
carrying no story. Thinking is dropped by choice, not absence — unhandled
block types fall through an `else empty` — so showing it is one added branch,
though the field name needs checking against a real stream line. Subagent
lines indent two spaces, keyed off `parent_tool_use_id`. Any line the renderer
can't parse passes through unchanged: a broken render costs one line, never
the log. The opening `[session]` line names the session id, and Claude Code
keeps the full transcript under `~/.claude/projects`, so nothing is truly
lost. The PR that landed it (dream#883) reported one session's rounds at 88 KB
rendered against 3.7 MB raw.

What the feed is for, per the requirements interview: activity visibility,
not narration. Minimal turn output from the agent is desired — GitHub is the
main channel — and the feed's job is to show the round is alive and what it's
touching. One gap against that goal: rendered lines carry no timestamps (only
the starting/exited lines do), so an attached reader can't tell "thinking for
two minutes" from "hung for an hour". Timestamping feed events, or a
staleness cue in `status`, is the observability seed of the later phase's
stall detection.

## The watcher

Where to read: `plugins/dream/skills/watcher/watch.sh` whole; the interactive
wrapper around it is `plugins/dream/skills/watcher/SKILL.md`.

One query, no subcommands: given a PR number, return the PR `state`, the new
user `posts` oldest first, and the `watermarkFile` path. The watermark is the
newest `createdAt` among the posts just returned, stored as a plain ISO-8601
timestamp (trailing Z, so string comparison sorts correctly — no date
arithmetic anywhere). It is the newest post seen, never the wall clock, so a
post landing mid-round stays above the watermark and surfaces next call. An
absent watermark file reads as the beginning of time, so the first call
returns the PR's whole history with no init step.

It reads all three places a user writes: conversation comments and review
bodies from one `gh pr view`, and inline diff comments from a paginated REST
call, since `gh pr view` doesn't carry those. A jq projection flattens the
three shapes into one post shape: `kind`, `createdAt`, `body`, plus `verdict`
on reviews and `path`, `line`, `id` on inline comments, `line` falling back to
`original_line` when later commits moved the code. Two filter rules then pick
the user's posts. A post is the user's when its author is the authenticated
account and its body lacks the footer from `agent-written-marks.json` — the
entire shared-account attribution mechanism is one `contains` check. And a
post must "say something": a non-empty body, or an APPROVED or
CHANGES_REQUESTED verdict. That second rule exists because GitHub wraps any
inline comment in a review with an empty body — including the agent's own
replies — and without it the wrapper would come back as fresh user input. The
relay will hit this on day one.

Error discipline: every failure leaves through `die` on stderr, and stdout is
written only on success, so `catch.sh` captures both streams merged and can
still parse the result while keeping the watcher's error message on failure.
Sequencing: compute, advance the watermark, then print — the watermark moves
before the caller acts, which is the crash window the requirements accept
("you can see the PR and say it again").

## The skill side of the contract

Where to read: in `plugins/dream/skills/smith/SKILL.md`, the sections
"Autonomy", "Mark your work", "Obtain session input", "Open the session PR",
and "Handle what the user posts"; `less/SKILL.md` has the same five, lighter.

Four passages plus a yield rule make a skill dispatchable. Boot input: scan
the branch name for `gh<number>` tokens, case-insensitive, several allowed;
no token means ask the user, which headless is the wedge below. The adopt
clause: a session starting on a branch other than `main` adopts it and opens
the PR from it — the half of the contract that lets the catcher find the PR
by branch head. Inbox handling: on a PR-inbox prompt, read the JSON file it
names, state first — MERGED sends smith to its Collect step to file leftover
issues (less just ends), CLOSED means post where work stopped — then act on
posts oldest first against a small taxonomy: requested change,
resolve-conflicts, defer-merge, question, answer; an approval needs no reply.
Marking: end every commit with the `commitTrailer` and every PR body and
comment with the `commentFooter` from `agent-written-marks.json`, which is
what makes the watcher's filter hold.

The yield rule hides in "Autonomy": a session that can't decide something
alone posts the question as a PR comment and ends its turn — explicitly not
`AskUserQuestion`, which would stall a headless round forever. The round model
works because the skills treat the PR as the only channel and turn-ending as
the way to yield. That is effectively a fourth clause for the dreamcatcher
contract page: end your turn to yield; the PR is the only channel.

Smith and less differ in ceremony (smith runs plan, copy-edit, coherence and
code reviews, posts a session-input comment, and Collects on merge; less does
a lighter inline review and skips the rest) but not in how they're dispatched
— which is what lets one catcher drive both. Both also budget their turn
output to about a sentence per turn, "the user interacts via GitHub, so turn
output is wasted tokens" — which suits the feed's actual goal of activity
visibility. Both name `dream:catcher` in prose ("a headless session exits,
and `dream:catcher` resumes it"), so retirement touches these files, not just
the catcher directory.

## The sharp edges

The wedge. A first round that opens no PR (for instance, smith finding no
`gh<number>` token and asking a user who isn't there) leaves a worktree that
blocks its issue in `dispatched_worktree_exists` while `resume_existing_work`
skips it every tick for having no PR. The catcher logs "no pull request yet;
see agent.log" and a human sorts it out. The new design should decide what
surfaces this state on the status board.

Inline comments lose their range. `watch.sh`'s projection keeps `path`,
`line`, `id`, `body` and drops `start_line`, `original_start_line`, `side`,
and `diff_hunk`, which the REST payload carries. A comment on a line range
reaches the agent as its last line only, so a multi-line suggestion — a
deletion especially — arrives with no way to tell what it replaces. Filed as
dream#891; the new relay should carry `start_line` (with the
`original_start_line` fallback) and consider `diff_hunk`, which hands the
agent the exact text under discussion at no extra API cost.

The watermark advances before the round acts. A crash between `watch.sh`
returning and the resumed round finishing loses that batch. Accepted in the
requirements: the user can see the PR and repost; no fancy recovery
machinery.

`final-started` records launched, not succeeded. A final round that crashes
mid-flight never reruns, and its worktree then stops claiming the issue.

The branch-equals-directory invariant is created once in `dispatch` and never
checked again. Renaming or moving a session worktree silently orphans it.

`already_handled` sees at most 500 PRs, so on a very busy repo an old
attempt's merged PR could fall out of view and let an issue re-dispatch.

Feed lines carry no timestamps, so staleness is invisible when attaching to a
quiet round — only the round's starting/exited lines are timestamped.

The two harnesses' logs don't share a format: rendered Claude events against
Codex's native text. The new daemon, holding the pipe itself, can normalise
both into one event feed.
