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
installation, run this command unless you already ran it from the README:

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

This installs the current development version of Dreamcatcher from GitHub.

## 2. Sign in to GitHub

Dreamcatcher acts as the account that `gh` is signed in as. For this
walkthrough, use HTTPS for Git too:

```sh
gh auth login --git-protocol https
gh auth setup-git
gh auth status
```

The account needs permission to read issues and pull requests and to push
branches to the repository. Later, assign the issue to this same account;
Dreamcatcher will ignore an issue assigned only to somebody else.

## 3. Prepare the repository

Use the main checkout of an ordinary clone, not a linked Git worktree.
Dreamcatcher deliberately refuses to run from a linked worktree because it
creates and manages child worktrees of its own.

```sh
git clone https://github.com/OWNER/REPOSITORY.git
cd REPOSITORY
git switch main
git pull --ff-only origin main
```

Replace `OWNER/REPOSITORY` with your repository. Dreamcatcher fetches
`origin main` before creating every assignment, so both must exist and your
account must be able to push to `origin`.

Now configure a Git identity if this repository does not already have one. The
empty commit that begins an assignment needs it:

```sh
git config user.name "Your Name"
git config user.email "you@example.com"
```

An assignment sees the files committed on `origin/main`, not uncommitted setup
from your main checkout. Before dispatching, commit and push the project's agent
instructions, dependency manifests, lockfiles and any scripts needed to set up
or test the project. Make those instructions non-interactive: nobody can answer
a prompt that waits inside an autonomous round.

This walkthrough assumes you may push that setup to `main`. If `main` is
protected, land the same files through your repository's normal pull-request
process before continuing.

## 4. Sign in to Claude and install the assignment skill

From the prepared repository, start Claude Code in auto permission mode:

```sh
claude --permission-mode auto
```

Follow the browser sign-in if Claude asks. Reaching the Claude prompt confirms
that this installation and account can start the mode Dreamcatcher uses.

Install the [`dream` plugin](https://github.com/alimanfoo/dream) in this same
session. When Claude asks for an
[installation scope](https://code.claude.com/docs/en/discover-plugins), choose
**User** so the skill is available in the child Git worktree where an assignment
runs:

```text
/plugin marketplace add alimanfoo/dream
/plugin install dream@dream
```

Restart Claude if the installation asks you to. Type `/` and confirm that
`/dream:smith` appears in the available commands, without running it. This is
the skill Dreamcatcher will use. Then leave Claude with `/exit`.

## 5. Configure one assignment route

Create `dreamcatcher.toml` at the repository root:

```toml
[[assignment]]
label = "dream:smith"

[assignment.claude]
prompt = "/dream:smith GH{issue}"
model = "opus[1m]"
effort = "high"
```

The label connects a GitHub issue to this route. `{issue}` becomes its issue
number, so issue 123 starts Claude with `/dream:smith GH123`.

Commit and push the configuration so the assignment worktree contains it too:

```sh
git add dreamcatcher.toml
git commit -m "Configure Dreamcatcher"
git push origin main
```

For more routes or another harness, see
[Configure labels and harnesses](configure.md). The
[configuration reference](configuration-reference.md) lists every setting.

## 6. Prepare a small issue

In GitHub:

1. Create the `dream:smith` label if the repository does not have it.
2. Open one small, self-contained issue. State the expected result and how to
   check it.
3. Assign it to the account shown by `gh auth status`.
4. Add the `dream:smith` label.

Choose work that can finish in one pull request. Avoid an issue with an open
blocking issue or an existing open pull request linked to it; either condition
keeps a new assignment from starting.

Suppose GitHub gives the issue number 123. The commands below call it `GH123`;
replace that with your own issue number.

## 7. Start Dreamcatcher

From the main checkout, start the daemon in its own terminal:

```sh
dreamcatcher run --harness claude --interval 30 --max-agents 1
```

Keep this terminal open. Every 30 seconds Dreamcatcher looks for work, with at
most one agent round running at a time. A round is one agent process, from the
moment Dreamcatcher starts it until that process exits.

Dreamcatcher starts Claude non-interactively in auto permission mode and allows
the selected Git, pull-request and issue commands the assignment needs to finish
the job. The agent can edit files, run tools, commit and push under your
account. These controls are not a security sandbox or a guarantee about what a
plugin will do, so use a repository, plugin and GitHub account you trust.

On dispatch, Dreamcatcher fetches `origin/main`, creates a branch and child
worktree, pushes an empty commit, and opens a linked **draft** pull request. The
draft means the assignment has begun; it does not mean the implementation is
ready for review. Claude then works in that child worktree.

## 8. Watch the assignment

In a second terminal, still at the repository root, open the local dashboard:

```sh
dreamcatcher web
```

Select `GH123` to see its rounds and live feed. The dashboard reads local state,
so it can show activity without publishing the agent's working notes to GitHub.
You can also follow the same feed in a terminal:

```sh
dreamcatcher feed GH123 --assignment
```

If the agent needs a decision, it should ask on the draft pull request. Reply
there using the same GitHub account that `gh` is signed in as. Dreamcatcher
relays your pull-request comment or review into another round at its next
update.

When the implementation is complete, the assignment skill changes the pull
request from draft to **ready for review**. That is the endpoint of this
tutorial: a normal pull request containing the implementation, checks and the
agent's account of the change.

Continue with [Review an assignment](review-an-assignment.md) to give feedback,
merge it, and let Dreamcatcher finish its wrap-up.
