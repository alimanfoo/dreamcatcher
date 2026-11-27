# About dreamcatcher

dreamcatcher lets you hand work on a GitHub repository to coding agents.
You can ask for work by putting a label on an issue, and dreamcatcher
will start an agent on it in the background. You can then work with the
agent on GitHub, much as you would with a colleague: it will post on the
issue or its pull request, and you can reply there.

dreamcatcher works for you, the **user**: the person whose account `gh`
is signed in to. Agents will post on GitHub from your account too, but
each post carries the hidden marker `<!-- dreamcatcher -->`, so
dreamcatcher can tell them apart from yours. A visible footer such as
"written by an agent" isn't that marker. Any other comment or label from
your account counts as yours, including one that an agent you work with
outside dreamcatcher made for you.

There are three kinds of agent work you can ask for:

- An **agent assignment**, where an agent will implement an issue and
  take it to a pull request that is ready for you to review. The agent
  will answer your feedback, try to fix failing checks, and merge the
  default branch when the assignment's branch conflicts with it, until
  you merge or close the pull request.
- A **campaign**, where an agent, the **lead**, will take on a parent
  issue whose work is planned as sub-issues. The lead will label each
  sub-issue for an assignment and merge its pull request into the
  campaign branch. You review and merge the campaign's own pull request
  into the default branch.
- An **issue conversation**, where an agent will answer your comments on
  an issue without changing any code.

## Setting up an instance

Each repository you use dreamcatcher with has its own **dreamcatcher
instance**: the configuration and state that dreamcatcher keeps for you
in the repository's main checkout. Colleagues who use dreamcatcher on
the same repository can each run their own instance on their own
computer. An instance will only look at issues assigned to its own user,
so they won't pick up each other's work.

dreamcatcher works from the repository's default branch, whatever that
branch is called. It follows a rename of the default branch on its next
fetch.

The configuration lives in `dreamcatcher.toml` at the root of the main
checkout. If it doesn't exist yet, you can create a default one with
`dreamcatcher init`. `init` will also check that `gh`, Git and an agent
harness, Claude Code or Codex, are ready, install the dream plugin,
which provides the skills the agents run, and create the configuration's
dispatch labels on GitHub. You can run it again at any time: it will
never change an existing `dreamcatcher.toml` or label.

Agents run in your own agent harness, so your harness's settings,
permission rules and plugins apply to them as they do to you. On top of
those, so that an agent can work unattended, dreamcatcher runs Claude
Code in its auto permission mode and Codex in its sandbox with network
access and its automatic reviewer, and allows the Git and GitHub
commands that the agent needs, such as committing, pushing and posting
on its issue or pull request. A conversation's agent is allowed less,
because it doesn't change code.

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
and `--max-agents` lets it run more. Every round takes one of those
agent slots while it runs, a campaign lead's included. Nothing will
happen while the daemon is stopped, and the work will pick up again when
you start it.

You can stop the daemon with Ctrl-C, or by sending its process a
termination signal with `kill`; `dreamcatcher status` will show whether
a daemon is running, and its process ID. A round that is still running
will be interrupted, and the next daemon run will give it the same input
again. If the daemon crashes or is killed outright, the next daemon run
will end any round it left running and give that round's input again.
The daemon writes its log to standard output, so to keep it running
after you close the terminal, you can start it with `nohup` and send its
output to a file. After you upgrade dreamcatcher, restart the daemon,
because a running daemon keeps the code it started with. A dream plugin
upgrade takes effect from the next round.

## Asking for work

Each **dispatch route** in `dreamcatcher.toml` ties one **dispatch
label** to one kind of agent work, and says how each agent harness
should start it: the prompt, usually a dream skill, and the model and
effort.

To ask for work, you can assign the issue to yourself and put one of the
dispatch labels on it. dreamcatcher will only look at open issues
assigned to you. Each application of an assignment or campaign label
makes one **request**. A conversation label acts as a switch. An
available request can start at the next update with a free agent slot.

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
- An assignment or campaign request is held while an open pull request
  **claims** the issue, for example with `Closes #123` in its
  description.
