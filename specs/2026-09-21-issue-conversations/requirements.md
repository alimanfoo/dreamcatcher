# Requirements: issue conversations

## What do I want to be able to do?

I want to talk to an agent about an issue through comments on that issue, like
asking a maintainer who knows the code. I want help understanding an issue,
exploring a partial idea, checking whether a bug is real, and deciding whether
anything needs doing.

## What's wrong or missing today?

Sometimes I have questions before I am ready to assign an issue for
implementation. Sometimes another agent raised the issue in a session that is
long gone, and I need someone to explain or investigate it. I want those
questions and answers to stay with the issue.

## What has to be true of anything I'd accept?

I invite a conversation partner by adding a conversation label and assigning the
issue to myself. This starts a session dedicated to that issue, with a
conversation contract that does not ask it to implement anything or open a pull
request.

Only my comments are passed to the agent. Comments from anyone else are filtered
out before the agent sees them, including as context, to reduce the risk of
prompt injection. This applies to both existing comments and new comments. The
agent answers my unanswered questions, including those I posted before adding
the label. Later rounds respond to newly posted comments, not edits to comments
already delivered. Comments posted while the conversation was inactive can be
picked up when it becomes eligible again.

My questions and its replies are comments on the same issue. Dreamcatcher
supplies the comments and posts the agent's final answer; the agent does not
fetch comments or post replies itself. Each round handles a batch of comments
and returns one reply, or indicates that no reply is needed. Keep replies
simple: address the questions together, and quote a question when that helps
make the answer clear.

I can see issue conversations in `dreamcatcher status`, inspect one with
`dreamcatcher conversation GH123`, and view its live feed to follow the agent's
work and diagnose problems. The web UI provides the same visibility through its
overview and a conversation page containing the details and live feed. Both
presentation layers must be available from the first usable delivery, not added
as finishing touches, and stay current as the capability grows.

It can read code, inspect Git history and diffs, run code, and try to reproduce
bugs. It must not edit source code, perform Git operations that change anything,
create branches or commits, push, or open a pull request. Its job is answering
and investigating, never implementation.

Each new batch should answer against current main. Keep that revision unchanged
during the round and any recovery of interrupted or failed work. The agent
should check earlier findings again where relevant and explain when changes to
the code affect an earlier answer. I do not need it pinned to the code from when
the conversation began.

Dreamcatcher watches for comments and takes new batches only while the issue is
open, has the conversation label, and is assigned to me. Closing the issue,
removing the label, or unassigning me stops Dreamcatcher watching it for
comments. An already-started round can continue, recover, and post its answer.
Keep the saved session so the conversation can resume if the issue becomes
eligible again, without polling comments on ineligible issues.

Conversation and implementation are independent. A conversation partner does not
claim the issue or prevent an implementation assignment. An implementation
assignment, an open pull request, or an unresolved dependency does not prevent
conversation. The conversation partner does not need to manage or coordinate
with the implementation agent.

## What limits this?

An issue conversation needs a simpler skill contract than an implementation
assignment. It must let the agent investigate without authorizing
implementation. Use practical harness permissions to reinforce that contract,
without requiring a new cross-platform isolation system or a hard security
guarantee.

## How will I know it worked?

I can post a question, add the label and assign myself, and get an informed
answer on the issue. I can ask follow-up questions, including about issues
raised by an agent that is no longer around. The answers help me decide whether
the issue needs work, without starting implementation.

## What's still open?

Nothing remains unsettled from this discussion. The accompanying design
describes code freshness, recovery, delivery, and the investigation boundary.
