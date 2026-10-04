import json
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import (
    CONFIG,
    PULL_REQUEST,
    REPOSITORY,
    comment,
    commit,
    git,
    pull_request,
    pull_requests,
)
from records import write_assignment, write_round

from dreamcatcher.agent_assignments import (
    AssignmentCreator,
    AssignmentRecord,
    AssignmentRoundInput,
    PullRequestObservation,
    cancel_assignment,
    find_open_assignments_by_issue,
    inspect_incomplete_assignment_setups,
    read_assignments,
    read_assignments_for_issue,
    record_assignment_harness_session_identifier,
    record_assignment_title,
    record_pull_request_observation,
)
from dreamcatcher.agent_rounds import (
    AgentRoundPaths,
    AgentRoundRecord,
    AssignmentRoundPurpose,
    InterruptedAgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import (
    _DREAMCATCHER_CONFIG_NAME,
    AgentHarness,
    read_dreamcatcher_config,
)
from dreamcatcher.documents import write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import add_worktree, fetch_main, make_empty_commit, push_branch
from dreamcatcher.github import ConversationComment, PullRequest, PullRequestState
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH12-20260819-184158"

BRANCH = f"dreamcatcher-{ASSIGNMENT_ID}"


def create_assignment(*, state, route, requested_harness, issue, at):
    """Create one assignment through the repository's creation boundary."""
    creator = AssignmentCreator(state=state, repository=REPOSITORY)
    return creator.create(
        route=route, requested_harness=requested_harness, issue=issue, at=at
    )


def linked_pull_requests(*, numbers: Sequence[int]) -> str:
    """Return what gh says when these pull requests are linked to an issue."""
    return json.dumps(
        {
            "number": 12,
            "title": "The issue title",
            "closedByPullRequestsReferences": [{"number": one} for one in numbers],
        }
    )


@pytest.fixture
def checkout(cloned):
    """A main checkout with an origin and an assignment configuration."""
    (cloned / _DREAMCATCHER_CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
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
    record = state.assignments / ASSIGNMENT_ID / "assignment.json"
    return AssignmentRecord.model_validate_json(record.read_text(encoding="utf-8"))


def test_an_assignment_cuts_a_worktree_of_its_own_under_the_state_directory(
    state, route
):
    assignment = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert assignment.identifier == ASSIGNMENT_ID
    assert assignment.record.worktree == state.worktrees / ASSIGNMENT_ID
    assert (assignment.record.worktree / "README.md").exists()


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

    assignment = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert assignment.record.branch == BRANCH
    assert BRANCH in git(arguments=["branch", "--list", BRANCH], cwd=state.root)
    assert (assignment.record.worktree / "later.txt").exists()


def test_an_assignment_records_its_settled_dispatch_recipe(state, route):
    assignment = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert written(state=state) == assignment.record
    assert assignment.record.issue == 12
    assert assignment.record.title == "The issue title"
    assert assignment.record.dispatch_label == "dream:smith"
    assert assignment.record.pull_request == PULL_REQUEST
    assert assignment.record.pull_request_observation == PullRequestObservation(
        state=PullRequestState.OPEN,
        is_draft=True,
        observed_at=PINNED,
    )
    assert assignment.record.harness == AgentHarness.CLAUDE
    assert assignment.record.model == "opus[1m]"
    assert assignment.record.effort == "xhigh"
    assert assignment.record.prompt.startswith("/dream:smith GH12\n")
    record = state.assignments / ASSIGNMENT_ID / "assignment.json"
    assert '"dispatch_label": "dream:smith"' in record.read_text(encoding="utf-8")


def test_an_assignment_titles_its_pull_request_after_its_issue(state, route, gh):
    create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    created = next(call for call in gh.calls if call.arguments[:2] == ["pr", "create"])
    assert (
        created.arguments[created.arguments.index("--title") + 1] == "The issue title"
    )


def test_an_assignment_runs_on_the_harness_the_run_named(state, route):
    assignment = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CODEX,
        issue=12,
        at=PINNED,
    )

    assert assignment.record.harness == AgentHarness.CODEX
    assert assignment.record.model == "gpt-5.6-sol"
    assert assignment.record.prompt.startswith("$dream:smith GH12\n")


def test_a_new_assignment_has_run_no_rounds_and_its_next_is_its_first(state, route):
    assignment = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert assignment.rounds == []
    assert assignment.compose_round_paths(number=1) == AgentRoundPaths(
        worktree=assignment.record.worktree,
        rounds_directory=state.assignments / ASSIGNMENT_ID / "rounds",
        number=1,
    )


def standing(*, state, rounds: Sequence[AgentRoundRecord]):
    """Return the assignment that these rounds leave behind, read back from disk."""
    directory = write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=12)
    for number, record in enumerate(rounds, start=1):
        write_round(directory=directory, number=number, record=record)
    return read_assignments(state=state)[0]