- When earlier work has used an assignment or campaign label's request,
  remove and re-add the label to ask for another attempt.

Once an assignment or campaign starts, it continues through its pull
request even if the issue's labels, assignee or blockers change. If you
reapply a label while work is open, that later request can start after
the work ends. To **pause** a conversation, remove its label or unassign
its issue. Put it back yourself to resume the same harness session.

## Agent assignments

When an assignment starts, dreamcatcher will create a worktree and a
branch for it, open a draft pull request, and start the agent with the
route's prompt, which points it at the issue. The agent will read the
issue and its comments as they stand at that moment. After that, the
pull request is the assignment's **channel**, where you and the agent
talk: later edits and comments on the issue won't reach the agent, so
any further guidance needs to go on the pull request.

The worktree is under `.dreamcatcher/` in your main checkout. It starts
with the files committed to the assignment's base branch, usually the
default branch. While the assignment is open, the worktree and its
branch belong to the agent. Ask for changes on the pull request.

The agent will work until it has nothing left to do, then mark the pull
request ready for review. If it needs a decision from you first, it will
ask on the pull request and leave it as a draft.

You can give feedback on the pull request in comments, inline comments,
or reviews that only comment. GitHub won't let you approve your own pull
request or request changes on it, and every pull request is opened from
your account. At the next update the agent will be given everything you
have posted since its last round, in a new round that resumes the same
harness session. Anything you post while a round is running will wait
for the round after. Posts from other accounts won't be passed on, so if
you want the agent to act on a colleague's review, you need to repeat
the points yourself.

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
round to wrap up at the next update, and may file issues for work it
left out. The assignment will then be complete. To ask for another
assignment on an issue that stays open, remove and re-add its label.

## Campaigns

Plan the work as sub-issues of an open parent issue. Record any
dependencies as blocked-by links. Assign the parent to yourself and
apply a campaign label. dreamcatcher creates the campaign branch from
the default branch, opens a draft pull request into the default branch
and starts the lead in its own worktree.

With the default route, the lead dispatches sub-issue assignments,
reviews their pull requests and gives their agents feedback. It merges
those pull requests into the campaign branch, and dreamcatcher closes
each sub-issue during the assignment's wrap-up. The campaign branch must
allow merges without an approving review, because the lead and the
sub-issue assignments all act under your account. Your repository
determines which checks run on those pull requests.

The campaign's pull request is the lead's channel. The lead asks and
answers there, and can run again when you post or a sub-issue changes in
a way it needs to hear of. When it judges every sub-issue done, it can
review and fix the whole change before marking the pull request ready
for review. Once ready, the pull request gets the same help with failing
checks and an out-of-date branch as an assignment. You can add
sub-issues while the campaign is open, including during review.

Merge the campaign's pull request when you're satisfied. GitHub closes
the parent. A merge or closure of the pull request calls for the lead's
wrap-up round. To take over before then, cancel the campaign and
continue with its pull request, branch and worktree.

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
  the reason. It shows what the last update found, not GitHub as it is
  now.
- `dreamcatcher web` lets you see the same in a browser.
  `dreamcatcher run` already serves and opens this web view unless you
  give it `--noweb`, so you rarely need `web` on its own.
- `dreamcatcher view` lets you see one piece of agent work in detail.
- `dreamcatcher feed` lets you see what an agent has done and said,
  round by round.
- `dreamcatcher retry` lets you get work going again after a **fault**.
  Work is in fault when two rounds in a row have errored, and it won't
  start another round until you fix the cause and retry.
- `dreamcatcher stop` lets you stop a running round, not the daemon, for
  example when an agent is heading the wrong way. The agent will then
  wait, you can tell it what to do instead on GitHub, and its next round
  will be told that it was stopped.
- `dreamcatcher cancel` lets you end an assignment or campaign to finish
  its pull request by hand. The pull request, worktree and branch stay
  available. While the pull request is open, it still claims the issue.
