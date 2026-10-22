# Roadmap for campaigns

Every session implementing a stage must correct the specifications as
details change and say on its pull request what it corrected. Each stage
must also update the enduring stories, ontology and architecture
wherever its changes affect them, in the same pull request. The final
consistency review does not defer this duty. A session may change how it
delivers a stage when earlier work or implementation discoveries justify
that change. It must raise changes to the stages, boundaries, order or
dependencies with the user.

The supervisor runs each stage's live acceptance exercise in the private
`alimanfoo/dreamcatcher-sandbox` repository before the stage merges. A
session implementing a stage maintains its automated coverage and leaves
the live exercise to the supervisor: it files no test issues in this
repository and launches no live harness runs. Each stage's exercise and
its success criteria stay as written.

## Stage 1: Start and end a campaign

Add the campaign kind, configurable campaign routes and state format 7.
Carry one initial campaign round through discovery, the shared runner,
detached workspace preparation and both harnesses. The configured prompt
acknowledges the parent issue directly; its final output stays in the
feed. Close the campaign after the parent closes and any running round
finishes.

Extend the existing config, work records, scheduler, prompts, harness
adapters, commands and status paths. Add the campaign module and
inspector described in the design. Provide a Campaigns tab with basic
lead cards, detail and feed access, and ended summaries. Include fair
three-kind scheduling, capacity, fault/cooldown, stop and retry support.
Retain shared recovery safeguards for an unfinished initial round. Apply
the design's eligibility rules before launch; do not create a second
campaign while its first round is waiting.

Add the campaign contract and the harness permissions needed by that
contract. Document the new format and leave v6 state untouched, without
migration. Keep contract version 1. Use an explicitly configured
acknowledgement prompt for now; the published skill and default setup
recipes arrive in stage 7.

The acceptance exercise labels a parent, observes one acknowledgement
and its feed, leaves it unchanged through further updates, then closes
it and observes the ending. Run it with both harnesses. Automated tests
cover routing, shared runner safeguards, fairness and format isolation.
Run the repository's tests and checks, and update affected documentation
and view goldens.

Defer parent-comment continuation, child observations, child
notifications and coordination decisions.

## Stage 2: Continue the lead through parent comments

Build on the campaign execution path to resume the same session for
eligible parent comments. Add the campaign input reader and comment
position, preserving the position in every delivered input. Refresh the
detached workspace before each round. Implement the design's
pause/resume, stopped-round delivery and interrupted-round recovery
rules through the existing runner and relay.

Most changes belong in the campaign module, campaign inspector and
prompt composition. The acknowledgement prompt becomes a simple
conversational stub. It publishes its replies itself, with the agent
marker; the runner does not publish its final answer.

The acceptance exercise exchanges messages, removes the campaign label,
posts while paused and restores the label. The same session answers the
waiting comment. Stop a round, give fresh direction, and confirm
continuation. Tests also cover unassignment and conflicting labels,
closure during a round, errored/interrupted input, retry and cooldown.
Confirm session resume and workspace refresh for both harnesses.

Defer child observation and automatic child wake-ups. The stub does not
manage assignments or merge pull requests.

## Stage 3: Observe the campaign's children

Add the paginated sub-issue read and the full current child snapshot
described in the design. Retain the work and ordinary inspection results
from each update, including ended assignments and new requests, then
inspect campaigns. Extend `PullRequestFinding` with the observed head
and running-check fact; reuse its merge status. Do not make duplicate
child pull-request reads.

Supply the snapshot and the daemon's active assignment routes in lead
input. Record current campaign observations for status, including while
the lead is paused. Show the closed/total count and child links on
active campaign cards. Include children without assignments. Report
failed observations as unknown and withhold lead rounds that would
receive an incomplete picture.

This stage extends `github.py`, scheduler observations and inspection
order, campaign input, status and the basic campaign view. It needs
stages 1 and 2's execution and input handling, but does not yet compare
snapshots to wake leads.

The acceptance exercise adds and removes children, starts an assignment
and closes a child while the lead is paused. Counts and links follow
GitHub. A parent comment after resuming gives the lead the current
picture. Tests cover pagination, assignment replacement, ended and
faulted work, work running or due, and failed reads. Child changes alone
start no lead round yet.

Defer notification filtering and expandable assignment cards.

## Stage 4: Wake a stub lead for actionable child changes

Compare the current snapshot with the newest delivered lead input and
apply the design's notification taxonomy and rules. Give each launched
round the full picture and the highlighted reasons for waking. Keep the
comparison in the campaign module and launch decisions in its inspector.
Recompute while capacity is unavailable; introduce no event queue or
per-child history.

Use an ordinary configured stub prompt that prints its supplied changes
to the feed and ends without altering GitHub. No new harness or
production simulation mode is needed. The stage depends on stage 3's
observations and stage 2's delivery and recovery rules.

