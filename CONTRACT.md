# Dispatchable skills

dreamcatcher watches a GitHub repository for issues that have been labelled for
implementation by an agent. The repository owner can configure which labels are
recognised by dreamcatcher, which agent harnesses are used to dispatch an agent
(Claude Code or Codex), and which agent skill should be invoked to initiate the
implementation of an issue. This guide describes how to write agent skills that
work well when used together with dreamcatcher. We call this a "dispatchable
skill".

To make this concrete, consider a hypothetical GitHub repository, where the
owner has configured dreamcatcher to look for issues with the "agent" label, and
to launch an agent for each labelled issue using a skill named "smith". For this
to work, the "smith" skill needs to follow this guide.

## Arguments

A dispatchable skill must accept a GitHub issue number as an argument, and it
must recognise that its purpose is to implement the work described in that
issue.

For example, the hypothetical "smith" skill should be able to be invoked with a
prompt like "/smith GH123" and to know its job is then to implement GitHub issue
number 123.

## Branch adoption

Before dreamcatcher dispatches an agent, it fetches origin's main, cuts a branch
from it, and adds a worktree on that branch. The agent runs in that worktree, so
the branch is checked out and the working tree is clean.

A dispatchable skill must instruct the agent to adopt the current branch, work
in the worktree where it is checked out, and open the pull request from that
branch.

## Opening a pull request

A dispatchable skill should open a draft pull request as soon as possible,
before it changes any code. This pull request then provides the primary channel
of communication between the agent and the user.

## Linking the pull request to the issue

The pull request's description must include `closes #123` or an equivalent
keyword, naming the issue given as the skill's argument. GitHub then links the
issue to the pull request, and that link is how dreamcatcher knows somebody is
working on the issue.

## Ending a turn

dreamcatcher runs an agent in rounds, and a round is over when the agent's
process exits. A dispatchable skill must instruct the agent to end its turn once
it has nothing left to do, and to post anything it has to tell the user on the
pull request rather than in its turn output. The harness runs headless, so
nobody reads that output.

A dispatchable skill must not instruct the agent to run anything that waits for
a person, such as a command that asks to be approved, an editor, or a prompt for
input. Nothing answers it, and the round stalls until dreamcatcher stops.

## Resumed rounds

dreamcatcher gives an agent a further round whenever there is more for it to do.
Each such round resumes the assignment's harness session where the last one left
off, so the agent still has what the earlier rounds said in front of it, and
dreamcatcher's prompt says why it was woken.

### A comment or review from the user

dreamcatcher's prompt names a JSON file and asks the agent to read it. `state`
in that file says where the pull request has got to, and `posts` holds every
comment and review the user has left since the last round that was given one,
oldest first.

A dispatchable skill must instruct the agent to read `state` before anything
else, and, when `state` reads `OPEN`, to act on every post and reply on the pull
request. dreamcatcher counts a post as delivered once the round starts, so it
never sends that post again.

### A merged or closed pull request

dreamcatcher gives the agent a last round when the user merges or closes the
pull request, with the same prompt naming the same file. `state` then reads
`MERGED` or `CLOSED`, and `posts` still holds anything the user said before
merging or closing.

A dispatchable skill must instruct the agent to wind the work up when `state`
reads anything but `OPEN`.

### An interrupted round

dreamcatcher's prompt says that the previous round did not finish, because that
round was killed with the dreamcatcher process that started it, or because it
failed on its own.

A dispatchable skill needs nothing of its own here. The resumed agent still has
its own transcript, and dreamcatcher's prompt is enough to carry it on.