def test_assignments_at_one_issue_are_read_behind_the_assignment_boundary(fabricated):
    write_assignment(state=fabricated, identifier="GH12-20260818-090000", issue=12)
    write_assignment(state=fabricated, identifier="GH13-20260819-090000", issue=13)
    write_assignment(state=fabricated, identifier="GH12-20260820-090000", issue=12)

    assignments = read_assignments_for_issue(state=fabricated, issue=12)

    assert [assignment.identifier for assignment in assignments] == [
        "GH12-20260818-090000",
        "GH12-20260820-090000",
    ]


def test_open_assignments_are_found_by_issue_across_assignment_histories(fabricated):
    for issue in (13, 14):
        complete = write_assignment(
            state=fabricated, identifier=f"GH{issue}-20260818-090000", issue=issue
        )
        write_round(
            directory=complete,
            number=1,
            record=AgentRoundRecord(
                number=1,
                started=PINNED,
                pid=1,
                purpose=AssignmentRoundPurpose.WRAP_UP,
                ending=_compose_agent_round_ending(at=PINNED, status=0),
            ),
        )
    write_assignment(state=fabricated, identifier="GH14-20260819-090000", issue=14)
    assignments = read_assignments(state=fabricated)

    open_assignments = find_open_assignments_by_issue(assignments=assignments)

    assert 12 not in open_assignments
    assert 13 not in open_assignments
    assert open_assignments[14].identifier == "GH14-20260819-090000"


def ended(*, status, minute=0, number: int = 1):
    """Return a round that started that minute past the hour and ended."""
    started = PINNED + timedelta(minutes=minute)
    return AgentRoundRecord(
        number=number,
        started=started,
        pid=1,
        purpose=AssignmentRoundPurpose.IMPLEMENT,
        ending=_compose_agent_round_ending(at=started, status=status),
    )


def running(*, minute=0, number: int = 1):
    """Return a round that started that minute past the hour and is still going."""
    return AgentRoundRecord(
        number=number,
        started=PINNED + timedelta(minutes=minute),
        pid=1,
        purpose=AssignmentRoundPurpose.IMPLEMENT,
    )


def test_a_round_an_assignment_has_run_is_found_by_the_number_it_ran_as(fabricated):
    assignment = standing(
        state=fabricated,
        rounds=[ended(status=0), ended(status=0, minute=1, number=2)],
    )

    assert assignment.compose_round_paths(number=2) == AgentRoundPaths(
        worktree=assignment.record.worktree,
        rounds_directory=fabricated.assignments / ASSIGNMENT_ID / "rounds",
        number=2,
    )


def test_an_assignment_that_has_run_no_round_has_left_nothing_unfinished(fabricated):
    assignment = standing(state=fabricated, rounds=[])

    assert assignment.describe_unfinished_round() is None
    assert not assignment.is_complete


def test_an_assignment_whose_last_round_has_no_ending_says_nothing(fabricated):
    assignment = standing(state=fabricated, rounds=[running()])

    assert assignment.describe_unfinished_round() is None


def test_an_assignment_whose_last_round_was_interrupted_says_so(fabricated):
    interrupted = running().model_copy(update={"ending": InterruptedAgentRoundEnding()})
    assignment = standing(state=fabricated, rounds=[interrupted])

    assert assignment.describe_unfinished_round() == "the last round was interrupted"


def test_an_assignment_whose_last_round_failed_says_the_status_it_failed_with(
    fabricated,
):
    assignment = standing(state=fabricated, rounds=[ended(status=2)])

    assert assignment.describe_unfinished_round() == "the last round failed (exit 2)"


def test_an_assignment_whose_last_round_ended_well_has_left_nothing_unfinished(
    fabricated,
):
    assignment = standing(
        state=fabricated,
        rounds=[ended(status=1), ended(status=0, minute=1, number=2)],
    )

    assert assignment.describe_unfinished_round() is None


