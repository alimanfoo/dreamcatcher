# Configuration reference

Dreamcatcher reads `dreamcatcher.toml` from the root of the main checkout where
`dreamcatcher run` starts. The file defines which issue labels dispatch
assignments or issue conversations, and the harness recipe available for each
label. It does not configure daemon controls such as the interval or agent cap;
those are [`run` options](command-reference.md#run).

The file is required and must be UTF-8 TOML. Dreamcatcher reports a missing,
unreadable or invalid file rather than supplying a default configuration.

The daemon reads the file when it starts. Restart it to apply a change. Commit
the file when everyone watching a repository should use the same routes.

## Complete example

```toml
[[assignment]]
label = "dream:smith"

[assignment.claude]
prompt = "/dream:smith GH{issue}"
model = "opus[1m]"
effort = "xhigh"

[assignment.codex]
prompt = "$dream:smith GH{issue}"
model = "gpt-5.6-sol"
effort = "xhigh"
config = { model_context_window = 1000000, model_auto_compact_token_limit = 900000 }

[[conversation]]
label = "dream:conversation"

[conversation.claude]
prompt = "Answer questions on GH{issue}."
model = "opus[1m]"
effort = "high"

[conversation.codex]
prompt = "Answer questions on GH{issue}."
model = "gpt-5.6-sol"
effort = "high"
```

This file offers both supported harnesses for both routes. A route may instead
contain only its `claude` or only its `codex` block.

## Top-level settings

| Setting        | Value                                                | Required | Default     | Constraint                                        |
| -------------- | ---------------------------------------------------- | -------- | ----------- | ------------------------------------------------- |
| `assignment`   | Array of route tables, written as `[[assignment]]`   | Yes      | None        | At least one entry.                               |
| `conversation` | Array of route tables, written as `[[conversation]]` | No       | Empty array | Each entry defines a separate conversation route. |

No other top-level settings are accepted. In particular, `assignee`, `interval`
and `max_agents` are not configuration-file settings. Dreamcatcher obtains the
account from authenticated `gh`; use `run --interval` and `run --max-agents` for
the two daemon controls.

## Assignment and conversation routes

An `[[assignment]]` entry and a `[[conversation]]` entry have the same schema:

| Setting  | Value        | Required | Default | Constraint                                                                     |
| -------- | ------------ | -------- | ------- | ------------------------------------------------------------------------------ |
| `label`  | String       | Yes      | None    | Identifies this route, matched case-insensitively against GitHub issue labels. |
| `claude` | Recipe table | No       | Absent  | Configures Claude for this route.                                              |
| `codex`  | Recipe table | No       | Absent  | Configures Codex for this route.                                               |

Every route must contain at least one harness recipe. `claude` and `codex` are
the only accepted harness-table names.

A label is a case-insensitive identity. No two assignment routes may repeat a
label, no two conversation routes may repeat one, and an assignment route and a
conversation route may not share one. Route order gives no route precedence.
Issue labels are also matched case-insensitively.

If an issue matches more than one assignment route, that assignment work has a
routing conflict. The same is independently true of conversation routes. One
assignment label and one conversation label may coexist on an issue. An
assignment conflict prevents a new assignment but does not stop an existing
assignment's rounds. A conversation conflict prevents new conversation batches
and recovery rounds, though a round already running may finish.

## Harness recipes

Each `[assignment.claude]`, `[assignment.codex]`, `[conversation.claude]` or
`[conversation.codex]` table requires three settings, which have no defaults. A
Codex table also accepts a `config` table, described in
[Codex config](#codex-config).

| Setting  | Value  | Effect and constraint                                                                                                                                                                            |
| -------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `prompt` | String | The prompt template for first contact with the harness. Every literal `{issue}` is replaced by the issue number. Other text in braces is left unchanged. Newlines and percent signs are allowed. |
| `model`  | String | Passed to the selected harness as its model. It may not contain `%`, a line feed or a carriage return.                                                                                           |
| `effort` | String | Passed to the selected harness as its reasoning-effort value. It has the same character restrictions as `model`.                                                                                 |

Dreamcatcher does not prescribe the harness-specific model and effort names; the
selected harness must accept the configured strings. Unknown settings at any
level are errors, so a misspelling is reported rather than ignored. The keys of
a Codex `config` table are the exception, because they belong to Codex.

Assignment prompts normally invoke an assignment skill that follows the
[agent-facing contract](../CONTRACT.md). Conversation prompts may be plain
instructions or invoke a suitable skill, but they must follow the
[issue-conversation contract](../CONTRACT.md#issue-conversation-instructions).
Dreamcatcher adds its operational instructions to either prompt.

## Codex config

A Codex recipe's `config` table gives Codex settings of its own, such as a
larger context window. Dreamcatcher passes each entry to every round of the
work, first and resumed, as `-c key=value`, with the value written as TOML. The
table is optional, and an absent table passes nothing.

| Part  | Constraint                                                                                                                                    |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Key   | A Codex setting's name, as `codex -c` takes it. A name is ASCII letters, digits, `_` and `-`, and a dot separates the parts of a nested name. |
| Value | A boolean, an integer or a string. A string may not contain `%`. Dreamcatcher refuses a float, an array and a table.                          |

Write a nested setting as one quoted key, such as
`"features.web_search_request" = true`. A dotted key without quotes makes a
table in TOML, and Dreamcatcher refuses a table as a value.

Dreamcatcher keeps these settings for itself, so that every round runs with the
recipe's model and effort and with the permissions that unattended work needs:

- `model` and `model_reasoning_effort`;
- `sandbox_mode`, `approval_policy`, `approvals_reviewer` and
  `sandbox_workspace_write.network_access`;
- `default_permissions` and the `permissions` table, which would choose a
  permissions profile in place of the sandbox settings.

A `config` table that sets one of these, or a key inside one, is an error.
Dreamcatcher does not check that Codex knows a setting, so a misspelt key in a
`config` table is not reported.

## Harness selection

`dreamcatcher run --harness claude` or `--harness codex` supplies the preferred
harness for newly created work:

- When a route has a recipe for the preferred harness, Dreamcatcher uses it.
- When a route has only the other harness's recipe, Dreamcatcher uses that
  harness instead.

The option is therefore a preference, not a repository-wide pin. At startup,
Dreamcatcher requires the named harness and every harness present in any route
to be installed on `PATH`. An existing assignment or conversation keeps the
label, harness, prompt, model, effort and Codex config chosen when it was
created; later configuration changes do not rewrite that record.

A saved conversation may become eligible through any one configured conversation
label on its issue, but it still keeps its original route and recipe. Changing
the current label does not switch its saved harness or settings.

A matching label selects a route but does not by itself make an issue ready for
dispatch. [From issue to pull request](tutorial.md) explains how to prepare an
assignment issue; [Discuss an issue](discuss-an-issue.md) explains how to start
and continue a conversation.
