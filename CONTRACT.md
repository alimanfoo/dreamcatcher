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
Each such round resumes the harness where the last one left off, and its prompt
says why the agent was woken. A dispatchable skill must handle both prompts.

The first says that the previous round did not finish, because that round was
killed with the dreamcatcher process that started it, or failed on its own. The
skill must carry the work on from where it stopped.

The second names a JSON file that holds what the pull request is now, and what
the user has said on it. The skill must read `state` before anything else.
`MERGED` or `CLOSED` means that the pull request is finished, and the skill
should wind the work up. Otherwise `posts` holds what the user newly said,
oldest first, and the skill must act on all of it and reply on the pull request.
dreamcatcher counts a post as delivered once the round starts, so it never sends
that post again.