def test_a_successful_wrap_up_completes_an_assignment(fabricated):
    assignment = standing(
        state=fabricated,
        rounds=[
            ended(status=0),
            AgentRoundRecord(
                number=2,
                started=PINNED + timedelta(minutes=1),
                pid=1,
                purpose=AssignmentRoundPurpose.WRAP_UP,
                is_recovery=True,
                ending=_compose_agent_round_ending(
                    at=PINNED + timedelta(minutes=1), status=0
                ),
            ),
        ],
    )

    assert assignment.is_complete


def test_only_the_final_round_can_complete_an_assignment(fabricated):
    assignment = standing(
        state=fabricated,
        rounds=[
            AgentRoundRecord(
                number=1,
                started=PINNED,
                pid=1,
                purpose=AssignmentRoundPurpose.WRAP_UP,
                ending=_compose_agent_round_ending(at=PINNED, status=0),
            ),
            ended(status=0, minute=1, number=2),
        ],
    )

    assert not assignment.is_complete


def test_a_cancelled_assignment_records_when_and_is_no_longer_open(fabricated):
    assignment = standing(state=fabricated, rounds=[ended(status=0)])

    cancel_assignment(assignment=assignment, at=PINNED + timedelta(hours=1))

    cancelled = read_assignments(state=fabricated)[0]
    assert cancelled.record.cancelled_at == PINNED + timedelta(hours=1)
    assert not cancelled.is_open
    assert find_open_assignments_by_issue(assignments=[cancelled]) == {}


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

    assert read_assignments(state=fabricated)[0].record.cancelled_at == PINNED


@pytest.mark.parametrize(
    "record",
    [
        AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
            ending=_compose_agent_round_ending(at=PINNED, status=0),
        ),
        AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=AssignmentRoundPurpose.WRAP_UP,
            ending=_compose_agent_round_ending(at=PINNED, status=1),
        ),
        AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=AssignmentRoundPurpose.WRAP_UP,
            ending=InterruptedAgentRoundEnding(),
        ),
    ],
)
def test_anything_other_than_a_successful_wrap_up_leaves_an_assignment_open(
    fabricated, record
):
    assignment = standing(state=fabricated, rounds=[record])

    assert not assignment.is_complete


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
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert git(arguments=["branch", "--list", BRANCH], cwd=state.root) == ""


def test_an_assignment_that_cannot_record_reuses_its_complete_setup(state, route, gh):
    state.assignments.mkdir(parents=True)
    (state.assignments / ASSIGNMENT_ID).write_text(
        "something else is here\n", encoding="utf-8"
    )

    with pytest.raises(ReportableError, match="cannot write"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert (state.worktrees / ASSIGNMENT_ID).exists()
    assert BRANCH in git(arguments=["branch", "--list", BRANCH], cwd=state.root)

    (state.assignments / ASSIGNMENT_ID).unlink()
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(stdout=linked_pull_requests(numbers=[PULL_REQUEST]), to="issue view")
    gh.replies(stdout=pull_request(state="OPEN", is_draft=True), to="pr view")
    recovered = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED + timedelta(hours=1),
    )

    assert recovered.identifier == ASSIGNMENT_ID
    commits = git(
        arguments=["rev-list", "--count", "origin/main..HEAD"],
        cwd=recovered.record.worktree,
    )
    assert commits.strip() == "1"
    created = [call for call in gh.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == 1


@pytest.mark.parametrize("checkpoint", ["worktree", "commit", "push", "pull request"])
def test_an_interrupted_creation_continues_from_its_existing_artifacts(
    state, route, gh, checkpoint
):
    fetch_main(root=state.root)
    worktree = state.worktrees / ASSIGNMENT_ID
    add_worktree(root=state.root, path=worktree, branch=BRANCH)
    if checkpoint != "worktree":
        make_empty_commit(worktree=worktree, message="GH12")
    if checkpoint in {"push", "pull request"}:
        push_branch(root=state.root, branch=BRANCH)
    if checkpoint == "pull request":
        gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
        gh.replies(stdout=linked_pull_requests(numbers=[PULL_REQUEST]), to="issue view")

    recovered = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED + timedelta(hours=1),
    )

    assert recovered.identifier == ASSIGNMENT_ID
    assert recovered.record.pull_request == PULL_REQUEST
    commits = git(arguments=["rev-list", "--count", "origin/main..HEAD"], cwd=worktree)
    assert commits.strip() == "1"
    remote = git(arguments=["ls-remote", "--heads", "origin", BRANCH], cwd=state.root)
    assert f"refs/heads/{BRANCH}" in remote
    created = [call for call in gh.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == (0 if checkpoint == "pull request" else 1)


def test_an_issue_with_an_open_assignment_cannot_receive_another(state, route, gh):
    create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    with pytest.raises(ReportableError, match="already has open assignment"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED + timedelta(hours=1),
        )

    assert len(list(state.worktrees.iterdir())) == 1
    branches = git(
        arguments=["branch", "--list", "dreamcatcher-GH12-*"], cwd=state.root
    )
    assert len(branches.splitlines()) == 1
    remote = git(
        arguments=["ls-remote", "--heads", "origin", "dreamcatcher-GH12-*"],
        cwd=state.root,
    )
    assert len(remote.splitlines()) == 1
    created = [call for call in gh.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == 1


def test_an_issue_whose_assignment_finished_can_receive_another(state, route):
    first = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    write_round(
        directory=first.directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=AssignmentRoundPurpose.WRAP_UP,
            ending=_compose_agent_round_ending(at=PINNED, status=0),
        ),
    )

    second = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED + timedelta(hours=1),
    )

    assert second.identifier == "GH12-20260819-194158"


