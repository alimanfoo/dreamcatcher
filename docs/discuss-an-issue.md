# Discuss an issue

An issue conversation lets an agent investigate the current code and post an
answer on the issue without turning the question into an implementation
assignment. Use it for questions such as where behavior comes from, whether a
reported problem can be reproduced, or how a possible change might fit.

You need a configured conversation route and a running daemon.
[Configure labels and harnesses](configure.md) shows a minimal route.

## Ask the first question

On GitHub:

1. Keep the issue open.
2. Assign it to the account authenticated through `gh`.
3. Add exactly one configured conversation label.
4. Post the question as an issue comment from that same account.

The title and issue body provide context, but they do not start a conversation
on their own. A comment is the request to answer. Comments from other accounts
are not delivered as user questions.

At its next update while the issue is eligible, Dreamcatcher asks the configured
harness to examine current `origin/main` and publishes the successful final
answer as a marked issue comment. Its progress and tool activity remain in the
local feed rather than becoming partial GitHub replies.

Monitor it in the dashboard or terminal:

```sh
dreamcatcher conversation GH123
dreamcatcher feed GH123 --conversation
```

## Continue the discussion

Post another issue comment from the authenticated account. Dreamcatcher resumes
the same harness session with the new comments, so a follow-up can refer to the
earlier answer while examining the latest `origin/main`.

The agent may read source, run reproductions and, when your question asks for
it, make suitable issue changes such as filing a follow-up issue. An issue
conversation investigates; it does not implement project changes or create and
update a pull request. To request implementation, prepare an assignment instead.

## Pause or resume eligibility

Conversation eligibility is checked continuously. Closing the issue, removing
its matching label, adding a second configured conversation label, or removing
the authenticated account as assignee prevents new comment batches and automatic
recovery. A round already running may finish and publish its answer.

The current configuration also matters. Removing the issue's only matching
conversation route pauses it after the daemon restarts. A saved conversation
keeps its original recipe and session even if a different configured label later
makes it eligible again.

Dreamcatcher keeps the saved conversation. If the issue later becomes eligible
again, comments posted while it was paused can be delivered and the saved
session can continue. To stop just the round that is running, follow
[Stop and recover work](stop-and-recover.md).
