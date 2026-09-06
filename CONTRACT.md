# What a dispatchable skill must do

dreamcatcher dispatches an agent skill at a labelled issue and carries that
issue to a pull request. This page says what a skill has to do to be one
dreamcatcher can dispatch. Map a label to a skill that does all of it, and
dreamcatcher can run every issue carrying that label.

## What a round gives you

dreamcatcher runs your skill as a round: one run of the harness's own command
line, which ends when that command exits. A session is one attempt at one issue,
and it holds every round that attempt runs.

Before the first round starts, dreamcatcher fetches origin's main, cuts a branch
from it, and adds a worktree on that branch. The round runs in that worktree, so
the branch is checked out and the working tree is clean when you wake up.

Your prompt arrives on standard input, and it carries the issue's number. Read
that number out of your prompt, and act on the issue it names.

## Open the pull request before you change anything

Adopt the branch you woke up on, work in the worktree it is checked out in, and
open the pull request from that branch. Open it as a draft as your first act,
before you change any code, and mark it ready when the work is done.

Opening it first is what gives you a channel and gives the user a window. The
pull request is the only way you can reach the user, so a question you need
answered has nowhere to go until the pull request is open. And the user watches
the pull request to see the commits arrive, so one opened at the end shows them
nothing until the work is over.

dreamcatcher finds your pull request by the head of the branch it cut. Don't cut
a branch of your own, and don't open the pull request from anywhere else. A
session whose branch has no pull request is one no round can move on, so the
board shows it as stuck for a person to read.

## Say that the pull request closes the issue

Write `Closes #123` in the pull request's description, naming the issue that
your prompt gave you. GitHub links the issue to the pull request when you do,
and that link is how dreamcatcher knows somebody is working on the issue.

An issue that no open pull request links to is one dreamcatcher is free to
dispatch again, once the session's worktree has gone. So a pull request that
never says it closes the issue costs a second session on the same work.

## Yield by ending your turn

End your turn when you have nothing left to do. dreamcatcher watches the
process, and the round is over when that process exits.

Post every question for the user as a pull request comment, and then end your
turn. A later round wakes you when the user replies. Don't ask in your turn
output or in an interactive prompt, because the harness runs headless and nobody
is there to read either one.

Don't run anything that waits on a person, such as a command that asks to be
approved, an editor, or a prompt for input. Nothing answers it, and the round
stalls for as long as the daemon lives.

## The rounds after the first

dreamcatcher wakes your session again whenever there is more for it to do. Every
round after the first resumes the harness's own session, so what the earlier
rounds said is still in front of you, and the new prompt says only why you were
woken.

### Carrying on

A round dies with the daemon that started it, and a round can fail on its own,
where a usage limit is the common cause. Either way the next tick wakes the
session with a prompt saying that the previous round did not finish. Carry on
from where the transcript stopped, and end your turn when the work is done.

### The pull request inbox

The other prompt names a JSON file and asks you to read it. That file is the
round's inbox, and it holds what the pull request is now and what the user has
said on it since the last round that was given one.

Read `state` first. It is the pull request's own state.

- `OPEN` means the user has posted something. `posts` holds what they posted,
  oldest first. Act on it, and reply on the pull request.
- `MERGED` or `CLOSED` means the pull request is finished, and this is the last
  round dreamcatcher runs for the session. Do whatever closing work your skill
  does, and end your turn. `posts` still holds anything the user said before
  they merged or closed the pull request.

Every post says what it is under `kind`, and carries `author`, `written_at` and
`body`:

- `comment` is a comment on the pull request's conversation.
- `review` is a review that the user submitted. Its `verdict` says what the
  review said, such as `APPROVED` or `CHANGES_REQUESTED`.
- `inlineComment` is a comment on the diff. It says which file under `path`, and
  what the comment was written against under `diff_hunk`. `line`, `start_line`
  and `side` place it on the diff, and `subject_type` says `file` when the user
  picked the whole file rather than any line of it.

The inbox holds only what you have not been given before.
