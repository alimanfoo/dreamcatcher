import json
from collections.abc import Sequence
from datetime import timedelta

import pytest
from clocks import PINNED
from conftest import (
    CONFIG,
    PULL_REQUEST,
    REPOSITORY,
    commit,
    git,
    pull_request,
    pull_requests,
)
from records import write_agent_assignment, write_round

from dreamcatcher.agent_assignments import (
    WATERMARK,
    AgentAssignmentCreator,
    AgentAssignmentRecord,
    advance_assignment_watermark,
    inspect_incomplete_assignment_setups,
    read_agent_assignments,
    read_agent_assignments_for_issue,
)
from dreamcatcher.agent_rounds import (
    AgentRoundPaths,
    AgentRoundRecord,
    InterruptedAgentRoundEnding,
    RoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.commands import CommandError
from dreamcatcher.config import CONFIG_NAME, Harness, read_config
from dreamcatcher.documents import write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import add_worktree, fetch, make_empty_commit, push_branch
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH12-20260819-184158"

BRANCH = f"dreamcatcher-{ASSIGNMENT_ID}"


def create_agent_assignment(*, state, route, named, issue, at):
    """Create one assignment through the repository's creation boundary."""
    creator = AgentAssignmentCreator(state=state, repository=REPOSITORY)
    return creator.create(route=route, named=named, issue=issue, at=at)


def linked_pull_requests(*, numbers: Sequence[int]) -> str:
    """Return what gh says when these pull requests are linked to an issue."""
    return json.dumps(
        {"closedByPullRequestsReferences": [{"number": one} for one in numbers]}
    )


@pytest.fixture
def checkout(cloned):
    """A main checkout with an origin to cut from and a config to dispatch by."""
    (cloned / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
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
    """The dispatch route of the one label that the config maps."""
    return read_config(root=checkout).dispatch[0]


def written(*, state):
    """Return the record that the assignment wrote about itself."""
    record = state.assignments / ASSIGNMENT_ID / "assignment.json"
    return AgentAssignmentRecord.model_validate_json(record.read_text(encoding="utf-8"))


def test_an_assignment_cuts_a_worktree_of_its_own_under_the_state_directory(
    state, route
):
    assignment = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
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

    assignment = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert assignment.record.branch == BRANCH
    assert BRANCH in git(arguments=["branch", "--list", BRANCH], cwd=state.root)
    assert (assignment.record.worktree / "later.txt").exists()


def test_an_assignment_records_what_it_was_dispatched_with(state, route):
    assignment = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert written(state=state) == assignment.record
    assert assignment.record.issue == 12
    assert assignment.record.label == "dream:smith"
    assert assignment.record.pull_request == PULL_REQUEST
    assert assignment.record.harness == Harness.CLAUDE
    assert assignment.record.model == "opus[1m]"
    assert assignment.record.effort == "xhigh"
    assert assignment.record.prompt.startswith("/dream:smith GH12\n")


def test_an_assignment_runs_on_the_harness_the_run_named(state, route):
    assignment = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CODEX,
        issue=12,
        at=PINNED,
    )

    assert assignment.record.harness == Harness.CODEX
    assert assignment.record.model == "gpt-5.6-sol"
    assert assignment.record.prompt.startswith("$dream:smith GH12\n")


def test_a_new_assignment_has_run_no_rounds_and_its_next_is_its_first(state, route):
    assignment = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert assignment.rounds == []
    assert assignment.next_workspace == AgentRoundPaths(
        worktree=assignment.record.worktree,
        directory=state.assignments / ASSIGNMENT_ID / "rounds" / "1",
    )


def standing(*, state, rounds: Sequence[AgentRoundRecord]):
    """Return the assignment that these rounds leave behind, read back from disk."""
    directory = write_agent_assignment(state=state, identifier=ASSIGNMENT_ID, issue=12)
    for number, record in enumerate(rounds, start=1):
        write_round(directory=directory, number=number, record=record)
    return read_agent_assignments(state=state)[0]


def test_assignments_at_one_issue_are_read_behind_the_assignment_boundary(fabricated):
    write_agent_assignment(
        state=fabricated, identifier="GH12-20260818-090000", issue=12
    )
    write_agent_assignment(
        state=fabricated, identifier="GH13-20260819-090000", issue=13
    )
    write_agent_assignment(
        state=fabricated, identifier="GH12-20260820-090000", issue=12
    )

    assignments = read_agent_assignments_for_issue(state=fabricated, issue=12)

    assert [assignment.identifier for assignment in assignments] == [
        "GH12-20260818-090000",
        "GH12-20260820-090000",
    ]


def ended(*, status, minute=0, number: int = 1):
    """Return a round that started that minute past the hour and ended."""
    started = PINNED + timedelta(minutes=minute)
    return AgentRoundRecord(
        number=number,
        started=started,
        pid=1,
        purpose=RoundPurpose.IMPLEMENT,
        ending=compose_agent_round_ending(at=started, status=status),
    )


def running(*, minute=0, number: int = 1):
    """Return a round that started that minute past the hour and is still going."""
    return AgentRoundRecord(
        number=number,
        started=PINNED + timedelta(minutes=minute),
        pid=1,
        purpose=RoundPurpose.IMPLEMENT,
    )


def test_a_round_an_assignment_has_run_is_found_by_the_number_it_ran_as(fabricated):
    assignment = standing(
        state=fabricated,
        rounds=[ended(status=0), ended(status=0, minute=1, number=2)],
    )

    assert assignment.workspace(number=2) == AgentRoundPaths(
        worktree=assignment.record.worktree,
        directory=fabricated.assignments / ASSIGNMENT_ID / "rounds" / "2",
    )


def test_an_assignment_that_has_run_no_round_has_left_nothing_unfinished(fabricated):
    assignment = standing(state=fabricated, rounds=[])

    assert assignment.describe_unfinished_round() is None
    assert not assignment.is_complete


def test_an_assignment_whose_last_round_was_interrupted_says_so(fabricated):
    assignment = standing(state=fabricated, rounds=[running()])

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
                purpose=RoundPurpose.WRAP_UP,
                is_recovery=True,
                ending=compose_agent_round_ending(
                    at=PINNED + timedelta(minutes=1), status=0
                ),
            ),
        ],
    )

    assert assignment.is_complete


