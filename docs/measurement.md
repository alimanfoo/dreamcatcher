# Measurement

This page holds the latest measurement of _dreamcatcher_ against
[the standard](standard.md). [The release checklist](releasing.md)
replaces it before each major or minor release. Earlier measurements are
in Git history.

Measured on 2026-10-28 at `f0de3f31`, for the v9.5.0 release
preparation. The review covers the 18 pull requests merged since v9.4.0:
the campaign on #827, which carried eleven sub-issues, four standalone
assignments, the maintainer's own label switch and triage-skill change,
and two Dependabot updates. The consistency review and issue triage ran
beside this measurement, in two passes: one over everything merged by
`98d0215f`, whose findings #851 corrected, and one over the three pull
requests merged after it.

## Results

| Criterion                  | Measured                                                                                                                 | Status | Issue |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------ | ----- |
| Cohesive modules           | 0 reviewed modules without one nameable responsibility                                                                   | met    |       |
| Focused functions          | 0 reviewed functions without one nameable job                                                                            | met    |       |
| No unused exports          | 31 public definitions without a direct named importer, one fewer than v9.4.0: `RequestStatusValue` now has an importer   | met    |       |
| One way                    | A card's rows render from one partial on the home page and the work page; the two work-page templates became one         | met    |       |
| No suppressions            | 0 `noqa`, 0 `type: ignore`, 3 platform pragmas                                                                           | met    |       |
| One vocabulary             | 10 disagreements found; 7 corrected by #851 and 3 in this preparation                                                    | met    |       |
| True documents             | Each merged change corrected the documents it moved; the stories, concepts and architecture agree with the code          | met    |       |
| Docs by purpose            | Tutorials, task guides, references and explanations remain separate; "ontology" became [Concepts](concepts.md)           | met    |       |
| Versioned contract         | State format 8 unchanged since v9.0.0; contract remains 1                                                                | met    |       |
| Machine-checked rules      | 11 import-linter contracts and a name check replace the architecture test; invisible characters checked by a pygrep hook | met    |       |
| Fast readable tests        | 42.95 seconds, 1,562 tests passed, 100% statement and branch coverage                                                    | met    |       |
| Current tracker            | 12 open issues triaged; 2 corrected; none ready to close                                                                 | met    |       |
| Reviewed changes           | 16 merged pull requests answer every definition-of-done question; 2 Dependabot updates                                   | met    |       |
| Rules not cases            | 11 ledger entries, unchanged; each new conditional applies a stated rule                                                 | met    |       |
| Invariants by construction | 71 nullable class fields, one fewer than v9.4.0                                                                          | met    |       |
| Few concepts               | One concept added, the card, named for what every view already showed; Blocked and Routing conflict folded into Held     | met    |       |
| Symmetry                   | Every card has the same rows in every view; conversations and campaigns are held as requests are                         | met    |       |

## Deferred work and previous findings

The v9.4.0 measurement left no disagreement open and filed no follow-up.

