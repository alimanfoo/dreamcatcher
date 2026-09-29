# Design: stop controls

## What we're building

The assignment and issue-conversation pages each offer a stop control while
their latest round is running. The control asks that round to stop promptly
without stopping the daemon or any other agent work.

A stopped round is different from an interrupted or errored round. Dreamcatcher
does not recover it on its own. The assignment waits for a new pull-request
post, and the conversation waits for a new issue comment. That feedback starts a
new round in the same harness session and tells the agent that the user stopped
the previous round.

## How it works

### The web process requests and the round stops

The web server and the daemon remain separate processes. A POST from an
assignment or conversation page writes an empty `stop-request` marker into the
latest round's directory. The round directory makes its target unambiguous even
when newer rounds start later.

Each running round watches its own request path on a daemon thread. The watcher
checks once per second, so the normal scheduler interval does not delay the
stop. When the request appears, the round marks the requested outcome before it
kills the harness process tree. The existing process boundary still owns the
platform-specific kill: the POSIX process group and the Windows Job Object both
stay inside the daemon process that created them.

The watcher exits when the round ends normally. Tests can set a shorter polling
interval without changing the production interval.

### A stopped ending waits for feedback

The round records `stopped` as a terminal outcome with the time at which it
stopped. Interruption remains the outcome for daemon shutdown and persistence
failures, and an error remains the outcome for a failed harness or finisher.
Only interruption and error trigger automatic recovery.

A stopped assignment follows the existing path for a completed round with no new
pull-request posts: it needs user feedback. A stopped conversation follows the
existing path for a completed round with no new issue comments: it is idle. A
stopped round does not count towards the consecutive-error fault rule.

The first new post or comment starts an ordinary feedback round, not a recovery
round. Its prompt begins by saying that the user stopped the previous round and
that the new feedback says what to do instead. Posts or comments that the
stopped round had already received remain delivered because the resumed harness
session already has them in its context.

A stopped conversation publishes no final answer from the stopped round.

### The control is narrow and protected

The stop form appears only while all of these facts hold:

- the daemon is running;
- the latest round is running;
- that agent work has reported a harness session identifier; and
- no stop request already exists for that round.

The session requirement means that the feedback round can resume the same agent
session. A request that races with a round's normal ending is harmless because
its file belongs only to that ended round.

Each POST must carry an `Origin` header that exactly matches the page's own
origin. The existing trusted-host check protects the Host header, and this check
prevents another website from posting to the loopback server through the user's
browser. A missing or different origin is refused.

After an accepted request, the server redirects to the same agent-work page. The
request file then hides the control while the round watcher acts on it.

## What changes

The round document model gains the `stopped` outcome, each round gains one
stop-request marker, and the round runner gains one watcher thread. Scheduling,
status reporting, prompts, the TUI, and the web view use the new outcome
wherever they describe or act on a round ending.

The web server is no longer read-only. Its one write is the stop request,
through the round boundary. It still reads no live object from the daemon,
contacts GitHub for nothing, and works as a status view when the daemon is
absent.

No state-format migration is needed. Existing round records still validate, and
the new request file appears only in a round that receives a stop request.
