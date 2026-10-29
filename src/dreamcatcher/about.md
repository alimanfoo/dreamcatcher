# About dreamcatcher

dreamcatcher lets you hand work on a GitHub repository to coding agents.
You can ask for work by putting a label on an issue, and dreamcatcher
will start an agent on it in the background. You can then work with the
agent on GitHub, much as you would with a colleague: it will post on the
issue or its pull request, and you can reply there.

dreamcatcher works for you, the **user**: the person whose account `gh`
is signed in to. Agents will post from that account, and dreamcatcher
will treat every other label and post from it as yours.

There are three kinds of agent work you can ask for:

- An **agent assignment**, where an agent will implement an issue and
  take it to a pull request that is ready for you to review. The agent
  will answer your feedback, try to fix failing checks, and merge main
  when the branch conflicts with it, until you merge or close the pull
  request.
- A **campaign**, where an agent, the **lead**, will take on a parent
  issue whose work is planned as sub-issues. The lead will label each
  sub-issue for an assignment, and merge each sub-issue's pull request
  once it is ready for review, its checks pass and it doesn't conflict.
- An **issue conversation**, where an agent will answer your comments on
  an issue without changing any code.

## Setting up an instance

Each repository you use dreamcatcher with has its own **dreamcatcher
instance**: the configuration and state that dreamcatcher keeps for you
in the repository's main checkout. Colleagues who use dreamcatcher on
the same repository can each run their own instance on their own
computer. An instance will only look at issues assigned to its own user,
so they won't pick up each other's work.

The configuration lives in `dreamcatcher.toml` at the root of the main
checkout. If it doesn't exist yet, you can create a default one with
`dreamcatcher init`. `init` will also check that `gh`, Git and an agent
harness, Claude Code or Codex, are ready, install the dream plugin,
which provides the skills the agents run, and create the configuration's
dispatch labels on GitHub. You can run it again at any time: it will
never change an existing `dreamcatcher.toml` or label.

You can start the instance with `dreamcatcher run --harness claude` or
`--harness codex`, from the same checkout. This will start the
**daemon**, a long-running process that manages agent work. Every two
minutes by default, the daemon will carry out an **update**: it will
read your issues and pull requests from GitHub, and start a **round**
for any agent work that has something to do. A round is one headless run
of the agent harness, such as `claude --print` or `codex exec`, with
dreamcatcher's preparation before it and its finishing step after. If a
round errors, dreamcatcher will recover by giving the next round the
same input again. By default the daemon will run one agent at a time,
and `--max-agents` lets it run more. Nothing will happen while the
daemon is stopped, and the work will pick up again when you start it.

$daemon

## Asking for work

Each **dispatch route** in the configuration ties one **dispatch label**
to one kind of agent work, and says how each agent harness should start
it: the prompt, usually a dream skill, and the model and effort.
$configuration

$routes

To ask for work, you can assign the issue to yourself and put one of
these labels on it. dreamcatcher will only look at open issues assigned
to you. Each dispatch label on such an issue is a **request**, and
dreamcatcher will start its work at the next update with a free agent
slot.

A request can also be **held**, and then won't start until whatever
holds it changes:

- If someone else put the label on, the request will be held, so that a
  colleague's label can't start work under your account. You can start
  it by taking the label off and putting it back yourself.
- If the issue has two labels of the same kind, such as two assignment
  labels, that's a **routing conflict**, and neither will start until
  you take one off.
- An assignment or a campaign will wait while its issue is blocked by
  another open issue, through GitHub's issue dependencies, and will
  start by itself once every blocker is closed. You can use this to put
  work in order.
- An assignment will also be held if there is already an open pull
  request **claiming** the issue, for example with `Closes #123` in its
  description, and will start by itself if that pull request closes.

Once an assignment has started, its pull request becomes the only
channel of communication with the assignment's agent, and changing the
issue's labels, assignee or blockers will make no difference to it. A
conversation or a campaign is different: you can **pause** one by taking
its label off or unassigning its issue, and resume it later, in the same
harness session, by putting things back.

## Agent assignments

When an assignment starts, dreamcatcher will create a worktree and a
branch for it, open a draft pull request, and start the agent with the
route's prompt, which points it at the issue. The agent will read the
issue and its comments as they stand at that moment. After that, the
pull request is the assignment's **channel**, where you and the agent
talk: later edits and comments on the issue won't reach the agent, so
any further guidance needs to go on the pull request.