@pytest.mark.parametrize(
    "record",
    [
        AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=RoundPurpose.IMPLEMENT,
            ending=compose_agent_round_ending(at=PINNED, status=0),
        ),
        AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=RoundPurpose.WRAP_UP,
            ending=compose_agent_round_ending(at=PINNED, status=1),
        ),
        AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=RoundPurpose.WRAP_UP,
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
    return [record.ending for record in read_agent_assignments(state=state)[0].rounds]


def test_a_second_read_does_not_open_a_round_record_it_has_already_read(fabricated):
    directory = write_agent_assignment(
        state=fabricated, identifier=ASSIGNMENT_ID, issue=12
    )
    write_round(directory=directory, number=1, record=ended(status=0))
    write_round(directory=directory, number=2, record=running(minute=1, number=2))
    read_agent_assignments(state=fabricated)

    # Rewriting the first round's record puts something there that only a read
    # of that file could find. A reader that has read it does not look again.
    write_round(directory=directory, number=1, record=ended(status=2))

    assert endings(state=fabricated) == [ended(status=0).ending, None]


def test_a_second_read_carries_an_ending_that_landed_since_the_first(fabricated):
    directory = write_agent_assignment(
        state=fabricated, identifier=ASSIGNMENT_ID, issue=12
    )
    write_round(directory=directory, number=1, record=running())
    read_agent_assignments(state=fabricated)

    write_round(directory=directory, number=1, record=ended(status=0))

    assert endings(state=fabricated) == [ended(status=0).ending]


def test_a_second_read_finds_a_round_that_has_started_since_the_first(fabricated):
    directory = write_agent_assignment(
        state=fabricated, identifier=ASSIGNMENT_ID, issue=12
    )
    write_round(directory=directory, number=1, record=ended(status=0))
    read_agent_assignments(state=fabricated)

    write_round(directory=directory, number=2, record=running(minute=1, number=2))

    read = read_agent_assignments(state=fabricated)[0]

    assert [record.started for record in read.rounds] == [
        PINNED,
        PINNED + timedelta(minutes=1),
    ]


