# Discuss an issue

An issue conversation lets an agent investigate the current code and
post an answer on the issue without turning the question into an
implementation assignment. Use it for questions such as where behavior
comes from, whether a reported problem can be reproduced, or how a
possible change might fit.

You need a configured conversation route and a running daemon. The
`dreamcatcher.toml` that `dreamcatcher init` writes routes the
`dream:scout` label to the `dream:scout` skill from
[dream](https://alimanfoo.github.io/dream/). That skill checks each
claim against the code, and cites the code it relies on.
[Configure labels and harnesses](configure.md) shows how to write a
route of your own.

## Ask the first question

On GitHub:

1. Keep the issue open.
2. Assign it to the account authenticated through `gh`.
3. Add exactly one configured conversation label, such as `dream:scout`.
4. Post the question as an issue comment from that same account.

The title and issue body provide context, but they do not start a
conversation on their own. A comment is the request to answer. Comments
from other accounts are not given to the agent as questions.

At its next update, _dreamcatcher_ asks the configured harness to
examine current `origin/main` and publishes the successful final answer
as a marked issue comment. Its progress and tool activity remain in the
local feed rather than becoming partial GitHub replies.

Monitor it on the web home page or in the terminal:

```sh
dreamcatcher view GH123
dreamcatcher feed GH123
```

## Continue the discussion

Post another issue comment from the authenticated account.
_dreamcatcher_ resumes the same harness session with the new comments,
so a follow-up can refer to the earlier answer while examining the
latest `origin/main`.

The agent may read source, run reproductions and, when your question
asks for it, make suitable issue changes such as filing a follow-up
issue. An issue conversation investigates; it does not implement project
changes or create and update a pull request. To request implementation,
prepare an assignment instead.

## Pause, resume or end a conversation

Each conversation belongs to the label that started it. _dreamcatcher_
checks its issue at every update, including while a round is running.
Removing that label, adding a second configured conversation label, or
removing the authenticated account as assignee pauses the conversation:
no new round starts, including one that would retry an errored round. A
round already running may finish and publish its answer.

Undo the change to resume the conversation. It continues in the same
harness session, and comments posted while it was paused are given to
it. It keeps its original recipe even if its route is removed from
`dreamcatcher.toml`.

Closing the issue ends the conversation after any running round
finishes, and the web home page lists it with your other ended work.
_dreamcatcher_ then removes its worktree and keeps its record. If the
issue is reopened with its label, a new conversation starts and is given
every comment you have posted on the issue.

Taking one conversation label off and putting another on pauses the
first conversation and starts a new one under the new label, with a
session of its own. The new conversation is given every comment you have
posted on the issue. Each conversation keeps its own agent work
identifier. With more than one piece of agent work at the issue,
`dreamcatcher view GH123` prints a command for each piece, with the
identifier that selects it, and giving one of those identifiers in place
of `GH123` shows that one.

To stop just the round that is running, follow
[Stop and recover work](stop-and-recover.md).
