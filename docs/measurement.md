# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-26 at `80b0a96f`, for the v9.3.0 release
preparation. The review covers the one pull request merged since v9.2.0:
PR #809, which makes work start, and a paused conversation or campaign
resume, only on a dispatch label that the signed-in user applied. The
consistency review and issue triage ran beside this measurement.

## Results

| Criterion                              | Measured                                                                                                                                         | Status | Issue |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ------ | ----- |
| S1 Modules are cohesive                | 0 reviewed modules without one nameable responsibility; `scheduler/labelling.py` added                                                           | met    |       |
| S2 Functions do one thing              | 0 reviewed functions without one nameable job                                                                                                    | met    |       |
| S3 Exports are used                    | 32 public definitions without a direct named importer, v9.2.0's 31 and `github.IssueEvent`, a GitHub response projection                         | met    |       |
| S4 Each thing is done one way          | Who applied a label is derived once, in `scheduler/labelling.py`, and worded once, in `status/findings.py`                                       | met    |       |
| S5 Nothing is suppressed               | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                                                                                                   | met    |       |
| C1 One vocabulary                      | 6 disagreements found, 5 corrected in this preparation and 1 accepted as the documents' existing use of request status names                     | met    |       |
| C2 Enduring documents are true         | #809 corrected all four; three gaps in the ontology's start rules and the architecture's pause and finding lists corrected here                  | met    |       |
| C3 Documentation by purpose            | Tutorials, task guides, references and explanations remain separate; no new page                                                                 | met    |       |
| C4 Formats and contracts are versioned | State format 8 unchanged since v9.0.0; the scheduler record gains a finding that older records need not hold; contract remains 1                 | met    |       |
| K1 Structural rules checked by machine | The 5 named rules remain checked                                                                                                                 | met    |       |
| K2 Suite is fast and speaks plainly    | 51.55 seconds, 1,571 tests passed, 100% statement and branch coverage                                                                            | met    |       |
| K3 Tracker is current                  | 12 open issues triaged; 2 bodies corrected; none ready to close                                                                                  | met    |       |
| K4 Every change reviewed to standard   | #809 answers all 7 definition-of-done questions                                                                                                  | met    |       |
| E1 Rules, not cases                    | 11 ledger entries, unchanged; each new conditional applies the rule that work starts or resumes only on a label the user applied                 | met    |       |
| E2 Invariants by construction          | 72 nullable class fields, unchanged; a failed read, another account and the user are three distinct answers of one function                      | met    |       |
| E3 Concept economy                     | No domain concept added; **held** joins the request statuses and a label that someone else applied joins the causes of a pause                   | met    |       |
| E4 Symmetry                            | Requests of every kind, and open conversations and campaigns, take the same check; open assignments, which their pull request governs, take none | met    |       |

## Deferred work and previous findings

The v9.2.0 measurement left no disagreement open and filed no follow-up.

Since v9.2.0, #594 was decided: the team is trusted, and the aim is that
a colleague's mistake cannot start work on someone else's machine. #808
recorded the rule, and #809 implemented it. A request whose dispatch
label someone other than the user applied is held, and open work whose
label someone else applied is paused, each naming the account and saying
that the user can remove and re-add the label. An acceptance control
inside _dreamcatcher_ was deferred until relabelling proves a nuisance.

The triage read all 12 open issues against the ontology and the code. It
corrected two bodies. #762 no longer calls who may start work an open
question, and asks which account GitHub would name as applying a label
that a lead applies through an app, since such a label would be held.
And #492 no longer says the ontology states the rule of a file for each
fact, and names the daemon's recovery of rounds left without an ending
in place of "the startup sweep". No issue's work is done, so none was
closed. #805, #806, #807, #810, #811, #812, #813 and #814 were filed
during this interval.

Issues #32, #492, #762, #803, #805, #806, #807, #810, #811, #812, #813
and #814 remain open.

## Notes