def test_a_round_that_ended_as_a_later_round_started_reads_back_ended(fabricated):
    directory = write_agent_assignment(
        state=fabricated, identifier=ASSIGNMENT_ID, issue=12
    )
    write_round(directory=directory, number=1, record=running())
    read_agent_assignments(state=fabricated)

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
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
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
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert (state.worktrees / ASSIGNMENT_ID).exists()
    assert BRANCH in git(arguments=["branch", "--list", BRANCH], cwd=state.root)

    (state.assignments / ASSIGNMENT_ID).unlink()
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(stdout=linked_pull_requests(numbers=[PULL_REQUEST]), to="issue view")
    gh.replies(stdout=pull_request(state="OPEN", is_draft=True), to="pr view")
    recovered = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
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
    fetch(root=state.root)
    worktree = state.worktrees / ASSIGNMENT_ID
    add_worktree(root=state.root, path=worktree, branch=BRANCH)
    if checkpoint != "worktree":
        make_empty_commit(worktree=worktree, message="GH12")
    if checkpoint in {"push", "pull request"}:
        push_branch(root=state.root, branch=BRANCH)
    if checkpoint == "pull request":
        gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
        gh.replies(stdout=linked_pull_requests(numbers=[PULL_REQUEST]), to="issue view")

    recovered = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
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
    create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    with pytest.raises(ReportableError, match="already has open assignment"):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
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
    first = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
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
            purpose=RoundPurpose.WRAP_UP,
            ending=compose_agent_round_ending(at=PINNED, status=0),
        ),
    )

    second = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED + timedelta(hours=1),
    )

    assert second.identifier == "GH12-20260819-194158"


@pytest.mark.parametrize(
    "ending",
    [
        None,
        InterruptedAgentRoundEnding(),
        compose_agent_round_ending(at=PINNED, status=1),
    ],
)
def test_an_issue_whose_final_work_is_unfinished_cannot_receive_another(
    state, route, ending
):
    first = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
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
            purpose=RoundPurpose.WRAP_UP,
            ending=ending,
        ),
    )

    with pytest.raises(ReportableError, match="already has open assignment"):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED + timedelta(hours=1),
        )


def test_several_incomplete_setups_for_one_issue_are_reported(state, route):
    fetch(root=state.root)
    for identifier in (ASSIGNMENT_ID, "GH12-20260819-194158"):
        add_worktree(
            root=state.root,
            path=state.worktrees / identifier,
            branch=f"dreamcatcher-{identifier}",
        )

    with pytest.raises(ReportableError, match="several incomplete assignment setups"):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED + timedelta(hours=2),
        )

    obstacles = inspect_incomplete_assignment_setups(state=state, repository=REPOSITORY)

    obstacle = obstacles[12]
    assert obstacle is not None
    assert obstacle.startswith("GH12 has several incomplete assignment setups: GH12-")


def test_an_incomplete_setup_without_a_pull_request_is_recoverable(state, gh):
    fetch(root=state.root)
    add_worktree(
        root=state.root,
        path=state.worktrees / ASSIGNMENT_ID,
        branch=BRANCH,
    )

    assert inspect_incomplete_assignment_setups(state=state, repository=REPOSITORY) == {
        12: None
    }


def test_an_incomplete_setup_with_its_linked_draft_is_recoverable(state, gh):
    fetch(root=state.root)
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
    fetch(root=state.root)
    add_worktree(
        root=state.root,
        path=state.worktrees / ASSIGNMENT_ID,
        branch="some-other-branch",
    )

    with pytest.raises(ReportableError, match="some-other-branch, not dreamcatcher"):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    obstacles = inspect_incomplete_assignment_setups(state=state, repository=REPOSITORY)

    assert obstacles[12] is not None
    assert "some-other-branch, not dreamcatcher" in obstacles[12]


@pytest.mark.parametrize("state_name", ["CLOSED", "MERGED"])
def test_a_finished_pull_request_on_the_incomplete_branch_is_not_adopted(
    state, route, gh, state_name
):
    fetch(root=state.root)
    worktree = state.worktrees / ASSIGNMENT_ID
    add_worktree(root=state.root, path=worktree, branch=BRANCH)
    make_empty_commit(worktree=worktree, message="GH12")
    push_branch(root=state.root, branch=BRANCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, state_name)]), to="pr list")

    with pytest.raises(ReportableError, match=state_name.lower()):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert not (state.assignments / ASSIGNMENT_ID / "assignment.json").exists()


def test_an_unlinked_pull_request_on_the_incomplete_branch_is_not_adopted(
    state, route, gh
):
    fetch(root=state.root)
    worktree = state.worktrees / ASSIGNMENT_ID
    add_worktree(root=state.root, path=worktree, branch=BRANCH)
    make_empty_commit(worktree=worktree, message="GH12")
    push_branch(root=state.root, branch=BRANCH)
    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")

    with pytest.raises(ReportableError, match="is not linked to GH12"):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert not (state.assignments / ASSIGNMENT_ID / "assignment.json").exists()


def test_a_ready_pull_request_on_the_incomplete_branch_is_not_adopted(state, route, gh):
    fetch(root=state.root)
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
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED,
        )


def test_a_pull_request_listing_failure_keeps_the_setup_for_a_retry(state, route, gh):
    gh.fails(stderr="gh: could not connect to github.com", to="pr list")

    with pytest.raises(ReportableError, match="cannot reconcile the pull request"):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
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
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    assert (state.worktrees / ASSIGNMENT_ID).exists()


