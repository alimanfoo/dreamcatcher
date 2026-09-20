import json
from collections.abc import Sequence
from itertools import product

import pytest
from conftest import (
    DISPATCH_LABEL,
    FILED,
    LATER,
    POSTED_BY,
    PULL_REQUEST,
    REPOSITORY,
    listing,
)
from observations import observed_issue
from records import write_agent_assignment

from dreamcatcher.agent_assignments import AgentAssignment, read_agent_assignments
from dreamcatcher.config import DreamcatcherConfig
from dreamcatcher.scheduler import (
    IssueFactValue,
    derive_issue_availability,
    observe_issues,
)
from dreamcatcher.state import StateDirectory

SETTINGS = {"prompt": "/dream:smith GH{issue}", "model": "opus[1m]", "effort": "xhigh"}
INDEPENDENT_FACTS = (
    "claimed_here",
    "claimed_elsewhere",
    "blocked",
    "routing_conflict",
)


def config_with_routes(
    *, labels: Sequence[str], assignee: str = "@me"
) -> DreamcatcherConfig:
    """Return a config that routes each label to the same harness recipe."""
    return DreamcatcherConfig.model_validate(
        {
            "assignee": assignee,
            "dispatch": [{"label": label, "claude": SETTINGS} for label in labels],
        }
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
    config: DreamcatcherConfig,
    assignments: Sequence[AgentAssignment] = (),
    incomplete_setups: dict[int, str | None] | None = None,
):
    """Return the issue observations after asserting that the listing succeeded."""
    found = observe_issues(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=config,
        assignments=list(assignments),
        incomplete_setups=({} if incomplete_setups is None else incomplete_setups),
    )
    assert found.failure is None
    return found.observations


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
        (
            {
                "is_open": IssueFactValue.FALSE,
                "claimed_elsewhere": IssueFactValue.UNKNOWN,
            },
            IssueFactValue.FALSE,
        ),
        (
            {
                "is_assigned_to_user": IssueFactValue.FALSE,
                "blocked": IssueFactValue.UNKNOWN,
            },
            IssueFactValue.FALSE,
        ),
        (
            {
                "dispatch_labels": (),
                "routing_conflict": IssueFactValue.UNKNOWN,
            },
            IssueFactValue.FALSE,
        ),
    ],
)
def test_availability_also_requires_an_open_assigned_routed_issue(change, expected):
    dispatch_labels = change.get("dispatch_labels", (DISPATCH_LABEL,))
    values = {key: value for key, value in change.items() if key != "dispatch_labels"}
    availability = derive_issue_availability(
        observation=observed_issue(
            issue=8, dispatch_labels=dispatch_labels, values=values
        )
    )

    assert availability.value is expected


def test_an_issue_with_no_preventing_fact_is_available(gh):
    found = observe(config=config_with_routes(labels=[DISPATCH_LABEL]))

    assert len(found) == 1
    assert derive_issue_availability(observation=found[0]).value is IssueFactValue.TRUE


def test_observed_issues_are_ordered_oldest_first(gh):
    gh.replies(stdout=listing(issues=[(8, LATER), (3, FILED)]), to="issue list")

    found = observe(config=config_with_routes(labels=[DISPATCH_LABEL]))

    assert [observation.issue for observation in found] == [3, 8]


def test_a_listing_failure_makes_the_whole_observation_unknown(gh):
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")

    found = observe_issues(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=config_with_routes(labels=[DISPATCH_LABEL]),
        assignments=[],
        incomplete_setups={},
    )

    assert found.observations == []
    assert found.failure is not None
    assert "could not connect" in found.failure


def test_a_later_route_failure_preserves_earlier_issue_observations(gh):
    gh.replies(
        stdout=listing(issues=[(8, FILED)]),
        to=f"issue list --repo {REPOSITORY} --assignee @me --label {DISPATCH_LABEL}",
    )
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=f"issue list --repo {REPOSITORY} --assignee @me --label dream:less",
    )

    found = observe_issues(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=config_with_routes(labels=[DISPATCH_LABEL, "dream:less"]),
        assignments=[],
        incomplete_setups={},
    )

    assert found.failure is not None
    assert "could not connect" in found.failure
    assert [observation.issue for observation in found.observations] == [8]
    assert found.observations[0].is_open.value is IssueFactValue.TRUE


def test_an_explicit_assignee_is_matched_without_case_sensitivity(gh):
    found = observe(
        config=config_with_routes(labels=[DISPATCH_LABEL], assignee=POSTED_BY.upper())
    )[0]

    assert found.is_assigned_to_user.value is IssueFactValue.TRUE


def test_routing_conflict_is_independent_of_external_claims_and_blockers(gh):
    issue = json.loads(listing(issues=[(8, FILED)]))[0]
    issue["labels"] = [{"name": DISPATCH_LABEL}, {"name": "dream:less"}]
    gh.replies(stdout=json.dumps([issue]), to="issue list")

    found = observe(config=config_with_routes(labels=[DISPATCH_LABEL, "dream:less"]))[0]

    assert found.dispatch_labels == ["dream:less", DISPATCH_LABEL]
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
        config=config_with_routes(labels=[DISPATCH_LABEL]),
        assignments=read_agent_assignments(state=state),
    )[0]

    assert found.claimed_here.value is IssueFactValue.TRUE
    assert found.claimed_elsewhere.value is IssueFactValue.TRUE
    assert found.claimed_elsewhere.evidence == "a pull request is open on it: #28"