The acceptance exercise drives a child through handback, checks
finishing later, becoming mergeable, and ending. Each relevant change
wakes the stub once after the child settles. Starting work, ongoing
checks and unrelated changes on main leave it quiet. Add a child while
another is working and confirm that membership still wakes the lead.

Automated tests cover every notification and quiet case, batched
changes, busy-to-settled transitions, replacement assignments, changes
during a lead round, capacity delays, parent comments combined with
child changes, stopped and unfinished lead inputs, failed reads, fault
and cancellation. Include a transition into the design's mergeable set
with no change to the head or checks, quiet transitions within that set,
and a failing check aggregate whose last running check later finishes.
Confirm recovery resumes the existing session without advancing delivery
for an unfinished input. Use the design's worked sequences as test
cases, including changes arriving between an interrupted round and its
recovery. Drive GitHub actions by hand or through test fixtures in this
stage; the stub only displays its input.

Defer review and merge judgment to the real lead skill.

## Stage 5: Expand child assignment cards within campaigns

Replace the basic child links with the design's expandable child
overview. Reuse assignment summaries and request statuses, including
children with no assignment or dispatch request. Keep assignments in
their own tab as well. Give each appearance a unique HTML identifier,
keep child output separate from lead output, and preserve expansion
during refresh. Ended campaigns retain only their summary and parent
link.

This stage changes status/view composition, templates and refresh
handling. It requires stage 3's observations; stage 4's notifications
are not a technical dependency.

The acceptance exercise expands a campaign containing unstarted, running
and ended child assignments. Observe live status and output in both
tabs, preserve the expansion across refresh, then close the parent and
verify the simpler ended view. Cover these interactions in browser
tests, regenerate affected goldens and inspect the rendered page.

Defer agent coordination decisions; this stage changes presentation.

## Stage 6: Coordinate a campaign with a project-local lead skill

Add a prototype lead skill in dreamcatcher using the repository's
project-local skill layout for both harnesses. It implements the review
and coordination responsibilities in the requirements and design,
including route selection, child feedback, proof execution,
specification corrections, downstream issue updates and merges. Parent
decisions, fault investigation and cancellation follow the agreed
boundaries. The lead never retries a child assignment or closes the
parent.

Exercise the actual campaign prompt and unattended harness permissions.
Child PR feedback must reach the ordinary assignment relay without the
agent marker; other posts retain it. The lead ends its turn while
waiting and avoids routine parent action logs and repeated checks of
unrelated main changes.

This stage requires stage 4's notification delivery. The child cards
help the user observe it but do not control the lead. The prototype must
be committed where detached worktrees can read it. Start fresh
acceptance campaigns when switching from the stub, since saved work
retains its instructions and session.

The acceptance exercise runs a small two-stage dependency chain in a
disposable repository carrying the prototype. Include a deliberately
incomplete proof so the lead requests a correction, receives the child's
response, verifies the result and merges. The next stage then starts
without parent nudges. Verify that a required plan decision reaches the
parent and stops merges until the user answers. Exercise both harnesses
and confirm user-selected routes are preserved. Tests cover the prompt,
publication and permission contracts; the live exercise establishes the
agent's review and merge behaviour.

Defer publishing the skill in dream and switching default setup to it.
Work in dream is an external dependency, not a stage in this repository.

## Stage 7: Use the published lead skill

This stage is blocked until a compatible `dream:lead` skill is published
in dream. Switch default campaign recipes and setup to that skill for
both harnesses, using the capable defaults specified in the design.
Remove the project-local prototype and update configuration and skill
guidance.

The acceptance exercise starts from a clean installation without the
local prototype, runs setup and carries a small campaign through the
published skill. Verify both default recipes and test
setup/configuration changes.

Do not include release preparation, release measurement or publication.
The state-format and compatibility changes belong with the
implementation that introduces them.

## Stage 8: Review and resolve semantic inconsistencies

Run `uncoded-consistency-review` on the resulting codebase. Assess each
finding against its evidence, the enduring documents and the campaign
specifications. Resolve confirmed inconsistencies on their merits in
code or documentation; do not mechanically make every claim agree with
whichever one was found first. Record a reasoned disposition for every
finding on the stage's pull request.

This stage follows the completed integration so the review includes the
final names and contracts. It does not replace each earlier stage's
responsibility to keep the enduring documents true.

The proof is the review report and the resolution of its findings. Check
the affected claims again after fixes, run the relevant behavioural
exercises for any changed behaviour, and pass the tests and checks. A
review with no supported findings is a valid result.

Exclude the rest of release preparation. Changes to agreed campaign
behaviour or roadmap boundaries still require the user's decision.