def test_an_unrelated_linked_pull_request_prevents_another_one(state, route, gh):
    gh.replies(stdout=linked_pull_requests(numbers=[28]), to="issue view")

    with pytest.raises(ReportableError, match=r"open linked pull request \(#28\)"):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
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
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED,
        )


def test_a_created_pull_request_that_cannot_be_read_is_reconciled_next_time(
    state, route, gh
):
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")

    with pytest.raises(ReportableError, match="cannot read the pull request created"):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED,
        )

    gh.replies(stdout=pull_requests(listed=[(PULL_REQUEST, "OPEN")]), to="pr list")
    gh.replies(stdout=linked_pull_requests(numbers=[PULL_REQUEST]), to="issue view")
    gh.replies(stdout=pull_request(state="OPEN", is_draft=True), to="pr view")
    recovered = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED + timedelta(hours=1),
    )

    assert recovered.identifier == ASSIGNMENT_ID
    created = [call for call in gh.calls if call.arguments[:2] == ["pr", "create"]]
    assert len(created) == 1


def test_a_created_pull_request_that_is_not_a_draft_is_reported(state, route, gh):
    gh.replies(stdout=pull_request(state="OPEN", is_draft=False), to="pr view")

    with pytest.raises(ReportableError, match="was not created as an open draft"):
        create_agent_assignment(
            state=state,
            route=route,
            named=Harness.CLAUDE,
            issue=12,
            at=PINNED,
        )


def test_a_state_directory_with_no_worktrees_holds_no_assignments(state):
    assert read_agent_assignments(state=state) == []


def test_an_assignment_reads_back_as_it_was_dispatched(state, route):
    created = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert read_agent_assignments(state=state) == [created]


def test_an_assignment_no_round_has_told_anything_yet_has_seen_no_post(state, route):
    create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    assert read_agent_assignments(state=state)[0].watermark == ""


def test_an_assignment_reads_back_the_newest_post_it_has_been_told_about(state, route):
    create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    write_text(
        text="2026-09-03T22:31:51Z\n",
        path=state.assignments / ASSIGNMENT_ID / WATERMARK,
    )

    assert read_agent_assignments(state=state)[0].watermark == "2026-09-03T22:31:51Z"


def test_an_assignment_told_about_a_batch_of_posts_reads_the_newest_of_them_back(
    state, route
):
    created = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )

    advance_assignment_watermark(assignment=created, newest="2026-09-03T22:31:51Z")

    assert read_agent_assignments(state=state)[0].watermark == "2026-09-03T22:31:51Z"


def test_an_assignments_rounds_read_back_in_number_order(state, route):
    create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    later = PINNED.replace(minute=50)
    directory = state.assignments / ASSIGNMENT_ID
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2, started=PINNED, pid=1, purpose=RoundPurpose.IMPLEMENT
        ),
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=later,
            pid=1,
            purpose=RoundPurpose.IMPLEMENT,
            ending=compose_agent_round_ending(at=later, status=0),
        ),
    )

    read = read_agent_assignments(state=state)[0]

    assert [record.number for record in read.rounds] == [1, 2]
    assert [record.started for record in read.rounds] == [later, PINNED]
    assert (
        read.next_workspace.directory
        == state.assignments / ASSIGNMENT_ID / "rounds" / "3"
    )


def test_every_assignment_of_the_repo_reads_back_by_identifier(state, route):
    create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=3,
        at=PINNED,
    )

    assert [
        assignment.identifier for assignment in read_agent_assignments(state=state)
    ] == [
        "GH12-20260819-184158",
        "GH3-20260819-184158",
    ]


def test_a_file_left_among_the_worktrees_is_not_an_assignment(state, route):
    created = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    (state.worktrees / ".DS_Store").write_text("a file browser\n", encoding="utf-8")

    assert read_agent_assignments(state=state) == [created]


def test_a_worktree_with_no_record_beside_it_is_not_an_assignment(state, route):
    created = create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    (state.worktrees / "GH3-20260819-184158").mkdir()

    assert read_agent_assignments(state=state) == [created]


def test_an_assignment_record_that_will_not_read_names_the_file(state, route):
    create_agent_assignment(
        state=state,
        route=route,
        named=Harness.CLAUDE,
        issue=12,
        at=PINNED,
    )
    (state.assignments / ASSIGNMENT_ID / "assignment.json").write_text(
        "{}", encoding="utf-8"
    )

    with pytest.raises(ReportableError, match=r"assignment\.json is not valid"):
        read_agent_assignments(state=state)