- **S1, S2.** The largest modules are `github.py` (890 lines),
  `agent_rounds.py` (785), `status/agent_work.py` (619),
  `scheduler/tick.py` (514), `agent_work.py` (484), `web/app.py` (467)
  and `status/report.py` (464). They retain their boundary's one
  responsibility. `github.py` grows by the projection of an issue event
  and the read of the events that applied a label. `scheduler/tick.py`
  grows by asking who applied a request's label before anything else
  that decides whether it starts. The new `scheduler/labelling.py` holds
  that one rule. The longest functions are those of v9.2.0, with the
  same jobs. `issue_work.inspect_open_issue_work` grows to 43 lines by
  the label check, and still inspects the lifetime of work whose channel
  is its issue.

  | Function                                      | Lines | Its job                                     |
  | --------------------------------------------- | ----: | ------------------------------------------- |
  | `cli._build_cli_parser`                       |   187 | Define the command-line grammar.            |
  | `AgentRound.__init__`                         |    82 | Record and start one round.                 |
  | `DreamcatcherDaemon.run`                      |    82 | Follow the daemon lifecycle.                |
  | `Scheduler.tick`                              |    81 | Follow the scheduler's update sequence.     |
  | `scheduler.assignments._inspect_pull_request` |    66 | Inspect an assignment's channel.            |
  | `scheduler.campaigns._inspect_lead_input`     |    66 | Decide whether a lead round is due.         |
  | `Scheduler._launch`                           |    61 | Create work and start its round.            |
  | `commands.spawn_command`                      |    52 | Start a child and contain its process tree. |

- **S3, S4.** An AST inventory finds 32 public class or function
  definitions without a direct named import from another source module.
  The one added since v9.2.0 is `github.IssueEvent`, the projection that
  `list_labelling_events` returns. Review also accounts for imports
  through module objects, package exports, document and view models,
  callback protocols and the console entry point. It establishes no
  unused public function. The account that applied a label is found in
  `scheduler/labelling.find_label_applied_by_other` alone, and the words
  for it in `status/findings.describe_label_applier`, which the request
  rows and the paused detail of open work both read.
- **S5, K1.** The three coverage pragmas remain at `teardown.py:20`,
  `teardown.py:110` and `commands.py:270`, all platform arms. The
  architecture tests and lint rules pass, with no suppression added.
- **C1.** The consistency review below found six disagreements. Five are
  corrected here. The documents' saying that a request "shows as held"
  is accepted: they name a request's status by the ontology's word, as
  they do for idle and routing-conflict requests, whose rows show only
  their reasons.
- **C2.** The review compares the changed scheduling, status, web and
  documentation paths with all four enduring documents. #809 corrected
  the stories, ontology and architecture in the same change. The
  ontology's rules for starting a conversation and a campaign, the
  architecture's account of what pauses open work, and its list of what
  a row holds still left out who applied the label; they now say so.
- **C3, C4.** The documentation map retains pages by reader purpose. The
  configure guide now states the rule for every kind of work. State
  format 8 and the agent contract's version 1 are unchanged. The
  scheduler record gains a finding naming the account that applied a
  label, which records that an earlier v9 release wrote never hold, so
  they still read.
- **K2.** The default suite passed with 1,571 tests, one platform-only
  skip, and 100% statement and branch coverage, in 51.55 seconds. Its
  slowest test was
  `test_a_closed_parent_ends_the_campaign_once_its_round_finishes`, at
  21.28 seconds. The separate browser and read-only GitHub integration
  groups passed together: 45 tests, one platform-only skip, 18.38
  seconds. Every pre-commit check passed. The 18 tests added since
  v9.2.0 are named for behaviour. Local timing does not establish timing
  on the other platforms; CI covers their behaviour.
- **K4.** #809 explains the change, links #808 and answers all seven
  questions. Its reviewer exercised it against the sandbox repository,
  with a workflow applying labels as `github-actions[bot]`, and a second
  commit made held and paused rows say why from the first tick. No
  commit reached main outside a pull request.
- **E1.** The ledger keeps its 11 entries, none added or removed. The
  new conditionals apply stated rules: work starts or resumes only on a
  dispatch label the user applied, read from the latest event that
  applied it; an open assignment's rounds answer its pull request
  whatever its label; and a failed read leaves whether work is paused
  unknown, so its fault still counts.
