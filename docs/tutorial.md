# From issue to pull request

This tutorial sends one small GitHub issue to Claude Code with the `dream:smith`
assignment skill. At the end, the agent's implementation is on a pull request
that is ready for you to review.

Use a repository where you are comfortable letting an agent create a branch,
commit and push changes, and update a pull request.

## 1. Install the tools

You need:

- [Git](https://git-scm.com/downloads);
- [uv](https://docs.astral.sh/uv/getting-started/installation/);
- [GitHub CLI](https://cli.github.com/), version 2.94.0 or later for the `dream`
  skills; and
- a [Claude Code](https://code.claude.com/docs/en/quickstart) account and setup
  that supports auto permission mode.

If you are upgrading an older installation, read
[Compatibility and upgrades](compatibility.md) before replacing it. For a first
installation, run this command unless you have already run it:

```sh
uv tool install git+https://github.com/alimanfoo/dreamcatcher
```

Then make the command available in your shell:

```sh
uv tool update-shell
```

Open a new terminal if `uv tool update-shell` asks you to, then check the
commands are available:

```sh
dreamcatcher --version
gh --version
claude --version
```

This installs the current development version of _dreamcatcher_ from GitHub.

## 2. Sign in to GitHub and Claude

_dreamcatcher_ acts as the account that `gh` is signed in as. For this
walkthrough, use HTTPS for Git too:

```sh
gh auth login --git-protocol https
gh auth setup-git
gh auth status
```

The account needs permission to push branches to the repository. Later, assign
the issue to this same account; _dreamcatcher_ will ignore an issue assigned
only to somebody else.

Start Claude Code in auto permission mode, and follow the browser sign-in if
Claude asks:

```sh
claude --permission-mode auto
```

Reaching the Claude prompt confirms that this installation and account can start
the mode _dreamcatcher_ uses. Leave Claude with `/exit`.

## 3. Prepare the repository

Use the main checkout of an ordinary clone, not a linked Git worktree.
_dreamcatcher_ deliberately refuses to run from a linked worktree because it
creates and manages child worktrees of its own.

```sh
git clone https://github.com/OWNER/REPOSITORY.git
cd REPOSITORY
git switch main
git pull --ff-only origin main
```

Replace `OWNER/REPOSITORY` with your repository.

An assignment sees the files committed on `origin/main`, not uncommitted setup
from your main checkout. Before dispatching, commit and push the project's agent
instructions, dependency manifests, lockfiles and any scripts needed to set up
or test the project. Make those instructions non-interactive: nobody can answer
a prompt that waits inside an autonomous round.

This walkthrough assumes you may push that setup to `main`. If `main` is
protected, land the same files through your repository's normal pull-request
process before continuing.

## 4. Run dreamcatcher init

From the main checkout, run:

```sh
dreamcatcher init
```

`init` checks that `gh` can push to the repository, that Git can commit and that
`origin/main` can be fetched. It writes a default `dreamcatcher.toml`, installs
the [`dream` plugin](https://github.com/alimanfoo/dream) for each harness the
file uses, and creates the labels the file names. It prints one line for each
step. If a step fails, `init` says how to fix it; fix it and run `init` again.
If Codex is installed as well as Claude, the file uses both, so sign in to Codex
too, with `codex login`.

The `dream` plugin is installed at user scope, outside the repository, so its
skills are available in the child Git worktree where an assignment runs. The
plugin provides `dream:smith`, the assignment skill this tutorial uses.

The `dreamcatcher.toml` that `init` writes routes the `dream:smith` and
`dream:less` labels to assignments, and the `dream:scout` label to issue
conversations. If Codex is not installed, the file keeps the Codex recipes as
comments. The label connects a GitHub issue to its route, and `{issue}` in a
prompt becomes the issue number, so issue 123 starts Claude with
`/dream:smith GH123`.

Until `origin/main` holds the file, `init` ends by printing the commands that
commit and push it. Run them, so the assignment worktree contains the file too:

```sh
git add dreamcatcher.toml
git commit -m "Configure dreamcatcher"
git push origin main
```

For other routes or another harness, see
[Configure labels and harnesses](configure.md). The
[configuration reference](configuration-reference.md) lists every setting.

## 5. Prepare a small issue

In GitHub:

1. Open one small, self-contained issue. State the expected result and how to
   check it.
2. Assign it to the account shown by `gh auth status`.
3. Add the `dream:smith` label.

Choose work that can finish in one pull request. Avoid an issue with an open
blocking issue or an existing open pull request linked to it; either condition
keeps a new assignment from starting.

Suppose GitHub gives the issue number 123. The commands below call it `GH123`;
replace that with your own issue number.

## 6. Start dreamcatcher

From the main checkout, start the daemon in its own terminal:

```sh
dreamcatcher run --harness claude --interval 30 --max-agents 1
```

Keep this terminal open. Every 30 seconds _dreamcatcher_ looks for work, with at
most one agent round running at a time. A round is one agent process, from the
moment _dreamcatcher_ starts it until that process exits.

_dreamcatcher_ starts Claude non-interactively in auto permission mode and
allows the selected Git, pull-request and issue commands the assignment needs to
finish the job. The agent can edit files, run tools, commit and push under your
account. These controls are not a security sandbox or a guarantee about what a
plugin will do, so use a repository, plugin and GitHub account you trust.

On dispatch, _dreamcatcher_ fetches `origin/main`, creates a branch and child
worktree, pushes an empty commit, and opens a linked **draft** pull request. The
draft means the assignment has begun; it does not mean the implementation is
ready for review. Claude then works in that child worktree.

## 7. Watch the assignment

In a second terminal, still at the repository root, open the web home page:

```sh
dreamcatcher web
```

Select `GH123` to see its rounds and live feed. The page reads local state, so
it can show activity without publishing the agent's working notes to GitHub. You
can also follow the same feed in a terminal:

```sh
dreamcatcher feed GH123 --assignment
```

If the agent needs a decision, it should ask on the draft pull request. Reply
there using the same GitHub account that `gh` is signed in as. _dreamcatcher_
relays your pull-request comment or review into another round at its next
update.

When the implementation is complete, the assignment skill changes the pull
request from draft to **ready for review**. That is the endpoint of this
tutorial: a normal pull request containing the implementation, checks and the
agent's account of the change.

Continue with [Review an assignment](review-an-assignment.md) to give feedback,
merge it, and let _dreamcatcher_ finish its wrap-up.
