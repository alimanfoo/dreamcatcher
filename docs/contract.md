# Agent-facing contract

Contract version **1** covers assignments, campaigns and issue
conversations. See the
[compatibility policy](compatibility.md#agent-contract) for what this
version promises and when it changes.

This page says what a skill that _dreamcatcher_ runs must say, and must
not say. _dreamcatcher_'s own prompt tells the agent everything else.

## Assignment skill contract

An assignment skill must:

- accept an issue number in the form `GH123`, and take implementing that
  issue as its job;
- tell the agent to adopt the current branch, its worktree and the draft
  pull request already open on it, rather than open another;
- tell the agent to post anything it has to tell the user on the pull
  request, because its final output is not published;
- tell the agent to mark the pull request ready when the implementation
  is ready for review;
- tell the agent to keep the pull request's `Closes #123` link when it
  replaces the description;
- tell the agent what to do with the user's feedback on the pull
  request, such as a requested change or a question;
- tell the agent what to do once the pull request is merged, and once it
  is closed;
- tell the agent to end its turn once it has nothing left to do.

An assignment skill must not tell the agent to run anything that waits
for a person, such as a command that asks to be approved, an editor or a
prompt for input.

## Campaign skill contract

A campaign skill must:

- accept a parent issue's number in the form `GH123`;
- tell the lead to start a sub-issue's assignment by assigning the
  sub-issue to the signed-in account and giving it an assignment label;
- tell the lead what to do with the user's comments on the parent issue;
- tell the lead what to do when a sub-issue changes, such as when its
  pull request is ready for review or its checks fail.

A campaign skill must not tell the lead to:

- edit project source, commit, push or open a pull request from its
  worktree;
- close the parent issue or change its assignees or labels;
- run anything that waits for a person.

## Conversation skill contract

A conversation skill must accept an issue number in the form `GH123`,
and take answering the user's questions on that issue as the agent's
job.

A conversation skill must not tell the agent to:

- implement a change, edit project source or mutate Git, such as by
  creating a branch, committing or pushing;
- open or change a pull request;
- close the issue or change its assignees or labels;
- fetch the issue's comments itself;
- post its answer itself, or contact the user elsewhere.
