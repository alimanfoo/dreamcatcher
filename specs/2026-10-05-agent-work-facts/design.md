# Design: one file for each changing fact of agent work

## What we're building

Several processes record facts about one assignment. The daemon records the pull
request observation and the harness session identifier. The `retry` and `cancel`
commands and the web controls record a retry request or a cancel. Each writer
used to read the whole of `assignment.json`, change one field and write the
whole record back, so a write could erase a field that another writer had
written a moment earlier. A lost cancel reopens the assignment, and the next
post on its pull request then starts a round on a branch that the user has taken
over. A conversation record had the same flaw.

Every writer now records its fact without rewriting anyone else's, so no fact
can be lost this way.

## How it works

### Creation writes the record once

Creation writes `assignment.json` or `conversation.json`, and nothing writes it
again. The record holds only what creation decides: the issue, title, dispatch
label, harness settings and prompt, and for an assignment its branch, worktree
and pull request.

### Each changing fact has a file of its own

Every fact that changes after creation lives in a file of its own in the
directory of the assignment or conversation. A write replaces the file whole,
from what the writer knows, and merges nothing into it.

| File                            | Holds                             | Kept by                    |
| ------------------------------- | --------------------------------- | -------------------------- |
| `pull-request-observation.json` | the latest pull request state     | assignments                |
| `cancel.json`                   | when the user cancelled           | assignments                |
| `harness-session.json`          | the session every round continues | assignments, conversations |
| `retry-request.json`            | when the user last asked to retry | assignments, conversations |

The stop request already worked this way, as a file in the round's directory.

Two writers of one fact are harmless. Two cancels, or two retries, each record a
time the user asked, and the file keeps whichever landed last. An assignment or
conversation runs one round at a time, so its harness session is reported by one
thread at a time: the scheduler as it resumes a session, then the round as its
output reports one. Recording the same session again changes nothing, and a
different session is refused.

### Creation writes the observation first

Assignment setup writes `pull-request-observation.json` before
`assignment.json`. A written record marks the setup complete, so every complete
assignment has an observation, and readers need no case for one without it.

### No two writes share a staging file

`documents.write_text` stages each write in a uniquely named file beside its
target, then moves it into place. Writes used to stage in one fixed name, so two
writes of one document at the same moment could move each other's text, and one
of them failed. One fact can have two writers, so this applies to every write.

### Every assignment has a title

Every state-format-5 assignment is created with its title. The backfill that
recorded a title for older records is removed, and the title is required.

## Why not a lock

A cross-process lock around each read and rewrite would also close the race. It
needs platform-specific locking code or a new dependency, and a timeout for a
holder that never lets go. Every future writer would also have to remember to
take it. Separate files remove the shared document that the lock would guard.

## What changes

State format 5 is unreleased, so it changes in place and keeps its number. A
`.dreamcatcher/v5/` directory written by an earlier development build no longer
reads.

Every reader takes these facts from the assignment or conversation it reads,
rather than from the record. `Conversation._record_lock` is removed, because no
writer rewrites the conversation record any more.
