import json
from collections.abc import Sequence
from itertools import product

import pytest
from conftest import FILED, LABEL, LATER, POSTED_BY, PULL_REQUEST, REPOSITORY, listing
from observations import observed_issue
from records import write_agent_assignment

from dreamcatcher.agent_assignments import AgentAssignment, read_agent_assignments
from dreamcatcher.config import Config
from dreamcatcher.github import Unknown
from dreamcatcher.scheduler import derive_issue_availability, observe_issues
from dreamcatcher.state import IssueFactValue, StateDirectory

SETTINGS = {"prompt": "/dream:smith GH{issue}", "model": "opus[1m]", "effort": "xhigh"}
INDEPENDENT_FACTS = (
    "claimed_here",
    "claimed_elsewhere",
    "blocked",
    "routing_conflict",
)


def config_with_routes(*, labels: Sequence[str]) -> Config:
    """Return a config that routes each label to the same harness recipe."""
    return Config.model_validate(
        {"dispatch": [{"label": label, "claude": SETTINGS} for label in labels]}
    )


@pytest.fixture
def gh(fake):
    """Return gh observing one open, assigned issue with no preventing facts."""
    stand_in = fake(program="gh")
    stand_in.replies(stdout=listing(issues=[(8, FILED)]), to="issue list")
    stand_in.replies(
        stdout=json.dumps({"closedByPullRequestsReferences": []}), to="issue view"
    )
    stand_in.replies(stdout="[]", to="api")
    return stand_in


def observe(
    *,
    config: Config,
    assignments: Sequence[AgentAssignment] = (),
    recovery_obstacles: dict[int, str | None] | None = None,
):
    """Return the issue observations after asserting that the listing succeeded."""
    found = observe_issues(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=config,
        assignments=list(assignments),
        recovery_obstacles=({} if recovery_obstacles is None else recovery_obstacles),
    )
    assert not isinstance(found, Unknown)
    return found


@pytest.mark.parametrize(
    "values",
    list(product(IssueFactValue, repeat=len(INDEPENDENT_FACTS))),
)
def test_availability_follows_the_independent_fact_truth_table(values):
    facts = dict(zip(INDEPENDENT_FACTS, values, strict=True))

    availability = derive_issue_availability(
        observation=observed_issue(issue=8, values=facts)
    )

    if IssueFactValue.TRUE in values:
        expected = IssueFactValue.FALSE
    elif IssueFactValue.UNKNOWN in values:
        expected = IssueFactValue.UNKNOWN
    else:
        expected = IssueFactValue.TRUE
    assert availability.value is expected


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"is_open": IssueFactValue.FALSE}, IssueFactValue.FALSE),
        ({"is_assigned_to_user": IssueFactValue.FALSE}, IssueFactValue.FALSE),
        ({"dispatch_labels": ()}, IssueFactValue.FALSE),
        ({"is_open": IssueFactValue.UNKNOWN}, IssueFactValue.UNKNOWN),
        ({"is_assigned_to_user": IssueFactValue.UNKNOWN}, IssueFactValue.UNKNOWN),
        ({"dispatch_labels": None}, IssueFactValue.UNKNOWN),
    ],
)
def test_availability_also_requires_an_open_assigned_routed_issue(change, expected):
    dispatch_labels = change.get("dispatch_labels", (LABEL,))
    values = {key: value for key, value in change.items() if key != "dispatch_labels"}
    availability = derive_issue_availability(
        observation=observed_issue(
            issue=8, dispatch_labels=dispatch_labels, values=values
        )
    )

    assert availability.value is expected


def test_an_issue_with_no_preventing_fact_is_available(gh):
    found = observe(config=config_with_routes(labels=[LABEL]))

    assert len(found) == 1
    assert derive_issue_availability(observation=found[0]).value is IssueFactValue.TRUE


def test_observed_issues_are_ordered_oldest_first(gh):
    gh.replies(stdout=listing(issues=[(8, LATER), (3, FILED)]), to="issue list")

    found = observe(config=config_with_routes(labels=[LABEL]))

    assert [observation.issue for observation in found] == [3, 8]


def test_a_listing_failure_makes_the_whole_observation_unknown(gh):
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")

    found = observe_issues(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=config_with_routes(labels=[LABEL]),
        assignments=[],
        recovery_obstacles={},
    )

    assert isinstance(found, Unknown)
    assert "could not connect" in found.reason