@pytest.mark.parametrize(
    "ending",
    [
        None,
        InterruptedAgentRoundEnding(),
        _compose_agent_round_ending(at=PINNED, status=1),
    ],
)
def test_an_issue_whose_final_work_is_unfinished_cannot_receive_another(
    state, route, ending
):
    first = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    write_round(
        directory=first.directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=AssignmentRoundPurpose.WRAP_UP,
            ending=ending,
        ),
    )

    with pytest.raises(ReportableError, match="already has open assignment"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED + timedelta(hours=1),
        )


def test_several_incomplete_setups_for_one_issue_are_reported(state, route):
    fetch_main(root=state.root)
    for identifier in (ASSIGNMENT_ID, "GH12-20260819-194158"):
        add_worktree(
            root=state.root,
            path=state.worktrees / identifier,
            branch=f"dreamcatcher-{identifier}",
        )

    with pytest.raises(ReportableError, match="several incomplete assignment setups"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED + timedelta(hours=2),
        )

    failures = inspect_incomplete_assignment_setups(state=state, repository=REPOSITORY)

    failure = failures[12]
    assert failure is not None
    assert failure.startswith("GH12 has several incomplete assignment setups: GH12-")


def test_an_incomplete_setup_without_a_pull_request_is_recoverable(state, gh):
    fetch_main(root=state.root)
    add_worktree(
        root=state.root,
        path=state.worktrees / ASSIGNMENT_ID,
        branch=BRANCH,
    )

    assert inspect_incomplete_assignment_setups(state=state, repository=REPOSITORY) == {
        12: None
    }


def test_an_incomplete_setup_with_its_linked_draft_is_recoverable(state, gh):
    fetch_main(root=state.root)
    add_worktree(
        root=state.root,
        path=state.worktrees / ASSIGNMENT_ID,
        branch=BRANCH,
    )
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(stdout=linked_pull_requests(numbers=[PULL_REQUEST]), to="issue view")

    assert inspect_incomplete_assignment_setups(state=state, repository=REPOSITORY) == {
        12: None
    }


def test_an_incomplete_worktree_on_another_branch_is_reported(state, route):
    fetch_main(root=state.root)
    add_worktree(
        root=state.root,
        path=state.worktrees / ASSIGNMENT_ID,
        branch="some-other-branch",
    )

    with pytest.raises(ReportableError, match="some-other-branch, not dreamcatcher"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    failures = inspect_incomplete_assignment_setups(state=state, repository=REPOSITORY)

    assert failures[12] is not None
    assert "some-other-branch, not dreamcatcher" in failures[12]


@pytest.mark.parametrize("state_name", ["CLOSED", "MERGED"])
def test_a_finished_pull_request_on_the_incomplete_branch_is_not_adopted(
    state, route, gh, state_name
):
    fetch_main(root=state.root)
    worktree = state.worktrees / ASSIGNMENT_ID
    add_worktree(root=state.root, path=worktree, branch=BRANCH)
    make_empty_commit(worktree=worktree, message="GH12")
    push_branch(root=state.root, branch=BRANCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, state_name)]), to="pr list")

    with pytest.raises(ReportableError, match=state_name.lower()):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert not (state.assignments / ASSIGNMENT_ID / "assignment.json").exists()


