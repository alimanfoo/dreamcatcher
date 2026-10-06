# Design: issue status

## What we're building

A status report shows an issue that the latest tick observed for one reason: its
assignment setup failed, it has an assignment routing conflict, it is blocked,
or it is available for an assignment. The terminal and the web each worked that
reason out again from the issue observation's facts, and so did the words that
explain it. Status now derives both once, as the issue's **issue status**, and
both presentations show what it derived.

## How it works

### One value, decided in order

An issue status has one of four values. The first that holds decides it:

1. **failed assignment setup**: the latest tick records an assignment setup
   failure for the issue;
2. **assignment routing conflict**: the issue carries more than one assignment
   label;
3. **blocked**: an open issue dependency prevents work from starting; and
4. **available**: the issue is available for an agent assignment.

An observed issue for which none holds has no issue status, and the report
leaves it out. A failed assignment setup comes first because the report shows it
even when another fact decides availability, as the ontology requires.

### The evidence explains the value

An issue status carries the evidence for its value as a list of pieces. It gives
the assignment setup failure, the assignment routing conflict and the blocker,
whichever hold, in that order. An available issue gives the availability
evidence, "available for assignment". A blocker's evidence names the blocking
issues, and it says so, so that the web can link each issue it names.

The terminal shows the evidence as one line. The web shows the same line, with
each blocking issue linked, and uses the value to choose the row's style.

### The report keeps two groups

The report lists the failed assignment setups apart from the other issue
statuses, because both presentations show them as a group of their own. Each
group keeps the scheduler's order.

## Why a new concept

Concept economy (E3) asks whether existing concepts compose to this. They do
not. An issue observation records independent facts, and availability is derived
from them, but availability answers only whether the scheduler may assign the
issue. An issue that is blocked or has an assignment routing conflict is
unavailable, and so is a claimed or closed one, which the report does not show.
A failed assignment setup is not one of the observed facts at all, and the
report shows it whether or not the issue is available. No existing concept says
which of those reasons puts an issue in the report, so each presentation had to
decide it for itself.

## What changes

The ontology defines the issue status beside the issue observation. The status
report holds issue statuses where it held issue observations. An available issue
reads "available for assignment" in both presentations, where it read
"available".
