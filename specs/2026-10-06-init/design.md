# Design: dreamcatcher init

## What we're building

`dreamcatcher init` prepares the main checkout of a GitHub repository for
_dreamcatcher_. A new user installs _dreamcatcher_, changes to a main checkout
and runs `init`. When it finishes, the checkout is ready for `dreamcatcher run`,
apart from committing the configuration and labelling an issue.

`init` checks what `run` needs and puts in place what is missing. It prints one
line for each step as it goes. When a step fails, it stops and says how to fix
the failure. Every step leaves alone what is already in place, so running `init`
again is safe, and a second run serves as a check.

## How it works

### The steps

`init` takes these steps in order, because each one depends on the ones before
it:

1. Check that the current directory is a repository's main checkout.
2. Ask gh which repository this is and which account it is signed in as, then
   check that the account can push to the repository.
3. Check that Git can commit here, by asking it for the author identity it would
   use. The empty commit that starts each assignment needs one.
4. Fetch `origin main`. Every assignment is cut from `origin/main`.
5. Find which harnesses are on the PATH. Refuse when neither is.
6. Write the default configuration to `dreamcatcher.toml`, unless the file is
   already there. Then read the file, so a mistake in it is reported now.
7. Refuse when the configuration routes work to a harness that is not on the
   PATH, because `run` would refuse to start.
8. For each harness that the configuration routes work to, check that it is
   signed in, then install the dream plugin for it.
9. Create every route label that the repository does not have yet.
10. Print the next steps.

### Shared checks

`run` already makes the checks in steps 1 and 2, apart from the push check.
Those checks move out of the daemon to the boundaries that own their subjects,
and both verbs call them there. The main-checkout check moves to `git.py`. The
repository and account check moves to `github.py`, which refuses with the reason
gh gave when it cannot tell either one.

### The default configuration

The default configuration lives in one file in the package,
`src/dreamcatcher/default_config.toml`. It is the complete example that the
configuration reference shows, and the reference includes the file rather than
keeping a copy. The `pymdownx.snippets` extension does the including, and its
`check_paths` setting makes the strict build fail when the file is missing.

The file offers a Claude recipe and a Codex recipe for every route. `init`
writes it with the recipe tables of each harness that is not on the PATH
commented out, because `run` refuses to start when a route names a missing
harness. Uncommenting those lines enables the harness once it is installed.

`init` never replaces an existing `dreamcatcher.toml`. The file may hold choices
that the repository already agrees on.

### Harness setup

Each harness adapter knows how to check that its harness is signed in and how to
install a plugin from a marketplace:

| Harness | Sign-in check        | Plugin install                                                             |
| ------- | -------------------- | -------------------------------------------------------------------------- |
| Claude  | `claude auth status` | `claude plugin marketplace add`, then `claude plugin install --scope user` |
| Codex   | `codex login status` | `codex plugin marketplace add`, then `codex plugin add`                    |

Each sign-in check exits with a non-zero status when the harness is signed out.
Each install command succeeds without a prompt, and succeeds again when the
plugin is already installed, so `init` runs them every time.

`init` installs the dream plugin from the `alimanfoo/dream` marketplace without
asking. The default configuration's prompts invoke its skills, and installing it
is part of what `init` is for. Both harnesses install it at user scope, which
adds to the user's settings outside the repository, so the command's help and
reference say so.

### Labels

`init` reads the repository's labels and creates each route label that is
missing, matching names case-insensitively as routing does. It leaves an
existing label's colour and description alone. A new label's description says
whether it starts an assignment or a conversation.

### What init does not do

`init` does not commit or push `dreamcatcher.toml`. `main` may be protected, and
a push publishes the user's work. It prints the commands instead, when it has
just written the file.

`init` does not check the version of gh or of a harness, and it does not update
an installed plugin.

## What changes

The command reference gains `init`. The tutorial replaces its sign-in, plugin,
configuration and label steps with one `init` step. The architecture gains a
repository setup boundary, and the harness adapters gain the two setup commands.
The ontology gains no concept: `init` composes the configuration, dispatch
labels and harnesses that it already names.