def test_routing_conflict_is_independent_of_external_claims_and_blockers(gh):
    issue = json.loads(listing(issues=[(8, FILED)]))[0]
    issue["labels"] = [{"name": LABEL}, {"name": "dream:less"}]
    gh.replies(stdout=json.dumps([issue]), to="issue list")

    found = observe(config=config_with_routes(labels=[LABEL, "dream:less"]))[0]

    assert found.dispatch_labels == ["dream:less", LABEL]
    assert found.routing_conflict.value is IssueFactValue.TRUE
    assert found.claimed_elsewhere.value is IssueFactValue.FALSE
    assert found.blocked.value is IssueFactValue.FALSE


def test_local_and_external_claims_can_both_be_true(gh, tmp_path):
    state = StateDirectory(root=tmp_path)
    write_agent_assignment(state=state, identifier="GH8-20260819-184158", issue=8)
    gh.replies(
        stdout=json.dumps(
            {
                "closedByPullRequestsReferences": [
                    {"number": PULL_REQUEST},
                    {"number": 28},
                ]
            }
        ),
        to="issue view",
    )
    gh.replies(
        stdout=json.dumps({"number": PULL_REQUEST, "state": "OPEN", "isDraft": True}),
        to="pr view",
    )

    found = observe(
        config=config_with_routes(labels=[LABEL]),
        assignments=read_agent_assignments(state=state),
    )[0]

    assert found.claimed_here.value is IssueFactValue.TRUE
    assert found.claimed_elsewhere.value is IssueFactValue.TRUE
    assert found.claimed_elsewhere.evidence == "a pull request is open on it: #28"


def test_a_recoverable_setup_is_not_treated_as_an_external_claim(gh):
    found = observe(
        config=config_with_routes(labels=[LABEL]), recovery_obstacles={8: None}
    )[0]

    assert found.claimed_elsewhere.value is IssueFactValue.FALSE


def test_a_setup_that_cannot_be_recovered_leaves_the_claim_unknown(gh):
    found = observe(
        config=config_with_routes(labels=[LABEL]),
        recovery_obstacles={8: "cannot reconcile its incomplete setup"},
    )[0]

    assert found.claimed_elsewhere.value is IssueFactValue.UNKNOWN
    assert found.claimed_elsewhere.evidence == "cannot reconcile its incomplete setup"


def test_a_failed_linked_pull_request_read_preserves_unknown_evidence(gh):
    gh.fails(stderr="gh: the issue is not there", to="issue view")

    found = observe(config=config_with_routes(labels=[LABEL]))[0]

    assert found.claimed_elsewhere.value is IssueFactValue.UNKNOWN
    assert found.claimed_elsewhere.evidence is not None
    assert (
        "cannot tell whether a pull request claims it"
        in found.claimed_elsewhere.evidence
    )


def test_open_blockers_are_observed_independently(gh):
    gh.replies(
        stdout=json.dumps(
            [{"number": 7, "state": "closed"}, {"number": 9, "state": "open"}]
        ),
        to="api",
    )

    found = observe(config=config_with_routes(labels=[LABEL]))[0]

    assert found.blocked.value is IssueFactValue.TRUE
    assert found.blocked.evidence == "blocked by GH9"


def test_a_failed_blocker_read_preserves_unknown_evidence(gh):
    gh.fails(stderr="gh: could not connect to github.com", to="api")

    found = observe(config=config_with_routes(labels=[LABEL]))[0]

    assert found.blocked.value is IssueFactValue.UNKNOWN
    assert found.blocked.evidence is not None
    assert "cannot tell what blocks it" in found.blocked.evidence


def test_an_open_local_assignment_is_observed_outside_the_listing(gh, tmp_path):
    state = StateDirectory(root=tmp_path)
    write_agent_assignment(state=state, identifier="GH13-20260819-184158", issue=13)
    gh.replies(stdout="[]", to="issue list")
    gh.replies(
        stdout=json.dumps(
            {
                "number": 13,
                "createdAt": LATER,
                "state": "CLOSED",
                "assignees": [],
                "labels": [],
            }
        ),
        to=(
            f"issue view 13 --repo {REPOSITORY} --json "
            "number,createdAt,state,assignees,labels"
        ),
    )

    found = observe(
        config=config_with_routes(labels=[LABEL]),
        assignments=read_agent_assignments(state=state),
    )

    assert [observation.issue for observation in found] == [13]
    assert found[0].is_open.value is IssueFactValue.FALSE
    assert found[0].is_open.evidence == "issue is closed"
    assert found[0].is_assigned_to_user.value is IssueFactValue.FALSE
    assert found[0].is_assigned_to_user.evidence == "is not assigned to alimanfoo"
    assert found[0].dispatch_labels == []
    assert found[0].claimed_here.value is IssueFactValue.TRUE