- **E2, E3, E4.** The nullable-field inventory is a prompt for review,
  not a target count, and it is unchanged. `find_label_applied_by_other`
  answers with none for the user, a finding naming another account, or a
  read failure, so no caller defends a combination the types allow. An
  account that GitHub no longer names is an empty applier, which the
  words call "an unknown account". No domain concept is added: **held**
  is a request status, and a label that someone else applied is a cause
  of a pause. Requests of all three kinds take the check in the tick,
  and conversations and campaigns share it for open work in
  `issue_work.py`. Open assignments take none, because the ontology says
  their pull request governs their rounds whatever their label.

## Semantic Consistency Review

### Scope

The namespace, the whole diff from v9.2.0, the source, templates,
enduring and user documents, the agent guide and the output a user sees
were reviewed. Each change was checked against the other claims about
its concept: a dispatch label and who applied it, the request statuses,
the causes of a pause, the order of checks in a tick, the findings a
request row holds and the words the status views show. No claim that
nobody checks who labelled an issue, or that the question is open,
remains. Formatting and design preferences are excluded.

### Summary

Six disagreements were found. Five were corrected in this preparation,
and one is accepted.

### Vocabulary findings

#### 1. When a conversation or a campaign request starts

**Claim A** — `docs/ontology.md` · "Starting an issue conversation"

> A conversation request starts a conversation only when its issue
> carries no other configured conversation label and has at least one
> eligible comment.

**Claim B** — `docs/ontology.md` · requests

> Any other request is **held** while an account other than the
> signed-in one applied its label

**How they differ:** The start rules stated complete conditions, the
campaign's alike, but a held request starts nothing. Both now require
that the signed-in account applied the label.

#### 2. What the configure guide says starts and pauses work

**Claim A** — `docs/configure.md` · "Label an issue"

> carries exactly one configured assignment label, which you applied
> yourself

**Claim B** — the same section, of conversations and campaigns

> carries exactly one configured conversation label

**How they differ:** Only the assignment condition named who applied the
label, and the causes of a conversation's pause left out a label that
another account applied. All three now say so.

#### 3. Whether a request "shows as held"

**Claim A** — `docs/configure.md`, `docs/changelog.md` and
`docs/stories.md`

> the status report shows its request as held

**Claim B** — `src/dreamcatcher/status/findings.py` ·
`describe_label_applier`

> label applied by {applier}: remove and re-add it yourself

**How they differ:** The row shows the reason, not the word. Accepted:
the documents name each request status by the ontology's word, and the
idle and routing-conflict rows likewise show only their reasons.

### Symbol-contract findings

#### 4. What pauses open work

**Claim A** — `docs/architecture.md` · "Scheduling", and the
`issue_work.py` module docstring

> the issue's labels and assignee decide whether it is paused

**Claim B** — `src/dreamcatcher/scheduler/issue_work.py` ·
`inspect_open_issue_work`, which also pauses work on
`find_label_applied_by_other` once nothing else pauses it and no round
runs.

**How they differ:** The architecture, its conversation and campaign
paragraphs, the module docstring and `PauseCause` now name who applied
the label as a further cause, read last and not while a round runs.

#### 5. What a request row holds

**Claim A** — `docs/architecture.md` · "Scheduling"

> for a conversation or campaign paused for any other reason, the cause;

**Claim B** — `src/dreamcatcher/scheduler/models.py` · `RequestFinding`,
which includes `LabelAppliedByOtherFinding(applier)`.

**How they differ:** The list had no entry for the account that applied
a label. It now has one, for a request and for open work.

#### 6. What the changelog says the upgrade changes

**Claim A** — `docs/changelog.md` · v9.3.0

> Work starts, and a paused conversation or campaign resumes, only on a
> dispatch label that the signed-in user applied themselves.

**Claim B** — `src/dreamcatcher/scheduler/issue_work.py` ·
`inspect_open_issue_work`, which pauses any open, unpaused conversation
or campaign whose label someone else applied.

**How they differ:** After the upgrade, a conversation or campaign that
a colleague's label started before v9.3.0 pauses. The entry now says so.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- AST inventories over `src` count public definitions without direct
  named importers and class fields whose own annotation admits `None`.
  Package exports and module-object callers are reviewed separately. The
  same inventories over v9.2.0 give the changes since then.
- The namespace and stubs guide targeted body reads and the diff from
  v9.2.0. The docs map guides the documentation review.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the tracker triage.