The agent will work until it has nothing left to do, then mark the pull
request ready for review. If it needs a decision from you first, it will
ask on the pull request and leave it as a draft.

You can give feedback on the pull request as you would to anyone, in
comments, reviews or inline comments. At the next update the agent will
be given everything you have posted since its last round, in a new round
that resumes the same harness session. Anything you post while a round
is running will wait for the round after. Posts from other accounts
won't be passed on, so if you want the agent to act on a colleague's
review, you need to repeat the points yourself.

Once the pull request is ready for review, the agent will also look
after it while it waits for you:

- If a check fails, the agent will try to fix it. It will get two
  attempts, and if the build is still red after that, it will wait for
  you to tell it what it's missing.
- If the branch conflicts with its base branch, the agent will merge the
  base branch in. If the repository requires branches to be up to date
  before merging, it will do the same whenever the branch falls behind.

So you don't need to watch the pull request: when you come to review it,
it should merge cleanly, however long it waited.

When the pull request is merged or closed, the agent will have one last
round to wrap up, and may file issues for work it left out. The
assignment will then be complete. If the pull request was closed without
being merged, the issue will stay open and can be given a new
assignment.

## Campaigns

A campaign is for a larger body of planned work. You can write the plan
as a parent issue, with the work in its sub-issues, and put a campaign
label on the parent. dreamcatcher will then start a lead agent on the
parent.

What the lead does is set by its route's prompt. With the default
campaign route, the lead will label the sub-issues for assignments,
review their pull requests and give their agents feedback, and merge
each pull request once it is ready for review, its checks pass and it
doesn't conflict. You don't need to handle the sub-issues yourself. The
lead works from your account, so its labels and feedback will count as
yours. If some sub-issues have to wait for others, you can mark them as
blocked by those, and their assignments will wait.

The parent issue is the campaign's channel. You can comment on it at any
time, and the lead will be given your comments at the next update and
answer there. If the lead meets something it can't decide, it will raise
it on the parent. It will also be woken when a sub-issue changes in a
way it needs to know about, such as an assignment handing its work back,
checks finishing, or a sub-issue closing.

When you're satisfied, you can close the parent issue to end the
campaign; the lead will never close it. The campaign will end once any
round that is still running has finished.

If your repository requires branches to be up to date before merging,
every merge will leave the campaign's other pull requests behind, and
wake each of their agents to merge main and run the checks again. A
merge queue will avoid this, or you can leave that setting off: a pull
request that has only fallen behind will still merge cleanly, and one
that conflicts will still wake its agent.

## Issue conversations

An issue conversation is for questions rather than changes:
investigating a bug, asking about the code, or thinking through a
design. You can put a conversation label on the issue and ask your
question in a comment; the title and body alone won't start it. The
agent will answer in a comment on the issue, and you can keep the
conversation going by replying. Each answer will continue the same
harness session, so the agent will remember what it said. If a comment
needs no reply, it won't post one, and it won't answer comments from
other accounts.

## Commands

You can direct the work on GitHub. The dreamcatcher CLI commands let you
see it from behind the scenes, and step in when something goes wrong. A
command that names one piece of agent work accepts its issue, as
`GH123`, or its agent work identifier, such as
`GH123-20260912-192458-assignment`. The commands that keep showing the
work as it changes will print it once and return when their output is
piped or captured.

- `dreamcatcher status` lets you see the instance, each piece of open
  agent work with its status, and each request that hasn't started, with
  the reason.
- `dreamcatcher web` lets you see the same in a browser.
  `dreamcatcher run` already serves and opens this web view unless you
  give it `--noweb`, so you rarely need `web` on its own.
- `dreamcatcher view` lets you see one piece of agent work in detail.
- `dreamcatcher feed` lets you see what an agent has done and said,
  round by round.
- `dreamcatcher retry` lets you get work going again after a **fault**.
  Work is in fault when two rounds in a row have errored, and it won't
  start another round until you fix the cause and retry.
- `dreamcatcher stop` lets you stop a running round, for example when an
  agent is heading the wrong way. The agent will then wait, you can tell
  it what to do instead on GitHub, and its next round will be told that
  it was stopped.
- `dreamcatcher cancel` lets you end an assignment for good, to finish
  its pull request by hand. The pull request, worktree and branch will
  be left for you, and while that pull request is open it will still
  claim the issue.