def test_a_recoverable_setup_is_not_treated_as_an_external_claim(gh):
    found = observe(
        config=config_with_routes(labels=[DISPATCH_LABEL]),
        incomplete_setups={8: None},
    )[0]

    assert found.claimed_elsewhere.value is IssueFactValue.FALSE
    assert found.setup_failure is None


def test_a_setup_that_cannot_be_recovered_leaves_the_claim_unknown(gh):
    found = observe(
        config=config_with_routes(labels=[DISPATCH_LABEL]),
        incomplete_setups={8: "cannot reconcile its incomplete setup"},
    )[0]

    assert found.claimed_elsewhere.value is IssueFactValue.UNKNOWN
    assert found.claimed_elsewhere.evidence == "cannot reconcile its incomplete setup"
    assert found.setup_failure == "cannot reconcile its incomplete setup"


def test_a_setup_failure_survives_a_failed_linked_pull_request_read(gh):
    gh.fails(stderr="gh: could not connect to github.com", to="issue view")

    found = observe(
        config=config_with_routes(labels=[DISPATCH_LABEL]),
        incomplete_setups={8: "cannot reconcile its incomplete setup"},
    )[0]

    assert found.claimed_elsewhere.value is IssueFactValue.UNKNOWN
    assert found.claimed_elsewhere.evidence == "cannot reconcile its incomplete setup"
    assert found.setup_failure == "cannot reconcile its incomplete setup"


def test_a_setup_failure_keeps_a_proven_external_claim(gh):
    gh.replies(
        stdout=json.dumps(
            {"closedByPullRequestsReferences": [{"number": PULL_REQUEST}]}
        ),
        to="issue view",
    )
    gh.replies(
        stdout=json.dumps({"number": PULL_REQUEST, "state": "OPEN", "isDraft": True}),
        to="pr view",
    )

    found = observe(
        config=config_with_routes(labels=[DISPATCH_LABEL]),
        incomplete_setups={8: "cannot reconcile its incomplete setup"},
    )[0]

    assert found.claimed_elsewhere.value is IssueFactValue.TRUE
    assert found.claimed_elsewhere.evidence == "a pull request is open on it: #52"
    assert found.setup_failure == "cannot reconcile its incomplete setup"


def test_a_failed_linked_pull_request_read_preserves_unknown_evidence(gh):
    gh.fails(stderr="gh: the issue is not there", to="issue view")

    found = observe(config=config_with_routes(labels=[DISPATCH_LABEL]))[0]

    assert found.claimed_elsewhere.value is IssueFactValue.UNKNOWN
    assert found.claimed_elsewhere.evidence is not None
    assert (
        "cannot tell whether a pull request claims it"
        in found.claimed_elsewhere.evidence
    )
    assert found.setup_failure is None


def test_open_blockers_are_observed_independently(gh):
    gh.replies(
        stdout=json.dumps(
            [{"number": 7, "state": "closed"}, {"number": 9, "state": "open"}]
        ),
        to="api",
    )

    found = observe(config=config_with_routes(labels=[DISPATCH_LABEL]))[0]

    assert found.blocked.value is IssueFactValue.TRUE
    assert found.blocked.evidence == "blocked by GH9"


def test_a_failed_blocker_read_preserves_unknown_evidence(gh):
    gh.fails(stderr="gh: could not connect to github.com", to="api")

    found = observe(config=config_with_routes(labels=[DISPATCH_LABEL]))[0]

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
        config=config_with_routes(labels=[DISPATCH_LABEL]),
        assignments=read_agent_assignments(state=state),
    )

    assert [observation.issue for observation in found] == [13]
    assert found[0].is_open.value is IssueFactValue.FALSE
    assert found[0].is_open.evidence == "issue is closed"
    assert found[0].is_assigned_to_user.value is IssueFactValue.FALSE
    assert found[0].is_assigned_to_user.evidence == "is not assigned to alimanfoo"
    assert found[0].dispatch_labels == []
    assert found[0].claimed_here.value is IssueFactValue.TRUE


def test_a_local_assignment_remains_observed_when_the_listing_and_issue_read_fail(
    gh, tmp_path
):
    state = StateDirectory(root=tmp_path)
    write_agent_assignment(state=state, identifier="GH13-20260819-184158", issue=13)
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=(
            f"issue view 13 --repo {REPOSITORY} --json "
            "number,createdAt,state,assignees,labels"
        ),
    )

    found = observe_issues(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=config_with_routes(labels=[DISPATCH_LABEL]),
        assignments=read_agent_assignments(state=state),
        incomplete_setups={},
    )

    assert found.failure is not None
    assert "could not connect" in found.failure
    assert [observation.issue for observation in found.observations] == [13]
    observation = found.observations[0]
    assert observation.is_open.value is IssueFactValue.UNKNOWN
    assert observation.is_assigned_to_user.value is IssueFactValue.UNKNOWN
    assert observation.routing_conflict.value is IssueFactValue.UNKNOWN
    assert observation.claimed_here.value is IssueFactValue.TRUE


def test_an_incomplete_setup_is_observed_outside_the_listing(gh):
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
        config=config_with_routes(labels=[DISPATCH_LABEL]),
        incomplete_setups={13: "cannot reconcile its incomplete setup"},
    )

    assert [observation.issue for observation in found] == [13]
    assert found[0].claimed_elsewhere.value is IssueFactValue.UNKNOWN
    assert (
        found[0].claimed_elsewhere.evidence == "cannot reconcile its incomplete setup"
    )
