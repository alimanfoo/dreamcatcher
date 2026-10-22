import json
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import (
    CONFIG,
    HEAD,
    PULL_REQUEST,
    REPOSITORY,
    comment,
    commit,
    git,
    pull_requests,
)
from records import (
    read_assignments,
    write_assignment,
    write_round,
)

from dreamcatcher.agent_assignments import (
    AssignmentRoundInput,
    cancel_assignment,
    complete_assignment,
    compose_assignment_branch,
    open_assignment_pull_request,
    read_assignment_pull_request_number,
    read_user_post_cursor,
)
from dreamcatcher.agent_rounds import (
    AgentRoundPaths,
    AgentRoundRecord,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import (
    AgentWorkEnding,
    AgentWorkEndReason,
    AgentWorkRecord,
    create_agent_work,
    read_agent_work_at_issue,
    record_harness_session_identifier,
    request_agent_work_retry,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import (
    DREAMCATCHER_CONFIG_NAME,
    AgentHarness,
    read_dreamcatcher_config,
)
from dreamcatcher.documents import write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import add_worktree, fetch_main, make_empty_commit, push_branch
from dreamcatcher.github import IssueComment, PullRequestState
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH12-20260819-184158-assignment"

BRANCH = f"dreamcatcher-{ASSIGNMENT_ID}"


def record_assignment(*, state, route, preferred_harness=AgentHarness.CLAUDE):
    """Record the assignment at issue 12, as the scheduler does when it picks one."""
    return create_agent_work(
        state=state,
        route=route,
        preferred_harness=preferred_harness,
        issue=12,
        title="The issue title",
        at=PINNED,
    )


def open_pull_request(*, state, assignment):
    """Open the assignment's pull request, as the round that opens it does."""
    open_assignment_pull_request(
        state=state, repository=REPOSITORY, assignment=assignment
    )


def open_assignment(*, state, route, preferred_harness, issue, at):
    """Record an assignment and open its pull request, as its opening round does."""
    assignment = create_agent_work(
        state=state,
        route=route,
        preferred_harness=preferred_harness,
        issue=issue,
        title="The issue title",
        at=at,
    )
    open_assignment_pull_request(
        state=state, repository=REPOSITORY, assignment=assignment
    )
    return assignment


@pytest.fixture
def checkout(cloned):
    """A main checkout with an origin and an assignment configuration."""
    (cloned / DREAMCATCHER_CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    return cloned


@pytest.fixture
def state(checkout, gh):
    """The state directory of that checkout."""
    return StateDirectory(root=checkout)


@pytest.fixture
def fabricated(tmp_path):
    """A state directory holding records alone, with no checkout behind it."""
    return StateDirectory(root=tmp_path)


@pytest.fixture
def route(checkout):
    """The assignment route of the one label that the config maps."""
    return read_dreamcatcher_config(root=checkout).assignment[0]


def written(*, state):
    """Return the record that the assignment wrote about itself."""
    record = state.work / ASSIGNMENT_ID / "work.json"
    return AgentWorkRecord.model_validate_json(record.read_text(encoding="utf-8"))


def test_an_assignment_cuts_a_worktree_of_its_own_under_the_state_directory(
    state, route
):
    assignment = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert assignment.identifier == ASSIGNMENT_ID
    assert assignment.worktree == state.worktrees / ASSIGNMENT_ID
    assert (assignment.worktree / "README.md").exists()


def test_an_assignment_cuts_a_branch_of_its_own_from_origins_main_as_it_is_now(
    state, route
):
    # Move origin's main on, then leave the checkout believing what it knew
    # before. Only a fetch of its own brings the creation the newer main.
    known = git(arguments=["rev-parse", "origin/main"], cwd=state.root).strip()
    (state.root / "later.txt").write_text("main moved on\n", encoding="utf-8")
    commit(path=state.root, message="move main on")
    git(arguments=["push", "origin", "main"], cwd=state.root)
    git(arguments=["update-ref", "refs/remotes/origin/main", known], cwd=state.root)

    assignment = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert compose_assignment_branch(identifier=assignment.identifier) == BRANCH
    assert BRANCH in git(arguments=["branch", "--list", BRANCH], cwd=state.root)
    assert (assignment.worktree / "later.txt").exists()
    message = git(
        arguments=["log", "-1", "--format=%s"], cwd=assignment.worktree
    ).strip()
    assert message == "GH12 [skip ci]"


def test_a_codex_assignment_records_its_recipes_config(state, route):
    codex = route.recipes[AgentHarness.CODEX]
    configured = route.model_copy(
        update={
            "codex": codex.model_copy(
                update={"config": {"model_context_window": 1000000}}
            )
        }
    )

    open_assignment(
        state=state,
        route=configured,
        preferred_harness=AgentHarness.CODEX,
        issue=12,
        at=PINNED,
    )

    assert written(state=state).harness_config == {"model_context_window": 1000000}


def test_an_assignment_records_its_settled_dispatch_recipe(state, route):
    assignment = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert written(state=state) == assignment.record
    assert assignment.record.issue == 12
    assert assignment.record.title == "The issue title"
    assert assignment.record.dispatch_label == "dream:smith"
    assert read_assignment_pull_request_number(assignment=assignment) == PULL_REQUEST
    assert assignment.record.harness == AgentHarness.CLAUDE
    assert assignment.record.model == "opus[1m]"
    assert assignment.record.effort == "xhigh"
    assert assignment.record.harness_config == {}
    assert assignment.record.instructions == "/dream:smith GH12"
    record = state.work / ASSIGNMENT_ID / "work.json"
    assert '"dispatch_label": "dream:smith"' in record.read_text(encoding="utf-8")


def test_an_assignment_is_recorded_before_any_git_or_github_step(state, route, gh):
    assignment = record_assignment(state=state, route=route)

    assert read_assignments(state=state) == [assignment]
    assert not assignment.worktree.exists()
    assert read_assignment_pull_request_number(assignment=assignment) is None
    assert git(arguments=["branch", "--list", BRANCH], cwd=state.root) == ""
    assert gh.calls == []


def test_an_assignment_titles_its_pull_request_after_its_record(state, route, gh):
    open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    created = next(call for call in gh.calls if call.arguments[:2] == ["pr", "create"])
    assert (
        created.arguments[created.arguments.index("--title") + 1] == "The issue title"
    )


def test_an_assignment_runs_on_the_harness_the_run_named(state, route):
    assignment = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CODEX,
        issue=12,
        at=PINNED,
    )

    assert assignment.record.harness == AgentHarness.CODEX
    assert assignment.record.model == "gpt-5.6-sol"
    assert assignment.record.instructions == "$dream:smith GH12"


def test_a_new_assignment_has_run_no_rounds_and_its_next_is_its_first(state, route):
    assignment = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert assignment.rounds == []
    assert assignment.compose_round_paths(number=1) == AgentRoundPaths(
        worktree=assignment.worktree,
        rounds_directory=state.work / ASSIGNMENT_ID / "rounds",
        number=1,
    )


def standing(*, state, rounds: Sequence[AgentRoundRecord]):
    """Return the assignment that these rounds leave behind, read back from disk."""
    directory = write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=12)
    for number, record in enumerate(rounds, start=1):
        write_round(directory=directory, number=number, record=record)
    return read_assignments(state=state)[0]


def test_assignments_at_one_issue_are_read_behind_the_assignment_boundary(fabricated):
    write_assignment(
        state=fabricated, identifier="GH12-20260818-090000-assignment", issue=12
    )
    write_assignment(
        state=fabricated, identifier="GH13-20260819-090000-assignment", issue=13
    )
    write_assignment(
        state=fabricated, identifier="GH12-20260820-090000-assignment", issue=12
    )

    assignments = read_agent_work_at_issue(state=fabricated, issue=12)

    assert [assignment.identifier for assignment in assignments] == [
        "GH12-20260818-090000-assignment",
        "GH12-20260820-090000-assignment",
    ]


def ended(*, status, minute=0, number: int = 1):
    """Return a round that started that minute past the hour and ended."""
    started = PINNED + timedelta(minutes=minute)
    return AgentRoundRecord(
        number=number,
        started=started,
        pid=1,
        ending=_compose_agent_round_ending(at=started, status=status),
    )


def running(*, minute=0, number: int = 1):
    """Return a round that started that minute past the hour and is still going."""
    return AgentRoundRecord(
        number=number,
        started=PINNED + timedelta(minutes=minute),
        pid=1,
    )


def test_a_round_an_assignment_has_run_is_found_by_the_number_it_ran_as(fabricated):
    assignment = standing(
        state=fabricated,
        rounds=[ended(status=0), ended(status=0, minute=1, number=2)],
    )

    assert assignment.compose_round_paths(number=2) == AgentRoundPaths(
        worktree=assignment.worktree,
        rounds_directory=fabricated.work / ASSIGNMENT_ID / "rounds",
        number=2,
    )


def test_an_assignment_is_open_until_its_ending_is_recorded(fabricated):
    assignment = standing(state=fabricated, rounds=[ended(status=0)])

    assert assignment.is_open


def test_completing_an_assignment_records_its_ending(fabricated):
    assignment = standing(state=fabricated, rounds=[ended(status=0)])

    complete_assignment(assignment=assignment, clock=lambda: PINNED, final_output=None)

    completed = read_assignments(state=fabricated)[0]
    assert completed.ending == AgentWorkEnding(
        at=PINNED, reason=AgentWorkEndReason.COMPLETED
    )
    assert not completed.is_open


def test_a_cancelled_assignment_records_when_and_is_no_longer_open(fabricated):
    assignment = standing(state=fabricated, rounds=[ended(status=0)])

    cancel_assignment(assignment=assignment, at=PINNED + timedelta(hours=1))

    cancelled = read_assignments(state=fabricated)[0]
    assert cancelled.ending == AgentWorkEnding(
        at=PINNED + timedelta(hours=1), reason=AgentWorkEndReason.CANCELLED
    )
    assert not cancelled.is_open


def test_recording_later_facts_leaves_the_assignment_record_as_it_was(fabricated):
    # Nothing rewrites the record, so no writer can erase another's fact.
    write_assignment(
        state=fabricated,
        identifier=ASSIGNMENT_ID,
        issue=12,
        harness_session_identifier=None,
    )
    assignment = read_assignments(state=fabricated)[0]
    record = assignment.directory / "work.json"
    created = record.read_bytes()

    record_harness_session_identifier(work=assignment, identifier="abc-123")
    request_agent_work_retry(work=assignment, at=PINNED)
    cancel_assignment(assignment=assignment, at=PINNED)

    assert record.read_bytes() == created
    recorded = read_assignments(state=fabricated)[0]
    assert recorded.retry_requested_at == PINNED
    assert recorded.ending == AgentWorkEnding(
        at=PINNED, reason=AgentWorkEndReason.CANCELLED
    )
    assert recorded.harness_session_identifier == "abc-123"


def test_cancelling_asks_a_round_with_no_ending_to_stop(fabricated):
    assignment = standing(state=fabricated, rounds=[ended(status=0), running(number=2)])

    cancel_assignment(assignment=assignment, at=PINNED)

    assert assignment.compose_round_paths(number=2).stop_request.is_file()


def test_cancelling_stops_a_round_that_started_after_the_assignment_was_read(
    fabricated,
):
    assignment = standing(state=fabricated, rounds=[ended(status=0)])
    write_round(
        directory=assignment.directory, number=2, record=running(minute=1, number=2)
    )

    cancel_assignment(assignment=assignment, at=PINNED)

    assert assignment.compose_round_paths(number=2).stop_request.is_file()


def test_cancelling_leaves_an_ended_round_alone(fabricated):
    assignment = standing(state=fabricated, rounds=[ended(status=0)])

    cancel_assignment(assignment=assignment, at=PINNED)

    assert not assignment.compose_round_paths(number=1).stop_request.exists()


def test_an_assignment_that_has_ended_cannot_be_cancelled(fabricated):
    assignment = standing(state=fabricated, rounds=[])
    cancel_assignment(assignment=assignment, at=PINNED)

    with pytest.raises(ReportableError, match=f"{ASSIGNMENT_ID} has already ended"):
        cancel_assignment(
            assignment=read_assignments(state=fabricated)[0],
            at=PINNED + timedelta(hours=1),
        )

    assert read_assignments(state=fabricated)[0].ending == AgentWorkEnding(
        at=PINNED, reason=AgentWorkEndReason.CANCELLED
    )


def endings(*, state):
    """Return how each round of the state directory's one assignment ended."""
    return [record.ending for record in read_assignments(state=state)[0].rounds]


def test_a_second_read_does_not_open_a_round_record_it_has_already_read(fabricated):
    directory = write_assignment(state=fabricated, identifier=ASSIGNMENT_ID, issue=12)
    write_round(directory=directory, number=1, record=ended(status=0))
    write_round(directory=directory, number=2, record=running(minute=1, number=2))
    read_assignments(state=fabricated)

    # Rewriting the first round's record puts something there that only a read
    # of that file could find. A reader that has read it does not look again.
    write_round(directory=directory, number=1, record=ended(status=2))

    assert endings(state=fabricated) == [ended(status=0).ending, None]


def test_a_second_read_carries_an_ending_that_landed_since_the_first(fabricated):
    directory = write_assignment(state=fabricated, identifier=ASSIGNMENT_ID, issue=12)
    write_round(directory=directory, number=1, record=running())
    read_assignments(state=fabricated)

    write_round(directory=directory, number=1, record=ended(status=0))

    assert endings(state=fabricated) == [ended(status=0).ending]


def test_a_second_read_finds_a_round_that_has_started_since_the_first(fabricated):
    directory = write_assignment(state=fabricated, identifier=ASSIGNMENT_ID, issue=12)
    write_round(directory=directory, number=1, record=ended(status=0))
    read_assignments(state=fabricated)

    write_round(directory=directory, number=2, record=running(minute=1, number=2))

    read = read_assignments(state=fabricated)[0]

    assert [record.started for record in read.rounds] == [
        PINNED,
        PINNED + timedelta(minutes=1),
    ]


def test_a_round_that_ended_as_a_later_round_started_reads_back_ended(fabricated):
    directory = write_assignment(state=fabricated, identifier=ASSIGNMENT_ID, issue=12)
    write_round(directory=directory, number=1, record=running())
    read_assignments(state=fabricated)

    # The first round ended, and the round that carried its work on started,
    # so the record that ended is no longer the assignment's newest.
    write_round(directory=directory, number=1, record=ended(status=0))
    write_round(directory=directory, number=2, record=running(minute=1, number=2))

    assert endings(state=fabricated) == [ended(status=0).ending, None]


def test_an_assignment_git_cannot_cut_leaves_no_branch_behind(state, route):
    # git makes the branch, then finds something already in the worktree's
    # place and stops. The worktree it never made cannot be removed, so the
    # back-out takes what git did leave.
    occupied = state.worktrees / ASSIGNMENT_ID
    occupied.mkdir(parents=True)
    (occupied / "in the way.txt").write_text("not ours\n", encoding="utf-8")

    with pytest.raises(CommandError):
        open_assignment(
            state=state,
            route=route,
            preferred_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert git(arguments=["branch", "--list", BRANCH], cwd=state.root) == ""


@pytest.mark.parametrize("checkpoint", ["worktree", "commit", "push", "pull request"])
def test_a_first_round_continues_from_what_an_earlier_attempt_left(
    state, route, gh, checkpoint
):
    assignment = record_assignment(state=state, route=route)
    fetch_main(root=state.root)
    worktree = state.worktrees / ASSIGNMENT_ID
    add_worktree(root=state.root, path=worktree, branch=BRANCH)
    if checkpoint != "worktree":
        make_empty_commit(worktree=worktree, message="GH12")
    if checkpoint in {"push", "pull request"}:
        push_branch(root=state.root, branch=BRANCH)
    if checkpoint == "pull request":
        gh.replies(stdout=pull_requests(numbers=[PULL_REQUEST]), to="pr list")

    open_pull_request(state=state, assignment=assignment)

    assert read_assignment_pull_request_number(assignment=assignment) == PULL_REQUEST
    commits = git(arguments=["rev-list", "--count", "origin/main..HEAD"], cwd=worktree)
    assert commits.strip() == "1"
    remote = git(arguments=["ls-remote", "--heads", "origin", BRANCH], cwd=state.root)
    assert f"refs/heads/{BRANCH}" in remote
    created = [call for call in gh.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == (0 if checkpoint == "pull request" else 1)


def test_a_pull_request_listing_failure_leaves_the_round_to_try_again(state, route, gh):
    gh.fails(stderr="gh: could not connect to github.com", to="pr list")
    assignment = record_assignment(state=state, route=route)

    with pytest.raises(ReportableError, match=f"cannot tell whether {BRANCH} has"):
        open_pull_request(state=state, assignment=assignment)

    assert (state.worktrees / ASSIGNMENT_ID).exists()
    assert read_assignment_pull_request_number(assignment=assignment) is None


def test_several_pull_requests_on_the_assignments_branch_are_reported(state, route, gh):
    gh.replies(
        stdout=pull_requests(numbers=[PULL_REQUEST, 53]),
        to="pr list",
    )
    assignment = record_assignment(state=state, route=route)

    with pytest.raises(ReportableError, match="more than one pull request"):
        open_pull_request(state=state, assignment=assignment)


def test_a_created_pull_request_that_cannot_be_read_is_adopted_next_time(
    state, route, gh
):
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")
    assignment = record_assignment(state=state, route=route)

    with pytest.raises(
        ReportableError, match=f"created the pull request for {BRANCH} but cannot read"
    ):
        open_pull_request(state=state, assignment=assignment)

    gh.replies(stdout=pull_requests(numbers=[PULL_REQUEST]), to="pr list")
    open_pull_request(state=state, assignment=assignment)

    assert read_assignment_pull_request_number(assignment=assignment) == PULL_REQUEST
    created = [call for call in gh.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == 1


def test_a_state_directory_with_no_worktrees_holds_no_assignments(state):
    assert read_assignments(state=state) == []


def test_an_assignment_reads_back_with_its_settled_dispatch_recipe(state, route):
    created = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert read_assignments(state=state) == [created]


def test_an_assignment_finds_a_session_reported_by_a_later_round(fabricated):
    directory = write_assignment(
        state=fabricated,
        identifier=ASSIGNMENT_ID,
        issue=12,
        harness_session_identifier=None,
    )
    for number in (1, 2):
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=PINNED,
                pid=1,
            ),
        )
    assignment = read_assignments(state=fabricated)[0]
    assignment.compose_round_paths(number=2).raw_output.write_bytes(
        (
            json.dumps(
                {
                    "type": "system",
                    "subtype": "init",
                    "model": "claude-opus-5",
                    "session_id": "replacement-session",
                }
            )
            + "\n"
        ).encode()
    )

    found = assignment.find_harness_session_identifier()

    assert found == "replacement-session"


def test_an_assignment_with_no_relayed_user_post_has_an_empty_cursor(state, route):
    open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert read_user_post_cursor(assignment=read_assignments(state=state)[0]) == ""


def test_an_assignment_reads_back_its_user_post_cursor(state, route):
    created = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    write_round(
        directory=created.directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=_compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    write_json(
        document=AssignmentRoundInput(
            pull_request_state=PullRequestState.OPEN,
            pull_request_head=HEAD,
            signals=[],
            user_posts=[
                IssueComment.model_validate(comment(created_at="2026-09-03T22:31:51Z"))
            ],
        ),
        path=created.compose_round_paths(number=1).round_input,
    )

    assert (
        read_user_post_cursor(assignment=read_assignments(state=state)[0])
        == "2026-09-03T22:31:51Z"
    )


def test_the_user_post_cursor_scans_past_an_input_that_relayed_no_posts(state, route):
    created = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    for number, posts in (
        (
            1,
            [IssueComment.model_validate(comment(created_at="2026-09-03T22:31:51Z"))],
        ),
        (2, []),
    ):
        write_round(
            directory=created.directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=PINNED + timedelta(minutes=number),
                pid=1,
                ending=_compose_agent_round_ending(at=PINNED, status=0),
            ),
        )
        write_json(
            document=AssignmentRoundInput(
                pull_request_state=PullRequestState.OPEN,
                pull_request_head=HEAD,
                signals=[],
                user_posts=posts,
            ),
            path=created.compose_round_paths(number=number).round_input,
        )

    assert (
        read_user_post_cursor(assignment=read_assignments(state=state)[0])
        == "2026-09-03T22:31:51Z"
    )


def test_an_assignments_rounds_read_back_in_number_order(state, route):
    open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    later = PINNED.replace(minute=50)
    directory = state.work / ASSIGNMENT_ID
    write_round(
        directory=directory,
        number=3,
        record=AgentRoundRecord(
            number=3,
            started=PINNED,
            pid=1,
        ),
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=later,
            pid=1,
            ending=_compose_agent_round_ending(at=later, status=0),
        ),
    )

    read = read_assignments(state=state)[0]

    assert [record.number for record in read.rounds] == [1, 3]
    assert [record.started for record in read.rounds] == [later, PINNED]
    assert read.next_round_number == 4
    assert (
        read.compose_round_paths(number=read.next_round_number).directory
        == state.work / ASSIGNMENT_ID / "rounds" / "4"
    )


def test_a_round_record_must_carry_the_number_of_its_directory(state, route):
    open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    write_round(
        directory=state.work / ASSIGNMENT_ID,
        number=2,
        record=AgentRoundRecord(
            number=3,
            started=PINNED,
            pid=1,
        ),
    )

    with pytest.raises(ReportableError, match="says it is round 3"):
        read_assignments(state=state)


def test_every_assignment_of_the_repo_reads_back_by_identifier(state, route):
    open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=3,
        at=PINNED,
    )

    assert [assignment.identifier for assignment in read_assignments(state=state)] == [
        "GH12-20260819-184158-assignment",
        "GH3-20260819-184158-assignment",
    ]


def test_a_file_left_among_the_worktrees_is_not_an_assignment(state, route):
    created = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    (state.worktrees / ".DS_Store").write_text("a file browser\n", encoding="utf-8")

    assert read_assignments(state=state) == [created]


def test_a_worktree_with_no_record_beside_it_is_not_an_assignment(state, route):
    created = open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    (state.worktrees / "GH3-20260819-184158-assignment").mkdir()

    assert read_assignments(state=state) == [created]


def test_an_assignment_record_that_will_not_read_names_the_file(state, route):
    open_assignment(
        state=state,
        route=route,
        preferred_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    (state.work / ASSIGNMENT_ID / "work.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ReportableError, match=r"work\.json is not valid"):
        read_assignments(state=state)