This interval redesigned what the user sees. Triage settled one layout
for every card (#842, #845): the issue and GitHub's state of what the
card stands for, then the route and _dreamcatcher_'s status, then any
detail or advice, then the agent's latest output. One status, Held, now
covers every request and every open conversation or campaign that the
scheduler holds back, whatever GitHub fact causes it; pausing stays the
user's own act. An ended card is a record of how things stood when the
work ended. #851 named the card, carried the same rows to the work page
and the terminal, and corrected the seven findings of the first review
pass. The feed lost its typing effect (#814) and follows by its scroll
position (#832), and each theme gained a motif that shows the agents at
work (#854).

The engineering checks moved from code to configuration where an
established tool fits: import-linter contracts for the architecture's
import rules (#811), a pygrep hook for invisible characters (#810) and a
CI gate job that branch protection requires in place of 19 named checks
(#805). The keyword-parameters script stays (#812, closed). The standard
names its criteria and definition-of-done questions by title (#813), and
the ontology became Concepts, recording the words each concept replaces
(#817, #806). The default labels name the kind of work they ask for
(#816), and this repository switched to them.

Triage in this interval:

- The second pass read #856, #857 and #860, filed during this interval.
  Each uses the concepts' words, and none's work is done. It retitled
  #850, which said "request rows" for what are now request cards.
- The first pass corrected #492's example record.
- Triage closed #803, #812, #821, #823, #825 and #837, each with its
  reason.
- Open: #32, #492, #762, #844, #847, #848, #850, #852, #856, #857 and
  #860. This preparation closes #834.

## Notes

- **Cohesive modules, Focused functions.** The largest modules are
  `github.py` (931 lines), `agent_rounds.py` (785),
  `status/agent_work.py` (629), `status/report.py` (543),
  `agent_work.py` (508), `scheduler/tick.py` (504) and `web/app.py`
  (455). They retain their boundary's one responsibility.
  `status/report.py` grows by the campaign summary's counts. The longest
  functions are those of v9.4.0, with the same jobs.

  | Function                                      | Lines | Its job                                     |
  | --------------------------------------------- | ----: | ------------------------------------------- |
  | `cli._build_cli_parser`                       |   187 | Define the command-line grammar.            |
  | `DreamcatcherDaemon.run`                      |    83 | Follow the daemon lifecycle.                |
  | `AgentRound.__init__`                         |    82 | Record and start one round.                 |
  | `Scheduler.tick`                              |    81 | Follow the scheduler's update sequence.     |
  | `scheduler.assignments._inspect_pull_request` |    66 | Inspect an assignment's channel.            |
  | `scheduler.campaigns._inspect_lead_input`     |    66 | Decide whether a lead round is due.         |
  | `Scheduler._launch`                           |    61 | Create work and start its round.            |
  | `commands.spawn_command`                      |    52 | Start a child and contain its process tree. |

- **No unused exports, One way.** An AST inventory finds 31 public class
  or function definitions without a direct named import from another
  source module. Review also accounts for imports through module
  objects, package exports, document and view models, callback protocols
  and the console entry point. It establishes no unused public function.
  The card is drawn by one partial, `work-card.html`, for the home page,
  a campaign's sub-issues and the work page, so the three cannot drift.
- **No suppressions, Machine-checked rules.** The three coverage pragmas
  remain at `teardown.py:20`, `teardown.py:110` and `commands.py:270`,
  all platform arms. `tests/test_architecture.py` is gone: 11
  import-linter contracts in `pyproject.toml` and a pygrep hook for the
  names presentation must not use now hold its rules, at commit time.
- **One vocabulary, True documents.** The first review pass, over
  everything merged by `98d0215f`, found seven disagreements, including
  "paused" written where the scheduler holds work back, "card" and "row"
  used for one thing, and the terminal and work page not showing the
  issue's state; #851 corrected all seven. The second pass, over #853,
  #855 and #859, found three, all wording, corrected here: the terminal
  row of a request also gives its label, the work page's card leaves out
  the latest output that its feed shows, and the documentation home
  page's header mock now shows the version beside the pid.
- **Docs by purpose, Versioned contract.** The documentation map retains
  pages by reader purpose. State format 8 holds: the scheduler record
  gains each request's issue state, which an older record never holds,
  so older records still read. The agent contract's version 1 is
  unchanged.
- **Fast readable tests.** The default suite passed with 1,562 tests,
  one platform-only skip, and 100% statement and branch coverage, in
  42.95 seconds. Its slowest test was
  `test_a_closed_parent_ends_the_campaign_once_its_round_finishes`, at
  20.89 seconds. The browser and read-only GitHub integration groups
  passed together: 72 tests, one platform-only skip, 15.69 seconds. The
  integration test that reads this repository's labels now expects
  `agent-assignment`, which `dream:smith` became when the repository
  switched to the new defaults; this preparation corrects it. Every
  pre-commit check passed.
- **Reviewed changes.** The maintainer reviewed each merged pull request
  against its issue, rendering the web changes with the fabricated web
  server in both themes, light and dark, and sent #855 back once, for a
  narrower page, motifs fitted to the margin and Nature's motif
  following the colour scheme. Branch protection on `main` now requires
  "Required checks pass" and `dependency-review`.
- **Rules not cases.** The ledger keeps its 11 entries. The new
  conditionals apply stated rules: a request or open conversation or
  campaign is held while a GitHub fact holds it; a row shows GitHub's
  state only as the latest update read it; and a motif shows one per
  working agent, only where the margin can hold it.
- **Invariants by construction, Few concepts, Symmetry.** The
  nullable-field inventory falls to 71: the two work views became one.
  The card is the one concept added; every view already drew it, and
  naming it freed "request row" to mean only the scheduler's finding.
  Held replaces Blocked and Routing conflict as request statuses, so one
  word means one scheduler state. Conversations, campaigns and requests
  are now held alike, and every view of a card gives its parts in the
  same order.

## Method

- `tools/measure_source.py` supplies physical module and function line
  counts; review assesses responsibility rather than imposing a limit.
- AST inventories over `src` count public definitions without direct
  named importers and class fields whose own annotation admits `None`.
  Package exports and module-object callers are reviewed separately. The
  same inventories over v9.4.0 give the changes since then.
- The namespace and stubs guide targeted body reads and the diff from
  v9.4.0. The docs map guides the documentation review.
- Test results establish local coverage, timing and rendered behaviour.
  PR descriptions establish the definition-of-done record, and current
  issue bodies establish the tracker triage.
