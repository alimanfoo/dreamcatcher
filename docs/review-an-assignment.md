# Review an assignment

Dreamcatcher opens a draft pull request before the assignment's first agent
round. That early draft proves the branch and communication channel exist; it is
not a claim that the implementation is finished. Begin your normal code review
when the assignment skill marks the pull request ready for review.

You need the daemon running for feedback and final wrap-up to reach the agent.
Use the web home page or `dreamcatcher assignment GH123` to confirm which pull
request belongs to the assignment.

## Answer questions and give feedback

Use the pull request as the conversation with the implementation agent. From the
same account that `gh` is authenticated as, you can:

- write a pull-request comment;
- submit a review with a comment or verdict; or
- leave an inline review comment on the diff.

Dreamcatcher collects new feedback in chronological order and relays it into a
later agent round. A submitted approval or request-for-changes verdict is also
relayed even when its review body is empty. Posts by other accounts and posts
marked as the agent's own are not treated as your feedback.

If the agent asks a blocking question while the pull request is still a draft,
reply on that pull request. Do not move the discussion to the issue: assignment
rounds listen to the pull request. The next scheduler update can resume the same
harness session with your answer.

Follow the response locally when useful:

```sh
dreamcatcher feed GH123 --assignment
```

If another decision is needed after the agent responds, add a new pull-request
comment or review for the next exchange.

## Merge or close

Merge the pull request when the change meets your repository's normal review and
check requirements. If the work should not land, close it instead.

Either action asks the agent for one final **wrap-up** round. That round
receives the merged or closed state and any feedback not relayed earlier. Keep
the daemon running until the assignment becomes **complete**: only a successful
wrap-up releases it.

```sh
dreamcatcher assignment GH123
```

A failed or interrupted wrap-up remains available for recovery.
[Stop and recover work](stop-and-recover.md) explains what happens automatically
and when to request a retry.

To finish the pull request by hand instead, cancel the assignment. Dreamcatcher
then runs no further rounds for it, and no wrap-up follows a merge or close.
[Take over an assignment's pull request](stop-and-recover.md#take-over-an-assignments-pull-request)
explains how.

Removing the assignment label is not a way to stop an active assignment; its
saved pull request continues to drive feedback and wrap-up. If you close a pull
request without merging and do not want a new assignment for the issue that's
still open, remove its assignment label before wrap-up completes. Once wrap-up
succeeds, the old assignment no longer claims the issue.