def test_an_unlinked_pull_request_on_the_incomplete_branch_is_not_adopted(
    state, route, gh
):
    fetch_main(root=state.root)
    worktree = state.worktrees / ASSIGNMENT_ID
    add_worktree(root=state.root, path=worktree, branch=BRANCH)
    make_empty_commit(worktree=worktree, message="GH12")
    push_branch(root=state.root, branch=BRANCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")

    with pytest.raises(ReportableError, match="is not linked to GH12"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert not (state.assignments / ASSIGNMENT_ID / "assignment.json").exists()


def test_a_ready_pull_request_on_the_incomplete_branch_is_not_adopted(state, route, gh):
    fetch_main(root=state.root)
    worktree = state.worktrees / ASSIGNMENT_ID
    add_worktree(root=state.root, path=worktree, branch=BRANCH)
    make_empty_commit(worktree=worktree, message="GH12")
    push_branch(root=state.root, branch=BRANCH)
    gh.replies(
        stdout=json.dumps(
            [{"number": PULL_REQUEST, "state": "OPEN", "isDraft": False}]
        ),
        to="pr list",
    )
    gh.replies(stdout=linked_pull_requests(numbers=[PULL_REQUEST]), to="issue view")

    with pytest.raises(ReportableError, match="ready for review rather than draft"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )


def test_a_pull_request_listing_failure_keeps_the_setup_for_a_retry(state, route, gh):
    gh.fails(stderr="gh: could not connect to github.com", to="pr list")

    with pytest.raises(ReportableError, match="cannot reconcile the pull request"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert (state.worktrees / ASSIGNMENT_ID).exists()


def test_a_linked_pull_request_read_failure_keeps_the_setup_for_a_retry(
    state, route, gh
):
    gh.fails(stderr="gh: could not connect to github.com", to="issue view")

    with pytest.raises(
        ReportableError, match="cannot tell whether another pull request claims GH12"
    ):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert (state.worktrees / ASSIGNMENT_ID).exists()


def test_an_unrelated_linked_pull_request_prevents_another_one(state, route, gh):
    gh.replies(stdout=linked_pull_requests(numbers=[28]), to="issue view")

    with pytest.raises(ReportableError, match=r"open linked pull request \(#28\)"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    created = [call for call in gh.calls if call.arguments[:2] == ["pr", "create"]]
    assert created == []


def test_several_pull_requests_on_an_incomplete_branch_are_reported(state, route, gh):
    gh.replies(
        stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN"), (53, "CLOSED")]),
        to="pr list",
    )

    with pytest.raises(ReportableError, match="more than one pull request"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )


def test_a_created_pull_request_that_cannot_be_read_is_reconciled_next_time(
    state, route, gh
):
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")

    with pytest.raises(
        ReportableError, match=f"created the pull request for {BRANCH} but cannot read"
    ):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(stdout=linked_pull_requests(numbers=[PULL_REQUEST]), to="issue view")
    gh.replies(stdout=pull_request(state="OPEN", is_draft=True), to="pr view")
    recovered = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED + timedelta(hours=1),
    )

    assert recovered.identifier == ASSIGNMENT_ID
    created = [call for call in gh.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == 1


def test_a_created_pull_request_that_is_not_a_draft_is_reported(state, route, gh):
    gh.replies(stdout=pull_request(state="OPEN", is_draft=False), to="pr view")

    with pytest.raises(ReportableError, match="was not created as an open draft"):
        create_assignment(
            state=state,
            route=route,
            requested_harness=AgentHarness.CLAUDE,
            issue=12,
            at=PINNED,
        )


def test_a_state_directory_with_no_worktrees_holds_no_assignments(state):
    assert read_assignments(state=state) == []


def test_an_assignment_reads_back_with_its_settled_dispatch_recipe(state, route):
    created = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert read_assignments(state=state) == [created]


def test_an_assignment_record_from_before_titles_and_pull_request_observations_reads(
    fabricated,
):
    directory = write_assignment(
        state=fabricated,
        identifier=ASSIGNMENT_ID,
        issue=12,
    )
    path = directory / "assignment.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["title"]
    del document["pull_request_observation"]
    path.write_bytes((json.dumps(document) + "\n").encode())

    record = read_assignments(state=fabricated)[0].record

    assert record.title is None
    assert record.pull_request_observation is None


def test_an_assignment_records_the_harness_session_its_first_round_reports(fabricated):
    write_assignment(
        state=fabricated,
        identifier=ASSIGNMENT_ID,
        issue=12,
        harness_session_identifier=None,
    )
    assignment = read_assignments(state=fabricated)[0]

    record_assignment_harness_session_identifier(
        assignment=assignment, identifier="abc-123"
    )
    record_assignment_harness_session_identifier(
        assignment=assignment, identifier="abc-123"
    )

    recorded = read_assignments(state=fabricated)[0]
    assert recorded.record.harness_session_identifier == "abc-123"


def test_an_assignment_recovers_a_session_reported_by_a_later_round(fabricated):
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
                purpose=AssignmentRoundPurpose.IMPLEMENT,
                is_recovery=number == 2,
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

    recovered = assignment.find_harness_session_identifier()

    assert recovered == "replacement-session"


def test_a_legacy_assignment_records_only_the_first_issue_title(fabricated):
    directory = write_assignment(
        state=fabricated,
        identifier=ASSIGNMENT_ID,
        issue=12,
    )
    assignment = read_assignments(state=fabricated)[0]

    record_assignment_title(assignment=assignment, title="First title")
    assignment = read_assignments(state=fabricated)[0]
    path = directory / "assignment.json"
    first_recording = path.read_bytes()
    record_assignment_title(assignment=assignment, title="Later title")

    recorded = read_assignments(state=fabricated)[0]
    assert recorded.record.title == "First title"
    assert path.read_bytes() == first_recording


def test_an_assignment_records_a_changed_pull_request_observation(fabricated):
    write_assignment(state=fabricated, identifier=ASSIGNMENT_ID, issue=12)
    assignment = read_assignments(state=fabricated)[0]
    record_pull_request_observation(
        assignment=assignment,
        pull_request=PullRequest(
            number=PULL_REQUEST,
            state=PullRequestState.OPEN,
            is_draft=True,
        ),
        observed_at=PINNED,
    )

    record_pull_request_observation(
        assignment=assignment,
        pull_request=PullRequest(
            number=PULL_REQUEST,
            state=PullRequestState.OPEN,
            is_draft=False,
        ),
        observed_at=PINNED + timedelta(minutes=1),
    )

    recorded = read_assignments(state=fabricated)[0]
    assert recorded.record.pull_request_observation == PullRequestObservation(
        state=PullRequestState.OPEN,
        is_draft=False,
        observed_at=PINNED + timedelta(minutes=1),
    )


def test_an_unchanged_pull_request_observation_leaves_the_record_untouched(fabricated):
    directory = write_assignment(
        state=fabricated,
        identifier=ASSIGNMENT_ID,
        issue=12,
    )
    assignment = read_assignments(state=fabricated)[0]
    pull_request = PullRequest(
        number=PULL_REQUEST,
        state=PullRequestState.OPEN,
        is_draft=True,
    )
    record_pull_request_observation(
        assignment=assignment,
        pull_request=pull_request,
        observed_at=PINNED,
    )
    path = directory / "assignment.json"
    before = path.read_bytes()

    record_pull_request_observation(
        assignment=assignment,
        pull_request=pull_request,
        observed_at=PINNED + timedelta(minutes=1),
    )

    assert path.read_bytes() == before


def test_an_assignment_refuses_a_different_harness_session(fabricated):
    write_assignment(
        state=fabricated,
        identifier=ASSIGNMENT_ID,
        issue=12,
        harness_session_identifier="abc-123",
    )
    assignment = read_assignments(state=fabricated)[0]

    with pytest.raises(ReportableError, match="but its record names abc-123"):
        record_assignment_harness_session_identifier(
            assignment=assignment, identifier="another-session"
        )


@pytest.mark.parametrize(
    ("identifier", "message"),
    [
        ("", "identifier is empty"),
        ("bad%identifier", "cannot hold a percent sign"),
        ("--last", "must begin with a letter or digit"),
        ("abc; touch another-file", "contain only ASCII letters"),
    ],
)
def test_an_assignment_refuses_an_invalid_harness_session_identifier(
    fabricated, identifier, message
):
    write_assignment(state=fabricated, identifier=ASSIGNMENT_ID, issue=12)
    assignment = read_assignments(state=fabricated)[0]

    with pytest.raises(ReportableError, match=message):
        record_assignment_harness_session_identifier(
            assignment=assignment, identifier=identifier
        )


def test_an_assignment_no_round_has_delivered_a_user_post_has_an_empty_cursor(
    state, route
):
    create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert read_assignments(state=state)[0].user_post_delivery_cursor == ""


def test_an_assignment_reads_back_its_user_post_delivery_cursor(state, route):
    created = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    write_round(
        directory=created.directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
            started=PINNED,
            pid=1,
            ending=_compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    write_json(
        document=AssignmentRoundInput(
            pull_request_state=PullRequestState.OPEN,
            user_posts=[
                ConversationComment.model_validate(
                    comment(created_at="2026-09-03T22:31:51Z")
                )
            ],
        ),
        path=created.compose_round_paths(number=1).round_input,
    )

    assert (
        read_assignments(state=state)[0].user_post_delivery_cursor
        == "2026-09-03T22:31:51Z"
    )


def test_the_user_post_cursor_scans_past_an_input_that_delivered_no_posts(state, route):
    created = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    for number, posts in (
        (
            1,
            [
                ConversationComment.model_validate(
                    comment(created_at="2026-09-03T22:31:51Z")
                )
            ],
        ),
        (2, []),
    ):
        write_round(
            directory=created.directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                purpose=AssignmentRoundPurpose.IMPLEMENT,
                started=PINNED + timedelta(minutes=number),
                pid=1,
                ending=_compose_agent_round_ending(at=PINNED, status=0),
            ),
        )
        write_json(
            document=AssignmentRoundInput(
                pull_request_state=PullRequestState.OPEN,
                user_posts=posts,
            ),
            path=created.compose_round_paths(number=number).round_input,
        )

    assert (
        read_assignments(state=state)[0].user_post_delivery_cursor
        == "2026-09-03T22:31:51Z"
    )


def test_an_assignments_rounds_read_back_in_number_order(state, route):
    create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    later = PINNED.replace(minute=50)
    directory = state.assignments / ASSIGNMENT_ID
    write_round(
        directory=directory,
        number=3,
        record=AgentRoundRecord(
            number=3,
            started=PINNED,
            pid=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
        ),
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=later,
            pid=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
            ending=_compose_agent_round_ending(at=later, status=0),
        ),
    )

    read = read_assignments(state=state)[0]

    assert [record.number for record in read.rounds] == [1, 3]
    assert [record.started for record in read.rounds] == [later, PINNED]
    assert read.next_round_number == 4
    assert (
        read.compose_round_paths(number=read.next_round_number).directory
        == state.assignments / ASSIGNMENT_ID / "rounds" / "4"
    )


def test_a_round_record_must_carry_the_number_of_its_directory(state, route):
    create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    write_round(
        directory=state.assignments / ASSIGNMENT_ID,
        number=2,
        record=AgentRoundRecord(
            number=3,
            started=PINNED,
            pid=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
        ),
    )

    with pytest.raises(ReportableError, match="says it is round 3"):
        read_assignments(state=state)


def test_every_assignment_of_the_repo_reads_back_by_identifier(state, route):
    create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=3,
        at=PINNED,
    )

    assert [assignment.identifier for assignment in read_assignments(state=state)] == [
        "GH12-20260819-184158",
        "GH3-20260819-184158",
    ]


def test_a_file_left_among_the_worktrees_is_not_an_assignment(state, route):
    created = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    (state.worktrees / ".DS_Store").write_text("a file browser\n", encoding="utf-8")

    assert read_assignments(state=state) == [created]


def test_a_worktree_with_no_record_beside_it_is_not_an_assignment(state, route):
    created = create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    (state.worktrees / "GH3-20260819-184158").mkdir()

    assert read_assignments(state=state) == [created]


def test_an_assignment_record_that_will_not_read_names_the_file(state, route):
    create_assignment(
        state=state,
        route=route,
        requested_harness=AgentHarness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    (state.assignments / ASSIGNMENT_ID / "assignment.json").write_text(
        "{}", encoding="utf-8"
    )

    with pytest.raises(ReportableError, match=r"assignment\.json is not valid"):
        read_assignments(state=state)
