# Configure labels and harnesses

Use `dreamcatcher.toml` to decide which GitHub labels start assignments or issue
conversations, and which dispatch recipe each label uses. Put the file in the
root of the repository's main checkout and commit it when everyone watching the
repository should use the same routes.

You need the harness CLIs you configure on `PATH`, plus an authenticated `gh`.
Dreamcatcher reads the file when the daemon starts, so restart a running daemon
after changing it.

## Start with distinct labels

Choose labels that say what kind of work they invite. The following file gives
Claude one assignment route and one conversation route:

```toml
[[assignment]]
label = "dream:smith"

[assignment.claude]
prompt = "/dream:smith GH{issue}"
model = "opus[1m]"
effort = "high"

[[conversation]]
label = "dream:discuss"

[conversation.claude]
prompt = "Investigate the question on GH{issue} and return a concise answer."
model = "opus[1m]"
effort = "high"
```

Create matching `dream:smith` and `dream:discuss` labels in the GitHub
repository. Label matching is case-insensitive, but using the same spelling
everywhere makes the route easier to recognise.

An assignment prompt normally invokes an installed assignment skill. The skill
must know how to adopt Dreamcatcher's branch and draft pull request; authors can
find the exact requirements in the [agent-facing contract](../CONTRACT.md). A
conversation prompt can be plain instructions, as above, because Dreamcatcher
adds the input and publication instructions itself.

## Decide which harness runs a route

Each route needs a `claude` recipe, a `codex` recipe, or both. The recipe fixes
the prompt, model, effort and any harness config that new work is created with.

The `--harness` value on `dreamcatcher run` is the preference for a route that
offers both harnesses. A route that offers only Claude always uses Claude; a
route that offers only Codex always uses Codex. At startup Dreamcatcher checks
that the preferred harness and every harness mentioned anywhere in the file is
installed.

A `codex` recipe can also give Codex settings of its own, such as a larger
context window:

```toml
[assignment.codex]
prompt = "$dream:smith GH{issue}"
model = "gpt-5.6-sol"
effort = "high"
config = { model_context_window = 1000000, model_auto_compact_token_limit = 900000 }
```

Dreamcatcher passes each entry to every Codex round. The
[configuration reference](configuration-reference.md#codex-config) says which
values it accepts and which settings it keeps for itself.

Existing assignments keep the label, harness and recipe they started with.
Conversations also keep their saved recipe and session, but their issue must
still match exactly one current conversation route. Removing its only matching
route pauses a conversation after the daemon restarts; adding a matching route
again can resume it without changing its saved recipe.

See the [configuration reference](configuration-reference.md) for a two-harness
example and every accepted setting.

## Label an issue for agent work

An issue is available for a new assignment when it:

- is open and assigned to the account authenticated through `gh`;
- carries exactly one configured assignment label;
- has no open assignment already managed by this checkout;
- has no other open pull request linked to it; and
- has no open issue recorded by GitHub as blocking it.

If an issue carries two configured assignment labels, Dreamcatcher reports a
routing conflict instead of guessing which recipe to use. Removing an assignment
label after dispatch does not stop the active assignment: its saved route and
pull request continue to govern later rounds. Use the controls in
[Stop and recover work](stop-and-recover.md) when you need to intervene.

An issue is eligible for a conversation when it is open, assigned to the
authenticated account and carries exactly one configured conversation label.
Those conditions remain active throughout the conversation. Closing or
unassigning the issue, or removing its last conversation label, pauses new
questions and automatic recovery. A round already running may still finish.

One assignment label and one conversation label may coexist on an issue because
they select different kinds of work.

## Apply and check the configuration

Commit and push `dreamcatcher.toml` and any project instructions or setup files
the agents need. Assignment worktrees start from fetched `origin/main`, so local
uncommitted files are not available to them.

Then start or restart the daemon from the ordinary main checkout:

```sh
dreamcatcher run --harness claude
```

A missing harness, invalid setting or duplicate label is reported before the
daemon begins scheduling. For all daemon options, see the
[`run` command reference](command-reference.md#run).
