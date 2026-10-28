# Configure labels and harnesses

Use `dreamcatcher.toml` to decide which GitHub labels start assignments,
issue conversations or campaigns, and which dispatch recipe each label
uses. Put the file in the root of the repository's main checkout and
commit it when everyone watching the repository should use the same
routes.

You need the harness CLIs you configure on `PATH`, plus an authenticated
`gh`. _dreamcatcher_ reads the file when the daemon starts, so restart a
running daemon after changing it.

[`dreamcatcher init`](command-reference.md#init) writes a starting file
with routes for the `dream` plugin's skills, when the checkout has none.
Edit that file, or write your own. `init` installs the `dream` plugin
for each harness the file uses, even when its prompts invoke other
skills.

## Start with distinct labels

Choose labels that say what kind of work they invite. The following file
gives Claude one assignment route, one conversation route and one
campaign route:

```toml
[[assignment]]
label = "agent-assignment"

[assignment.claude]
prompt = "/dream:smith GH{issue}"
model = "opus[1m]"
effort = "high"

[[conversation]]
label = "discuss"

[conversation.claude]
prompt = "Investigate the question on GH{issue} and return a concise answer."
model = "opus[1m]"
effort = "high"

[[campaign]]
label = "agent-campaign"

[campaign.claude]
prompt = "/dream:lead GH{issue}"
model = "opus[1m]"
effort = "high"
```

Run [`dreamcatcher init`](command-reference.md#init) to create any of
the file's labels that the GitHub repository lacks. Label matching is
case-insensitive, but using the same spelling everywhere makes the route
easier to recognise.

An assignment prompt normally invokes an installed assignment skill. The
skill must know how to adopt _dreamcatcher_'s branch and draft pull
request; authors can find the exact requirements in the
[assignment skill contract](contract.md#assignment-skill-contract). A
conversation prompt normally invokes a conversation skill, but it can be
plain instructions, as above, because _dreamcatcher_ adds the input and
publication instructions itself. Authors can find the conversation
skill's requirements in the
[conversation skill contract](contract.md#conversation-skill-contract).
A campaign prompt normally invokes a campaign skill such as
`dream:lead`, whose requirements are in the
[campaign skill contract](contract.md#campaign-skill-contract).

## Match the recipe to how hard the work is

Give work of one kind more than one route when it varies in how much
capability it needs. Each route's recipe sets that capability through
the skill that its prompt runs, its `model` and its `effort`. The file
that `init` writes has two assignment routes, and
[Customise skills](customise-skills.md) says what the skill of each one
does. `agent-assignment-easy` runs a lighter skill on a smaller model
than `agent-assignment` does. Put `agent-assignment-easy` on an issue
only when the work is easy to get right, such as a typo or a renamed
setting. A small change can still be hard, and then it needs
`agent-assignment`.

To give the hardest work a stronger recipe, add an assignment route
under a label of its own, such as `agent-assignment-hard`.

## Decide which harness runs a route

Each route needs a `claude` recipe, a `codex` recipe, or both. The
recipe fixes the prompt, model, effort and any harness config that new
work is created with.

The `--harness` value on `dreamcatcher run` is the preference for a
route that offers both harnesses. A route that offers only Claude always
uses Claude; a route that offers only Codex always uses Codex. At
startup _dreamcatcher_ checks that the preferred harness and every
harness mentioned anywhere in the file is installed.

A `codex` recipe can also give Codex settings of its own, such as a
larger context window:

```toml
[assignment.codex]
prompt = "$dream:smith GH{issue}"
model = "gpt-5.6-sol"
effort = "high"
config = { model_context_window = 1000000, model_auto_compact_token_limit = 900000 }
```

_dreamcatcher_ passes each entry to every Codex round. The
[configuration reference](configuration-reference.md#codex-config) says
which values it accepts and which settings it keeps for itself.

Existing agent work keeps the label, harness and recipe it started with,
even if its route is later removed.

See the [configuration reference](configuration-reference.md) for a
two-harness example and every accepted setting.

## Label an issue for agent work

An issue is available for a new assignment when it:

- is open and assigned to the account authenticated through `gh`;
- carries exactly one configured assignment label, which you applied
  yourself;
- has no open assignment already managed by this checkout;
- has no other open pull request linked to it; and
- has no open issue recorded by GitHub as blocking it.

If an issue carries two configured assignment labels, _dreamcatcher_
reports a routing conflict instead of guessing which recipe to use.
Removing an assignment label after dispatch does not stop the active
assignment: its saved route and pull request continue to govern later
rounds. Use the controls in [Stop and recover work](stop-and-recover.md)
when you need to intervene.

A conversation starts on an open issue that is assigned to the
authenticated account and carries exactly one configured conversation
label, which you applied yourself, once you post a comment. Unassigning
the issue, removing the conversation's label, adding a second
conversation label or another account applying its label pauses the
conversation, and closing the issue ends it.
[Discuss an issue](discuss-an-issue.md#pause-resume-or-end-a-conversation)
explains both.

A campaign starts on an open parent issue that is assigned to the
authenticated account, carries exactly one configured campaign label,
which you applied yourself, and has no open issue recorded by GitHub as
blocking it. It pauses and ends as a conversation does.
[Start a campaign](start-a-campaign.md) explains how.

Labels of different kinds may coexist on an issue because they select
different kinds of work.

Apply a dispatch label yourself, once the issue is assigned to you. Work
starts, and paused work resumes, only on a label that the authenticated
account applied. A label that a colleague puts on an issue assigned to
you starts nothing, and the status report shows its request as held,
naming who labelled the issue. Remove the label and add it again
yourself to start the work.

## Apply and check the configuration

Commit and push `dreamcatcher.toml` and any project instructions or
setup files the agents need. Every agent's worktree starts from fetched
`origin/main`, so local uncommitted files are not available to it.

Then start or restart the daemon from the ordinary main checkout:

```sh
dreamcatcher run --harness claude
```

A missing harness, invalid setting or duplicate label is reported before
the daemon begins scheduling. For all daemon options, see the
[`run` command reference](command-reference.md#run).
